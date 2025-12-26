// Copyright (c) Aether-V
// SPDX-License-Identifier: MPL-2.0

// Package client provides the API client for communicating with the Aether-V server.
package client

// API endpoint paths
const (
	// Virtual Machines
	PathVMs           = "/api/v1/resources/vms"
	PathVMByID        = "/api/v1/resources/vms/%s"
	PathVMInitialize  = "/api/v1/resources/vms/%s/initialize"

	// Disks
	PathDisks         = "/api/v1/resources/disks"
	PathDiskByID      = "/api/v1/resources/disks/%s"
	PathVMDisks       = "/api/v1/resources/vms/%s/disks"

	// Network Adapters
	PathNICs          = "/api/v1/resources/nics"
	PathNICByID       = "/api/v1/resources/nics/%s"
	PathVMNICs        = "/api/v1/resources/vms/%s/nics"

	// Jobs
	PathJobs          = "/api/v1/jobs"
	PathJobByID       = "/api/v1/jobs/%s"

	// Inventory
	PathInventory     = "/api/v1/inventory"
	PathHosts         = "/api/v1/hosts"
	PathImages        = "/api/v1/images"
	PathNetworks      = "/api/v1/networks"
)
