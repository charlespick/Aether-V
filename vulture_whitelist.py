# Vulture whitelist file
# This file contains false positives that vulture incorrectly flags as dead code.
# These are typically framework-registered functions, Pydantic fields, pytest fixtures, etc.
#
# Usage: python3 -m vulture . vulture_whitelist.py

# =============================================================================
# FastAPI Route Handlers (registered via @router.get/post decorators)
# =============================================================================
# These functions are called by FastAPI when matching HTTP requests arrive.
# Vulture cannot see this because the registration happens via decorators.

get_service_diagnostics  # routes.py - GET /api/v1/diagnostics/services
get_about  # routes.py - GET /api/v1/about
get_oss_licenses  # routes.py - GET /api/v1/about/licenses
get_inventory  # routes.py - GET /api/v1/inventory
list_hosts  # routes.py - GET /api/v1/hosts
list_host_vms  # routes.py - GET /api/v1/hosts/{host}/vms
list_vms  # routes.py - GET /api/v1/vms
start_vm_action  # routes.py - POST /api/v1/vms/{vm_id}/start
shutdown_vm_action  # routes.py - POST /api/v1/vms/{vm_id}/shutdown
stop_vm_action  # routes.py - POST /api/v1/vms/{vm_id}/stop
reset_vm_action  # routes.py - POST /api/v1/vms/{vm_id}/reset
list_jobs  # routes.py - GET /api/v1/jobs
list_vm_resources  # routes.py - GET /api/v1/resources/vms
get_vm_resource  # routes.py - GET /api/v1/resources/vms/{vm_id}
create_vm_resource  # routes.py - POST /api/v1/resources/vms
update_vm_resource  # routes.py - PUT /api/v1/resources/vms/{vm_id}
delete_vm_resource  # routes.py - DELETE /api/v1/resources/vms/{vm_id}
create_disk_resource  # routes.py - POST /api/v1/resources/vms/{vm_id}/disks
list_vm_disks  # routes.py - GET /api/v1/resources/vms/{vm_id}/disks
get_vm_disk  # routes.py - GET /api/v1/resources/vms/{vm_id}/disks/{disk_id}
update_disk_resource  # routes.py - PUT /api/v1/resources/vms/{vm_id}/disks/{disk_id}
delete_disk_resource  # routes.py - DELETE /api/v1/resources/vms/{vm_id}/disks/{disk_id}
create_nic_resource  # routes.py - POST /api/v1/resources/vms/{vm_id}/nics
list_vm_nics  # routes.py - GET /api/v1/resources/vms/{vm_id}/nics
get_vm_nic  # routes.py - GET /api/v1/resources/vms/{vm_id}/nics/{nic_id}
update_nic_resource  # routes.py - PUT /api/v1/resources/vms/{vm_id}/nics/{nic_id}
delete_nic_resource  # routes.py - DELETE /api/v1/resources/vms/{vm_id}/nics/{nic_id}
initialize_vm_resource  # routes.py - POST /api/v1/resources/vms/{vm_id}/initialize
create_managed_deployment  # routes.py - POST /api/v1/deployments
submit_noop_test  # routes.py - POST /api/v1/test/noop
get_notifications  # routes.py - GET /api/v1/notifications
mark_all_notifications_read  # routes.py - POST /api/v1/notifications/read-all
direct_login  # routes.py - POST /api/v1/auth/direct-login
login  # routes.py - GET /api/v1/auth/login
auth_callback  # routes.py - GET /api/v1/auth/callback
get_auth_token  # routes.py - GET /api/v1/auth/token
websocket_endpoint  # routes.py - WebSocket /ws

# =============================================================================
# FastAPI Middleware (registered via @app.middleware decorator)
# =============================================================================
misconfiguration_guard  # main.py - guards against startup config errors
security_and_audit_middleware  # main.py - adds security headers and audit logging

# =============================================================================
# FastAPI Page Routes (registered via @app.get decorator for HTML pages)
# =============================================================================
custom_swagger_ui_html  # main.py - GET /docs
cluster_page  # main.py - GET /cluster/{name}
host_page  # main.py - GET /host/{name}
vm_page  # main.py - GET /vm/{name}
disconnected_hosts_page  # main.py - GET /disconnected
ui  # main.py - GET /{path} catchall for SPA

# =============================================================================
# Pydantic Model Fields (accessed via JSON serialization/deserialization)
# =============================================================================
# These are schema fields that API clients read/write via JSON.
# Vulture sees them as unused class variables.

_.ip_address  # VM model field
_.size_gb  # VMDisk model field
_.file_size_gb  # VMDisk model field
_.virtual_switch  # VMNetworkAdapter model field
_.vlan  # VMNetworkAdapter model field
_.mac_address  # VMNetworkAdapter model field
_.total_clusters  # InventorySummary model field
_.disconnected_count  # InventorySummary model field
_.timestamp  # Various model fields
_.total_count  # NotificationListResponse model field
_.license  # OSSPackage model field
_.ecosystem  # OSSPackage model field
_.total  # OSSLicenseSummary model field
_.python  # OSSLicenseSummary model field
_.javascript  # OSSLicenseSummary model field
_.inflight  # Various metrics model fields
_.hosts_with_active_io  # RemoteTaskMetrics model field
_.max_connections  # RemoteTaskMetrics model field
_.total_connections  # RemoteTaskMetrics model field
_.dispatch_interval_seconds  # RemoteTaskMetrics model field
_.short_queue  # RemoteTaskMetrics model field
_.io_queue  # RemoteTaskMetrics model field
_.worker_count  # JobServiceMetrics model field
_.pending_jobs  # JobServiceMetrics model field
_.completed_jobs  # JobServiceMetrics model field
_.failed_jobs  # JobServiceMetrics model field
_.total_tracked_jobs  # JobServiceMetrics model field
_.hosts_tracked  # InventoryServiceMetrics model field
_.vms_tracked  # InventoryServiceMetrics model field
_.clusters_tracked  # InventoryServiceMetrics model field
_.refresh_in_progress  # InventoryServiceMetrics model field
_.initial_refresh_completed  # InventoryServiceMetrics model field
_.initial_refresh_succeeded  # InventoryServiceMetrics model field
_.refresh_overrun  # InventoryServiceMetrics model field
_.host_refresh_timestamps  # InventoryServiceMetrics model field
_.enabled  # HostDeploymentMetrics model field
_.startup  # HostDeploymentMetrics model field
_.remote_tasks  # ServiceDiagnosticsResponse model field
_.inventory  # ServiceDiagnosticsResponse model field
_.host_deployment  # ServiceDiagnosticsResponse model field
_.controller_type  # DiskSpec model field

# =============================================================================
# Pydantic model_config (ConfigDict for Pydantic v2 configuration)
# =============================================================================
_.model_config  # Pydantic V2 configuration attribute

# =============================================================================
# Pydantic Validators (called by Pydantic during model validation)
# =============================================================================
_.validate_parameter_sets  # GuestConfigRequest validator

# =============================================================================
# Pydantic Model Classes (used for API request/response schemas)
# =============================================================================
Config  # config.py - Pydantic settings class
ResourceDeleteRequest  # models.py - API request model

# =============================================================================
# Pydantic Config class attributes
# =============================================================================
_.env_file  # Pydantic settings configuration
_.case_sensitive  # Pydantic settings configuration

# =============================================================================
# Enum Values (may be used by external systems or reserved for future use)
# =============================================================================
_.STARTING  # VMState enum value
_.GENERAL  # TaskCategory enum value

# =============================================================================
# OIDC Metadata (fetched and used at runtime for OAuth flows)
# =============================================================================
OIDC_METADATA  # auth.py - cached OIDC discovery metadata

# =============================================================================
# Pytest Fixtures (discovered by pytest at runtime by name)
# =============================================================================
anyio_backend  # pytest-anyio fixture for async test backend configuration
pwsh_available  # pytest fixture for PowerShell availability check
restore_jwks_cache  # pytest fixture for restoring JWKS cache state
restore_agent_version_path  # pytest fixture for restoring agent version path
restore_config_validation  # pytest fixture for restoring config validation state
mock_gssapi_components  # pytest fixture for mocking GSSAPI components

# =============================================================================
# unittest TestCase Methods (called by test framework lifecycle)
# =============================================================================
_.setUp  # unittest.TestCase setup method
_.asyncSetUp  # unittest.IsolatedAsyncioTestCase async setup method
_.asyncTearDown  # unittest.IsolatedAsyncioTestCase async teardown method

# =============================================================================
# unittest.mock Magic Attributes (used to configure mock behavior)
# =============================================================================
_.return_value  # Mock return value configuration
_.side_effect  # Mock side effect configuration
_.powershell  # Mock attribute for PowerShell mock objects
_.began  # Mock attribute for timing tests
_.safe_dump  # Mock attribute for yaml.safe_dump

# =============================================================================
# Test Variables (used in unpacking or assertions)
# =============================================================================
# These are often unpacked from tuples/results but vulture doesn't track usage
exc_type  # Exception type in context manager __exit__
tb  # Traceback in context manager __exit__
vid  # VM ID variable in tests
desc  # Description variable in tests
sort_keys  # yaml.safe_dump parameter
capture_output  # subprocess.run parameter
check  # subprocess.run parameter
IMPORT_ERROR  # Test import error tracking
pytestmark  # pytest marker for test modules

# =============================================================================
# Test Helper Classes
# =============================================================================
DummyVM  # Test helper class for VM mocking

# =============================================================================
# Test Fixture Methods (match interface of real services)
# =============================================================================
_.track_job_vm  # Mock inventory service method in tests
_.clear_job_vm  # Mock inventory service method in tests
_._execute_operation  # Test helper method for operation execution

# =============================================================================
# Dataclass/Model Fields (accessed at runtime)
# =============================================================================
_.submitted_at  # TaskResult dataclass field

# =============================================================================
# Public API Methods (may be used externally or for future features)
# =============================================================================
# These are intentional public API methods that provide useful functionality
# even if not currently called internally.

generate_pkce_pair  # auth.py - PKCE helper for OAuth flows (may be used client-side)
get_session_secret  # config.py - session secret getter for WebSocket auth
_.has_completed_initial_refresh  # inventory_service.py - public status check method
_.get_notification  # notification_service.py - public API for single notification
_.get_connection_count  # websocket_service.py - diagnostics/metrics utility
_.get_session  # winrm_service.py - public API for runspace pool access
_.close_all_sessions  # winrm_service.py - cleanup API (no-op but keeps consistent interface)
_.get_container_version  # host_deployment_service.py - public getter for container version
_.deploy_to_all_hosts  # host_deployment_service.py - public API for batch deployment

# =============================================================================
# Feature Methods (implemented but not yet wired - intentional placeholders)
# =============================================================================
# These methods are implemented features that may be wired up in the future.
# Remove from whitelist once wired up or if confirmed unused.

_.create_job_completed_notification  # notification_service.py - ready for job completion events
_.cleanup_old_notifications  # notification_service.py - needs periodic task scheduling
_.clear_host_notifications  # notification_service.py - needs host removal event wiring
_.clear_cache  # host_resources_service.py - cache invalidation for config changes
