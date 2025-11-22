"""Pydantic models for VM resource specifications and job requests.

Phase 1: These models are introduced in parallel to the existing schema system.
They do not replace the schemas yet, but provide a new validation layer.

Models defined here:
- Resource specifications: VmSpec, DiskSpec, NicSpec, GuestConfigSpec
- Deployment requests: ManagedDeploymentRequest
- Job envelope: JobRequest, JobResult (enhanced)
"""
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field, field_validator, model_validator, ConfigDict
from enum import Enum


# ============================================================================
# Resource Specification Models
# ============================================================================


class VmSpec(BaseModel):
    """Virtual machine hardware specification.
    
    This model represents VM hardware configuration that is sent to the
    host agent for VM creation. It does NOT include guest configuration
    fields (those are in GuestConfigSpec).
    """
    vm_name: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="Unique name for the new virtual machine",
    )
    gb_ram: int = Field(
        ...,
        ge=1,
        le=512,
        description="Amount of memory to assign to the VM in gigabytes",
    )
    cpu_cores: int = Field(
        ...,
        ge=1,
        le=64,
        description="Number of virtual CPU cores",
    )
    storage_class: Optional[str] = Field(
        None,
        description="Name of the storage class where VM configuration will be stored",
    )
    vm_clustered: bool = Field(
        False,
        description="Request that the new VM be registered with the Failover Cluster",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "vm_name": "web-01",
                "gb_ram": 4,
                "cpu_cores": 2,
                "storage_class": "fast-ssd",
                "vm_clustered": False,
            }
        }
    )


class DiskSpec(BaseModel):
    """Virtual disk specification.
    
    Represents a disk to be created and optionally attached to a VM.
    Either image_name (for cloning) or disk_size_gb (for blank disk) should be provided.
    """
    vm_id: Optional[str] = Field(
        None,
        min_length=36,
        max_length=36,
        description="Hyper-V ID of the virtual machine to attach the disk to",
    )
    image_name: Optional[str] = Field(
        None,
        description="Name of a golden image to clone. If omitted, creates a blank disk",
    )
    disk_size_gb: int = Field(
        100,
        ge=1,
        le=65536,
        description="Size of the virtual disk in gigabytes",
    )
    storage_class: Optional[str] = Field(
        None,
        description="Name of the storage class where the disk will be stored",
    )
    disk_type: str = Field(
        "Dynamic",
        description="Type of virtual hard disk (Dynamic or Fixed)",
    )
    controller_type: str = Field(
        "SCSI",
        description="Type of controller to attach the disk to (SCSI or IDE)",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "vm_id": "12345678-1234-1234-1234-123456789abc",
                "image_name": "Windows Server 2022",
                "storage_class": "fast-ssd",
                "disk_type": "Dynamic",
                "controller_type": "SCSI",
            }
        }
    )


class NicSpec(BaseModel):
    """Network adapter hardware specification.
    
    Represents NIC hardware configuration that is sent to the host agent.
    Guest IP configuration is handled separately in GuestConfigSpec.
    """
    vm_id: Optional[str] = Field(
        None,
        min_length=36,
        max_length=36,
        description="Hyper-V ID of the virtual machine to attach the adapter to",
    )
    network: str = Field(
        ...,
        description="Name of the network to connect the adapter to",
    )
    adapter_name: Optional[str] = Field(
        None,
        description="Optional name for the network adapter",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "vm_id": "12345678-1234-1234-1234-123456789abc",
                "network": "Production",
                "adapter_name": "Network Adapter 2",
            }
        }
    )


class GuestConfigSpec(BaseModel):
    """Guest operating system configuration specification.
    
    This model aggregates all guest-level configuration from VM and NIC specs.
    It is transmitted to the guest agent via KVP for OS-level provisioning.
    """
    # VM-level guest config
    guest_la_uid: str = Field(
        ...,
        description="Username for the guest operating system's local administrator",
    )
    guest_la_pw: str = Field(
        ...,
        description="Password for the guest operating system's local administrator",
    )
    
    # Domain join configuration (all-or-none)
    guest_domain_jointarget: Optional[str] = Field(
        None,
        description="Fully qualified domain name to join",
    )
    guest_domain_joinuid: Optional[str] = Field(
        None,
        description="User account used to join the domain",
    )
    guest_domain_joinpw: Optional[str] = Field(
        None,
        description="Password for the domain join account",
    )
    guest_domain_joinou: Optional[str] = Field(
        None,
        description="Organizational unit path for the computer account",
    )
    
    # Ansible configuration (all-or-none)
    cnf_ansible_ssh_user: Optional[str] = Field(
        None,
        description="Username used by Ansible for SSH automation",
    )
    cnf_ansible_ssh_key: Optional[str] = Field(
        None,
        description="Public key provided to the guest for Ansible SSH access",
    )
    
    # NIC-level guest config (static IP - all-or-none)
    guest_v4_ipaddr: Optional[str] = Field(
        None,
        description="Static IPv4 address to assign to the guest adapter",
    )
    guest_v4_cidrprefix: Optional[int] = Field(
        None,
        description="CIDR prefix length that accompanies the static IPv4 address",
    )
    guest_v4_defaultgw: Optional[str] = Field(
        None,
        description="Default IPv4 gateway for the guest adapter",
    )
    guest_v4_dns1: Optional[str] = Field(
        None,
        description="Primary IPv4 DNS server for the guest adapter",
    )
    guest_v4_dns2: Optional[str] = Field(
        None,
        description="Secondary IPv4 DNS server for the guest adapter",
    )
    guest_net_dnssuffix: Optional[str] = Field(
        None,
        description="DNS search suffix for the guest network configuration",
    )

    @model_validator(mode='after')
    def validate_parameter_sets(self) -> 'GuestConfigSpec':
        """Validate all-or-none parameter sets for domain join and ansible."""
        # Domain join: all-or-none
        domain_fields = [
            self.guest_domain_jointarget,
            self.guest_domain_joinuid,
            self.guest_domain_joinpw,
            self.guest_domain_joinou,
        ]
        domain_provided = [f for f in domain_fields if f is not None and f != ""]
        if domain_provided and len(domain_provided) != len(domain_fields):
            raise ValueError(
                "Domain join configuration requires all fields: "
                "guest_domain_jointarget, guest_domain_joinuid, "
                "guest_domain_joinpw, guest_domain_joinou"
            )
        
        # Ansible: all-or-none
        ansible_fields = [self.cnf_ansible_ssh_user, self.cnf_ansible_ssh_key]
        ansible_provided = [f for f in ansible_fields if f is not None and f != ""]
        if ansible_provided and len(ansible_provided) != len(ansible_fields):
            raise ValueError(
                "Ansible configuration requires all fields: "
                "cnf_ansible_ssh_user, cnf_ansible_ssh_key"
            )
        
        # Static IP: all-or-none for required fields
        static_ip_required = [
            self.guest_v4_ipaddr,
            self.guest_v4_cidrprefix,
            self.guest_v4_defaultgw,
            self.guest_v4_dns1,
        ]
        static_ip_provided = [f for f in static_ip_required if f is not None and f != ""]
        if static_ip_provided and len(static_ip_provided) != len(static_ip_required):
            raise ValueError(
                "Static IP configuration requires all fields: "
                "guest_v4_ipaddr, guest_v4_cidrprefix, "
                "guest_v4_defaultgw, guest_v4_dns1"
            )
        
        return self

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "guest_la_uid": "Administrator",
                "guest_la_pw": "SecurePass123!",
                "guest_domain_jointarget": "corp.example.com",
                "guest_domain_joinuid": "EXAMPLE\\svc_join",
                "guest_domain_joinpw": "DomainPass456!",
                "guest_domain_joinou": "OU=Servers,DC=corp,DC=example,DC=com",
            }
        }
    )


class ManagedDeploymentRequest(BaseModel):
    """Request for a managed VM deployment.
    
    This represents a complete VM deployment including VM hardware, disk,
    network adapter, and guest configuration. It is the top-level request
    for the managed deployment orchestration.
    """
    vm_spec: VmSpec = Field(
        ...,
        description="VM hardware specification",
    )
    disk_spec: Optional[DiskSpec] = Field(
        None,
        description="Optional disk specification. If provided, a disk will be created",
    )
    nic_spec: Optional[NicSpec] = Field(
        None,
        description="Optional NIC specification. If provided, a NIC will be created",
    )
    guest_config: Optional[GuestConfigSpec] = Field(
        None,
        description="Optional guest configuration. If provided, guest will be initialized",
    )
    target_host: str = Field(
        ...,
        description="Hostname of the connected Hyper-V host that will execute the job",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "vm_spec": {
                    "vm_name": "web-01",
                    "gb_ram": 4,
                    "cpu_cores": 2,
                },
                "disk_spec": {
                    "image_name": "Windows Server 2022",
                },
                "nic_spec": {
                    "network": "Production",
                },
                "guest_config": {
                    "guest_la_uid": "Administrator",
                    "guest_la_pw": "SecurePass123!",
                },
                "target_host": "hyperv-01.example.com",
            }
        }
    )


# ============================================================================
# Job Envelope Models
# ============================================================================


class JobRequest(BaseModel):
    """Job request envelope sent to host agent.
    
    This is the standard structure for all job requests sent to the
    PowerShell host agent via STDIN as JSON.
    """
    operation: str = Field(
        ...,
        description="Operation type identifier (e.g., 'vm.create', 'disk.clone', 'nic.update')",
    )
    resource_spec: Dict[str, Any] = Field(
        ...,
        description="Structured object matching the operation's expected specification",
    )
    correlation_id: str = Field(
        ...,
        description="Unique identifier used for log tracking",
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Optional metadata such as timestamps, host identifier, or debug flags",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "operation": "vm.create",
                "resource_spec": {
                    "vm_name": "web-01",
                    "gb_ram": 4,
                    "cpu_cores": 2,
                },
                "correlation_id": "12345678-1234-1234-1234-123456789abc",
                "metadata": {
                    "timestamp": "2025-11-22T04:43:48.376Z",
                    "host": "hyperv-01",
                },
            }
        }
    )


class JobResultStatus(str, Enum):
    """Job result status values."""
    SUCCESS = "success"
    ERROR = "error"
    PARTIAL = "partial"


class JobResultEnvelope(BaseModel):
    """Job result envelope returned by host agent.
    
    This is the standard structure for all job results returned by the
    PowerShell host agent as JSON.
    
    Note: This extends the existing JobResult model from core.models
    to provide a more complete envelope structure.
    """
    status: JobResultStatus = Field(
        ...,
        description="Outcome status of the job",
    )
    message: str = Field(
        ...,
        description="Human-readable description of the outcome",
    )
    data: Dict[str, Any] = Field(
        default_factory=dict,
        description="Structured output (e.g., created object identifiers, resolved file paths)",
    )
    code: Optional[str] = Field(
        None,
        description="Optional machine-readable error code",
    )
    logs: List[str] = Field(
        default_factory=list,
        description="Optional array of log or debug lines generated during execution",
    )
    correlation_id: Optional[str] = Field(
        None,
        description="Mirrors the correlation_id sent in the request",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": "success",
                "message": "VM created successfully",
                "data": {
                    "vm_id": "12345678-1234-1234-1234-123456789abc",
                    "vm_name": "web-01",
                },
                "correlation_id": "12345678-1234-1234-1234-123456789abc",
            }
        }
    )
