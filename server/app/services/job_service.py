"""Schema-driven job submission service."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any, Dict, Optional, List

from ..core.models import Job, JobStatus, JobSubmission, VMDeleteRequest

logger = logging.getLogger(__name__)


class JobService:
    """Service for tracking submitted jobs awaiting host orchestration."""

    def __init__(self) -> None:
        self.jobs: Dict[str, Job] = {}
        self._started = False

    def start(self) -> None:
        """Mark the job service as ready."""
        if self._started:
            return
        logger.info("Job service initialised (schema-driven queue)")
        self._started = True

    def stop(self) -> None:
        """Mark the job service as stopped."""
        if not self._started:
            return
        logger.info("Job service stopped")
        self._started = False

    def submit_provisioning_job(
        self, submission: JobSubmission, payload: Dict[str, Any], target_host: Optional[str]
    ) -> Job:
        """Persist a schema-driven provisioning job."""

        job_id = str(uuid.uuid4())
        job = Job(
            job_id=job_id,
            job_type="provision_vm",
            status=JobStatus.PENDING,
            created_at=datetime.utcnow(),
            target_host=target_host,
            parameters={
                "schema_version": submission.schema_version,
                "definition": payload,
            },
        )

        self.jobs[job_id] = job
        logger.info("Queued provisioning job %s for host %s", job_id, target_host or "<unspecified>")
        return job

    def submit_delete_job(self, request: VMDeleteRequest) -> Job:
        """Persist a VM deletion job request for future orchestration."""

        job_id = str(uuid.uuid4())
        job = Job(
            job_id=job_id,
            job_type="delete_vm",
            status=JobStatus.PENDING,
            created_at=datetime.utcnow(),
            target_host=request.hyperv_host,
            parameters=request.model_dump(),
        )

        self.jobs[job_id] = job
        logger.info("Queued delete job %s for VM %s", job_id, request.vm_name)
        return job

    def get_job(self, job_id: str) -> Optional[Job]:
        """Return a previously submitted job."""

        return self.jobs.get(job_id)

    def get_all_jobs(self) -> List[Job]:
        """Return all tracked jobs."""

        return list(self.jobs.values())


job_service = JobService()
