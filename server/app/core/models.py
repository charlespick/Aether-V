"""Data models for the application."""
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
from datetime import datetime
from enum import Enum


class NotificationLevel(str, Enum):
    """Notification severity level."""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    SUCCESS = "success"


class NotificationCategory(str, Enum):
    """Notification category."""
    SYSTEM = "system"
    HOST = "host"
    VM = "vm"
    JOB = "job"
    AUTHENTICATION = "authentication"


class OSFamily(str, Enum):
    """Operating system family."""
    WINDOWS = "windows"
    LINUX = "linux"


class JobStatus(str, Enum):
    """Job execution status."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class VMState(str, Enum):
    """Virtual machine state."""
    RUNNING = "Running"
    OFF = "Off"
    PAUSED = "Paused"
    SAVED = "Saved"
    STARTING = "Starting"
    STOPPING = "Stopping"
    UNKNOWN = "Unknown"


class Cluster(BaseModel):
    """Hyper-V cluster information."""
    name: str
    hosts: List[str] = Field(default_factory=list)
    connected_hosts: int = 0
    total_hosts: int = 0


class Host(BaseModel):
    """Hyper-V host information."""
    hostname: str
    cluster: Optional[str] = None  # Cluster name this host belongs to
    connected: bool = False
    last_seen: Optional[datetime] = None
    error: Optional[str] = None


class Notification(BaseModel):
    """System notification."""
    id: str
    title: str
    message: str
    level: NotificationLevel
    category: NotificationCategory
    created_at: datetime
    read: bool = False
    related_entity: Optional[str] = None  # Host name, VM name, Job ID, etc.


class VM(BaseModel):
    """Virtual machine information."""
    name: str
    host: str
    state: VMState
    cpu_cores: int = 0
    memory_gb: float = 0.0
    os_family: Optional[OSFamily] = None
    created_at: Optional[datetime] = None


class VMCreateRequest(BaseModel):
    """Request to create a new VM."""
    vm_name: str = Field(..., min_length=1, max_length=64)
    image_name: str = Field(...,
                            description="Name of the golden image without extension")
    hyperv_host: str = Field(..., description="Target Hyper-V host")
    gb_ram: int = Field(4, ge=1, le=512, description="RAM in GB")
    cpu_cores: int = Field(2, ge=1, le=64, description="Number of CPU cores")
    vlan_id: Optional[int] = Field(
        None, ge=1, le=4094, description="VLAN ID for network isolation")

    # Guest OS configuration
    guest_la_uid: str = Field(..., description="Local administrator username")
    guest_la_pw: str = Field(..., description="Local administrator password")
    guest_v4_ipaddr: Optional[str] = Field(
        None, description="Static IPv4 address")
    guest_v4_cidrprefix: Optional[int] = Field(
        None, ge=1, le=32, description="IPv4 CIDR prefix")
    guest_v4_defaultgw: Optional[str] = Field(
        None, description="Default gateway")
    guest_v4_dns1: Optional[str] = Field(
        None, description="Primary DNS server")
    guest_v4_dns2: Optional[str] = Field(
        None, description="Secondary DNS server")
    guest_net_dnssuffix: Optional[str] = Field(None, description="DNS suffix")

    # Windows domain join (Windows only)
    guest_domain_jointarget: Optional[str] = Field(
        None, description="Domain to join")
    guest_domain_joinuid: Optional[str] = Field(
        None, description="Domain join username")
    guest_domain_joinpw: Optional[str] = Field(
        None, description="Domain join password")
    guest_domain_joinou: Optional[str] = Field(
        None, description="OU path for computer account")

    # Linux SSH configuration (Linux only)
    cnf_ansible_ssh_user: Optional[str] = Field(
        None, description="Ansible SSH username")
    cnf_ansible_ssh_key: Optional[str] = Field(
        None, description="Ansible SSH public key")

    # Clustering
    vm_clustered: Optional[bool] = Field(
        False, description="Add VM to cluster")


class VMDeleteRequest(BaseModel):
    """Request to delete a VM."""
    vm_name: str
    hyperv_host: str
    force: bool = Field(
        False, description="Force delete even if VM is running")


class Job(BaseModel):
    """Job execution tracking."""
    job_id: str
    job_type: str  # "create_vm", "delete_vm"
    status: JobStatus
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    target_host: str
    parameters: Dict[str, Any]
    output: List[str] = Field(default_factory=list)
    error: Optional[str] = None


class InventoryResponse(BaseModel):
    """Inventory summary response."""
    clusters: List[Cluster] = Field(default_factory=list)
    hosts: List[Host]
    vms: List[VM]
    disconnected_hosts: List[Host] = Field(default_factory=list)
    total_hosts: int
    total_vms: int
    total_clusters: int = 0
    disconnected_count: int = 0
    last_refresh: Optional[datetime] = None


class HealthResponse(BaseModel):
    """Health check response."""
    status: str
    version: str
    timestamp: datetime


class NotificationsResponse(BaseModel):
    """Notifications response."""
    notifications: List[Notification]
    total_count: int
    unread_count: int
