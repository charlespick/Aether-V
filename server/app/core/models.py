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
    metadata: Dict[str, Any] = Field(default_factory=dict)


class VM(BaseModel):
    """Virtual machine information."""
    name: str
    host: str
    state: VMState
    cpu_cores: int = 0
    memory_gb: float = 0.0
    os_family: Optional[OSFamily] = None
    created_at: Optional[datetime] = None


class VMDeleteRequest(BaseModel):
    """Request to delete a VM."""
    vm_name: str
    hyperv_host: str
    force: bool = Field(
        False, description="Force delete even if VM is running")


class Job(BaseModel):
    """Job execution tracking."""
    job_id: str
    job_type: str  # "provision_vm", "delete_vm", etc.
    status: JobStatus
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    target_host: Optional[str] = None
    parameters: Dict[str, Any]
    output: List[str] = Field(default_factory=list)
    error: Optional[str] = None
    notification_id: Optional[str] = None


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


class JobSubmission(BaseModel):
    """Schema-driven job submission payload."""

    schema_version: int = Field(..., description="Version of the job schema used")
    values: Dict[str, Any] = Field(
        default_factory=dict,
        description="Field values keyed by schema field id",
    )
    target_host: Optional[str] = Field(
        default=None,
        description="Hostname of the connected Hyper-V host that will execute the job",
    )


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
