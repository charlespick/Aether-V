import sys
import types
from pathlib import Path
from unittest import TestCase, skipIf
from unittest import mock


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:  # pragma: no cover - test path guard
    sys.path.insert(0, str(PROJECT_ROOT))


try:  # pragma: no cover - prefer real dependency when available
    import httpx  # type: ignore  # noqa: F401
except ModuleNotFoundError:  # pragma: no cover - fallback stub for minimal envs
    httpx_module = types.ModuleType("httpx")

    class HTTPError(Exception):
        pass


    class AsyncClient:  # pragma: no cover - test stub
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, *args, **kwargs):  # noqa: D401 - simple stub
            raise HTTPError("httpx stub is not functional in tests")


    httpx_module.AsyncClient = AsyncClient
    httpx_module.HTTPError = HTTPError
    sys.modules.setdefault("httpx", httpx_module)


try:  # pragma: no cover - prefer real dependency when available
    import pypsrp  # type: ignore  # noqa: F401
except ModuleNotFoundError:  # pragma: no cover - fallback stub for minimal envs
    pypsrp_module = types.ModuleType("pypsrp")

    exceptions_module = types.ModuleType("pypsrp.exceptions")

    class AuthenticationError(Exception):
        pass


    class WinRMError(Exception):
        pass


    class WinRMTransportError(Exception):
        pass


    class PSInvocationState:
        COMPLETED = object()
        FAILED = object()
        STOPPED = object()
        DISCONNECTED = object()


    exceptions_module.AuthenticationError = AuthenticationError
    exceptions_module.PSInvocationState = PSInvocationState
    exceptions_module.WinRMError = WinRMError
    exceptions_module.WinRMTransportError = WinRMTransportError

    powershell_module = types.ModuleType("pypsrp.powershell")

    class PowerShell:  # pragma: no cover - test stub
        def __init__(self, *args, **kwargs):
            self.output = []
            self.streams = types.SimpleNamespace(error=[])

        def close(self):  # noqa: D401 - simple stub
            return None


    class RunspacePool:  # pragma: no cover - test stub
        def __init__(self, *args, **kwargs):
            pass

        def close(self):  # noqa: D401 - simple stub
            return None


    powershell_module.PowerShell = PowerShell
    powershell_module.RunspacePool = RunspacePool

    wsman_module = types.ModuleType("pypsrp.wsman")

    class WSMan:  # pragma: no cover - test stub
        def __init__(self, *args, **kwargs):
            pass

        def close(self):  # noqa: D401 - simple stub
            return None


    wsman_module.WSMan = WSMan

    pypsrp_module.exceptions = exceptions_module
    pypsrp_module.powershell = powershell_module
    pypsrp_module.wsman = wsman_module

    sys.modules.setdefault("pypsrp", pypsrp_module)
    sys.modules.setdefault("pypsrp.exceptions", exceptions_module)
    sys.modules.setdefault("pypsrp.powershell", powershell_module)
    sys.modules.setdefault("pypsrp.wsman", wsman_module)


try:
    from server.app.services.host_deployment_service import HostDeploymentService
    HOST_DEPLOYMENT_IMPORT_ERROR = None
except ModuleNotFoundError as exc:  # pragma: no cover - optional dependency guard
    HostDeploymentService = None
    HOST_DEPLOYMENT_IMPORT_ERROR = exc


@skipIf(
    HostDeploymentService is None,
    f"Host deployment service unavailable: {HOST_DEPLOYMENT_IMPORT_ERROR}",
)
class HostDeploymentServiceVersionTests(TestCase):
    def setUp(self) -> None:
        self.service = HostDeploymentService()

    def test_needs_update_skips_when_versions_match_even_if_not_numeric(self):
        self.service._container_version = "unknown"
        self.assertFalse(self.service._needs_update("unknown"))

    def test_needs_update_requires_upgrade_for_lower_host_version(self):
        self.service._container_version = "2.0.1"
        self.assertTrue(self.service._needs_update("2.0.0"))

    def test_needs_update_accepts_matching_semantic_versions(self):
        self.service._container_version = "2.0.1"
        self.assertFalse(self.service._needs_update("2.0.1"))

    def test_deploy_to_host_skips_when_versions_match_after_refresh(self):
        self.service._deployment_enabled = True
        self.service._container_version = "3.1.4"

        with mock.patch.object(
            self.service, "_get_host_version", return_value="3.1.4"
        ) as get_version, mock.patch.object(
            self.service, "_ensure_install_directory"
        ) as ensure_dir, mock.patch.object(
            self.service, "_clear_host_install_directory"
        ) as clear_dir:
            result = self.service._deploy_to_host("host-1", observed_host_version="3.1.4")

        self.assertTrue(result)
        get_version.assert_called_once_with("host-1")
        ensure_dir.assert_not_called()
        clear_dir.assert_not_called()

