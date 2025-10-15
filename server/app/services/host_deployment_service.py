"""Service for deploying scripts and ISOs to Hyper-V hosts."""
import logging
import os
from pathlib import Path
from typing import List, Tuple
import base64

from ..core.config import settings
from .winrm_service import winrm_service

logger = logging.getLogger(__name__)


class HostDeploymentService:
    """Service for deploying artifacts (scripts and ISOs) to Hyper-V hosts."""
    
    def __init__(self):
        self._container_version: str = ""
        self._load_container_version()
    
    def _load_container_version(self):
        """Load version from container artifacts."""
        version_file = settings.version_file_path
        try:
            with open(version_file, 'r') as f:
                self._container_version = f.read().strip()
            logger.info(f"Container version: {self._container_version}")
        except Exception as e:
            logger.error(f"Failed to load container version: {e}")
            self._container_version = "0.0.0"
    
    def get_container_version(self) -> str:
        """Get the container version."""
        return self._container_version
    
    async def ensure_host_setup(self, hostname: str) -> bool:
        """
        Ensure host has correct scripts and ISOs deployed.
        
        Args:
            hostname: Target Hyper-V host
            
        Returns:
            True if setup successful, False otherwise
        """
        logger.info(f"Ensuring host setup for {hostname}")
        
        try:
            # Check host version
            host_version = self._get_host_version(hostname)
            logger.info(f"Host {hostname} version: {host_version}")
            
            if self._needs_update(host_version):
                logger.info(f"Host {hostname} needs update from {host_version} to {self._container_version}")
                return await self._deploy_to_host(hostname)
            else:
                logger.info(f"Host {hostname} is up-to-date")
                return True
                
        except Exception as e:
            logger.error(f"Failed to ensure host setup for {hostname}: {e}")
            return False
    
    def _get_host_version(self, hostname: str) -> str:
        """Get the version currently deployed on a host."""
        version_file_path = f"{settings.host_install_directory}\\version"
        
        command = f"Get-Content -Path '{version_file_path}' -ErrorAction SilentlyContinue"
        
        try:
            stdout, stderr, exit_code = winrm_service.execute_ps_command(hostname, command)
            
            if exit_code == 0 and stdout.strip():
                return stdout.strip()
            else:
                # Version file doesn't exist, return 0.0.0
                return "0.0.0"
        except Exception as e:
            logger.warning(f"Failed to get host version for {hostname}: {e}")
            return "0.0.0"
    
    def _needs_update(self, host_version: str) -> bool:
        """Check if host needs to be updated."""
        if host_version == "0.0.0":
            return True
        
        try:
            # Parse versions as semantic version tuples
            host_parts = [int(x) for x in host_version.split('.')]
            container_parts = [int(x) for x in self._container_version.split('.')]
            
            # Compare versions
            return container_parts > host_parts
        except Exception as e:
            logger.warning(f"Version comparison failed: {e}, forcing update")
            return True
    
    async def _deploy_to_host(self, hostname: str) -> bool:
        """Deploy scripts and ISOs to a host."""
        logger.info(f"Starting deployment to {hostname}")
        
        try:
            # Create installation directory
            if not self._ensure_install_directory(hostname):
                return False
            
            # Deploy scripts
            if not await self._deploy_scripts(hostname):
                return False
            
            # Deploy ISOs
            if not await self._deploy_isos(hostname):
                return False
            
            # Deploy version file
            if not self._deploy_version_file(hostname):
                return False
            
            logger.info(f"Deployment to {hostname} completed successfully")
            return True
            
        except Exception as e:
            logger.error(f"Deployment to {hostname} failed: {e}")
            return False
    
    def _ensure_install_directory(self, hostname: str) -> bool:
        """Ensure the installation directory exists on the host."""
        install_dir = settings.host_install_directory
        
        command = f"New-Item -ItemType Directory -Path '{install_dir}' -Force | Out-Null"
        
        try:
            _, stderr, exit_code = winrm_service.execute_ps_command(hostname, command)
            
            if exit_code != 0:
                logger.error(f"Failed to create directory on {hostname}: {stderr}")
                return False
            
            return True
        except Exception as e:
            logger.error(f"Failed to ensure install directory on {hostname}: {e}")
            return False
    
    async def _deploy_scripts(self, hostname: str) -> bool:
        """Deploy PowerShell scripts to host."""
        logger.info(f"Deploying scripts to {hostname}")
        
        script_dir = settings.script_path
        install_dir = settings.host_install_directory
        
        try:
            # Get list of script files
            script_files = [f for f in os.listdir(script_dir) if f.endswith('.ps1')]
            
            if not script_files:
                logger.warning(f"No script files found in {script_dir}")
                return True
            
            logger.info(f"Found {len(script_files)} scripts to deploy")
            
            for script_file in script_files:
                local_path = os.path.join(script_dir, script_file)
                remote_path = f"{install_dir}\\{script_file}"
                
                if not self._copy_file_to_host(hostname, local_path, remote_path):
                    logger.error(f"Failed to deploy script {script_file} to {hostname}")
                    return False
                
                logger.debug(f"Deployed {script_file} to {hostname}")
            
            logger.info(f"All scripts deployed to {hostname}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to deploy scripts to {hostname}: {e}")
            return False
    
    async def _deploy_isos(self, hostname: str) -> bool:
        """Deploy ISO files to host."""
        logger.info(f"Deploying ISOs to {hostname}")
        
        iso_dir = settings.iso_path
        install_dir = settings.host_install_directory
        
        try:
            # Get list of ISO files
            iso_files = [f for f in os.listdir(iso_dir) if f.endswith('.iso')]
            
            if not iso_files:
                logger.warning(f"No ISO files found in {iso_dir}")
                return False
            
            logger.info(f"Found {len(iso_files)} ISOs to deploy")
            
            for iso_file in iso_files:
                local_path = os.path.join(iso_dir, iso_file)
                remote_path = f"{install_dir}\\{iso_file}"
                
                if not self._copy_file_to_host(hostname, local_path, remote_path):
                    logger.error(f"Failed to deploy ISO {iso_file} to {hostname}")
                    return False
                
                logger.info(f"Deployed {iso_file} to {hostname}")
            
            logger.info(f"All ISOs deployed to {hostname}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to deploy ISOs to {hostname}: {e}")
            return False
    
    def _deploy_version_file(self, hostname: str) -> bool:
        """Deploy version file to host."""
        logger.info(f"Deploying version file to {hostname}")
        
        version_file = settings.version_file_path
        remote_path = f"{settings.host_install_directory}\\version"
        
        try:
            return self._copy_file_to_host(hostname, version_file, remote_path)
        except Exception as e:
            logger.error(f"Failed to deploy version file to {hostname}: {e}")
            return False
    
    def _copy_file_to_host(self, hostname: str, local_path: str, remote_path: str) -> bool:
        """
        Copy a file from the container to a remote host via WinRM.
        
        This uses base64 encoding to transfer the file content.
        """
        try:
            # Read file content
            with open(local_path, 'rb') as f:
                file_content = f.read()
            
            # Encode content to base64
            encoded_content = base64.b64encode(file_content).decode('utf-8')
            
            # Build PowerShell command to decode and write file
            # Split into chunks to avoid command length limits
            chunk_size = 8000  # Safe chunk size for WinRM
            chunks = [encoded_content[i:i+chunk_size] for i in range(0, len(encoded_content), chunk_size)]
            
            logger.debug(f"Copying {local_path} to {hostname}:{remote_path} in {len(chunks)} chunk(s)")
            
            # First, initialize the file (delete if exists)
            init_command = f"Remove-Item -Path '{remote_path}' -Force -ErrorAction SilentlyContinue"
            winrm_service.execute_ps_command(hostname, init_command)
            
            # Write each chunk
            for i, chunk in enumerate(chunks):
                if i == 0:
                    # First chunk: create new file
                    command = f"$bytes = [Convert]::FromBase64String('{chunk}'); [IO.File]::WriteAllBytes('{remote_path}', $bytes)"
                else:
                    # Subsequent chunks: append to file
                    command = f"$bytes = [Convert]::FromBase64String('{chunk}'); $existing = [IO.File]::ReadAllBytes('{remote_path}'); [IO.File]::WriteAllBytes('{remote_path}', $existing + $bytes)"
                
                _, stderr, exit_code = winrm_service.execute_ps_command(hostname, command)
                
                if exit_code != 0:
                    logger.error(f"Failed to copy file chunk {i+1}/{len(chunks)} to {hostname}: {stderr}")
                    return False
            
            logger.debug(f"Successfully copied {local_path} to {hostname}:{remote_path}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to copy file {local_path} to {hostname}:{remote_path}: {e}")
            return False
    
    async def deploy_to_all_hosts(self, hostnames: List[str]) -> Tuple[int, int]:
        """
        Deploy to all specified hosts.
        
        Args:
            hostnames: List of host names to deploy to
            
        Returns:
            Tuple of (successful_count, failed_count)
        """
        successful = 0
        failed = 0
        
        for hostname in hostnames:
            if await self.ensure_host_setup(hostname):
                successful += 1
            else:
                failed += 1
        
        return successful, failed


# Global host deployment service instance
host_deployment_service = HostDeploymentService()
