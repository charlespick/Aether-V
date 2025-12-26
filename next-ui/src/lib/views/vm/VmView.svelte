<script lang="ts">
	import { goto } from "$app/navigation";
	import { base } from "$app/paths";
	import ViewLoader from "$lib/components/ViewLoader.svelte";
	import Icon from "$lib/components/common/Icon.svelte";
	import VmActionButtons from "$lib/components/vm/VmActionButtons.svelte";
	import VmActionConfirmation from "$lib/components/vm/VmActionConfirmation.svelte";
	import VmEditModal from "$lib/components/modals/VmEditModal.svelte";
	import DiskCreateModal from "$lib/components/modals/DiskCreateModal.svelte";
	import DiskEditModal from "$lib/components/modals/DiskEditModal.svelte";
	import NicCreateModal from "$lib/components/modals/NicCreateModal.svelte";
	import NicEditModal from "$lib/components/modals/NicEditModal.svelte";
	import { useAsyncData } from "$lib/composables/useAsyncData";
	import { inventoryStore } from "$lib/stores/inventoryStore";
	import { toastStore } from "$lib/stores/toastStore";
	import type { VM } from "$lib/stores/inventoryStore";
	import {
		getVmStateMeta,
		formatOsFamily,
		formatHostname,
		extractIpAddresses,
		formatDate,
		formatValue,
				buildMemoryHardwareItems,
				formatDiskCapacity,
				extractAdapterAddresses,
				getNotesContent,
				getActionLabel,
				estimateNextState,
				formatBooleanSetting,
				formatBandwidthRange,
		} from "$lib/utils/vm";

	interface Props {
		vmId: string;
	}

	let { vmId }: Props = $props();

	interface VMData {
		vm: VM;
		inventory: any;
	}

	// Fetch VM data by ID and full inventory
	const vmData = useAsyncData<VMData>(
		async () => {
			// Fetch specific VM by ID
			const vmResponse = await fetch(
				`/api/v1/virtualmachines/${encodeURIComponent(vmId)}`,
				{
					credentials: "same-origin",
				},
			);

			if (!vmResponse.ok) {
				throw new Error(`VM ${vmId} not found`);
			}

			const vm = await vmResponse.json();

			// Fetch full inventory for context
			const inventory = inventoryStore.getData() || {
				hosts: [],
				vms: [],
				clusters: [],
			};

			return { vm, inventory };
		},
		{
			cache: false,
			refetchOnMount: true,
		},
	);

	// Re-fetch data when vmId changes
	$effect(() => {
		vmId;
		vmData.execute();
	});

	const vm = $derived($vmData.data?.vm);
	const inventory = $derived($vmData.data?.inventory);
	const environmentName = inventoryStore.environmentName;

	// State management
	let activeTab = $state("hardware");
	let actionInProgress = $state(false);
	let confirmingAction = $state<{
		action: string;
		buttonRef: HTMLElement;
	} | null>(null);
	let currentVmState = $state<string | undefined>(undefined);

	// Modal state
	let showVmEditModal = $state(false);
	let showDiskCreateModal = $state(false);
	let showDiskEditModal = $state(false);
	let showNicCreateModal = $state(false);
	let showNicEditModal = $state(false);
	let selectedDisk = $state<any>(null);
	let selectedNic = $state<any>(null);

	// Update local state when VM data changes
	$effect(() => {
		if (vm) {
			currentVmState = vm.state;
		}
	});

	const displayState = $derived(currentVmState || vm?.state || "Unknown");
	const meta = $derived(getVmStateMeta(displayState));

	// Find host info
	const hostInfo = $derived(
		vm && inventory
			? inventory.hosts?.find((h: any) => h.hostname === vm.host)
			: null,
	);

		// Determine cluster status
		const clusterStatus = $derived(() => {
				if (!vm) return { isClustered: false, clusterName: null };

				// Use the authoritative clustered boolean from inventory
				const isClustered =
						vm.clustered === true || vm.clustered === "true" || vm.clustered === "True";
				const clusterName = isClustered ? (vm.cluster_name ?? null) : null;

				return {
						isClustered,
						clusterName,
				};
		});

		const vmTabs = [
				{ id: "hardware", label: "VM Hardware" },
				{ id: "disks", label: "Disks" },
				{ id: "networks", label: "Networks" },
				{ id: "security", label: "Security" },
				{ id: "boot", label: "Boot & Host" },
				{ id: "integration", label: "Integration Services" },
				{ id: "notes", label: "Notes" },
		];

		const integrationServices = $derived([
				{
						key: "shutdown",
						label: "Guest Shutdown",
						value: vm?.integration_services_shutdown,
						description: "Gracefully request shutdown from the guest OS.",
				},
				{
						key: "time",
						label: "Time Synchronization",
						value: vm?.integration_services_time,
						description: "Keeps guest clocks aligned with the host.",
				},
				{
						key: "data_exchange",
						label: "Data Exchange",
						value: vm?.integration_services_data_exchange,
						description: "Shares host and guest information for tooling.",
				},
				{
						key: "heartbeat",
						label: "Heartbeat",
						value: vm?.integration_services_heartbeat,
						description: "Monitors guest health via heartbeat signals.",
				},
				{
						key: "vss_backup",
						label: "Backup (VSS)",
						value: vm?.integration_services_vss_backup,
						description: "Coordinates backup operations using VSS.",
				},
				{
						key: "guest_services",
						label: "Guest Services",
						value: vm?.integration_services_guest_services,
						description: "Enables file copy and guest-side utilities.",
				},
		]);

		const securityProfile = $derived({
				secureBoot: formatBooleanSetting(vm?.secure_boot_enabled),
				secureBootTemplate: formatValue(vm?.secure_boot_template),
				tpm: formatBooleanSetting(vm?.trusted_platform_module_enabled),
				keyProtector: formatValue(vm?.key_protector_kind),
		});

		const bootProfile = $derived({
				primaryBootDevice: formatValue(vm?.primary_boot_device, "Not configured"),
				hostRecoveryAction: formatValue(vm?.host_recovery_action, "Use host policy"),
				hostStopAction: formatValue(vm?.host_stop_action, "Use host policy"),
		});

	// Handle action button clicks
	function handleAction(action: string) {
		if (action === "edit") {
			showVmEditModal = true;
			return;
		}

		// Actions requiring confirmation
		if (["stop", "shutdown", "reset", "delete"].includes(action)) {
			const buttonRef = document.querySelector(
				`[data-action="${action}"]`,
			) as HTMLElement;
			if (buttonRef) {
				confirmingAction = { action, buttonRef };
			}
			return;
		}

		// Execute immediately
		executeVmAction(action);
	}

	// Execute VM action
	async function executeVmAction(action: string) {
		if (!vm) return;

		confirmingAction = null;
		actionInProgress = true;

		const actionLabel = getActionLabel(action);
		const endpoint =
			action === "delete"
				? `/api/v1/virtualmachines/${encodeURIComponent(vm.id)}?delete_disks=true&force=false`
				: `/api/v1/virtualmachines/${encodeURIComponent(vm.id)}/${action}`;

		toastStore.info(`Sending ${actionLabel} request...`, {
			title: `${actionLabel.charAt(0).toUpperCase()}${actionLabel.slice(1)} in progress`,
		});

		try {
			const response = await fetch(endpoint, {
				method: action === "delete" ? "DELETE" : "POST",
				credentials: "same-origin",
			});

			const payload = await response.json().catch(() => null);

			if (response.ok) {
				const message =
					payload?.message ||
					`${actionLabel.charAt(0).toUpperCase()}${actionLabel.slice(1)} command accepted for VM ${vm.name}.`;

				toastStore.success(message, {
					title: "VM action accepted",
				});

				// Update optimistic state
				currentVmState = estimateNextState(action);

				// Refresh data after a delay
				setTimeout(() => {
					vmData.execute();
				}, 400);
			} else {
				let detail =
					payload?.detail ||
					payload?.message ||
					response.statusText ||
					"Request failed";

				// Enhanced shutdown error
				if (action === "shutdown" && typeof detail === "string") {
					const message = detail.toLowerCase();
					if (
						message.includes("stop-vm") ||
						message.includes("shutdown") ||
						message.includes("unspecified") ||
						message.includes("failed")
					) {
						detail +=
							'\n\nNote: Graceful shutdown requires the guest OS to be responsive and have working Hyper-V Integration Services. If the VM is unresponsive, use "Turn Off" instead.';
					}
				}

				toastStore.error(`Unable to ${actionLabel} VM: ${detail}`, {
					title: "VM action failed",
				});
			}
		} catch (error: any) {
			toastStore.error(`Failed to ${actionLabel} VM: ${error.message}`, {
				title: "VM action failed",
			});
		} finally {
			actionInProgress = false;
		}
	}

	// Handle resource actions (disk/nic)
	async function handleResourceDelete(
		resourceType: "disk" | "nic",
		resourceId: string,
	) {
		if (!vm) return;

		const resourceName =
			resourceType === "disk" ? "disk" : "network adapter";
		const endpoint =
			resourceType === "disk"
				? `/api/v1/virtualmachines/${encodeURIComponent(vm.id)}/disks/${encodeURIComponent(resourceId)}`
				: `/api/v1/virtualmachines/${encodeURIComponent(vm.id)}/networkadapters/${encodeURIComponent(resourceId)}`;

		toastStore.info(`Deleting ${resourceName}...`, {
			title: "Deleting resource",
		});

		try {
			const response = await fetch(endpoint, {
				method: "DELETE",
				credentials: "same-origin",
			});

			const payload = await response.json().catch(() => null);

			if (response.ok) {
				const message =
					payload?.message ||
					`${resourceName.charAt(0).toUpperCase() + resourceName.slice(1)} deletion queued.`;
				toastStore.success(message, {
					title: "Resource deletion queued",
				});

				// Refresh view
				setTimeout(() => {
					vmData.execute();
				}, 400);
			} else {
				const detail =
					payload?.detail ||
					payload?.message ||
					response.statusText ||
					"Request failed";
				const errorMsg =
					typeof detail === "string"
						? detail
						: JSON.stringify(detail);
				toastStore.error(
					`Failed to delete ${resourceName}: ${errorMsg}`,
					{
						title: "Deletion failed",
					},
				);
			}
		} catch (error: any) {
			toastStore.error(
				`Failed to delete ${resourceName}: ${error.message}`,
				{
					title: "Deletion failed",
				},
			);
		}
	}
</script>

<svelte:head>
	<title>{$environmentName} - {vm?.name || "VM"}</title>
</svelte:head>

<ViewLoader loading={$vmData.loading} error={$vmData.error} skeleton="vm">
	{#if vm}
		{@const osName = formatOsFamily(vm)}
		{@const ipAddresses = extractIpAddresses(vm)}
		{@const memoryItems = buildMemoryHardwareItems(vm)}
		{@const disks = Array.isArray(vm.disks) ? vm.disks : []}
		{@const networks = Array.isArray(vm.networks) ? vm.networks : []}
		{@const notesContent = getNotesContent(vm)}
		{@const cluster = clusterStatus()}

		<div class="vm-header">
			<div class="vm-title-group">
				<h1 class="page-title">{vm.name}</h1>
				<span class="status {meta.badgeClass}">{meta.label}</span>
			</div>
			<VmActionButtons {vm} {actionInProgress} onAction={handleAction} />
		</div>

		<p class="subtitle">
			Virtual Machine • Generation {formatValue(vm.generation)} • Version {formatValue(
				vm.version,
			)}
		</p>

		<!-- Confirmation dialog -->
		{#if confirmingAction}
			<VmActionConfirmation
				action={confirmingAction.action}
				vmName={vm.name}
				buttonRef={confirmingAction.buttonRef}
				onConfirm={() => executeVmAction(confirmingAction!.action)}
				onCancel={() => (confirmingAction = null)}
			/>
		{/if}

		<!-- VM Overview -->
		<section
			class="vm-overview-panel surface-card"
			aria-label="Virtual machine overview"
		>
			<div class="section-header">
				<h2>Virtual Machine Information</h2>
			</div>
			<div class="vm-overview-grid">
				<div class="vm-overview-item">
					<span class="vm-overview-label">Hyper-V Host</span>
					<span class="vm-overview-value">
						<a
							href="{base}/host/{encodeURIComponent(vm.host)}"
							class="vm-link"
							onclick={(e) => {
								e.preventDefault();
								goto(
									`${base}/host/${encodeURIComponent(vm.host)}`,
								);
							}}
						>
							{formatHostname(vm.host)}
						</a>
					</span>
				</div>
				<div class="vm-overview-item">
					<span class="vm-overview-label">IP Address(es)</span>
					<span class="vm-overview-value">{ipAddresses}</span>
				</div>
				<div class="vm-overview-item">
					<span class="vm-overview-label">Operating System</span>
					<span class="vm-overview-value">{osName}</span>
				</div>
				<div class="vm-overview-item">
					<span class="vm-overview-label">Clustered</span>
					<span class="vm-overview-value">
						{#if cluster.isClustered && cluster.clusterName}
							{@const clusterName = cluster.clusterName}
							Yes (<a
								href="{base}/cluster/{encodeURIComponent(
									clusterName,
								)}"
								class="vm-link"
								onclick={(e) => {
									e.preventDefault();
									goto(
										`${base}/cluster/${encodeURIComponent(clusterName)}`,
									);
								}}
							>
								{clusterName}
							</a>)
						{:else}
							{cluster.isClustered ? "Yes" : "No"}
						{/if}
					</span>
				</div>
				<div class="vm-overview-item">
					<span class="vm-overview-label">Created</span>
					<span class="vm-overview-value"
						>{formatDate(vm.created_at)}</span
					>
				</div>
			</div>
		</section>

		<!-- Tabbed Details -->
		<section class="vm-detail-tabs" aria-label="Virtual machine details">
						<div
								class="vm-tab-list"
								role="tablist"
								aria-label="Virtual machine detail tabs"
						>
								{#each vmTabs as tab}
										<button
												class="vm-tab"
												class:active={activeTab === tab.id}
						role="tab"
						id="vm-tab-{tab.id}"
						aria-selected={activeTab === tab.id}
						tabindex={activeTab === tab.id ? 0 : -1}
						onclick={() => (activeTab = tab.id)}
					>
						{tab.label}
					</button>
				{/each}
			</div>

			<div
				class="vm-tab-panels surface-card"
				class:first-tab-active={activeTab === "hardware"}
			>
				<!-- Hardware Tab -->
				{#if activeTab === "hardware"}
					<div
						class="vm-tab-panel"
						role="tabpanel"
						aria-labelledby="vm-tab-hardware"
					>
						<div class="vm-hardware-grid">
							<div class="vm-hardware-item">
								<span class="vm-property-label">CPU Cores</span>
								<span class="vm-property-value"
									>{formatValue(vm.cpu_cores)}</span
								>
							</div>
							{#each memoryItems as item}
								<div class="vm-hardware-item">
									<span class="vm-property-label"
										>{item.label}</span
									>
									<span class="vm-property-value"
										>{item.value}</span
									>
								</div>
							{/each}
							<div class="vm-hardware-item">
								<span class="vm-property-label">Generation</span
								>
								<span class="vm-property-value"
									>{formatValue(vm.generation)}</span
								>
							</div>
							<div class="vm-hardware-item">
								<span class="vm-property-label"
									>Configuration Version</span
								>
								<span class="vm-property-value"
									>{formatValue(vm.version)}</span
								>
							</div>
						</div>
					</div>
				{/if}

				<!-- Disks Tab -->
				{#if activeTab === "disks"}
					<div
						class="vm-tab-panel vm-tab-panel--table"
						role="tabpanel"
						aria-labelledby="vm-tab-disks"
					>
						<div class="vm-table">
														<div class="table-header">
																<div>Disk</div>
																<div>Type</div>
																<div>Capacity</div>
																<div>Storage Class</div>
																<div>Location</div>
																<div>Actions</div>
														</div>
														{#if disks.length === 0}
								<div class="vm-empty-row">
									Disk information not available yet.
								</div>
							{:else}
								{#each disks as disk}
																		<div class="table-row">
																				<div>{disk.name || "Disk"}</div>
																				<div>{disk.type || "—"}</div>
																				<div>{formatDiskCapacity(disk)}</div>
																				<div>{formatValue(disk.storage_class)}</div>
																				<div>{disk.path || "—"}</div>
																				<div class="vm-resource-actions">
																					<button
																						type="button"
																						class="resource-menu-btn"
																						aria-label="Edit disk"
																						title="Edit"
																						onclick={() => {
																							selectedDisk = disk;
																							showDiskEditModal = true;
																						}}
																					>
																						<Icon name="edit" size={18} />
																					</button>
																					<button
																						type="button"
																						class="resource-menu-btn text-danger"
																						aria-label="Delete disk"
																						title="Delete"
																						onclick={() => handleResourceDelete("disk", disk.id)}
																					>
																						<Icon name="delete" size={18} />
																					</button>
																				</div>
									</div>
								{/each}
							{/if}
						</div>
						<div class="vm-tab-actions">
							<button
								class="action-btn"
								onclick={() => {
									showDiskCreateModal = true;
								}}
							>
								<Icon
									name="add_circle"
									className="action-icon"
									size={24}
								/>
								<span>Add Disk</span>
							</button>
						</div>
					</div>
				{/if}

				<!-- Networks Tab -->
				{#if activeTab === "networks"}
					<div
						class="vm-tab-panel vm-tab-panel--table"
						role="tabpanel"
						aria-labelledby="vm-tab-networks"
					>
												<div class="vm-table">
														<div class="table-header">
																<div>Adapter</div>
																<div>IP Address</div>
																<div>Network</div>
																<div>Switch / VLAN</div>
																<div>MAC & Mode</div>
																<div>Security</div>
																<div>Bandwidth</div>
																<div>Actions</div>
														</div>
														{#if networks.length === 0}
																<div class="vm-empty-row">
																		Network details not available yet.
																</div>
														{:else}
																{#each networks as adapter}
																		{@const networkDisplay =
																				adapter.network ||
																				(adapter.virtual_switch &&
																				adapter.vlan_id
																						? `${adapter.virtual_switch}/${adapter.vlan_id}`
																						: adapter.vlan_id
																								? `VLAN ${adapter.vlan_id}`
																								: adapter.virtual_switch ||
																										"—")}
																		<div class="table-row">
																				<div>
																						{adapter.adapter_name || "Adapter"}
																				</div>
																				<div>
																						{extractAdapterAddresses(adapter)}
																				</div>
																				<div>{networkDisplay}</div>
																				<div class="table-metadata">
																						<div class="metadata-label">Virtual Switch</div>
																						<div class="metadata-value">{formatValue(adapter.virtual_switch)}</div>
																						<div class="metadata-label">VLAN</div>
																						<div class="metadata-value">{formatValue(adapter.vlan_id)}</div>
																				</div>
																				<div class="table-metadata">
																						<div class="metadata-label">MAC Address</div>
																						<div class="metadata-value">{formatValue(adapter.mac_address)}</div>
																						<div class="metadata-label">Assignment</div>
																						<div class="metadata-value">{formatValue(adapter.mac_address_config)}</div>
																				</div>
																				<div class="security-badges">
																						{#if typeof adapter.dhcp_guard !== "undefined"}
																								<span class={`badge ${adapter.dhcp_guard ? "badge-success" : "badge-muted"}`}>
																										DHCP Guard {adapter.dhcp_guard ? "On" : "Off"}
																								</span>
																						{/if}
																						{#if typeof adapter.router_guard !== "undefined"}
																								<span class={`badge ${adapter.router_guard ? "badge-success" : "badge-muted"}`}>
																										Router Guard {adapter.router_guard ? "On" : "Off"}
																								</span>
																						{/if}
																						{#if typeof adapter.mac_spoof_guard !== "undefined"}
																								<span class={`badge ${adapter.mac_spoof_guard ? "badge-success" : "badge-muted"}`}>
																										MAC Spoof Guard {adapter.mac_spoof_guard ? "On" : "Off"}
																								</span>
																						{/if}
																						{#if typeof adapter.dhcp_guard === "undefined" && typeof adapter.router_guard === "undefined" && typeof adapter.mac_spoof_guard === "undefined"}
																								<span class="badge badge-muted">Security defaults</span>
																						{/if}
																				</div>
																				<div>
																						{formatBandwidthRange(
																								adapter.min_bandwidth_mbps,
																								adapter.max_bandwidth_mbps,
																						)}
																				</div>
																				<div class="vm-resource-actions">
																					<button
																						type="button"
																						class="resource-menu-btn"
																						aria-label="Edit network adapter"
																						title="Edit"
																						onclick={() => {
																							selectedNic = adapter;
																							showNicEditModal = true;
																						}}
																					>
																						<Icon name="edit" size={18} />
																					</button>
																					<button
																						type="button"
																						class="resource-menu-btn text-danger"
																						aria-label="Delete network adapter"
																						title="Delete"
																						onclick={() => handleResourceDelete("nic", adapter.id)}
																					>
																						<Icon name="delete" size={18} />
																					</button>
																				</div>
									</div>
								{/each}
							{/if}
						</div>
						<div class="vm-tab-actions">
							<button
								class="action-btn"
								onclick={() => {
									showNicCreateModal = true;
								}}
							>
								<Icon
									name="add_circle"
									className="action-icon"
									size={24}
								/>
								<span>Add Network Adapter</span>
							</button>
						</div>
										</div>
								{/if}

								<!-- Security Tab -->
								{#if activeTab === "security"}
										<div
												class="vm-tab-panel vm-tab-panel--grid"
												role="tabpanel"
												aria-labelledby="vm-tab-security"
										>
												<div class="vm-grid">
														<div class="vm-card">
																<div class="vm-property-label">Secure Boot</div>
																<div class="vm-property-value">{securityProfile.secureBoot}</div>
																<div class="vm-helper-text">Template: {securityProfile.secureBootTemplate}</div>
														</div>
														<div class="vm-card">
																<div class="vm-property-label">Trusted Platform Module</div>
																<div class="vm-property-value">{securityProfile.tpm}</div>
																<div class="vm-helper-text">Reported status from host</div>
														</div>
														<div class="vm-card">
																<div class="vm-property-label">Key Protector</div>
																<div class="vm-property-value">{securityProfile.keyProtector}</div>
																<div class="vm-helper-text">Indicates how the VM is shielded</div>
														</div>
												</div>
										</div>
								{/if}

								<!-- Boot & Host Tab -->
								{#if activeTab === "boot"}
										<div
												class="vm-tab-panel vm-tab-panel--grid"
												role="tabpanel"
												aria-labelledby="vm-tab-boot"
										>
												<div class="vm-grid">
														<div class="vm-card">
																<div class="vm-property-label">Primary Boot Device</div>
																<div class="vm-property-value">{bootProfile.primaryBootDevice}</div>
																<div class="vm-helper-text">Device Hyper-V uses first during startup</div>
														</div>
														<div class="vm-card">
																<div class="vm-property-label">Host Recovery Action</div>
																<div class="vm-property-value">{bootProfile.hostRecoveryAction}</div>
																<div class="vm-helper-text">Action when the host service recovers</div>
														</div>
														<div class="vm-card">
																<div class="vm-property-label">Host Stop Action</div>
																<div class="vm-property-value">{bootProfile.hostStopAction}</div>
																<div class="vm-helper-text">Behavior when the host stops unexpectedly</div>
														</div>
												</div>
										</div>
								{/if}

								<!-- Integration Services Tab -->
								{#if activeTab === "integration"}
										<div
												class="vm-tab-panel vm-tab-panel--grid"
												role="tabpanel"
												aria-labelledby="vm-tab-integration"
										>
												<div class="integration-grid">
														{#each integrationServices as service}
																<div class="integration-card">
																		<div class="integration-header">
																				<span class="integration-name">{service.label}</span>
																				<span
																						class={`badge ${service.value ? "badge-success" : "badge-muted"}`}
																						aria-label={`${service.label} is ${service.value ? "enabled" : "disabled"}`}
																				>
																						{formatBooleanSetting(service.value)}
																				</span>
																		</div>
																		<div class="integration-description">{service.description}</div>
																</div>
														{/each}
												</div>
										</div>
								{/if}

								<!-- Notes Tab -->
								{#if activeTab === "notes"}
										<div
												class="vm-tab-panel vm-tab-panel--notes"
						role="tabpanel"
						aria-labelledby="vm-tab-notes"
					>
						<div class="vm-notes" aria-live="polite">
							<div class="vm-notes-content">{notesContent}</div>
						</div>
					</div>
				{/if}
			</div>
		</section>
	{/if}
</ViewLoader>

{#if vm}
	<VmEditModal
		bind:isOpen={showVmEditModal}
		{vm}
		onSuccess={() => vmData.execute()}
		onClose={() => (showVmEditModal = false)}
	/>

	<DiskCreateModal
		bind:isOpen={showDiskCreateModal}
		vmId={vm.id}
		vmName={vm.name}
		onSuccess={() => vmData.execute()}
		onClose={() => (showDiskCreateModal = false)}
	/>

	{#if selectedDisk}
		<DiskEditModal
			bind:isOpen={showDiskEditModal}
			vmId={vm.id}
			vmName={vm.name}
			disk={selectedDisk}
			onSuccess={() => vmData.execute()}
			onClose={() => {
				showDiskEditModal = false;
				selectedDisk = null;
			}}
		/>
	{/if}

	<NicCreateModal
		bind:isOpen={showNicCreateModal}
		vmId={vm.id}
		vmName={vm.name}
		onSuccess={() => vmData.execute()}
		onClose={() => (showNicCreateModal = false)}
	/>

	{#if selectedNic}
		<NicEditModal
			bind:isOpen={showNicEditModal}
			vmId={vm.id}
			vmName={vm.name}
			nic={selectedNic}
			onSuccess={() => vmData.execute()}
			onClose={() => {
				showNicEditModal = false;
				selectedNic = null;
			}}
		/>
	{/if}
{/if}

<style>
	/* VM Header */
	.vm-header {
		display: flex;
		justify-content: space-between;
		align-items: baseline;
		margin-bottom: 0;
		gap: 1.5rem;
	}

	.vm-title-group {
		display: flex;
		align-items: baseline;
		gap: 1rem;
	}

	.page-title {
		font-size: 2rem;
		font-weight: 700;
		margin: 0 0 0.5rem 0;
		color: var(--text-primary);
	}

	.subtitle {
		color: var(--text-secondary);
		margin: 0 0 1.5rem 0;
		font-size: 0.875rem;
	}

	.status {
		display: inline-block;
		padding: 0.375rem 0.875rem;
		border-radius: var(--radius-full, 9999px);
		font-size: 0.875rem;
		font-weight: 600;
		white-space: nowrap;
		vertical-align: baseline;
		line-height: 1;
		transform: translateY(-0.375rem);
	}

	.status-success {
		background: var(--success);
		color: white;
	}

	.status-off {
		background: var(--text-tertiary);
		color: white;
	}

	.status-warning {
		background: var(--warning);
		color: white;
	}

	.status-info {
		background: var(--info, #3b82f6);
		color: white;
	}

	.status-danger {
		background: var(--danger);
		color: white;
	}

	.status-unknown {
		background: var(--bg-tertiary);
		color: var(--text-secondary);
	}

	/* VM Overview Panel */
	.vm-overview-panel {
		margin-bottom: 2rem;
	}

	.surface-card {
		background: var(--bg-tertiary);
		border: 1px solid var(--border-color);
		border-radius: var(--radius-lg);
		padding: 1.5rem;
	}

	.section-header {
		margin-bottom: 1.25rem;
	}

	.section-header h2 {
		font-size: 1.125rem;
		font-weight: 600;
		margin: 0;
		color: var(--text-primary);
	}

	.vm-overview-grid {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
		gap: 1.5rem;
	}

	.vm-overview-item {
		display: flex;
		flex-direction: column;
		gap: 0.375rem;
	}

	.vm-overview-label {
		font-size: 0.875rem;
		color: var(--text-secondary);
		font-weight: 500;
	}

	.vm-overview-value {
		font-size: 1rem;
		color: var(--text-primary);
	}

	.vm-link {
		color: var(--primary, #3b82f6);
		text-decoration: none;
		transition: color 0.2s ease;
	}

	.vm-link:hover {
		color: var(--primary-hover, #2563eb);
		text-decoration: underline;
	}

	/* Tabs */
	.vm-detail-tabs {
		margin-bottom: 2rem;
	}

	.vm-tab-list {
		display: flex;
		gap: 0.25rem;
		margin-bottom: -1px;
		position: relative;
		z-index: 1;
	}

	.vm-tab {
		padding: 0.75rem 1.5rem;
		border: 1px solid transparent;
		border-bottom: none;
		border-radius: var(--radius-md) var(--radius-md) 0 0;
		background: transparent;
		color: var(--text-secondary);
		font-size: 0.875rem;
		font-weight: 500;
		cursor: pointer;
		transition: all 0.2s ease;
		position: relative;
	}

	.vm-tab:hover {
		color: var(--text-primary);
		background: var(--bg-tertiary);
	}

	.vm-tab.active {
		color: var(--text-primary);
		background: var(--bg-tertiary);
		border-color: var(--border-color);
		border-bottom-color: var(--bg-tertiary);
	}

	.vm-tab-panels {
		min-height: fit-content;
	}

	/* Remove top-left corner radius when first tab is active */
	.vm-tab-panels.first-tab-active {
		border-top-left-radius: 0;
	}

	/* Hardware Grid */
	.vm-hardware-grid {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
		gap: 1.5rem;
	}

	.vm-hardware-item {
		display: flex;
		flex-direction: column;
		gap: 0.375rem;
	}

	.vm-property-label {
		font-size: 0.875rem;
		color: var(--text-secondary);
		font-weight: 500;
	}

	.vm-property-value {
		font-size: 1rem;
		color: var(--text-primary);
		font-weight: 500;
	}

	/* Table Styles */

	.vm-table {
		background-color: var(--bg-tertiary);
		border-radius: var(--radius-lg);
		border: 1px solid var(--border-color);
		overflow: hidden;
	}

	.table-header {
		display: grid;
		gap: 1rem;
		padding: 1rem;
		border-bottom: 2px solid var(--border-color);
		font-size: 0.75rem;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		color: var(--text-primary);
	}

		/* Disks table: 6 columns */
		.vm-tab-panel[aria-labelledby="vm-tab-disks"] .table-header,
		.vm-tab-panel[aria-labelledby="vm-tab-disks"] .table-row {
				grid-template-columns: 1.5fr 1fr 1fr 1fr 1.5fr 80px;
		}

		/* Networks table: 8 columns */
		.vm-tab-panel[aria-labelledby="vm-tab-networks"] .table-header,
		.vm-tab-panel[aria-labelledby="vm-tab-networks"] .table-row {
				grid-template-columns: 1fr 1.2fr 1fr 1fr 1fr 1.1fr 1fr 80px;
		}

	.table-row {
		display: grid;
		gap: 1rem;
		padding: 1rem;
		border-bottom: 1px solid var(--border-color);
		transition: background-color var(--transition-fast);
		align-items: center;
	}

	.table-row:last-child {
		border-bottom: none;
	}

	.table-row:hover {
		background-color: var(--bg-hover);
	}

	.table-row > div {
		color: var(--text-primary);
	}

	.vm-empty-row {
		text-align: center;
		color: var(--text-secondary);
		font-style: italic;
		padding: 2rem;
	}

	.vm-resource-actions {
		display: flex;
		justify-content: center;
		align-items: center;
	}

	.resource-menu-btn {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: 32px;
		height: 32px;
		padding: 0;
		border: 1px solid transparent;
		border-radius: var(--radius-md);
		background: transparent;
		color: var(--text-secondary);
		cursor: pointer;
		transition: all 0.2s ease;
	}

	.resource-menu-btn:hover {
		background: var(--bg-tertiary);
		color: var(--text-primary);
		border-color: var(--border-color);
	}

	/* Tab Actions */
	.vm-tab-actions {
		padding: 0.75rem 0 0 0;
	}

	.action-btn {
		display: inline-flex;
		align-items: center;
		gap: 0.625rem;
		padding: 0.625rem 1.125rem;
		border: none;
		border-radius: var(--radius-md);
		background: var(--primary, #3b82f6);
		color: white;
		font-size: 0.875rem;
		font-weight: 600;
		cursor: pointer;
		transition: all 0.2s ease;
		box-shadow: 0 1px 2px rgba(0, 0, 0, 0.05);
	}

	.action-btn:hover {
		background: var(--primary-hover, #2563eb);
		box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
	}

	.vm-notes {
		min-height: 200px;
	}

		.vm-notes-content {
				padding: 1.25rem;
				background: var(--bg-tertiary);
				border: 1px solid var(--border-color);
				border-radius: var(--radius-md);
				white-space: pre-wrap;
				word-wrap: break-word;
				color: var(--text-primary);
				line-height: 1.6;
				font-size: 0.9375rem;
		}

		.table-metadata {
				display: grid;
				grid-template-columns: repeat(2, minmax(0, 1fr));
				gap: 0.25rem 0.75rem;
		}

		.metadata-label {
				font-size: 0.75rem;
				color: var(--text-secondary);
		}

		.metadata-value {
				font-weight: 600;
				color: var(--text-primary);
		}

		.security-badges {
				display: flex;
				flex-wrap: wrap;
				gap: 0.5rem;
		}

		.badge {
				display: inline-flex;
				align-items: center;
				padding: 0.25rem 0.5rem;
				border-radius: var(--radius-full, 999px);
				font-size: 0.75rem;
				font-weight: 700;
		}

		.badge-success {
				background: var(--success);
				color: white;
		}

		.badge-muted {
				background: var(--bg-tertiary);
				color: var(--text-secondary);
				border: 1px solid var(--border-color);
		}

		.vm-grid {
				display: grid;
				grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
				gap: 1rem;
		}

		.vm-card {
				border: 1px solid var(--border-color);
				border-radius: var(--radius-md);
				padding: 1rem;
				background: var(--bg-tertiary);
				display: flex;
				flex-direction: column;
				gap: 0.5rem;
		}

		.vm-helper-text {
				color: var(--text-secondary);
				font-size: 0.875rem;
		}

		.integration-grid {
				display: grid;
				grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
				gap: 1rem;
		}

		.integration-card {
				border: 1px solid var(--border-color);
				border-radius: var(--radius-md);
				padding: 1rem;
				background: var(--bg-tertiary);
				display: flex;
				flex-direction: column;
				gap: 0.5rem;
		}

		.integration-header {
				display: flex;
				align-items: center;
				justify-content: space-between;
				gap: 0.75rem;
		}

		.integration-name {
				font-weight: 600;
				color: var(--text-primary);
		}

		.integration-description {
				color: var(--text-secondary);
				font-size: 0.9rem;
		}

	/* Responsive */
	@media (max-width: 768px) {
		.vm-header {
			flex-direction: column;
			align-items: flex-start;
		}

		.vm-overview-grid,
		.vm-hardware-grid {
			grid-template-columns: 1fr;
		}

		.vm-tab-list {
			overflow-x: auto;
			-webkit-overflow-scrolling: touch;
		}

		.vm-tab {
			white-space: nowrap;
		}
	}
</style>
