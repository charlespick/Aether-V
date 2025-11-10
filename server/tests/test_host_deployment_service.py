import asyncio
import sys
import tempfile
import types
from pathlib import Path
from unittest import IsolatedAsyncioTestCase, TestCase, skipIf
from unittest import mock


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:  # pragma: no cover - test path guard
    sys.path.insert(0, str(PROJECT_ROOT))


try:  # pragma: no cover - prefer real dependency when available
    pass
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
    from server.app.core.config import settings
    from server.app.services.host_deployment_service import (
        HostDeploymentService,
        HostSetupStatus,
    )
    HOST_DEPLOYMENT_IMPORT_ERROR = None
except ModuleNotFoundError as exc:  # pragma: no cover - optional dependency guard
    HostDeploymentService = None
    HostSetupStatus = None
    settings = None  # type: ignore[assignment]
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

    def test_assess_host_version_handles_empty_container_version(self):
        self.service._container_version = "   "
        needs_update, normalized, reason = self.service._assess_host_version("1.2.3")
        self.assertTrue(needs_update)
        self.assertEqual(normalized, "1.2.3")
        self.assertEqual(reason, "container version unavailable")

    def test_assess_host_version_reports_unparsable_host_version(self):
        self.service._container_version = "2.0.0"
        needs_update, normalized, reason = self.service._assess_host_version("v2")
        self.assertTrue(needs_update)
        self.assertEqual(normalized, "v2")
        self.assertEqual(reason, "host version unparsable")

    def test_assess_host_version_allows_host_ahead(self):
        self.service._container_version = "1.0.0"
        needs_update, normalized, reason = self.service._assess_host_version("1.0.1")
        self.assertFalse(needs_update)
        self.assertEqual(normalized, "1.0.1")
        self.assertEqual(reason, "host version ahead of container")

    def test_normalize_version_text_handles_bom_and_null_padding(self):
        raw_value = "\ufeff2.0.1\x00\r\n"
        self.assertEqual(
            self.service._normalize_version_text(raw_value),
            "2.0.1",
        )

    def test_normalize_version_text_returns_first_non_empty_line(self):
        raw_value = "\n\r  \n 2.3.4 \nextra"
        self.assertEqual(
            self.service._normalize_version_text(raw_value),
            "2.3.4",
        )

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
        get_version.assert_not_called()
        ensure_dir.assert_not_called()
        clear_dir.assert_not_called()

    def test_get_host_version_reads_value_with_padding(self):
        with mock.patch(
            "server.app.services.host_deployment_service.winrm_service.execute_ps_command",
            return_value=("\ufeff2.0.0\x00\r\n", "", 0),
        ) as exec_mock:
            version = self.service._get_host_version("host-1")

        self.assertEqual(version, "2.0.0")
        command = exec_mock.call_args[0][1]
        self.assertIn("\n$trimmed = $content.Trim()", command)
        self.assertIn("$trimmed = $trimmed.TrimStart([char]0xFEFF)", command)


@skipIf(
    HostDeploymentService is None,
    f"Host deployment service unavailable: {HOST_DEPLOYMENT_IMPORT_ERROR}",
)
class HostDeploymentServiceUtilityTests(TestCase):
    def setUp(self) -> None:
        self.service = HostDeploymentService()
        self.service._deployment_enabled = True
        self.service._agent_download_base_url = "https://example.test/agent"

    def test_download_file_to_host_retries_until_success(self):
        attempts: list[int] = []

        def side_effect(*args, **kwargs):
            attempts.append(1)
            if len(attempts) == 1:
                return "", "error", 1
            return "", "", 0

        with mock.patch(
            "server.app.services.host_deployment_service.winrm_service.execute_ps_command",
            side_effect=side_effect,
        ) as exec_mock, mock.patch(
            "server.app.services.host_deployment_service.time.sleep"
        ) as sleep_mock:
            result = self.service._download_file_to_host(
                "host-1", "artifact.txt", "C:/remote/artifact.txt"
            )

        self.assertTrue(result)
        self.assertGreaterEqual(exec_mock.call_count, 2)
        sleep_mock.assert_called_once()

    def test_download_file_to_host_respects_failure_after_attempts(self):
        with mock.patch.object(
            self.service, "_deployment_enabled", True
        ), mock.patch(
            "server.app.services.host_deployment_service.winrm_service.execute_ps_command",
            return_value=("", "error", 1),
        ) as exec_mock, mock.patch.object(
            settings, "agent_download_max_attempts", 2
        ), mock.patch(
            "server.app.services.host_deployment_service.time.sleep"
        ) as sleep_mock:
            result = self.service._download_file_to_host(
                "host-1", "artifact.txt", "C:/remote/artifact.txt"
            )

        self.assertFalse(result)
        self.assertEqual(exec_mock.call_count, 2)
        sleep_mock.assert_called_once()

    def test_download_file_to_host_requires_enabled_service(self):
        self.service._deployment_enabled = False
        with mock.patch(
            "server.app.services.host_deployment_service.winrm_service.execute_ps_command"
        ) as exec_mock:
            result = self.service._download_file_to_host(
                "host-1", "artifact.txt", "C:/remote/artifact.txt"
            )

        self.assertFalse(result)
        exec_mock.assert_not_called()

    def test_build_download_url_requires_configured_base(self):
        self.service._agent_download_base_url = None
        with self.assertRaises(RuntimeError):
            self.service._build_download_url("artifact.txt")

    def test_collect_script_and_iso_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            script = tmp_path / "deploy.ps1"
            script.write_text("echo")
            ignored = tmp_path / "readme.txt"
            ignored.write_text("ignore")
            iso = tmp_path / "disk.iso"
            iso.write_text("iso")
            with mock.patch(
                "server.app.services.host_deployment_service.AGENT_ARTIFACTS_DIR", tmp_path
            ):
                scripts = self.service._collect_script_files()
                isos = self.service._collect_iso_files()

        self.assertEqual([path.name for path in scripts], ["deploy.ps1"])
        self.assertEqual([path.name for path in isos], ["disk.iso"])

    def test_collect_files_handles_missing_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            missing_dir = Path(tmpdir) / "missing"
            with mock.patch(
                "server.app.services.host_deployment_service.AGENT_ARTIFACTS_DIR", missing_dir
            ):
                scripts = self.service._collect_script_files()
                isos = self.service._collect_iso_files()

        self.assertEqual(scripts, [])
        self.assertEqual(isos, [])

    def test_clear_install_directory_reports_success(self):
        with mock.patch(
            "server.app.services.host_deployment_service.winrm_service.execute_ps_command",
            return_value=("", "", 0),
        ) as exec_mock:
            self.assertTrue(self.service._clear_host_install_directory("host-1"))

        self.assertEqual(exec_mock.call_count, 1)

    def test_clear_install_directory_reports_failure(self):
        with mock.patch(
            "server.app.services.host_deployment_service.winrm_service.execute_ps_command",
            return_value=("", "boom", 1),
        ):
            self.assertFalse(self.service._clear_host_install_directory("host-1"))

    def test_verify_install_directory_empty_handles_errors(self):
        with mock.patch(
            "server.app.services.host_deployment_service.winrm_service.execute_ps_command",
            return_value=("", "boom", 1),
        ):
            self.assertFalse(self.service._verify_install_directory_empty("host-1"))

    def test_verify_expected_artifacts_present(self):
        with mock.patch(
            "server.app.services.host_deployment_service.winrm_service.execute_ps_command",
            return_value=("", "", 0),
        ):
            self.assertTrue(
                self.service._verify_expected_artifacts_present(
                    "host-1", ["a.txt", "b.txt"]
                )
            )

    def test_ps_literal_and_array_helpers(self):
        self.assertEqual(self.service._ps_literal("O'Reilly"), "'O''Reilly'")
        array_literal = self.service._ps_array_literal(["one", "two"])
        self.assertEqual(array_literal, "@('one', 'two')")
        self.assertEqual(self.service._ps_array_literal([]), "@()")

    def test_build_remote_path_uses_windows_paths(self):
        remote = self.service._build_remote_path("script.ps1")
        self.assertIn("script.ps1", remote)
        self.assertIn("\\", remote)

    def test_build_health_check_url_variants(self):
        self.service._agent_download_base_url = "https://example.test/agent"
        self.assertEqual(
            self.service._build_health_check_url(), "https://example.test/healthz"
        )
        self.service._agent_download_base_url = "invalid"
        self.assertIsNone(self.service._build_health_check_url())

    def test_ensure_inventory_ready_short_circuits_when_disabled(self):
        self.service._deployment_enabled = False
        readiness = asyncio.run(self.service.ensure_inventory_ready("host-1"))
        self.assertTrue(readiness.ready)
        self.assertFalse(readiness.preparing)
        self.assertIsNone(readiness.error)

    def test_ensure_inventory_ready_uses_cached_version(self):
        self.service._verified_host_versions["host-1"] = self.service._container_version
        readiness = asyncio.run(self.service.ensure_inventory_ready("host-1"))
        self.assertTrue(readiness.ready)
        self.assertFalse(readiness.preparing)
        self.assertIsNone(readiness.error)

    def test_ensure_inventory_ready_handles_failure(self):
        async def ensure_host_setup(hostname: str) -> bool:
            return False

        self.service.ensure_host_setup = ensure_host_setup  # type: ignore[assignment]
        self.service._host_setup_status["host-1"] = HostSetupStatus(
            state="error", error="boom"
        )
        readiness = asyncio.run(self.service.ensure_inventory_ready("host-1"))
        self.assertFalse(readiness.ready)
        self.assertFalse(readiness.preparing)
        self.assertEqual(readiness.error, "boom")


@skipIf(
    HostDeploymentService is None,
    f"Host deployment service unavailable: {HOST_DEPLOYMENT_IMPORT_ERROR}",
)
class HostDeploymentServiceIngressTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.service = HostDeploymentService()
        self.service._deployment_enabled = True
        self.service._container_version = "2.0.0"

    async def test_ensure_host_setup_waits_for_ingress_when_update_needed(self):
        wait_mock = mock.AsyncMock()
        self.service._wait_for_agent_endpoint_ready = wait_mock

        async def run_call_side_effect(hostname, func, *args, **kwargs):
            if func is self.service._get_host_version:
                return "1.0.0"
            if func is self.service._deploy_to_host:
                self.assertEqual(wait_mock.await_count, 1)
                return True
            raise AssertionError(f"Unexpected function {func}")

        run_mock = mock.AsyncMock(side_effect=run_call_side_effect)

        with mock.patch.object(self.service, "_run_winrm_call", run_mock):
            result = await self.service.ensure_host_setup("host-1")

        self.assertTrue(result)
        self.assertEqual(run_mock.await_count, 2)
        self.assertEqual(wait_mock.await_count, 1)

    async def test_ensure_host_setup_does_not_wait_when_host_current(self):
        wait_mock = mock.AsyncMock()
        self.service._wait_for_agent_endpoint_ready = wait_mock

        async def run_call_side_effect(hostname, func, *args, **kwargs):
            if func is self.service._get_host_version:
                return "2.0.0"
            raise AssertionError(f"Unexpected function {func}")

        run_mock = mock.AsyncMock(side_effect=run_call_side_effect)

        with mock.patch.object(self.service, "_run_winrm_call", run_mock):
            result = await self.service.ensure_host_setup("host-1")

        self.assertTrue(result)
        self.assertEqual(run_mock.await_count, 1)
        wait_mock.assert_not_called()

    async def test_ensure_host_setup_serializes_concurrent_invocations(self):
        self.service._wait_for_agent_endpoint_ready = mock.AsyncMock()

        deploy_started = asyncio.Event()
        release_deploy = asyncio.Event()
        call_sequence: list[str] = []

        async def run_call(hostname, func, *args, **kwargs):
            if func is self.service._get_host_version:
                call_sequence.append("version")
                return "1.0.0"
            if func is self.service._deploy_to_host:
                call_sequence.append("deploy")
                deploy_started.set()
                await release_deploy.wait()
                return True
            raise AssertionError(f"Unexpected function {func}")

        run_mock = mock.AsyncMock(side_effect=run_call)

        with mock.patch.object(self.service, "_run_winrm_call", run_mock):
            first = asyncio.create_task(self.service.ensure_host_setup("host-1"))
            await deploy_started.wait()

            second = asyncio.create_task(self.service.ensure_host_setup("host-1"))

            await asyncio.sleep(0)
            self.assertEqual(call_sequence, ["version", "deploy"])

            release_deploy.set()

            result_one, result_two = await asyncio.gather(first, second)

        self.assertTrue(result_one)
        self.assertTrue(result_two)
        self.assertEqual(run_mock.await_count, 2)
        self.assertEqual(call_sequence, ["version", "deploy"])

