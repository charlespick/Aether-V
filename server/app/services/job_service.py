"""Job execution service for VM provisioning and management."""
import logging
import asyncio
import uuid
from datetime import datetime
from typing import Dict, Optional, List
from queue import Queue
from threading import Thread
from pathlib import PureWindowsPath

from ..core.models import Job, JobStatus, VMCreateRequest, VMDeleteRequest, OSFamily
from ..core.config import settings
from .winrm_service import winrm_service

logger = logging.getLogger(__name__)


class JobService:
    """Service for managing and executing jobs."""
    
    def __init__(self):
        self.jobs: Dict[str, Job] = {}
        self._job_queue: Queue = Queue()
        self._worker_thread: Optional[Thread] = None
        self._running = False
    
    def start(self):
        """Start the job service worker."""
        logger.info("Starting job service")
        self._running = True
        self._worker_thread = Thread(target=self._worker, daemon=True)
        self._worker_thread.start()
    
    def stop(self):
        """Stop the job service worker."""
        logger.info("Stopping job service")
        self._running = False
        if self._worker_thread:
            self._worker_thread.join(timeout=5)
    
    def _worker(self):
        """Background worker to process jobs."""
        while self._running:
            try:
                job_id = self._job_queue.get(timeout=1)
                self._execute_job(job_id)
            except:
                # Queue.get timeout or other errors
                continue
    
    def _execute_job(self, job_id: str):
        """Execute a job."""
        job = self.jobs.get(job_id)
        if not job:
            logger.error(f"Job {job_id} not found")
            return
        
        logger.info(f"Executing job {job_id}: {job.job_type}")
        job.status = JobStatus.RUNNING
        job.started_at = datetime.utcnow()
        
        try:
            if job.job_type == "create_vm":
                self._execute_create_vm(job)
            elif job.job_type == "delete_vm":
                self._execute_delete_vm(job)
            else:
                raise ValueError(f"Unknown job type: {job.job_type}")
            
            job.status = JobStatus.COMPLETED
            job.completed_at = datetime.utcnow()
            logger.info(f"Job {job_id} completed successfully")
        
        except Exception as e:
            logger.error(f"Job {job_id} failed: {e}")
            job.status = JobStatus.FAILED
            job.error = str(e)
            job.completed_at = datetime.utcnow()
    
    def _execute_create_vm(self, job: Job):
        """Execute VM creation job (mirrors Ansible Provisioning.yaml)."""
        params = job.parameters
        hostname = job.target_host

        # Determine OS family from image name
        image_name = params["image_name"]
        os_family = self._determine_os_family(image_name)
        job.output.append(f"Detected OS family: {os_family}")

        script_base = PureWindowsPath(settings.host_install_directory)

        # Clear invalid parameters based on OS
        if os_family == "linux":
            # Clear domain join for Linux
            if any(k in params for k in ["guest_domain_jointarget", "guest_domain_joinuid", "guest_domain_joinpw", "guest_domain_joinou"]):
                job.output.append("WARNING: Domain join is not supported for Linux. Clearing domain join variables.")
                params["guest_domain_jointarget"] = None
                params["guest_domain_joinuid"] = None
                params["guest_domain_joinpw"] = None
                params["guest_domain_joinou"] = None
        else:  # windows
            # Clear Ansible SSH for Windows
            if any(k in params for k in ["cnf_ansible_ssh_user", "cnf_ansible_ssh_key"]):
                job.output.append("WARNING: Ansible SSH is not supported for Windows. Clearing Ansible SSH variables.")
                params["cnf_ansible_ssh_user"] = None
                params["cnf_ansible_ssh_key"] = None
        
        # Step 1: Copy Image
        job.output.append("Step 1: Copying image...")
        script_path = str(script_base / "CopyImage.ps1")
        copy_params = {
            "VMName": params["vm_name"],
            "ImageName": params["image_name"]
        }
        stdout, stderr, exit_code = winrm_service.execute_ps_script(hostname, script_path, copy_params)
        
        if exit_code != 0:
            raise Exception(f"CopyImage failed: {stderr}")
        
        vm_data_folder = stdout.strip()
        job.output.append(f"Image copied to: {vm_data_folder}")
        
        # Step 2: Copy Provisioning ISO
        job.output.append("Step 2: Copying provisioning ISO...")
        script_path = str(script_base / "CopyProvisioningISO.ps1")
        iso_params = {
            "OSFamily": os_family,
            "VMDataFolder": vm_data_folder
        }
        stdout, stderr, exit_code = winrm_service.execute_ps_script(hostname, script_path, iso_params)
        
        if exit_code != 0:
            raise Exception(f"CopyProvisioningISO failed: {stderr}")
        
        job.output.append("Provisioning ISO copied")
        
        # Step 3: Register VM
        job.output.append("Step 3: Registering VM...")
        script_path = str(script_base / "RegisterVM.ps1")
        register_params = {
            "OSFamily": os_family,
            "GBRam": params["gb_ram"],
            "CPUcores": params["cpu_cores"],
            "VMDataFolder": vm_data_folder
        }
        if params.get("vlan_id"):
            register_params["VLANId"] = params["vlan_id"]
        
        stdout, stderr, exit_code = winrm_service.execute_ps_script(hostname, script_path, register_params)
        
        if exit_code != 0:
            raise Exception(f"RegisterVM failed: {stderr}")
        
        job.output.append("VM registered and started")
        
        # Step 4: Wait for provisioning to start
        job.output.append("Step 4: Waiting for VM to signal provisioning readiness...")
        script_path = str(script_base / "WaitForProvisioningKey.ps1")
        wait_params = {
            "VMName": params["vm_name"]
        }
        stdout, stderr, exit_code = winrm_service.execute_ps_script(hostname, script_path, wait_params)
        
        if exit_code != 0:
            raise Exception(f"WaitForProvisioningKey failed: {stderr}")
        
        job.output.append("VM is ready for provisioning data")
        
        # Step 5: Publish provisioning data
        job.output.append("Step 5: Publishing provisioning data to VM...")
        script_path = str(script_base / "PublishProvisioningData.ps1")
        publish_params = {
            "GuestHostName": params["vm_name"],
            "GuestLaUid": params["guest_la_uid"]
        }
        
        # Add optional parameters
        optional_params = [
            "guest_v4_ipaddr", "guest_v4_cidrprefix", "guest_v4_defaultgw",
            "guest_v4_dns1", "guest_v4_dns2", "guest_net_dnssuffix",
            "guest_domain_jointarget", "guest_domain_joinuid", "guest_domain_joinou",
            "cnf_ansible_ssh_user", "cnf_ansible_ssh_key"
        ]
        
        for param in optional_params:
            if params.get(param):
                # Convert snake_case to PascalCase for PowerShell
                ps_param = ''.join(word.capitalize() for word in param.split('_'))
                publish_params[ps_param] = params[param]
        
        # Sensitive environment variables
        env_vars = {
            "GuestLaPw": params["guest_la_pw"]
        }
        if params.get("guest_domain_joinpw"):
            env_vars["GuestDomainJoinPw"] = params["guest_domain_joinpw"]
        
        stdout, stderr, exit_code = winrm_service.execute_ps_script(
            hostname, script_path, publish_params, env_vars
        )
        
        if exit_code != 0:
            raise Exception(f"PublishProvisioningData failed: {stderr}")
        
        job.output.append("Provisioning data published to VM")
        
        # Step 6: Add to cluster if requested
        if params.get("vm_clustered"):
            job.output.append("Step 6: Adding VM to cluster...")
            
            # Enable CredSSP
            command = "Enable-WSManCredSSP -Role Server -Force"
            stdout, stderr, exit_code = winrm_service.execute_ps_command(hostname, command)
            
            # Wait a bit for CredSSP to be ready
            import time
            time.sleep(5)
            
            # Add to cluster
            command = f"Add-ClusterVirtualMachineRole -VMName '{params['vm_name']}'"
            stdout, stderr, exit_code = winrm_service.execute_ps_command(hostname, command)
            
            # Disable CredSSP
            command = "Disable-WSManCredSSP -Role Server"
            winrm_service.execute_ps_command(hostname, command)
            
            if exit_code != 0:
                job.output.append(f"WARNING: Failed to add VM to cluster: {stderr}")
            else:
                job.output.append("VM added to cluster")
        
        job.output.append("VM provisioning completed successfully!")
    
    def _execute_delete_vm(self, job: Job):
        """Execute VM deletion job."""
        params = job.parameters
        hostname = job.target_host
        vm_name = params["vm_name"]
        force = params.get("force", False)
        
        job.output.append(f"Deleting VM: {vm_name}")
        
        # Stop VM if running
        if force:
            job.output.append("Stopping VM (forced)...")
            command = f"Stop-VM -Name '{vm_name}' -Force -TurnOff"
            stdout, stderr, exit_code = winrm_service.execute_ps_command(hostname, command)
            if exit_code != 0:
                job.output.append(f"WARNING: Failed to stop VM: {stderr}")
        
        # Remove VM
        job.output.append("Removing VM...")
        command = f"Remove-VM -Name '{vm_name}' -Force"
        stdout, stderr, exit_code = winrm_service.execute_ps_command(hostname, command)
        
        if exit_code != 0:
            raise Exception(f"Failed to remove VM: {stderr}")
        
        # Delete VM files
        job.output.append("Deleting VM files...")
        command = f"""
        $vm = Get-VM -Name '{vm_name}' -ErrorAction SilentlyContinue
        if (-not $vm) {{
            $vmPath = Get-ChildItem -Path 'C:\\ClusterStorage\\*\\Hyper-V\\{vm_name}' -Directory -ErrorAction SilentlyContinue
            if ($vmPath) {{
                Remove-Item -Path $vmPath.FullName -Recurse -Force
            }}
        }}
        """
        stdout, stderr, exit_code = winrm_service.execute_ps_command(hostname, command)
        
        job.output.append("VM deleted successfully")
    
    def _determine_os_family(self, image_name: str) -> str:
        """Determine OS family from image name."""
        image_lower = image_name.lower()
        
        linux_keywords = ["ubuntu", "rhel", "centos", "rocky", "alma", "oracle", "debian", "suse", "opensuse", "fedora", "red hat"]
        windows_keywords = ["windows", "microsoft windows"]
        
        for keyword in windows_keywords:
            if keyword in image_lower:
                return "windows"
        
        for keyword in linux_keywords:
            if keyword in image_lower:
                return "linux"
        
        raise ValueError(f"Unable to determine OS family from image name: {image_name}")
    
    def create_vm_job(self, request: VMCreateRequest) -> Job:
        """Create and queue a VM creation job."""
        job_id = str(uuid.uuid4())
        
        job = Job(
            job_id=job_id,
            job_type="create_vm",
            status=JobStatus.PENDING,
            created_at=datetime.utcnow(),
            target_host=request.hyperv_host,
            parameters=request.model_dump()
        )
        
        self.jobs[job_id] = job
        self._job_queue.put(job_id)
        
        logger.info(f"Created VM creation job {job_id} for {request.vm_name}")
        return job
    
    def delete_vm_job(self, request: VMDeleteRequest) -> Job:
        """Create and queue a VM deletion job."""
        job_id = str(uuid.uuid4())
        
        job = Job(
            job_id=job_id,
            job_type="delete_vm",
            status=JobStatus.PENDING,
            created_at=datetime.utcnow(),
            target_host=request.hyperv_host,
            parameters=request.model_dump()
        )
        
        self.jobs[job_id] = job
        self._job_queue.put(job_id)
        
        logger.info(f"Created VM deletion job {job_id} for {request.vm_name}")
        return job
    
    def get_job(self, job_id: str) -> Optional[Job]:
        """Get a job by ID."""
        return self.jobs.get(job_id)
    
    def get_all_jobs(self) -> List[Job]:
        """Get all jobs."""
        return list(self.jobs.values())


# Global job service instance
job_service = JobService()
