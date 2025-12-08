<script lang="ts">
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
			<div class="environment-name">Development</div>
		</div>
	</div>
	
	<div class="header-center">
		<div class="search-container">
			<svg class="search-icon" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor">
				<circle cx="11" cy="11" r="8"></circle>
				<path d="m21 21-4.35-4.35"></path>
			</svg>
			<input class="search" placeholder="Search Everywhere" />
		</div>
	</div>
	
	<div class="header-right">
		<button class="icon-btn" title="Notifications">
			<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor">
				<path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"></path>
				<path d="M13.73 21a2 2 0 0 1-3.46 0"></path>
			</svg>
		</button>
		
		<div class="profile-menu">
			<button class="icon-btn profile-btn" onclick={toggleProfile} title="Account">
				<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor">
					<circle cx="12" cy="12" r="10"></circle>
					<circle cx="12" cy="10" r="3"></circle>
					<path d="M7 20.662V19a2 2 0 0 1 2-2h6a2 2 0 0 1 2 2v1.662"></path>
				</svg>
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
		width: 32px;
		height: 32px;
		background: linear-gradient(135deg, var(--accent-primary), var(--accent-hover));
		border-radius: var(--radius-sm);
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

	.search-icon {
		position: absolute;
		left: 0.75rem;
		top: 50%;
		transform: translateY(-50%);
		color: var(--text-tertiary);
		width: 18px;
		height: 18px;
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
