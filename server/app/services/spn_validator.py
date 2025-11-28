"""Service Principal Name (SPN) validation for WinRM authentication."""

import logging
import subprocess
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


def check_wsman_spn(
    host: str, realm: Optional[str] = None
) -> Tuple[bool, str]:
    """
    Check if WSMAN SPN exists for a host.

    Uses 'setspn -Q' to query for WSMAN service principal.

    Args:
        host: Hostname to check
        realm: Optional Kerberos realm

    Returns:
        Tuple of (success: bool, message: str)
    """
    try:
        # Query for WSMAN SPN
        # Format: WSMAN/hostname or WSMAN/hostname.domain
        spn_to_check = f"WSMAN/{host}"

        # Try setspn -Q (Windows AD query)
        result = subprocess.run(
            ["setspn", "-Q", spn_to_check],
            capture_output=True,
            text=True,
            timeout=15,
        )

        # setspn -Q returns 0 if SPN is found
        if result.returncode == 0:
            # Parse output to confirm SPN exists
            if spn_to_check.lower() in result.stdout.lower():
                return (True, f"WSMAN SPN '{spn_to_check}' found")
            else:
                msg = (
                    f"WSMAN SPN '{spn_to_check}' not found in "
                    "Active Directory"
                )
                return (False, msg)
        else:
            msg = (
                f"WSMAN SPN '{spn_to_check}' not found "
                f"(setspn exit code: {result.returncode})"
            )
            return (False, msg)

    except FileNotFoundError:
        # setspn not available (likely not on Windows or not in PATH)
        # Try alternative: kvno command (attempts to get service ticket)
        try:
            kvno_spn = f"WSMAN/{host}"
            if realm:
                kvno_spn = f"{kvno_spn}@{realm}"

            result = subprocess.run(
                ["kvno", kvno_spn],
                capture_output=True,
                text=True,
                timeout=15,
            )

            if result.returncode == 0:
                return (True, "WSMAN SPN validated via kvno")
            else:
                msg = (
                    f"WSMAN SPN '{kvno_spn}' not found or inaccessible: "
                    f"{result.stderr.strip()}"
                )
                return (False, msg)

        except FileNotFoundError:
            logger.warning(
                "Neither setspn nor kvno available - "
                "cannot validate WSMAN SPN for %s",
                host,
            )
            msg = (
                "Cannot validate WSMAN SPN - "
                "setspn and kvno tools not available"
            )
            return (False, msg)
        except subprocess.TimeoutExpired:
            return (False, "WSMAN SPN check timed out using kvno")
        except Exception as exc:
            return (False, f"WSMAN SPN validation failed: {exc}")

    except subprocess.TimeoutExpired:
        return (False, "WSMAN SPN check timed out")
    except Exception as exc:
        return (False, f"WSMAN SPN check failed: {exc}")
