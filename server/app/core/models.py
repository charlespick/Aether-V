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
    state: VMState
    cpu_cores: int = 0
    memory_gb: float = 0.0
    memory_startup_gb: Optional[float] = None
    memory_min_gb: Optional[float] = None
    memory_max_gb: Optional[float] = None
    dynamic_memory_enabled: Optional[bool] = None
    ip_address: Optional[str] = None
    ip_addresses: List[str] = Field(default_factory=list)
    notes: Optional[str] = None
    os_family: Optional[OSFamily] = None
    os_name: Optional[str] = None
    generation: Optional[int] = None
    version: Optional[str] = None
    created_at: Optional[datetime] = None
    disks: List["VMDisk"] = Field(default_factory=list)
    networks: List["VMNetworkAdapter"] = Field(default_factory=list)


class VMDisk(BaseModel):
    """Virtual disk attached to a VM."""

    id: Optional[str] = None
    name: Optional[str] = None
    path: Optional[str] = None
    location: Optional[str] = None
    type: Optional[str] = None
    size_gb: Optional[float] = None
    file_size_gb: Optional[float] = None


class VMNetworkAdapter(BaseModel):
    """Network adapter attached to a VM."""

    id: Optional[str] = None
    name: Optional[str] = None
    adapter_name: Optional[str] = None
    network: Optional[str] = None
    virtual_switch: Optional[str] = None
    vlan: Optional[str] = None
    network_name: Optional[str] = None
    ip_addresses: List[str] = Field(default_factory=list)
    mac_address: Optional[str] = None


VM.model_rebuild()


class VMDeleteRequest(BaseModel):
    """Request to delete a VM."""
    vm_name: str
    hyperv_host: str
    force: bool = Field(
        False, description="Force delete even if VM is running")
    delete_disks: bool = Field(
        False, description="Delete all attached disks with the VM (validates no shared disks)")


class ResourceCreateRequest(BaseModel):
    """Base class for resource creation requests."""
    values: Dict[str, Any] = Field(
        default_factory=dict,
        description="Field values keyed by schema field id",
    )
    target_host: str = Field(
        ...,
        description="Hostname of the connected Hyper-V host that will execute the job",
    )


class DiskCreateRequest(ResourceCreateRequest):
    """Request to create a new disk."""
    pass


class NicCreateRequest(ResourceCreateRequest):
    """Request to create a new network adapter."""
    pass


class ResourceUpdateRequest(ResourceCreateRequest):
    """Request to update an existing resource."""

    resource_id: str = Field(
        ..., description="Hyper-V ID of the resource being updated"
    )


class ResourceDeleteRequest(BaseModel):
    """Request to delete a resource by ID."""
    resource_id: str = Field(...,
                             description="Hyper-V ID of the resource to delete")
    hyperv_host: str = Field(...,
                             description="Host where the resource is located")


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


class RemoteTaskPoolMetrics(BaseModel):
    """Snapshot of a remote task worker pool."""

    queue_depth: int
    inflight: int
    current_workers: int
    min_workers: Optional[int] = None
    max_workers: Optional[int] = None
    configured_workers: Optional[int] = None


class RemoteTaskMetrics(BaseModel):
    """Aggregated diagnostics for the remote task service."""

    started: bool
    average_duration_seconds: float
    completed_tasks: int
    scale_up_backlog_threshold: int
    scale_up_duration_threshold_seconds: float
    idle_timeout_seconds: float
    cpu_percent: float
    memory_percent: float
    configured_max_workers: int
    current_max_workers: int
    dynamic_ceiling: int
    dynamic_scale_increment: int
    resource_scale_interval_seconds: float
    resource_observation_window_seconds: float
    resource_cpu_threshold_percent: float
    resource_memory_threshold_percent: float
    dynamic_adjustments: int
    maxed_out_for_seconds: float
    fast_pool: RemoteTaskPoolMetrics
    job_pool: RemoteTaskPoolMetrics


class JobServiceMetrics(BaseModel):
    """Diagnostic information about job processing."""

    started: bool
    queue_depth: int
    worker_count: int
    configured_concurrency: int
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
