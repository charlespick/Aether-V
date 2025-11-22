"""Phase 6 Tests: Managed Deployment V2 with New Protocol

This test suite validates the Phase 6 implementation of managed deployment
using the new Pydantic-based protocol.

Tests cover:
1. Endpoint validation with ManagedDeploymentRequest
2. Job submission and queuing
3. Job execution with new protocol (VM, Disk, NIC creation)
4. Guest config generation and integration
5. End-to-end workflow validation

Phase 6 Note: These tests validate that the managed deployment workflow
now uses Pydantic models and bypasses schemas entirely.
"""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from app.core.pydantic_models import (
    ManagedDeploymentRequest,
    VmSpec,
    DiskSpec,
    NicSpec,
    GuestConfigSpec,
    JobResultEnvelope,
    JobResultStatus,
)


class TestManagedDeploymentV2Request:
    """Test ManagedDeploymentRequest Pydantic model validation."""
    
    def test_minimal_managed_deployment_request(self):
        """Test minimal valid managed deployment request."""
        request = ManagedDeploymentRequest(
            vm_spec=VmSpec(
                vm_name="test-vm",
                gb_ram=4,
                cpu_cores=2,
            ),
            target_host="hyperv-01.example.com",
        )
        
        assert request.vm_spec.vm_name == "test-vm"
        assert request.vm_spec.gb_ram == 4
        assert request.vm_spec.cpu_cores == 2
        assert request.target_host == "hyperv-01.example.com"
        assert request.disk_spec is None
        assert request.nic_spec is None
        assert request.guest_config is None
    
    def test_full_managed_deployment_request(self):
        """Test managed deployment request with all optional components."""
        request = ManagedDeploymentRequest(
            vm_spec=VmSpec(
                vm_name="web-01",
                gb_ram=8,
                cpu_cores=4,
                storage_class="fast-ssd",
            ),
            disk_spec=DiskSpec(
                image_name="Windows Server 2022",
                disk_size_gb=100,
                storage_class="fast-ssd",
            ),
            nic_spec=NicSpec(
                network="Production",
                adapter_name="Ethernet 1",
            ),
            guest_config=GuestConfigSpec(
                guest_la_uid="Administrator",
                guest_la_pw="SecurePass123!",
                guest_domain_jointarget="corp.example.com",
                guest_domain_joinuid="EXAMPLE\\svc_join",
                guest_domain_joinpw="DomainPass456!",
                guest_domain_joinou="OU=Servers,DC=corp,DC=example,DC=com",
            ),
            target_host="hyperv-01.example.com",
        )
        
        assert request.vm_spec.vm_name == "web-01"
        assert request.disk_spec.image_name == "Windows Server 2022"
        assert request.nic_spec.network == "Production"
        assert request.guest_config.guest_la_uid == "Administrator"
        assert request.guest_config.guest_domain_jointarget == "corp.example.com"
    
    def test_managed_deployment_with_static_ip(self):
        """Test managed deployment with static IP configuration."""
        request = ManagedDeploymentRequest(
            vm_spec=VmSpec(
                vm_name="app-01",
                gb_ram=16,
                cpu_cores=8,
            ),
            nic_spec=NicSpec(
                network="Production",
            ),
            guest_config=GuestConfigSpec(
                guest_la_uid="Administrator",
                guest_la_pw="SecurePass123!",
                guest_v4_ipaddr="192.168.1.100",
                guest_v4_cidrprefix=24,
                guest_v4_defaultgw="192.168.1.1",
                guest_v4_dns1="192.168.1.10",
            ),
            target_host="hyperv-02.example.com",
        )
        
        assert request.guest_config.guest_v4_ipaddr == "192.168.1.100"
        assert request.guest_config.guest_v4_cidrprefix == 24


class TestManagedDeploymentV2JobSubmission:
    """Test job submission for managed deployment v2."""
    
    def test_submit_managed_deployment_v2_job(self):
        """Test submitting a managed deployment v2 job."""
        from app.services.job_service import JobService
        from app.core.models import JobStatus
        
        async def run_test():
            service = JobService()
            await service.start()
            
            try:
                request = ManagedDeploymentRequest(
                    vm_spec=VmSpec(
                        vm_name="test-vm",
                        gb_ram=4,
                        cpu_cores=2,
                    ),
                    target_host="hyperv-01",
                )
                
                job = await service.submit_managed_deployment_v2_job(request=request)
                
                assert job.job_id is not None
                assert job.job_type == "managed_deployment_v2"
                assert job.status == JobStatus.PENDING
                assert job.target_host == "hyperv-01"
                assert "request" in job.parameters
                
                # Verify request was serialized correctly
                stored_request = ManagedDeploymentRequest(**job.parameters["request"])
                assert stored_request.vm_spec.vm_name == "test-vm"
            finally:
                await service.stop()
        
        asyncio.run(run_test())
    
    def test_submit_full_managed_deployment_v2_job(self):
        """Test submitting a full managed deployment v2 job with all components."""
        from app.services.job_service import JobService
        from app.core.models import JobStatus
        
        async def run_test():
            service = JobService()
            await service.start()
            
            try:
                request = ManagedDeploymentRequest(
                    vm_spec=VmSpec(
                        vm_name="web-01",
                        gb_ram=8,
                        cpu_cores=4,
                    ),
                    disk_spec=DiskSpec(
                        image_name="Windows Server 2022",
                        disk_size_gb=100,
                    ),
                    nic_spec=NicSpec(
                        network="Production",
                    ),
                    guest_config=GuestConfigSpec(
                        guest_la_uid="Administrator",
                        guest_la_pw="SecurePass123!",
                    ),
                    target_host="hyperv-01",
                )
                
                job = await service.submit_managed_deployment_v2_job(request=request)
                
                assert job.job_type == "managed_deployment_v2"
                
                # Verify all components were serialized
                stored_request = ManagedDeploymentRequest(**job.parameters["request"])
                assert stored_request.disk_spec.image_name == "Windows Server 2022"
                assert stored_request.nic_spec.network == "Production"
                assert stored_request.guest_config.guest_la_uid == "Administrator"
            finally:
                await service.stop()
        
        asyncio.run(run_test())


class TestManagedDeploymentV2Execution:
    """Test execution of managed deployment v2 jobs."""
    
    def test_execute_minimal_deployment(self, monkeypatch):
        """Test executing a minimal managed deployment (VM only)."""
        from app.services import job_service as job_service_module
        from app.core.models import Job, JobStatus
        
        service = job_service_module.job_service
        
        request = ManagedDeploymentRequest(
            vm_spec=VmSpec(
                vm_name="test-vm",
                gb_ram=4,
                cpu_cores=2,
            ),
            target_host="hyperv-01",
        )
        
        job = Job(
            job_id="test-job-1",
            job_type="managed_deployment_v2",
            status=JobStatus.PENDING,
            created_at=datetime.utcnow(),
            target_host="hyperv-01",
            parameters={"request": request.model_dump()},
        )
        
        # Mock the new protocol execution
        mock_vm_result = JobResultEnvelope(
            status=JobResultStatus.SUCCESS,
            message="VM created successfully",
            data={"vm_id": "test-vm-id-123"},
        )
        
        async def mock_execute_new_protocol(job, target_host, job_request, desc):
            return mock_vm_result
        
        # Mock host preparation
        monkeypatch.setattr(
            job_service_module.host_deployment_service,
            "ensure_host_setup",
            AsyncMock(return_value=True),
        )
        
        # Mock the new protocol execution
        monkeypatch.setattr(
            service,
            "_execute_new_protocol_operation",
            AsyncMock(side_effect=mock_execute_new_protocol),
        )
        
        # Mock job update methods
        monkeypatch.setattr(service, "_append_job_output", AsyncMock())
        monkeypatch.setattr(service, "_update_job", AsyncMock())
        
        # Execute the job
        asyncio.run(service._execute_managed_deployment_v2_job(job))
        
        # Verify the protocol operation was called for VM creation
        assert service._execute_new_protocol_operation.called
        call_args = service._execute_new_protocol_operation.call_args_list[0]
        assert "VM creation" in call_args[0][3]
    
    def test_execute_full_deployment_with_guest_config(self, monkeypatch):
        """Test executing a full deployment with VM, Disk, NIC, and guest config."""
        from app.services import job_service as job_service_module
        from app.core.models import Job, JobStatus
        
        service = job_service_module.job_service
        
        request = ManagedDeploymentRequest(
            vm_spec=VmSpec(
                vm_name="web-01",
                gb_ram=8,
                cpu_cores=4,
            ),
            disk_spec=DiskSpec(
                image_name="Windows Server 2022",
                disk_size_gb=100,
            ),
            nic_spec=NicSpec(
                network="Production",
            ),
            guest_config=GuestConfigSpec(
                guest_la_uid="Administrator",
                guest_la_pw="SecurePass123!",
            ),
            target_host="hyperv-01",
        )
        
        job = Job(
            job_id="test-job-2",
            job_type="managed_deployment_v2",
            status=JobStatus.PENDING,
            created_at=datetime.utcnow(),
            target_host="hyperv-01",
            parameters={"request": request.model_dump()},
        )
        
        # Track which operations were called
        operations_called = []
        
        async def mock_execute_new_protocol(job, target_host, job_request, desc):
            operations_called.append(desc)
            if "VM creation" in desc:
                return JobResultEnvelope(
                    status=JobResultStatus.SUCCESS,
                    message="VM created",
                    data={"vm_id": "vm-123"},
                )
            elif "Disk creation" in desc:
                return JobResultEnvelope(
                    status=JobResultStatus.SUCCESS,
                    message="Disk created",
                    data={"disk_id": "disk-456"},
                )
            elif "NIC creation" in desc:
                return JobResultEnvelope(
                    status=JobResultStatus.SUCCESS,
                    message="NIC created",
                    data={"nic_id": "nic-789"},
                )
        
        # Mock initialization job for guest config
        async def mock_queue_child_job(parent_job, job_type, schema_id, payload):
            return Job(
                job_id=f"{job_type}-child",
                job_type=job_type,
                schema_id=schema_id,
                status=JobStatus.PENDING,
                created_at=datetime.utcnow(),
                parameters=payload,
                target_host=parent_job.target_host,
            )
        
        async def mock_wait_for_child_job(parent_job_id, child_job_id):
            return Job(
                job_id=child_job_id,
                job_type="initialize_vm",
                schema_id="initialize-vm",
                status=JobStatus.COMPLETED,
                created_at=datetime.utcnow(),
                parameters={},
                target_host="hyperv-01",
            )
        
        # Setup mocks
        monkeypatch.setattr(
            job_service_module.host_deployment_service,
            "ensure_host_setup",
            AsyncMock(return_value=True),
        )
        monkeypatch.setattr(
            service,
            "_execute_new_protocol_operation",
            AsyncMock(side_effect=mock_execute_new_protocol),
        )
        monkeypatch.setattr(service, "_append_job_output", AsyncMock())
        monkeypatch.setattr(service, "_update_job", AsyncMock())
        monkeypatch.setattr(
            service,
            "_queue_child_job",
            AsyncMock(side_effect=mock_queue_child_job),
        )
        monkeypatch.setattr(
            service,
            "_wait_for_child_job_completion",
            AsyncMock(side_effect=mock_wait_for_child_job),
        )
        
        # Execute the job
        asyncio.run(service._execute_managed_deployment_v2_job(job))
        
        # Verify all operations were called
        assert "VM creation" in operations_called
        assert "Disk creation" in operations_called
        assert "NIC creation" in operations_called
        
        # Verify guest config initialization was called
        assert service._queue_child_job.called
        init_call = service._queue_child_job.call_args
        assert init_call[1]["job_type"] == "initialize_vm"
        
        # Verify guest config was properly generated and included
        init_payload = init_call[1]["payload"]
        assert "guest_la_uid" in init_payload["fields"]
        assert "guest_la_pw" in init_payload["fields"]


class TestGuestConfigIntegration:
    """Test guest config generation integration in managed deployment v2."""
    
    def test_guest_config_generated_correctly(self):
        """Test that guest config is generated correctly during deployment."""
        from app.core.guest_config_generator import generate_guest_config
        
        vm_spec = VmSpec(
            vm_name="test-vm",
            gb_ram=4,
            cpu_cores=2,
        )
        
        guest_config_spec = GuestConfigSpec(
            guest_la_uid="Administrator",
            guest_la_pw="SecurePass123!",
            guest_domain_jointarget="corp.example.com",
            guest_domain_joinuid="EXAMPLE\\svc_join",
            guest_domain_joinpw="DomainPass456!",
            guest_domain_joinou="OU=Servers,DC=corp,DC=example,DC=com",
        )
        
        config = generate_guest_config(
            vm_spec=vm_spec,
            guest_config_spec=guest_config_spec,
        )
        
        # Verify all domain join fields are present
        assert "guest_la_uid" in config
        assert "guest_la_pw" in config
        assert "guest_domain_jointarget" in config
        assert "guest_domain_joinuid" in config
        assert "guest_domain_joinpw" in config
        assert "guest_domain_joinou" in config
    
    def test_guest_config_with_static_ip(self):
        """Test guest config generation with static IP."""
        from app.core.guest_config_generator import generate_guest_config
        
        vm_spec = VmSpec(
            vm_name="app-01",
            gb_ram=8,
            cpu_cores=4,
        )
        
        nic_spec = NicSpec(
            network="Production",
        )
        
        guest_config_spec = GuestConfigSpec(
            guest_la_uid="Administrator",
            guest_la_pw="SecurePass123!",
            guest_v4_ipaddr="192.168.1.100",
            guest_v4_cidrprefix=24,
            guest_v4_defaultgw="192.168.1.1",
            guest_v4_dns1="192.168.1.10",
        )
        
        config = generate_guest_config(
            vm_spec=vm_spec,
            nic_spec=nic_spec,
            guest_config_spec=guest_config_spec,
        )
        
        # Verify static IP fields are present
        assert config["guest_v4_ipaddr"] == "192.168.1.100"
        assert config["guest_v4_cidrprefix"] == 24
        assert config["guest_v4_defaultgw"] == "192.168.1.1"
        assert config["guest_v4_dns1"] == "192.168.1.10"


class TestNewProtocolOperations:
    """Test individual new protocol operations."""
    
    def test_vm_create_via_new_protocol(self):
        """Test VM creation via new protocol."""
        from app.core.job_envelope import create_job_request
        
        vm_spec = VmSpec(
            vm_name="test-vm",
            gb_ram=4,
            cpu_cores=2,
        )
        
        job_request = create_job_request(
            operation="vm.create",
            resource_spec=vm_spec.model_dump(),
            correlation_id="test-correlation-id",
        )
        
        assert job_request.operation == "vm.create"
        assert job_request.resource_spec["vm_name"] == "test-vm"
        assert job_request.resource_spec["gb_ram"] == 4
        assert job_request.correlation_id == "test-correlation-id"
    
    def test_disk_create_via_new_protocol(self):
        """Test disk creation via new protocol."""
        from app.core.job_envelope import create_job_request
        
        disk_spec = DiskSpec(
            vm_id="12345678-1234-1234-1234-123456789abc",
            image_name="Windows Server 2022",
            disk_size_gb=100,
        )
        
        job_request = create_job_request(
            operation="disk.create",
            resource_spec=disk_spec.model_dump(),
            correlation_id="test-disk-id",
        )
        
        assert job_request.operation == "disk.create"
        assert job_request.resource_spec["vm_id"] == "12345678-1234-1234-1234-123456789abc"
        assert job_request.resource_spec["image_name"] == "Windows Server 2022"
    
    def test_nic_create_via_new_protocol(self):
        """Test NIC creation via new protocol."""
        from app.core.job_envelope import create_job_request
        
        nic_spec = NicSpec(
            vm_id="12345678-1234-1234-1234-123456789abc",
            network="Production",
            adapter_name="Ethernet 1",
        )
        
        job_request = create_job_request(
            operation="nic.create",
            resource_spec=nic_spec.model_dump(),
            correlation_id="test-nic-id",
        )
        
        assert job_request.operation == "nic.create"
        assert job_request.resource_spec["vm_id"] == "12345678-1234-1234-1234-123456789abc"
        assert job_request.resource_spec["network"] == "Production"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
