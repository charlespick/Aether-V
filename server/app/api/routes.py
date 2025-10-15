"""API route handlers."""
from fastapi import APIRouter, Depends, HTTPException, status
from typing import List
from datetime import datetime

from ..core.models import (
    Host, VM, Job, VMCreateRequest, VMDeleteRequest,
    InventoryResponse, HealthResponse
)
from ..core.auth import get_current_user
from ..core.config import settings
from ..services.inventory_service import inventory_service
from ..services.job_service import job_service

router = APIRouter()


@router.get("/healthz", response_model=HealthResponse, tags=["Health"])
async def health_check():
    """Health check endpoint."""
    return HealthResponse(
        status="healthy",
        version=settings.app_version,
        timestamp=datetime.utcnow()
    )


@router.get("/readyz", response_model=HealthResponse, tags=["Health"])
async def readiness_check():
    """Readiness check endpoint."""
    # Check if inventory has been initialized
    if not inventory_service.last_refresh:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Inventory not yet initialized"
        )
    
    return HealthResponse(
        status="ready",
        version=settings.app_version,
        timestamp=datetime.utcnow()
    )


@router.get("/api/v1/inventory", response_model=InventoryResponse, tags=["Inventory"])
async def get_inventory(user: dict = Depends(get_current_user)):
    """Get complete inventory of hosts and VMs."""
    hosts = inventory_service.get_all_hosts()
    vms = inventory_service.get_all_vms()
    
    return InventoryResponse(
        hosts=hosts,
        vms=vms,
        total_hosts=len(hosts),
        total_vms=len(vms),
        last_refresh=inventory_service.last_refresh
    )


@router.get("/api/v1/hosts", response_model=List[Host], tags=["Hosts"])
async def list_hosts(user: dict = Depends(get_current_user)):
    """List all Hyper-V hosts."""
    return inventory_service.get_all_hosts()


@router.get("/api/v1/hosts/{hostname}/vms", response_model=List[VM], tags=["Hosts"])
async def list_host_vms(hostname: str, user: dict = Depends(get_current_user)):
    """List VMs on a specific host."""
    return inventory_service.get_host_vms(hostname)


@router.get("/api/v1/vms", response_model=List[VM], tags=["VMs"])
async def list_vms(user: dict = Depends(get_current_user)):
    """List all VMs across all hosts."""
    return inventory_service.get_all_vms()


@router.get("/api/v1/vms/{hostname}/{vm_name}", response_model=VM, tags=["VMs"])
async def get_vm(hostname: str, vm_name: str, user: dict = Depends(get_current_user)):
    """Get details of a specific VM."""
    vm = inventory_service.get_vm(hostname, vm_name)
    
    if not vm:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"VM {vm_name} not found on host {hostname}"
        )
    
    return vm


@router.post("/api/v1/vms/create", response_model=Job, tags=["VMs"])
async def create_vm(request: VMCreateRequest, user: dict = Depends(get_current_user)):
    """Create a new VM."""
    # Validate host exists
    hosts = inventory_service.get_all_hosts()
    if request.hyperv_host not in [h.hostname for h in hosts]:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Host {request.hyperv_host} not found"
        )
    
    # Check if VM already exists
    existing_vm = inventory_service.get_vm(request.hyperv_host, request.vm_name)
    if existing_vm:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"VM {request.vm_name} already exists on host {request.hyperv_host}"
        )
    
    # Create job
    job = job_service.create_vm_job(request)
    return job


@router.post("/api/v1/vms/delete", response_model=Job, tags=["VMs"])
async def delete_vm(request: VMDeleteRequest, user: dict = Depends(get_current_user)):
    """Delete a VM."""
    # Check if VM exists
    vm = inventory_service.get_vm(request.hyperv_host, request.vm_name)
    if not vm:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"VM {request.vm_name} not found on host {request.hyperv_host}"
        )
    
    # Create job
    job = job_service.delete_vm_job(request)
    return job


@router.get("/api/v1/jobs", response_model=List[Job], tags=["Jobs"])
async def list_jobs(user: dict = Depends(get_current_user)):
    """List all jobs."""
    return job_service.get_all_jobs()


@router.get("/api/v1/jobs/{job_id}", response_model=Job, tags=["Jobs"])
async def get_job(job_id: str, user: dict = Depends(get_current_user)):
    """Get job details."""
    job = job_service.get_job(job_id)
    
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job {job_id} not found"
        )
    
    return job
