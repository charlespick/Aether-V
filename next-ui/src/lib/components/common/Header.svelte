<script lang="ts">
	import Icon from './Icon.svelte';
	import ThemeToggle from './ThemeToggle.svelte';
	import { inventoryStore } from '$lib/stores/inventoryStore';
	
	const environmentName = inventoryStore.environmentName;
	let isProfileOpen = $state(false);
	
	function toggleProfile() {
		isProfileOpen = !isProfileOpen;
	}
</script>

<header class="header">
	<div class="header-left">
		<div class="decorative-square"></div>
		<div class="environment-info">
			<div class="environment-label">Working in</div>
			<div class="environment-name">{$environmentName}</div>
		</div>
	</div>
	
	<div class="header-center">
		<div class="search-container">
			<div class="search-icon-wrapper">
				<Icon name="search" size={18} class="search-icon" />
			</div>
			<input class="search" placeholder="Search Everywhere" />
		</div>
	</div>
	
	<div class="header-right">
		<ThemeToggle />
		
		<button class="icon-btn" title="Notifications">
			<Icon name="notifications" size={24} />
		</button>
		
		<div class="profile-menu">
			<button class="icon-btn profile-btn" onclick={toggleProfile} title="Account">
				<Icon name="account_circle" size={24} />
			</button>
			
			{#if isProfileOpen}
			<div class="profile-dropdown">
				<div class="profile-header">
					<div class="profile-name">Guest User</div>
					<div class="profile-email">Not signed in</div>
				</div>
				<div class="profile-role">
					<span>API role</span>
					<span class="role-value">Unavailable</span>
				</div>
				<button class="logout-btn">Log out</button>
			</div>
			{/if}
		</div>
	</div>
</header>

<style>
	.header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 0.75rem 1.5rem;
		background-color: var(--bg-tertiary);
		border-bottom: 1px solid var(--border-color);
		height: 60px;
	}

	.header-left {
		display: flex;
		align-items: center;
		gap: 1rem;
	}

	.decorative-square {
		width: 60px;
		height: 60px;
		background: linear-gradient(135deg, #8b5cf6, #ec4899);
		margin-left: -24px;
		margin-right: 0.5rem;
		margin-top: -12px;
		margin-bottom: -12px;
	}

	.environment-info {
		display: flex;
		flex-direction: column;
	}

	.environment-label {
		font-size: 0.75rem;
		color: var(--text-secondary);
	}

	.environment-name {
		font-size: 0.875rem;
		font-weight: 600;
		color: var(--text-primary);
	}

	.header-center {
		flex: 1;
		max-width: 500px;
		padding: 0 2rem;
	}

	.search-container {
		position: relative;
		width: 100%;
	}

	.search-icon-wrapper {
		position: absolute;
		left: 0.75rem;
		top: 50%;
		transform: translateY(-50%);
		color: var(--text-tertiary);
		pointer-events: none;
	}

	.search {
		width: 100%;
		padding: 0.625rem 0.75rem 0.625rem 2.5rem;
		background-color: var(--bg-primary);
		border: 1px solid var(--border-subtle);
		border-radius: var(--radius-md);
		color: var(--text-primary);
		font-size: 0.875rem;
		transition: border-color var(--transition-fast);
	}

	.search:focus {
		outline: none;
		border-color: var(--accent-primary);
	}

	.header-right {
		display: flex;
		align-items: center;
		gap: 0.75rem;
	}

	.icon-btn {
		padding: 0.5rem;
		color: var(--text-secondary);
		transition: color var(--transition-fast), background-color var(--transition-fast);
		border-radius: var(--radius-sm);
	}

	.icon-btn:hover {
		color: var(--text-primary);
		background-color: var(--bg-hover);
	}

	.profile-menu {
		position: relative;
	}

	.profile-dropdown {
		position: absolute;
		right: 0;
		top: calc(100% + 0.5rem);
		background-color: var(--bg-tertiary);
		border: 1px solid var(--border-color);
		border-radius: var(--radius-lg);
		padding: 1rem;
		min-width: 240px;
		box-shadow: var(--shadow-lg);
		z-index: 1000;
	}

	.profile-header {
		padding-bottom: 0.75rem;
		border-bottom: 1px solid var(--border-color);
		margin-bottom: 0.75rem;
	}

	.profile-name {
		font-weight: 600;
		color: var(--text-primary);
		margin-bottom: 0.25rem;
	}

	.profile-email {
		font-size: 0.875rem;
		color: var(--text-secondary);
	}

	.profile-role {
		display: flex;
		justify-content: space-between;
		font-size: 0.875rem;
		padding: 0.5rem 0;
		color: var(--text-secondary);
	}

	.role-value {
		color: var(--text-primary);
		font-weight: 500;
	}

	.logout-btn {
		width: 100%;
		padding: 0.625rem;
		margin-top: 0.75rem;
		background-color: var(--bg-primary);
		color: var(--text-primary);
		border-radius: var(--radius-md);
		font-weight: 500;
		transition: background-color var(--transition-fast);
	}

	.logout-btn:hover {
		background-color: var(--bg-hover);
	}
</style>
