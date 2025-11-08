# Virtual machine deletion service

The VM deletion pipeline mirrors the provisioning job engine so destructive
operations are queued, observable, and executed as a single remote task on the
Hyper-V host. The FastAPI control plane, websocket notifications, and WinRM job
streaming all participate so operators receive immediate feedback while disks
and registrations are removed safely.

## API and queueing flow
- `/api/v1/vms/delete` validates that the VM is tracked on the requested host,
  rejects running VMs unless the caller explicitly sets `force`, and persists a
  `delete_vm` job.
- `JobService.submit_delete_job` stores metadata, emits notifications, and
  enqueues the job alongside provisioning work so the existing concurrency guard
  prevents multiple destructive operations from hitting the same host at once.
- Status transitions publish websocket events and job notifications; the
  inventory service marks VMs as `Deleting` once the job runs and prunes them on
  completion or restores the previous state on failure.

## Remote execution lifecycle
- `_execute_delete_job` reuses the host deployment service to guarantee the
  latest agent bundle (including `Invoke-DeleteVmJob.ps1`) is present before
  dispatching work.
- Job parameters are serialised to compact JSON, base64-encoded, and piped into
  the PowerShell orchestrator via the existing WinRM streaming helper so log
  output is relayed live to the UI and stored with the job record.
- The remote task service runs the command inside the long-running job worker
  pool, enforcing the same timeout envelope used for provisioning.

## Host-side deletion workflow
`Powershell/Invoke-DeleteVmJob.ps1` concentrates the destructive logic on the
host to minimise network chatter:

1. **Parse and validate request** – ensure `vm_name` is present, honour optional
   `force`, and echo the control-plane host for traceability.
2. **Failover cluster cleanup** – attempt to import the Failover Clusters module
   and remove any cluster role registered for the VM before proceeding.
3. **Shutdown guard** – refuse to continue if the VM is running (unless force is
   enabled, in which case the VM is turned off and verified).
4. **Detach and delete disks** – enumerate VHD attachments, remove them from the
   VM definition, confirm detachment, and delete the backing files.
5. **Unmount ISO media** – remove virtual DVD drives, delete attached ISOs, and
   sweep common provisioning ISO names from both the VM folder and its parent.
6. **Unregister VM** – call `Remove-VM`, verify the registration no longer
   exists, and then prune empty VM and parent directories while preserving
   unknown contents.
7. **Verification and error handling** – after each destructive action the
   script checks for the expected state change (e.g. missing files, absent VM)
   and raises terminating errors if anything persists so the job reports a
   failure promptly.

## Observability and UI
- The VM details view now exposes a delete action next to other lifecycle
  buttons. It is disabled while the VM is running and gated behind a
  confirmation dialog. Once queued, the VM state is shown as `Deleting` and
  the toast notification includes the job identifier for follow-up.
- Job overlay pages render `delete_vm` entries with the same live output stream
  used for provisioning so operators can watch cluster removal, disk deletion,
  and folder cleanup in real time.

## Safety considerations
- Every folder deletion is preceded by a check to ensure the directory is empty,
  preventing accidental removal of stray artefacts that may have been dropped in
  the VM hierarchy by hand.
- Cluster membership removal is a prerequisite, guaranteeing that cluster-managed
  workloads are gracefully detached before Hyper-V resources disappear.
- Inventory rollbacks on failure make sure the UI reflects the VM’s last known
  good state instead of leaving it flagged as `Deleting` indefinitely.
