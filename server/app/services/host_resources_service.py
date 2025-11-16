"""Service for managing host resources configuration."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import PureWindowsPath
from typing import Any, Dict, List, Optional

import yaml

from ..core.config import settings
from .winrm_service import winrm_service

logger = logging.getLogger(__name__)


class HostResourcesService:
    """Service for loading and caching host resources configuration."""

    def __init__(self) -> None:
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    async def get_host_configuration(self, host: str) -> Optional[Dict[str, Any]]:
        """Load host resources configuration from the host.
        
        Args:
            host: Target host FQDN or hostname
            
        Returns:
            Dictionary containing host resources configuration or None if not found
        """
        async with self._lock:
            if host in self._cache:
                return self._cache[host]

        try:
            config = await self._load_configuration_from_host(host)
            if config:
                async with self._lock:
                    self._cache[host] = config
            return config
        except Exception:
            logger.exception("Failed to load host resources configuration for %s", host)
            return None

    async def _load_configuration_from_host(self, host: str) -> Optional[Dict[str, Any]]:
        """Load configuration file from host via WinRM.
        
        Args:
            host: Target host FQDN or hostname
            
        Returns:
            Parsed configuration dictionary or None
        """
        # Try JSON first, then YAML
        config_paths = [
            PureWindowsPath("C:/ProgramData/Aether-V/hostresources.json"),
            PureWindowsPath("C:/ProgramData/Aether-V/hostresources.yaml"),
        ]

        for config_path in config_paths:
            try:
                command = f"Get-Content -LiteralPath '{config_path}' -Raw -ErrorAction Stop"
                result = await asyncio.to_thread(
                    winrm_service.run_ps_command,
                    host,
                    command,
                )
                
                if result.status_code != 0:
                    continue

                content = result.std_out.strip()
                if not content:
                    continue

                # Parse based on file extension
                if str(config_path).endswith('.json'):
                    config = json.loads(content)
                else:
                    config = yaml.safe_load(content)

                # Validate required fields
                if self._validate_configuration(config):
                    logger.info(
                        "Loaded host resources configuration from %s on host %s",
                        config_path,
                        host,
                    )
                    return config
                else:
                    logger.warning(
                        "Invalid host resources configuration at %s on host %s",
                        config_path,
                        host,
                    )
            except Exception as exc:
                logger.debug(
                    "Could not load configuration from %s on host %s: %s",
                    config_path,
                    host,
                    exc,
                )
                continue

        logger.warning("No valid host resources configuration found on host %s", host)
        return None

    def _validate_configuration(self, config: Any) -> bool:
        """Validate that configuration has required structure.
        
        Args:
            config: Configuration to validate
            
        Returns:
            True if valid, False otherwise
        """
        if not isinstance(config, dict):
            return False

        required_keys = {'version', 'schema_name', 'storage_classes', 'networks', 'virtual_machines_path'}
        if not all(key in config for key in required_keys):
            return False

        if not isinstance(config.get('storage_classes'), list):
            return False

        if not isinstance(config.get('networks'), list):
            return False

        return True

    def validate_network_name(
        self,
        network_name: str,
        config: Dict[str, Any],
    ) -> bool:
        """Validate that a network name exists in the configuration.
        
        Args:
            network_name: Name of the network to validate
            config: Host resources configuration
            
        Returns:
            True if network exists, False otherwise
        """
        if not config or 'networks' not in config:
            return False

        networks = config['networks']
        if not isinstance(networks, list):
            return False

        return any(
            network.get('name') == network_name
            for network in networks
        )

    def validate_storage_class(
        self,
        storage_class: str,
        config: Dict[str, Any],
    ) -> bool:
        """Validate that a storage class exists in the configuration.
        
        Args:
            storage_class: Name of the storage class to validate
            config: Host resources configuration
            
        Returns:
            True if storage class exists, False otherwise
        """
        if not config or 'storage_classes' not in config:
            return False

        storage_classes = config['storage_classes']
        if not isinstance(storage_classes, list):
            return False

        return any(
            sc.get('name') == storage_class
            for sc in storage_classes
        )

    def get_available_networks(self, config: Dict[str, Any]) -> List[str]:
        """Get list of available network names.
        
        Args:
            config: Host resources configuration
            
        Returns:
            List of network names
        """
        if not config or 'networks' not in config:
            return []

        networks = config.get('networks', [])
        if not isinstance(networks, list):
            return []

        return [
            network['name']
            for network in networks
            if isinstance(network, dict) and 'name' in network
        ]

    def get_available_storage_classes(self, config: Dict[str, Any]) -> List[str]:
        """Get list of available storage class names.
        
        Args:
            config: Host resources configuration
            
        Returns:
            List of storage class names
        """
        if not config or 'storage_classes' not in config:
            return []

        storage_classes = config.get('storage_classes', [])
        if not isinstance(storage_classes, list):
            return []

        return [
            sc['name']
            for sc in storage_classes
            if isinstance(sc, dict) and 'name' in sc
        ]

    async def clear_cache(self, host: Optional[str] = None) -> None:
        """Clear cached configuration.
        
        Args:
            host: Specific host to clear, or None to clear all
        """
        async with self._lock:
            if host:
                self._cache.pop(host, None)
            else:
                self._cache.clear()


host_resources_service = HostResourcesService()
