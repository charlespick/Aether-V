<script lang="ts">
	import Modal from "$lib/components/Modal.svelte";
	import FormField from "$lib/components/forms/FormField.svelte";
	import FormSection from "$lib/components/forms/FormSection.svelte";
	import FormActions from "$lib/components/forms/FormActions.svelte";
	import Button from "$lib/components/common/Button.svelte";
	import { toastStore } from "$lib/stores/toastStore";
	import { inventoryStore } from "$lib/stores/inventoryStore";
	import {
		validateRequired,
		validateRange,
		validateParameterSets,
		validatePattern,
		validateIPv4,
		validateCIDRPrefix,
		combineValidationErrors,
		hasErrors,
		patterns,
		type ParameterSet,
	} from "$lib/utils/validation";

	interface Props {
		isOpen: boolean;
		onClose: () => void;
		onSuccess?: (jobId: string) => void;
	}

	let { isOpen = $bindable(false), onClose, onSuccess }: Props = $props();

	// Form state - VM Hardware
	let vmData = $state({
		vm_name: "",
		gb_ram: 4,
		cpu_cores: 2,
		storage_class: "",
		vm_clustered: false,
	});

	// Disk configuration (disk_type is inherited from the source image when cloning)
	let diskData = $state({
		disk_size_gb: 100,
		controller_type: "SCSI" as "SCSI" | "IDE",
	});

	// NIC configuration
	let nicData = $state({
		network: "",
		adapter_name: "",
	});

	// Guest configuration - Local Admin
	let guestLocalAdmin = $state({
		guest_la_uid: "",
		guest_la_pw: "",
	});

	// Guest configuration - Domain Join (all-or-none)
	let domainJoinEnabled = $state(false);
	let domainJoinData = $state({
		guest_domain_join_target: "",
		guest_domain_join_uid: "",
		guest_domain_join_pw: "",
		guest_domain_join_ou: "",
	});

	// Guest configuration - Ansible (all-or-none)
	let ansibleEnabled = $state(false);
	let ansibleData = $state({
		cnf_ansible_ssh_user: "",
		cnf_ansible_ssh_key: "",
	});

	// Guest configuration - Static IP (all-or-none)
	let staticIpEnabled = $state(false);
	let staticIpData = $state({
		guest_v4_ip_addr: "",
		guest_v4_cidr_prefix: 24,
		guest_v4_default_gw: "",
		guest_v4_dns1: "",
		guest_v4_dns2: "",
		guest_net_dns_suffix: "",
	});

	// Host and image selection
	let deploymentMode = $state<"host" | "cluster">("host");
	let targetHost = $state("");
	let targetCluster = $state("");
	let imageName = $state("");

	// Available hosts, clusters, and images
	let availableHosts = $derived(
		$inventoryStore?.hosts
			?.filter((h) => h.connected)
			.map((h) => h.hostname) || [],
	);
	let availableClusters = $state<
		Array<{ name: string; connected_hosts: number }>
	>([]);

	// Auto-enable clustering when cluster mode is selected
	$effect(() => {
		if (deploymentMode === "cluster") {
			vmData.vm_clustered = true;
		}
	});

	let errors = $state<Record<string, string>>({});
	let isSubmitting = $state(false);

	// Parameter sets for all-or-none validation
	const parameterSets: ParameterSet[] = [
		{
			name: "Domain Join",
			fields: [
				"guest_domain_join_target",
				"guest_domain_join_uid",
				"guest_domain_join_pw",
				"guest_domain_join_ou",
			],
		},
		{
			name: "Ansible Configuration",
			fields: ["cnf_ansible_ssh_user", "cnf_ansible_ssh_key"],
		},
		{
			name: "Static IP Configuration",
			fields: [
				"guest_v4_ip_addr",
				"guest_v4_cidr_prefix",
				"guest_v4_default_gw",
				"guest_v4_dns1",
			],
		},
	];

	// Combine all form data
	function getFullFormData() {
		const data: Record<string, any> = {
			...vmData,
			...diskData,
			...nicData,
			...guestLocalAdmin,
			...(deploymentMode === "host"
				? { target_host: targetHost }
				: { target_cluster: targetCluster }),
			image_name: imageName,
		};

		// Add optional parameter sets if enabled
		if (domainJoinEnabled) {
			Object.assign(data, domainJoinData);
		}

		if (ansibleEnabled) {
			Object.assign(data, ansibleData);
		}

		if (staticIpEnabled) {
			Object.assign(data, staticIpData);
		}

		return data;
	}

	// Validation
	function validate(): boolean {
		const fullData = getFullFormData();

		const validationErrors = combineValidationErrors([
			// Required fields - conditional on deployment mode
			...validateRequired(fullData, [
				"vm_name",
				"gb_ram",
				"cpu_cores",
				"disk_size_gb",
				"controller_type",
				"network",
				"guest_la_uid",
				"guest_la_pw",
			]),

			// Deployment target validation with clear error messages
			...(deploymentMode === "host"
				? validateRequired(fullData, ["target_host"])
				: validateRequired(fullData, ["target_cluster"])),

			// Range validations
			validateRange(fullData, "gb_ram", 1, 512),
			validateRange(fullData, "cpu_cores", 1, 64),
			validateRange(fullData, "disk_size_gb", 1, 65536),

			// VM name validation (hostname pattern)
			validatePattern(
				fullData,
				"vm_name",
				patterns.hostname,
				"Must be a valid hostname (alphanumeric and hyphens only)",
			),

			// Network name validation
			validatePattern(
				fullData,
				"network",
				patterns.networkName,
				"Invalid network name format",
			),

			// Parameter set validations (all-or-none)
			...validateParameterSets(fullData, parameterSets),
		]);

		// Static IP specific validations if enabled
		if (staticIpEnabled) {
			if (
				staticIpData.guest_v4_ip_addr &&
				!validateIPv4(staticIpData.guest_v4_ip_addr)
			) {
				validationErrors.guest_v4_ip_addr = "Invalid IPv4 address";
			}

			if (
				staticIpData.guest_v4_default_gw &&
				!validateIPv4(staticIpData.guest_v4_default_gw)
			) {
				validationErrors.guest_v4_default_gw = "Invalid IPv4 address";
			}

			if (
				staticIpData.guest_v4_dns1 &&
				!validateIPv4(staticIpData.guest_v4_dns1)
			) {
				validationErrors.guest_v4_dns1 = "Invalid IPv4 address";
			}

			if (
				staticIpData.guest_v4_dns2 &&
				staticIpData.guest_v4_dns2 !== "" &&
				!validateIPv4(staticIpData.guest_v4_dns2)
			) {
				validationErrors.guest_v4_dns2 = "Invalid IPv4 address";
			}

			if (!validateCIDRPrefix(staticIpData.guest_v4_cidr_prefix)) {
				validationErrors.guest_v4_cidr_prefix =
					"Must be between 0 and 32";
			}
		}

		errors = validationErrors;
		return !hasErrors(validationErrors);
	}

	// Handle form submission
	async function handleSubmit(e: Event) {
		e.preventDefault();

		if (!validate()) {
			toastStore.error("Please fix the validation errors");
			return;
		}

		isSubmitting = true;

		try {
			// Build flat payload that mirrors form fields directly
			// The server parses this flat structure into hardware specs internally
			const payload: Record<string, any> = {
				// Deployment target - either host or cluster
				...(deploymentMode === "host"
					? { target_host: targetHost }
					: { target_cluster: targetCluster }),
				// VM hardware
				vm_name: vmData.vm_name,
				gb_ram: vmData.gb_ram,
				cpu_cores: vmData.cpu_cores,
				storage_class: vmData.storage_class || undefined,
				vm_clustered: vmData.vm_clustered,
				// Disk configuration (disk_type is inherited from the source image when cloning)
				image_name: imageName || undefined,
				disk_size_gb: diskData.disk_size_gb,
				controller_type: diskData.controller_type,
				// Network
				network: nicData.network,
				// Guest config - local admin (required)
				...guestLocalAdmin,
			};

			// Add domain join config if enabled
			if (domainJoinEnabled) {
				Object.assign(payload, domainJoinData);
			}

			// Add Ansible config if enabled
			if (ansibleEnabled) {
				Object.assign(payload, ansibleData);
			}

			// Add static IP config if enabled
			if (staticIpEnabled) {
				Object.assign(payload, staticIpData);
			}

			const response = await fetch("/api/v1/managed-deployments", {
				method: "POST",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify(payload),
			});

			if (!response.ok) {
				const error = await response.json();
				throw new Error(error.detail || "Failed to create VM");
			}

			const result = await response.json();
			toastStore.success(`VM provisioning started for ${vmData.vm_name}`);
			onClose();

			// Call success callback with job ID
			if (result.job_id) {
				onSuccess?.(result.job_id);
			}
		} catch (error) {
			console.error("Failed to create VM:", error);
			toastStore.error(
				error instanceof Error ? error.message : "Failed to create VM",
			);
		} finally {
			isSubmitting = false;
		}
	}

	// Reset form when modal closes
	$effect(() => {
		if (!isOpen) {
			vmData = {
				vm_name: "",
				gb_ram: 4,
				cpu_cores: 2,
				storage_class: "",
				vm_clustered: false,
			};
			deploymentMode = "host";
			targetHost = "";
			targetCluster = "";
			diskData = {
				disk_size_gb: 100,
				controller_type: "SCSI",
			};
			nicData = {
				network: "",
				adapter_name: "",
			};
			guestLocalAdmin = {
				guest_la_uid: "",
				guest_la_pw: "",
			};
			domainJoinEnabled = false;
			domainJoinData = {
				guest_domain_join_target: "",
				guest_domain_join_uid: "",
				guest_domain_join_pw: "",
				guest_domain_join_ou: "",
			};
			ansibleEnabled = false;
			ansibleData = {
				cnf_ansible_ssh_user: "",
				cnf_ansible_ssh_key: "",
			};
			staticIpEnabled = false;
			staticIpData = {
				guest_v4_ip_addr: "",
				guest_v4_cidr_prefix: 24,
				guest_v4_default_gw: "",
				guest_v4_dns1: "",
				guest_v4_dns2: "",
				guest_net_dns_suffix: "",
			};
			imageName = "";
			errors = {};
		}
	});

	// Fetch available clusters
	$effect(() => {
		if (isOpen) {
			fetch("/api/v1/clusters")
				.then((res) => res.json())
				.then((clusters) => {
					// Filter clusters with at least one connected host
					availableClusters = clusters.filter(
						(c: any) => c.host_count > 0,
					);
				})
				.catch((err) =>
					console.error("Failed to fetch clusters:", err),
				);
		}
	});
</script>

<Modal
	{isOpen}
	{onClose}
	title="Create Virtual Machine"
	variant="slideOver"
	width="xl"
>
	<form onsubmit={handleSubmit}>
		<div class="form-content">
			<!-- Primary Controls: Host & Image -->
			<FormSection
				title="Deployment Target"
				description="Select the destination and base image"
			>
				<FormField
					label="Deployment Mode"
					description="Deploy to a specific host or let the cluster select the optimal host"
					required
				>
					<div class="radio-group">
						<label class="radio-label">
							<input
								type="radio"
								bind:group={deploymentMode}
								value="host"
								disabled={isSubmitting}
							/>
							<span>Specific Host</span>
						</label>
						<label class="radio-label">
							<input
								type="radio"
								bind:group={deploymentMode}
								value="cluster"
								disabled={isSubmitting}
							/>
							<span>Cluster (Auto-select Host)</span>
						</label>
					</div>
				</FormField>

				{#if deploymentMode === "host"}
					<FormField
						label="Target Host"
						description="Hyper-V host where the VM will be created"
						required
						error={errors.target_host}
					>
						<select bind:value={targetHost} disabled={isSubmitting}>
							<option value="">Select a host...</option>
							{#each availableHosts as host}
								<option value={host}>{host}</option>
							{/each}
						</select>
					</FormField>
				{:else}
					<FormField
						label="Target Cluster"
						description="Cluster where the VM will be created - host will be auto-selected based on available memory"
						required
						error={errors.target_cluster}
					>
						<select
							bind:value={targetCluster}
							disabled={isSubmitting}
						>
							<option value="">Select a cluster...</option>
							{#each availableClusters as cluster}
								<option value={cluster.name}
									>{cluster.name} ({cluster.host_count} hosts)</option
								>
							{/each}
						</select>
					</FormField>
				{/if}
				<FormField
					label="Base Image"
					description="Name of the golden image to clone"
					error={errors.image_name}
				>
					<input
						type="text"
						bind:value={imageName}
						placeholder="e.g., Windows Server 2022"
						disabled={isSubmitting}
					/>
				</FormField>
			</FormSection>

			<!-- VM Hardware -->
			<FormSection
				title="Virtual Machine Configuration"
				description="Define the hardware specifications for the VM"
			>
				<FormField
					label="VM Name"
					description="Unique name for the virtual machine (will be used as hostname)"
					required
					error={errors.vm_name}
				>
					<input
						type="text"
						bind:value={vmData.vm_name}
						placeholder="e.g., web-server-01"
						disabled={isSubmitting}
					/>
				</FormField>

				<FormField
					label="Memory (GB)"
					description="Amount of RAM to allocate"
					required
					error={errors.gb_ram}
				>
					<input
						type="number"
						bind:value={vmData.gb_ram}
						min="1"
						max="512"
						disabled={isSubmitting}
					/>
				</FormField>

				<FormField
					label="CPU Cores"
					description="Number of virtual processors"
					required
					error={errors.cpu_cores}
				>
					<input
						type="number"
						bind:value={vmData.cpu_cores}
						min="1"
						max="64"
						disabled={isSubmitting}
					/>
				</FormField>

				<FormField
					label="Storage Class"
					description="Optional: storage tier or class identifier"
					error={errors.storage_class}
				>
					<input
						type="text"
						bind:value={vmData.storage_class}
						placeholder="e.g., fast-ssd"
						disabled={isSubmitting}
					/>
				</FormField>

				<FormField
					description="Enable high availability clustering for this VM"
				>
					<label class="checkbox-label">
						<input
							type="checkbox"
							bind:checked={vmData.vm_clustered}
							disabled={isSubmitting ||
								deploymentMode === "cluster"}
						/>
						<span
							>Enable VM Clustering{deploymentMode === "cluster"
								? " (Auto-enabled)"
								: ""}</span
						>
					</label>
				</FormField>
			</FormSection>

			<!-- Disk Configuration -->
			<FormSection
				title="Disk Configuration"
				description="Configure the primary virtual disk"
			>
				<FormField
					label="Disk Size (GB)"
					description="Size of the virtual disk"
					required
					error={errors.disk_size_gb}
				>
					<input
						type="number"
						bind:value={diskData.disk_size_gb}
						min="1"
						max="65536"
						disabled={isSubmitting}
					/>
				</FormField>

				<!-- Note: Disk type (Dynamic/Fixed) is inherited from the source image when cloning -->

				<FormField
					label="Controller Type"
					required
					error={errors.controller_type}
				>
					<select
						bind:value={diskData.controller_type}
						disabled={isSubmitting}
					>
						<option value="SCSI">SCSI (recommended)</option>
						<option value="IDE">IDE</option>
					</select>
				</FormField>
			</FormSection>

			<!-- Network Configuration -->
			<FormSection
				title="Network Configuration"
				description="Configure the primary network adapter"
			>
				<FormField
					label="Network"
					description="Name of Hyper-V virtual switch to connect to"
					required
					error={errors.network}
				>
					<input
						type="text"
						bind:value={nicData.network}
						placeholder="e.g., External-Network"
						disabled={isSubmitting}
					/>
				</FormField>

				<FormField
					label="Adapter Name"
					description="Optional: custom name for the network adapter"
					error={errors.adapter_name}
				>
					<input
						type="text"
						bind:value={nicData.adapter_name}
						placeholder="e.g., Network Adapter 1"
						disabled={isSubmitting}
					/>
				</FormField>

				<!-- Static IP Configuration -->
				<FormField>
					<label class="checkbox-label">
						<input
							type="checkbox"
							bind:checked={staticIpEnabled}
							disabled={isSubmitting}
						/>
						<span>Configure Static IP</span>
					</label>
				</FormField>

				{#if staticIpEnabled}
					<div class="parameter-set-note">
						IP address, CIDR prefix, gateway, and primary DNS must
						be provided together.
					</div>

					<FormField
						label="IP Address"
						description="Static IPv4 address"
						required={staticIpEnabled}
						error={errors.guest_v4_ip_addr}
					>
						<input
							type="text"
							bind:value={staticIpData.guest_v4_ip_addr}
							placeholder="e.g., 192.168.1.100"
							disabled={isSubmitting}
						/>
					</FormField>

					<FormField
						label="CIDR Prefix"
						description="Subnet mask in CIDR notation"
						required={staticIpEnabled}
						error={errors.guest_v4_cidr_prefix}
					>
						<input
							type="number"
							bind:value={staticIpData.guest_v4_cidr_prefix}
							min="0"
							max="32"
							disabled={isSubmitting}
						/>
					</FormField>

					<FormField
						label="Default Gateway"
						description="IPv4 gateway address"
						required={staticIpEnabled}
						error={errors.guest_v4_default_gw}
					>
						<input
							type="text"
							bind:value={staticIpData.guest_v4_default_gw}
							placeholder="e.g., 192.168.1.1"
							disabled={isSubmitting}
						/>
					</FormField>

					<FormField
						label="Primary DNS"
						description="Primary DNS server"
						required={staticIpEnabled}
						error={errors.guest_v4_dns1}
					>
						<input
							type="text"
							bind:value={staticIpData.guest_v4_dns1}
							placeholder="e.g., 192.168.1.10"
							disabled={isSubmitting}
						/>
					</FormField>

					<FormField
						label="Secondary DNS"
						description="Optional: secondary DNS server"
						error={errors.guest_v4_dns2}
					>
						<input
							type="text"
							bind:value={staticIpData.guest_v4_dns2}
							placeholder="e.g., 192.168.1.11"
							disabled={isSubmitting}
						/>
					</FormField>

					<FormField
						label="DNS Suffix"
						description="Optional: DNS search suffix"
						error={errors.guest_net_dns_suffix}
					>
						<input
							type="text"
							bind:value={staticIpData.guest_net_dns_suffix}
							placeholder="e.g., example.com"
							disabled={isSubmitting}
						/>
					</FormField>
				{/if}
			</FormSection>

			<!-- Guest Configuration: Local Admin -->
			<FormSection
				title="Guest Configuration: Local Administrator"
				description="Required: credentials for the local administrator account"
			>
				<FormField
					label="Username"
					description="Local administrator username"
					required
					error={errors.guest_la_uid}
				>
					<input
						type="text"
						bind:value={guestLocalAdmin.guest_la_uid}
						placeholder="Administrator"
						disabled={isSubmitting}
					/>
				</FormField>

				<FormField
					label="Password"
					description="Local administrator password"
					required
					error={errors.guest_la_pw}
				>
					<input
						type="password"
						bind:value={guestLocalAdmin.guest_la_pw}
						disabled={isSubmitting}
					/>
				</FormField>
			</FormSection>

			<!-- Guest Configuration: Domain Join -->
			<FormSection
				title="Guest Configuration: Domain Join"
				description="Optional: join the VM to an Active Directory domain"
				collapsible
				defaultExpanded={false}
			>
				<FormField>
					<label class="checkbox-label">
						<input
							type="checkbox"
							bind:checked={domainJoinEnabled}
							disabled={isSubmitting}
						/>
						<span>Enable Domain Join</span>
					</label>
				</FormField>

				{#if domainJoinEnabled}
					<div class="parameter-set-note">
						All domain join fields must be provided together.
					</div>

					<FormField
						label="Domain"
						description="Fully qualified domain name"
						required={domainJoinEnabled}
						error={errors.guest_domain_join_target}
					>
						<input
							type="text"
							bind:value={domainJoinData.guest_domain_join_target}
							placeholder="e.g., ad.example.com"
							disabled={isSubmitting}
						/>
					</FormField>

					<FormField
						label="Domain Join Username"
						description="Account with permission to join computers to the domain"
						required={domainJoinEnabled}
						error={errors.guest_domain_join_uid}
					>
						<input
							type="text"
							bind:value={domainJoinData.guest_domain_join_uid}
							placeholder="e.g., DOMAIN\\admin"
							disabled={isSubmitting}
						/>
					</FormField>

					<FormField
						label="Domain Join Password"
						required={domainJoinEnabled}
						error={errors.guest_domain_join_pw}
					>
						<input
							type="password"
							bind:value={domainJoinData.guest_domain_join_pw}
							disabled={isSubmitting}
						/>
					</FormField>

					<FormField
						label="Organizational Unit"
						description="LDAP path to OU (optional)"
						error={errors.guest_domain_join_ou}
					>
						<input
							type="text"
							bind:value={domainJoinData.guest_domain_join_ou}
							placeholder="e.g., OU=Servers,DC=ad,DC=example,DC=com"
							disabled={isSubmitting}
						/>
					</FormField>
				{/if}
			</FormSection>

			<!-- Guest Configuration: Ansible -->
			<FormSection
				title="Guest Configuration: Ansible"
				description="Optional: configure SSH access for Ansible"
				collapsible
				defaultExpanded={false}
			>
				<FormField>
					<label class="checkbox-label">
						<input
							type="checkbox"
							bind:checked={ansibleEnabled}
							disabled={isSubmitting}
						/>
						<span>Enable Ansible Configuration</span>
					</label>
				</FormField>

				{#if ansibleEnabled}
					<div class="parameter-set-note">
						All Ansible fields must be provided together.
					</div>

					<FormField
						label="SSH Username"
						description="Username for Ansible SSH connection"
						required={ansibleEnabled}
						error={errors.cnf_ansible_ssh_user}
					>
						<input
							type="text"
							bind:value={ansibleData.cnf_ansible_ssh_user}
							placeholder="e.g., ansible"
							disabled={isSubmitting}
						/>
					</FormField>

					<FormField
						label="SSH Public Key"
						description="Public key for passwordless authentication"
						required={ansibleEnabled}
						error={errors.cnf_ansible_ssh_key}
					>
						<textarea
							bind:value={ansibleData.cnf_ansible_ssh_key}
							placeholder="ssh-rsa AAAAB3..."
							disabled={isSubmitting}
						></textarea>
					</FormField>
				{/if}
			</FormSection>
		</div>

		<FormActions>
			<Button
				variant="secondary"
				onclick={onClose}
				disabled={isSubmitting}>Cancel</Button
			>
			<Button type="submit" variant="primary" disabled={isSubmitting}>
				{isSubmitting ? "Creating VM..." : "Create Virtual Machine"}
			</Button>
		</FormActions>
	</form>
</Modal>

<style>
	.form-content {
		display: flex;
		flex-direction: column;
		gap: 1.5rem;
	}

	.radio-group {
		display: flex;
		flex-direction: column;
		gap: 0.5rem;
	}

	.radio-label {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		cursor: pointer;
		font-size: 0.875rem;
		color: var(--text-primary);
	}

	.radio-label input[type="radio"] {
		margin: 0;
	}

	.checkbox-label {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		cursor: pointer;
		font-size: 0.875rem;
		color: var(--text-primary);
	}

	.checkbox-label input[type="checkbox"] {
		margin: 0;
	}

	.parameter-set-note {
		padding: 0.75rem;
		background: rgba(251, 191, 36, 0.1);
		border: 1px solid rgba(251, 191, 36, 0.4);
		border-radius: var(--radius-md);
		font-size: 0.8125rem;
		color: var(--text-secondary);
		font-style: italic;
		margin-bottom: 0.5rem;
	}
</style>
