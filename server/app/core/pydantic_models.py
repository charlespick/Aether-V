"""Pydantic models for VM resource specifications and job requests.

These models provide validation and type safety for all VM resource operations.

Models defined here:
- Resource specifications: VmSpec, DiskSpec, NicSpec (hardware-only models for independent APIs)
- Deployment requests: ManagedDeploymentRequest (flat form payload for UI-driven flow)
- Job envelope: JobRequest, JobResult

Architecture Note:
    The ManagedDeploymentRequest is a FLAT model that mirrors the UI form submission.
    All form fields are top-level properties, NOT nested in sub-objects. The managed
    deployment service internally parses this flat payload, constructs hardware specs,
    and composes the guest configuration for the Initialize step.
    
    VmSpec, DiskSpec, and NicSpec are hardware-only models used by the independent
    resource APIs (Terraform flow). They do NOT contain guest configuration fields.
    
    This design:
    1. Keeps the API contract simple (flat form → flat payload)
    2. Centralizes parsing/orchestration logic in the managed deployment service
    3. Maintains clean separation between hardware and guest config concerns
"""
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field, model_validator, ConfigDict
from enum import Enum


# ============================================================================
# Resource Specification Models
# ============================================================================


class OSFamily(str, Enum):
    """Operating system family for secure boot configuration."""
    WINDOWS = "windows"
    LINUX = "linux"


class VmSpec(BaseModel):
    """Virtual machine hardware specification.
    
    This model represents VM hardware configuration that is sent to the
    host agent for VM creation. It is used by the independent resource API
    (POST /api/v1/resources/vms) for Terraform and programmatic access.
    
    Guest configuration is NOT included in this model - it is handled
    separately by the Initialize API for independent resources, or
    automatically by the ManagedDeploymentRequest for UI-driven deployments.
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
        description="Name of the storage class where VM configuration files and disks will be stored",
    )
    vm_clustered: bool = Field(
        False,
        description="Request that the new VM be registered with the Failover Cluster",
    )
    os_family: Optional[OSFamily] = Field(
        None,
        description="Operating system family (windows or linux). Used to configure secure boot settings. If not specified, defaults to windows.",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "vm_name": "web-01",
                "gb_ram": 4,
                "cpu_cores": 2,
                "storage_class": "fast-ssd",
                "vm_clustered": False,
                "os_family": "windows",
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
        deprecated=True,
        description="[Deprecated in v0.5.0] Storage class is now determined by the VM's location. Disks are stored in the same folder as the VM configuration files. This field is ignored and will be removed in v1.0.0.",
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
                "disk_type": "Dynamic",
                "controller_type": "SCSI",
            }
        }
    )


class NicSpec(BaseModel):
    """Network adapter hardware specification.
    
    This model represents NIC hardware configuration that is sent to the
    host agent for NIC creation. It is used by the independent resource API
    (POST /api/v1/resources/nics) for Terraform and programmatic access.
    
    Guest IP configuration is NOT included in this model - it is handled
    separately by the Initialize API for independent resources, or as
    flat fields in ManagedDeploymentRequest for UI-driven deployments.
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


class ManagedDeploymentRequest(BaseModel):
    """Flat request model for managed VM deployment (UI-driven flow).
    
    This model mirrors the UI form submission directly - all fields are top-level
    properties, NOT nested in sub-objects. The managed deployment service parses
    this flat payload internally to construct hardware specs and guest config.
    
    This design keeps the API contract simple: what the user enters in the form
    is exactly what gets sent to the API. The server handles all orchestration.
    
    For Terraform/programmatic access, use the independent resource APIs instead:
    - POST /api/v1/resources/vms (VmSpec)
    - POST /api/v1/resources/disks (DiskSpec)
    - POST /api/v1/resources/nics (NicSpec)
    - POST /api/v1/resources/vms/{vm_id}/initialize (guest config dict)
    """
    # === Target Host (required) ===
    target_host: str = Field(
        ...,
        description="Hostname of the connected Hyper-V host that will execute the job",
    )
    
    # === VM Hardware Configuration (required) ===
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
        description="Name of the storage class where VM files will be stored",
    )
    vm_clustered: bool = Field(
        False,
        description="Request that the new VM be registered with the Failover Cluster",
    )
    
    # === Disk Configuration (optional - if image_name provided, disk is created) ===
    image_name: Optional[str] = Field(
        None,
        description="Name of a golden image to clone. If provided, a disk will be created",
    )
    disk_size_gb: int = Field(
        100,
        ge=1,
        le=65536,
        description="Size of the virtual disk in gigabytes",
    )
    
    # === Network Configuration (required) ===
    network: str = Field(
        ...,
        description="Name of the network to connect the adapter to",
    )
    
    # === Guest Configuration - Local Admin (required for guest init) ===
    guest_la_uid: str = Field(
        ...,
        description="Username for the guest operating system's local administrator",
    )
    guest_la_pw: str = Field(
        ...,
        description="Password for the guest operating system's local administrator",
    )
    
    # === Guest Configuration - Domain Join (optional, all-or-none) ===
    guest_domain_join_target: Optional[str] = Field(
        None,
        description="Fully qualified domain name to join",
    )
    guest_domain_join_uid: Optional[str] = Field(
        None,
        description="User account used to join the domain",
    )
    guest_domain_join_pw: Optional[str] = Field(
        None,
        description="Password for the domain join account",
    )
    guest_domain_join_ou: Optional[str] = Field(
        None,
        description="Organizational unit path for the computer account",
    )
    
    # === Guest Configuration - Ansible (optional, all-or-none) ===
    cnf_ansible_ssh_user: Optional[str] = Field(
        None,
        description="Username used by Ansible for SSH automation",
    )
    cnf_ansible_ssh_key: Optional[str] = Field(
        None,
        description="Public key provided to the guest for Ansible SSH access",
    )
    
    # === Guest Configuration - Static IP (optional, all-or-none for required fields) ===
    guest_v4_ip_addr: Optional[str] = Field(
        None,
        description="Static IPv4 address to assign to the guest adapter",
    )
    guest_v4_cidr_prefix: Optional[int] = Field(
        None,
        ge=0,
        le=32,
        description="CIDR prefix length that accompanies the static IPv4 address",
    )
    guest_v4_default_gw: Optional[str] = Field(
        None,
        description="Default IPv4 gateway for the guest adapter",
    )
    guest_v4_dns1: Optional[str] = Field(
        None,
        description="Primary IPv4 DNS server for the guest adapter",
    )
    guest_v4_dns2: Optional[str] = Field(
        None,
        description="Secondary IPv4 DNS server for the guest adapter (optional)",
    )
    guest_net_dns_suffix: Optional[str] = Field(
        None,
        description="DNS search suffix for the guest network configuration (optional)",
    )

    @model_validator(mode='after')
    def validate_parameter_sets(self) -> 'ManagedDeploymentRequest':
        """Validate all-or-none parameter sets for domain join, ansible, and static IP."""
        # Domain join: all-or-none
        domain_fields = [
            self.guest_domain_join_target,
            self.guest_domain_join_uid,
            self.guest_domain_join_pw,
            self.guest_domain_join_ou,
        ]
        domain_provided = [f for f in domain_fields if f is not None and f != ""]
        if domain_provided and len(domain_provided) != len(domain_fields):
            raise ValueError(
                "Domain join configuration requires all fields: "
                "guest_domain_join_target, guest_domain_join_uid, "
                "guest_domain_join_pw, guest_domain_join_ou"
            )
        
        # Ansible: all-or-none
        ansible_fields = [self.cnf_ansible_ssh_user, self.cnf_ansible_ssh_key]
        ansible_provided = [f for f in ansible_fields if f is not None and f != ""]
        if ansible_provided and len(ansible_provided) != len(ansible_fields):
            raise ValueError(
                "Ansible configuration requires all fields: "
                "cnf_ansible_ssh_user, cnf_ansible_ssh_key"
            )
        
        # Static IP: all-or-none for required fields (dns2, dns_suffix optional)
        static_ip_required = [
            self.guest_v4_ip_addr,
            self.guest_v4_cidr_prefix,
            self.guest_v4_default_gw,
            self.guest_v4_dns1,
        ]
        static_ip_provided = [f for f in static_ip_required if f is not None and f != ""]
        if static_ip_provided and len(static_ip_provided) != len(static_ip_required):
            raise ValueError(
                "Static IP configuration requires all fields: "
                "guest_v4_ip_addr, guest_v4_cidr_prefix, "
                "guest_v4_default_gw, guest_v4_dns1"
            )
        
        return self

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "target_host": "hyperv-01.example.com",
                "vm_name": "web-01",
                "gb_ram": 4,
                "cpu_cores": 2,
                "storage_class": "fast-ssd",
                "vm_clustered": False,
                "image_name": "Windows Server 2022",
                "disk_size_gb": 100,
                "network": "Production",
                "guest_la_uid": "Administrator",
                "guest_la_pw": "SecurePass123!",
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
