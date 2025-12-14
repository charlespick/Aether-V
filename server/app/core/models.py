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
    CREATING = "Creating"
    DELETING = "Deleting"


class NetworkModel(str, Enum):
    """Network model type."""
    VLAN = "vlan"


class HostRecoveryAction(str, Enum):
    """VM automatic start action after host recovery."""
    NONE = "none"
    RESUME = "resume"
    ALWAYS_START = "always-start"


class HostStopAction(str, Enum):
    """VM action when host stops."""
    SAVE = "save"
    STOP = "stop"
    SHUT_DOWN = "shut-down"


class StorageClass(BaseModel):
    """Storage class configuration for a host.
    
    Represents a named storage location where VM disks can be stored.
    Maps storage class names to filesystem paths.
    """
    name: str = Field(..., description="Unique identifier for the storage class")
    path: str = Field(..., description="Filesystem path where VM disks will be stored")


class VlanConfiguration(BaseModel):
    """VLAN network configuration.
    
    Configuration specific to VLAN-based networks.
    """
    virtual_switch: str = Field(..., description="Name of the Hyper-V virtual switch")
    vlan_id: int = Field(..., ge=1, le=4094, description="VLAN identifier")


class Network(BaseModel):
    """Network configuration for a host.
    
    Represents a named network that VMs can connect to.
    Maps network names to VLAN IDs and virtual switches.
    """
    name: str = Field(..., description="Unique identifier for the network")
    model: NetworkModel = Field(..., description="Network model type")
    configuration: VlanConfiguration = Field(..., description="Network configuration data")


class HostResources(BaseModel):
    """Host resources configuration.
    
    Complete resource configuration for a host including storage classes,
    networks, and default paths. This model matches the hostresources.json
    schema that can be deployed to hosts.
    """
    version: int = Field(..., description="Schema version number")
    schema_name: str = Field(..., description="Name of the schema")
    storage_classes: List[StorageClass] = Field(default_factory=list, description="Available storage classes")
    networks: List[Network] = Field(default_factory=list, description="Available networks")
    virtual_machines_path: str = Field(..., description="Default path for VM configuration files")


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
    total_cpu_cores: int = 0
    total_memory_gb: float = 0.0
    resources: Optional[HostResources] = None  # Host resource configuration
    

class HostSummary(BaseModel):
    """Shallow host representation for list views."""

    hostname: str
    cluster: Optional[str] = None
    connected: bool = False
    last_seen: Optional[datetime] = None
    vm_count: int = 0


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
    metadata: Dict[str, Any] = Field(default_factory=dict)


class VM(BaseModel):
    """Virtual machine information."""
    id: Optional[str] = None
    name: str
    host: str
    cluster: Optional[str] = None
    state: VMState
    cpu_cores: int = 0
    memory_gb: float = 0.0
    memory_startup_gb: Optional[float] = None
    memory_min_gb: Optional[float] = None
    memory_max_gb: Optional[float] = None
    dynamic_memory_enabled: Optional[bool] = None
    dynamic_memory_buffer: Optional[int] = None  # Memory buffer percentage for dynamic memory
    ip_address: Optional[str] = None
    ip_addresses: List[str] = Field(default_factory=list)
    notes: Optional[str] = None
    os_family: Optional[OSFamily] = None
    os_name: Optional[str] = None
    generation: Optional[int] = None
    version: Optional[str] = None
    created_at: Optional[datetime] = None
    # Security settings
    secure_boot_enabled: Optional[bool] = None
    secure_boot_template: Optional[str] = None
    trusted_platform_module_enabled: Optional[bool] = None
    tpm_key_protector: Optional[str] = None
    # Boot settings
    primary_boot_device: Optional[str] = None
    # Host actions
    host_recovery_action: Optional[HostRecoveryAction] = None
    host_stop_action: Optional[HostStopAction] = None
    # Integration services
    integration_services_shutdown: Optional[bool] = None
    integration_services_time: Optional[bool] = None
    integration_services_data_exchange: Optional[bool] = None
    integration_services_heartbeat: Optional[bool] = None
    integration_services_vss_backup: Optional[bool] = None
    integration_services_guest_services: Optional[bool] = None
    # Related objects
    disks: List["VMDisk"] = Field(default_factory=list)
    networks: List["VMNetworkAdapter"] = Field(default_factory=list)


class VMListItem(BaseModel):
    """Shallow VM representation for inventory tables."""

    id: Optional[str] = None
    name: str
    host: str
    cluster: Optional[str] = None
    state: VMState
    os_name: Optional[str] = None
    ip_address: Optional[str] = None


class VMDisk(BaseModel):
    """Virtual disk attached to a VM."""

    id: Optional[str] = None
    name: Optional[str] = None
    path: Optional[str] = None
    location: Optional[str] = None
    type: Optional[str] = None
    size_gb: Optional[float] = None
    file_size_gb: Optional[float] = None
    storage_class: Optional[str] = None  # Storage class name from host resources


class VMNetworkAdapter(BaseModel):
    """Network adapter attached to a VM."""

    id: Optional[str] = None
    name: Optional[str] = None
    adapter_name: Optional[str] = None
    network: Optional[str] = None  # Network name from host resources
    virtual_switch: Optional[str] = None
    vlan_id: Optional[int] = None  # VLAN ID from network configuration
    vlan: Optional[str] = None  # Legacy field, kept for backward compatibility
    network_name: Optional[str] = None
    ip_addresses: List[str] = Field(default_factory=list)
    mac_address: Optional[str] = None
    mac_address_config: Optional[str] = None  # "Dynamic" or "Static"
    # Security settings
    dhcp_guard: Optional[bool] = None
    router_guard: Optional[bool] = None
    mac_spoof_guard: Optional[bool] = None
    # Bandwidth settings
    min_bandwidth_mbps: Optional[int] = None
    max_bandwidth_mbps: Optional[int] = None


class DiskDetail(VMDisk):
    """Disk detail including owning VM reference."""

    vm_id: Optional[str] = None


class NetworkAdapterDetail(VMNetworkAdapter):
    """NIC detail including owning VM reference."""

    vm_id: Optional[str] = None


VM.model_rebuild()


class VMDeleteRequest(BaseModel):
    """Request to delete a VM."""
    vm_name: str
    hyperv_host: str
    force: bool = Field(
        False, description="Force delete even if VM is running")
    delete_disks: bool = Field(
        False, description="Delete all attached disks with the VM (validates no shared disks)")


class VMCreateRequest(BaseModel):
    """Request to create a virtual machine on a specific host."""

    target_host: str = Field(
        ..., description="Hostname of the connected Hyper-V host that will execute the job",
    )
    vm_name: str = Field(
        ..., min_length=1, max_length=64, description="Unique name for the new virtual machine",
    )
    gb_ram: int = Field(
        ..., ge=1, le=512, description="Amount of memory to assign to the VM in gigabytes",
    )
    cpu_cores: int = Field(
        ..., ge=1, le=64, description="Number of virtual CPU cores",
    )
    storage_class: Optional[str] = Field(
        None, description="Name of the storage class where VM configuration files will be stored",
    )
    vm_clustered: bool = Field(
        False, description="Request that the new VM be registered with the Failover Cluster",
    )
    os_family: Optional[OSFamily] = Field(
        None,
        description="Operating system family (windows or linux) used to configure secure boot settings",
    )


class VMUpdateRequest(BaseModel):
    """Request to update VM hardware properties."""

    vm_name: str = Field(
        ..., min_length=1, max_length=64, description="Existing name of the virtual machine",
    )
    gb_ram: int = Field(
        ..., ge=1, le=512, description="Amount of memory to assign to the VM in gigabytes",
    )
    cpu_cores: int = Field(
        ..., ge=1, le=64, description="Number of virtual CPU cores",
    )
    storage_class: Optional[str] = Field(
        None, description="Name of the storage class where VM configuration files will be stored",
    )
    vm_clustered: bool = Field(
        False, description="Request that the VM be registered with the Failover Cluster",
    )
    os_family: Optional[OSFamily] = Field(
        None,
        description="Operating system family (windows or linux) used to configure secure boot settings",
    )


class DiskCreateRequest(BaseModel):
    """Request to create a new disk attached to a VM."""

    disk_size_gb: int = Field(
        100, ge=1, le=65536, description="Size of the virtual disk in gigabytes",
    )
    disk_type: str = Field(
        "Dynamic", description="Type of virtual hard disk (Dynamic or Fixed)",
    )
    controller_type: str = Field(
        "SCSI", description="Type of controller to attach the disk to (SCSI or IDE)",
    )
    image_name: Optional[str] = Field(
        None, description="Optional golden image name to clone for the disk",
    )
    storage_class: Optional[str] = Field(
        None,
        deprecated=True,
        description="[Deprecated] Storage class is determined by the VM location and is ignored",
    )


class DiskUpdateRequest(DiskCreateRequest):
    """Request to update an existing disk attached to a VM."""
    pass


class NicCreateRequest(BaseModel):
    """Request to create a new network adapter on a VM."""

    network: str = Field(
        ..., description="Name of the network to connect the adapter to",
    )
    adapter_name: Optional[str] = Field(
        None, description="Optional name for the network adapter",
    )


class NicUpdateRequest(NicCreateRequest):
    """Request to update an existing network adapter on a VM."""
    pass


class VMInitializationRequest(BaseModel):
    """Request to initialize an existing VM with guest configuration."""

    target_host: str = Field(
        ..., description="Hostname of the connected Hyper-V host that will execute the job"
    )
    guest_configuration: Dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Pre-formed guest configuration values to apply to the VM. External callers "
            "must persist and supply these values when triggering initialization."
        ),
    )


class NoopTestRequest(BaseModel):
    """Request to execute a noop-test job using the JobRequest envelope protocol.

    Validates the round-trip communication between server and host agent
    without performing actual operations.
    """

    target_host: str = Field(
        ...,
        description="Hostname of the connected Hyper-V host that will execute the test",
    )
    resource_spec: Dict[str, Any] = Field(
        default_factory=dict,
        description="Test data to echo back through the new protocol",
    )
    correlation_id: Optional[str] = Field(
        None,
        description="Optional correlation ID for tracking the request",
    )


class JobResult(BaseModel):
    """Result of a job submission that returns immediately."""
    job_id: str
    status: str = "queued"
    message: str


class Job(BaseModel):
    """Job execution tracking."""
    job_id: str
    job_type: str  # "create_vm", "delete_vm", "managed_deployment", etc.
    status: JobStatus
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    target_host: Optional[str] = None
    parameters: Dict[str, Any]
    output: List[str] = Field(default_factory=list)
    error: Optional[str] = None
    notification_id: Optional[str] = None
    child_jobs: List[Dict[str, Any]] = Field(default_factory=list)


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
    environment_name: str = "Production Environment"  # New field for page titles


class ClusterSummary(BaseModel):
    """Shallow cluster representation."""

    id: str
    name: str
    host_count: int = 0
    vm_count: int = 0


class ClusterDetail(BaseModel):
    """Cluster detail view with shallow child objects."""

    id: str
    name: str
    hosts: List[HostSummary] = Field(default_factory=list)
    virtual_machines: List[VMListItem] = Field(default_factory=list)


class HostDetail(HostSummary):
    """Host detail with shallow VM list."""

    virtual_machines: List[VMListItem] = Field(default_factory=list)


class StatisticsResponse(BaseModel):
    """Inventory statistics replacing legacy inventory summary counts."""

    total_hosts: int
    total_clusters: int
    total_vms: int
    disconnected_count: int = 0
    environment_name: str
    last_refresh: Optional[datetime] = None


class BuildInfo(BaseModel):
    """Information about the running container build."""

    version: str
    source_control: str = "unknown"
    git_commit: Optional[str] = None
    git_ref: Optional[str] = None
    git_state: Optional[str] = None
    github_repository: Optional[str] = None
    build_time: Optional[datetime] = None
    build_host: Optional[str] = None


class HealthResponse(BaseModel):
    """Health check response."""

    status: str
    version: str
    timestamp: datetime
    build: Optional[BuildInfo] = None


class AboutResponse(BaseModel):
    """Metadata returned for the About screen."""

    name: str
    description: Optional[str] = None
    build: BuildInfo


class NotificationsResponse(BaseModel):
    """Notifications response."""
    notifications: List[Notification]
    total_count: int
    unread_count: int


class OSSPackage(BaseModel):
    """Information about an open source package."""

    name: str
    version: str
    license: str
    author: Optional[str] = None
    url: Optional[str] = None
    ecosystem: str


class OSSLicenseSummary(BaseModel):
    """Summary statistics for OSS license information."""

    total: int
    python: int
    javascript: int


class OSSLicenseResponse(BaseModel):
    """Response containing OSS license information."""

    packages: List[OSSPackage]
    summary: OSSLicenseSummary


class ShortQueueMetrics(BaseModel):
    """Metrics for the short job queue (rate-limited)."""

    queue_depth: int
    inflight: int
    completed: int


class IOQueueMetrics(BaseModel):
    """Metrics for the IO job queue (per-host serialized)."""

    queue_depth: int
    inflight: int
    completed: int
    hosts_with_active_io: int


class RemoteTaskMetrics(BaseModel):
    """Aggregated diagnostics for the remote task service.
    
    The service uses static concurrency limits with two queues:
    - SHORT queue: Rate-limited dispatch for quick operations
    - IO queue: Per-host serialization for disk/guest-init operations
    """

    started: bool
    max_connections: int
    total_connections: int
    dispatch_interval_seconds: float
    short_queue: ShortQueueMetrics
    io_queue: IOQueueMetrics


class JobServiceMetrics(BaseModel):
    """Diagnostic information about job processing."""

    started: bool
    queue_depth: int
    worker_count: int
    pending_jobs: int
    running_jobs: int
    completed_jobs: int
    failed_jobs: int
    total_tracked_jobs: int


class InventoryServiceMetrics(BaseModel):
    """Diagnostic information about the inventory refresh loop."""

    hosts_tracked: int
    vms_tracked: int
    clusters_tracked: int
    last_refresh: Optional[datetime]
    refresh_in_progress: bool
    bootstrap_running: bool
    refresh_loop_running: bool
    initial_refresh_running: bool
    initial_refresh_completed: bool
    initial_refresh_succeeded: bool
    refresh_overrun: bool
    host_refresh_timestamps: Dict[str, datetime]


class HostDeploymentMetrics(BaseModel):
    """Diagnostic information about host agent deployment."""

    enabled: bool
    ingress_ready: bool
    startup_task_running: bool
    startup: Dict[str, Any]


class ServiceDiagnosticsResponse(BaseModel):
    """Composite diagnostics payload returned by the API."""

    remote_tasks: RemoteTaskMetrics
    jobs: JobServiceMetrics
    inventory: InventoryServiceMetrics
    host_deployment: HostDeploymentMetrics
