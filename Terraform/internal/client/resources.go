// Copyright (c) Aether-V
// SPDX-License-Identifier: MPL-2.0

package client

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"net/url"
)

// VMState represents the state of a virtual machine.
type VMState string

const (
	VMStateRunning  VMState = "Running"
	VMStateOff      VMState = "Off"
	VMStatePaused   VMState = "Paused"
	VMStateSaved    VMState = "Saved"
	VMStateStarting VMState = "Starting"
	VMStateStopping VMState = "Stopping"
	VMStateUnknown  VMState = "Unknown"
	VMStateCreating VMState = "Creating"
	VMStateDeleting VMState = "Deleting"
)

// OSFamily represents the operating system family.
type OSFamily string

const (
	OSFamilyWindows OSFamily = "windows"
	OSFamilyLinux   OSFamily = "linux"
)

// VM represents a virtual machine from the API.
type VM struct {
	ID                   string   `json:"id,omitempty"`
	Name                 string   `json:"name"`
	Host                 string   `json:"host"`
	State                VMState  `json:"state,omitempty"`
	CPUCores             int      `json:"cpu_cores"`
	MemoryGB             float64  `json:"memory_gb,omitempty"`
	MemoryStartupGB      *float64 `json:"memory_startup_gb,omitempty"`
	MemoryMinGB          *float64 `json:"memory_min_gb,omitempty"`
	MemoryMaxGB          *float64 `json:"memory_max_gb,omitempty"`
	DynamicMemoryEnabled *bool    `json:"dynamic_memory_enabled,omitempty"`
	IPAddresses          []string `json:"ip_addresses,omitempty"`
	OSFamily             OSFamily `json:"os_family,omitempty"`
	Generation           *int     `json:"generation,omitempty"`
	Disks                []Disk   `json:"disks,omitempty"`
	Networks             []NIC    `json:"networks,omitempty"`
}

// VmSpec represents the request body for creating a VM.
type VmSpec struct {
	VMName       string   `json:"vm_name"`
	Host         string   `json:"host,omitempty"`
	Cluster      string   `json:"cluster,omitempty"`
	GBRam        int      `json:"gb_ram"`
	CPUCores     int      `json:"cpu_cores"`
	StorageClass string   `json:"storage_class,omitempty"`
	VMClustered  bool     `json:"vm_clustered,omitempty"`
	OSFamily     OSFamily `json:"os_family,omitempty"`
}

// Disk represents a virtual disk from the API.
type Disk struct {
	ID         string   `json:"id,omitempty"`
	Name       string   `json:"name,omitempty"`
	Path       string   `json:"path,omitempty"`
	Type       string   `json:"type,omitempty"`
	SizeGB     *float64 `json:"size_gb,omitempty"`
	FileSizeGB *float64 `json:"file_size_gb,omitempty"`
}

// DiskSpec represents the request body for creating/attaching a disk.
type DiskSpec struct {
	VMID           string `json:"vm_id,omitempty"`
	ImageName      string `json:"image_name,omitempty"`
	DiskSizeGB     int    `json:"disk_size_gb,omitempty"`
	DiskType       string `json:"disk_type,omitempty"`
	ControllerType string `json:"controller_type,omitempty"`
}

// NIC represents a network adapter from the API.
type NIC struct {
	ID            string   `json:"id,omitempty"`
	Name          string   `json:"name,omitempty"`
	Network       string   `json:"network,omitempty"`
	VirtualSwitch string   `json:"virtual_switch,omitempty"`
	IPAddresses   []string `json:"ip_addresses,omitempty"`
	MACAddress    string   `json:"mac_address,omitempty"`
}

// NicSpec represents the request body for creating/attaching a NIC.
type NicSpec struct {
	VMID        string `json:"vm_id,omitempty"`
	Network     string `json:"network"`
	AdapterName string `json:"adapter_name,omitempty"`
}

// VMInitializationRequest represents the guest initialization configuration.
type VMInitializationRequest struct {
	TargetHost         string                 `json:"target_host"`
	GuestConfiguration map[string]interface{} `json:"guest_configuration"`
}

// ListVMs returns all virtual machines.
func (c *Client) ListVMs(ctx context.Context) ([]VM, error) {
	respBody, err := c.Get(ctx, PathVMs)
	if err != nil {
		return nil, err
	}

	var vms []VM
	if err := json.Unmarshal(respBody, &vms); err != nil {
		return nil, fmt.Errorf("failed to parse VMs response: %w", err)
	}

	return vms, nil
}

// GetVM returns a specific virtual machine by ID.
func (c *Client) GetVM(ctx context.Context, vmID string) (*VM, error) {
	path := fmt.Sprintf(PathVMByID, url.PathEscape(vmID))
	respBody, err := c.Get(ctx, path)
	if err != nil {
		return nil, err
	}

	var vm VM
	if err := json.Unmarshal(respBody, &vm); err != nil {
		return nil, fmt.Errorf("failed to parse VM response: %w", err)
	}

	return &vm, nil
}

// CreateVM creates a new virtual machine and waits for the job to complete.
func (c *Client) CreateVM(ctx context.Context, spec *VmSpec) (*JobResult, error) {
	body, err := json.Marshal(spec)
	if err != nil {
		return nil, fmt.Errorf("failed to marshal VM spec: %w", err)
	}

	respBody, err := c.Post(ctx, PathVMs, bytes.NewReader(body))
	if err != nil {
		return nil, err
	}

	var result JobResult
	if err := json.Unmarshal(respBody, &result); err != nil {
		return nil, fmt.Errorf("failed to parse job result: %w", err)
	}

	return &result, nil
}

// DeleteVM deletes a virtual machine.
func (c *Client) DeleteVM(ctx context.Context, vmID string) (*JobResult, error) {
	path := fmt.Sprintf(PathVMByID, url.PathEscape(vmID))
	respBody, err := c.Delete(ctx, path)
	if err != nil {
		return nil, err
	}

	var result JobResult
	if err := json.Unmarshal(respBody, &result); err != nil {
		return nil, fmt.Errorf("failed to parse job result: %w", err)
	}

	return &result, nil
}

// CreateDisk creates a new disk and optionally attaches it to a VM.
func (c *Client) CreateDisk(ctx context.Context, spec *DiskSpec) (*JobResult, error) {
	body, err := json.Marshal(spec)
	if err != nil {
		return nil, fmt.Errorf("failed to marshal disk spec: %w", err)
	}

	respBody, err := c.Post(ctx, PathDisks, bytes.NewReader(body))
	if err != nil {
		return nil, err
	}

	var result JobResult
	if err := json.Unmarshal(respBody, &result); err != nil {
		return nil, fmt.Errorf("failed to parse job result: %w", err)
	}

	return &result, nil
}

// DeleteDisk deletes a disk.
func (c *Client) DeleteDisk(ctx context.Context, diskID string) (*JobResult, error) {
	path := fmt.Sprintf(PathDiskByID, url.PathEscape(diskID))
	respBody, err := c.Delete(ctx, path)
	if err != nil {
		return nil, err
	}

	var result JobResult
	if err := json.Unmarshal(respBody, &result); err != nil {
		return nil, fmt.Errorf("failed to parse job result: %w", err)
	}

	return &result, nil
}

// CreateNIC creates a new network adapter and optionally attaches it to a VM.
func (c *Client) CreateNIC(ctx context.Context, spec *NicSpec) (*JobResult, error) {
	body, err := json.Marshal(spec)
	if err != nil {
		return nil, fmt.Errorf("failed to marshal NIC spec: %w", err)
	}

	respBody, err := c.Post(ctx, PathNICs, bytes.NewReader(body))
	if err != nil {
		return nil, err
	}

	var result JobResult
	if err := json.Unmarshal(respBody, &result); err != nil {
		return nil, fmt.Errorf("failed to parse job result: %w", err)
	}

	return &result, nil
}

// DeleteNIC deletes a network adapter.
func (c *Client) DeleteNIC(ctx context.Context, nicID string) (*JobResult, error) {
	path := fmt.Sprintf(PathNICByID, url.PathEscape(nicID))
	respBody, err := c.Delete(ctx, path)
	if err != nil {
		return nil, err
	}

	var result JobResult
	if err := json.Unmarshal(respBody, &result); err != nil {
		return nil, fmt.Errorf("failed to parse job result: %w", err)
	}

	return &result, nil
}

// InitializeVM applies guest configuration to a VM.
func (c *Client) InitializeVM(ctx context.Context, vmID string, req *VMInitializationRequest) (*JobResult, error) {
	path := fmt.Sprintf(PathVMInitialize, url.PathEscape(vmID))

	body, err := json.Marshal(req)
	if err != nil {
		return nil, fmt.Errorf("failed to marshal initialization request: %w", err)
	}

	respBody, err := c.Post(ctx, path, bytes.NewReader(body))
	if err != nil {
		return nil, err
	}

	var result JobResult
	if err := json.Unmarshal(respBody, &result); err != nil {
		return nil, fmt.Errorf("failed to parse job result: %w", err)
	}

	return &result, nil
}
