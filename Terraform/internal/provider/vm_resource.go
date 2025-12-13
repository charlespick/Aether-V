// Copyright (c) Aether-V
// SPDX-License-Identifier: MPL-2.0

package provider

import (
	"context"
	"fmt"

	"github.com/aetherv/aether-v/terraform/internal/client"
	"github.com/hashicorp/terraform-plugin-framework-validators/stringvalidator"
	"github.com/hashicorp/terraform-plugin-framework/attr"
	"github.com/hashicorp/terraform-plugin-framework/diag"
	"github.com/hashicorp/terraform-plugin-framework/path"
	"github.com/hashicorp/terraform-plugin-framework/resource"
	"github.com/hashicorp/terraform-plugin-framework/resource/schema"
	"github.com/hashicorp/terraform-plugin-framework/resource/schema/booldefault"
	"github.com/hashicorp/terraform-plugin-framework/resource/schema/int64default"
	"github.com/hashicorp/terraform-plugin-framework/resource/schema/planmodifier"
	"github.com/hashicorp/terraform-plugin-framework/resource/schema/stringdefault"
	"github.com/hashicorp/terraform-plugin-framework/resource/schema/stringplanmodifier"
	"github.com/hashicorp/terraform-plugin-framework/schema/validator"
	"github.com/hashicorp/terraform-plugin-framework/types"
	"github.com/hashicorp/terraform-plugin-log/tflog"
)

// Ensure provider defined types fully satisfy framework interfaces.
var (
	_ resource.Resource                = &VirtualMachineResource{}
	_ resource.ResourceWithImportState = &VirtualMachineResource{}
)

// NewVirtualMachineResource creates a new VirtualMachineResource.
func NewVirtualMachineResource() resource.Resource {
	return &VirtualMachineResource{}
}

// VirtualMachineResource defines the resource implementation.
type VirtualMachineResource struct {
	client *client.Client
}

// VirtualMachineResourceModel describes the resource data model.
type VirtualMachineResourceModel struct {
	// Core identifiers
	ID      types.String `tfsdk:"id"`
	Name    types.String `tfsdk:"name"`
	Host    types.String `tfsdk:"host"`
	Cluster types.String `tfsdk:"cluster"`

	// Compute
	CPUCores        types.Int64   `tfsdk:"cpu_cores"`
	StartupMemoryGB types.Float64 `tfsdk:"startup_memory_gb"`
	DynamicMemory   types.Object  `tfsdk:"dynamic_memory"`

	// Security
	SecureBoot             types.String `tfsdk:"secure_boot"`
	TrustedPlatformModule  types.Object `tfsdk:"trusted_platform_module"`

	// Storage
	BootDisk types.Object `tfsdk:"boot_disk"`
	Disks    types.List   `tfsdk:"disk"`

	// Networking
	NetworkInterfaces types.List `tfsdk:"network_if"`

	// Guest specialization
	SpecializationFamily types.String `tfsdk:"specialization_family"`
	User                 types.Object `tfsdk:"user"`
	DomainJoin           types.Object `tfsdk:"domain_join"`
	Ansible              types.Object `tfsdk:"ansible"`

	// Behavior
	HostRecoveryAction types.String `tfsdk:"host_recovery_action"`
	HostStopAction     types.String `tfsdk:"host_stop_action"`
	IntegrationSvcs    types.Object `tfsdk:"integration_svcs"`
}

// DynamicMemoryModel describes the dynamic memory configuration.
type DynamicMemoryModel struct {
	MemoryGBMin       types.Float64 `tfsdk:"memory_gb_min"`
	MemoryGBMax       types.Float64 `tfsdk:"memory_gb_max"`
	MemoryPrcntBuffer types.Int64   `tfsdk:"memory_prcnt_buffer"`
}

// TPMModel describes trusted platform module configuration.
type TPMModel struct {
	KeyProtector types.String `tfsdk:"key_protector"`
}

// BootDiskModel describes the boot disk configuration.
type BootDiskModel struct {
	ID           types.String  `tfsdk:"id"`
	SourceImage  types.String  `tfsdk:"source_image"`
	ExpandToGB   types.Float64 `tfsdk:"expand_to_gb"`
	StorageClass types.String  `tfsdk:"storage_class"`
}

// DiskModel describes additional disk configuration.
type DiskModel struct {
	ID           types.String  `tfsdk:"id"`
	SizeGB       types.Float64 `tfsdk:"size_gb"`
	StorageClass types.String  `tfsdk:"storage_class"`
}

// NetworkInterfaceModel describes a network interface configuration.
type NetworkInterfaceModel struct {
	ID              types.String `tfsdk:"id"`
	Network         types.String `tfsdk:"network"`
	DHCPGuard       types.Bool   `tfsdk:"dhcp_guard"`
	RouterGuard     types.Bool   `tfsdk:"router_guard"`
	MACSpoofGuard   types.Bool   `tfsdk:"mac_spoof_guard"`
	MACAddress      types.String `tfsdk:"mac_address"`
	MinBandwidthMbps types.Int64  `tfsdk:"min_bandwidth_mbps"`
	MaxBandwidthMbps types.Int64  `tfsdk:"max_bandwidth_mbps"`
	IPConfig        types.Object `tfsdk:"ipconfig"`
}

// IPConfigModel describes IP configuration for a network interface.
type IPConfigModel struct {
	IPv4         types.Object `tfsdk:"ipv4"`
	IPv6         types.Object `tfsdk:"ipv6"`
	SearchSuffix types.String `tfsdk:"search_suffix"`
}

// IPAddressConfigModel describes IPv4 or IPv6 configuration.
type IPAddressConfigModel struct {
	Address types.String `tfsdk:"address"`
	Gateway types.String `tfsdk:"gateway"`
	DNS     types.List   `tfsdk:"dns"`
}

// UserModel describes the local user configuration.
type UserModel struct {
	Username types.String `tfsdk:"username"`
	Password types.String `tfsdk:"password"`
}

// DomainJoinModel describes domain join configuration.
type DomainJoinModel struct {
	DomainName         types.String `tfsdk:"domain_name"`
	OrganizationalUnit types.String `tfsdk:"organizational_unit"`
	Username           types.String `tfsdk:"username"`
	Password           types.String `tfsdk:"password"`
}

// AnsibleModel describes Ansible configuration.
type AnsibleModel struct {
	Username types.String `tfsdk:"username"`
	SSHKey   types.String `tfsdk:"ssh_key"`
}

// IntegrationServicesModel describes Hyper-V integration services.
type IntegrationServicesModel struct {
	Shutdown      types.Bool `tfsdk:"shutdown"`
	Time          types.Bool `tfsdk:"time"`
	DataExchange  types.Bool `tfsdk:"data_exchange"`
	Heartbeat     types.Bool `tfsdk:"heartbeat"`
	VSSBackup     types.Bool `tfsdk:"vss_backup"`
	GuestServices types.Bool `tfsdk:"guest_services"`
}

func (r *VirtualMachineResource) Metadata(ctx context.Context, req resource.MetadataRequest, resp *resource.MetadataResponse) {
	resp.TypeName = req.ProviderTypeName + "_virtual_machine"
}

func (r *VirtualMachineResource) Schema(ctx context.Context, req resource.SchemaRequest, resp *resource.SchemaResponse) {
	resp.Schema = schema.Schema{
		MarkdownDescription: "Manages an Aether-V virtual machine including its disks, network interfaces, and guest configuration.",

		Attributes: map[string]schema.Attribute{
			// Core identifiers
			"id": schema.StringAttribute{
				Computed:            true,
				MarkdownDescription: "The unique identifier of the virtual machine (GUID).",
				PlanModifiers: []planmodifier.String{
					stringplanmodifier.UseStateForUnknown(),
				},
			},
			"name": schema.StringAttribute{
				Required:            true,
				MarkdownDescription: "The name of the virtual machine.",
				PlanModifiers: []planmodifier.String{
					stringplanmodifier.RequiresReplace(),
				},
			},
			"host": schema.StringAttribute{
				Optional:            true,
				MarkdownDescription: "The target host for the VM. Required if cluster is not set.",
			},
			"cluster": schema.StringAttribute{
				Optional:            true,
				MarkdownDescription: "The cluster for the VM. Required if host is not set. Enables failover.",
			},

			// Compute
			"cpu_cores": schema.Int64Attribute{
				Required:            true,
				MarkdownDescription: "The number of CPU cores for the virtual machine (1-64).",
			},
			"startup_memory_gb": schema.Float64Attribute{
				Required:            true,
				MarkdownDescription: "The startup memory in GB for the virtual machine.",
			},
			"dynamic_memory": schema.SingleNestedAttribute{
				Optional:            true,
				MarkdownDescription: "Dynamic memory configuration for the virtual machine.",
				Attributes: map[string]schema.Attribute{
					"memory_gb_min": schema.Float64Attribute{
						Optional:            true,
						MarkdownDescription: "Minimum memory in GB.",
					},
					"memory_gb_max": schema.Float64Attribute{
						Optional:            true,
						MarkdownDescription: "Maximum memory in GB.",
					},
					"memory_prcnt_buffer": schema.Int64Attribute{
						Optional:            true,
						MarkdownDescription: "Memory buffer percentage.",
					},
				},
			},

			// Security
			"secure_boot": schema.StringAttribute{
				Optional:            true,
				MarkdownDescription: "Secure boot template. Valid values: 'Microsoft Windows', 'Microsoft UEFI Certificate Authority', 'Open Source Shielded VM', or 'Disabled'.",
				Validators: []validator.String{
					stringvalidator.OneOf(
						"Microsoft Windows",
						"Microsoft UEFI Certificate Authority",
						"Open Source Shielded VM",
						"Disabled",
					),
				},
			},
			"trusted_platform_module": schema.SingleNestedAttribute{
				Optional:            true,
				MarkdownDescription: "Trusted Platform Module (TPM) configuration.",
				Attributes: map[string]schema.Attribute{
					"key_protector": schema.StringAttribute{
						Optional:            true,
						MarkdownDescription: "Key protector configuration.",
					},
				},
			},

			// Storage - Boot Disk
			"boot_disk": schema.SingleNestedAttribute{
				Required:            true,
				MarkdownDescription: "Boot disk configuration. Dictates boot order.",
				Attributes: map[string]schema.Attribute{
					"id": schema.StringAttribute{
						Computed:            true,
						MarkdownDescription: "The unique identifier of the boot disk (GUID).",
						PlanModifiers: []planmodifier.String{
							stringplanmodifier.UseStateForUnknown(),
						},
					},
					"source_image": schema.StringAttribute{
						Required:            true,
						MarkdownDescription: "The source image to clone for the boot disk.",
						PlanModifiers: []planmodifier.String{
							stringplanmodifier.RequiresReplace(),
						},
					},
					"expand_to_gb": schema.Float64Attribute{
						Optional:            true,
						MarkdownDescription: "Expand the disk to this size in GB.",
					},
					"storage_class": schema.StringAttribute{
						Optional:            true,
						MarkdownDescription: "Storage class for the disk.",
					},
				},
			},

			// Storage - Additional Disks
			"disk": schema.ListNestedAttribute{
				Optional:            true,
				MarkdownDescription: "Additional data disks for the virtual machine.",
				NestedObject: schema.NestedAttributeObject{
					Attributes: map[string]schema.Attribute{
						"id": schema.StringAttribute{
							Computed:            true,
							MarkdownDescription: "The unique identifier of the disk (GUID).",
							PlanModifiers: []planmodifier.String{
								stringplanmodifier.UseStateForUnknown(),
							},
						},
						"size_gb": schema.Float64Attribute{
							Required:            true,
							MarkdownDescription: "Size of the disk in GB.",
						},
						"storage_class": schema.StringAttribute{
							Optional:            true,
							MarkdownDescription: "Storage class for the disk.",
						},
					},
				},
			},

			// Networking
			"network_if": schema.ListNestedAttribute{
				Optional:            true,
				MarkdownDescription: "Network interfaces for the virtual machine.",
				NestedObject: schema.NestedAttributeObject{
					Attributes: map[string]schema.Attribute{
						"id": schema.StringAttribute{
							Computed:            true,
							MarkdownDescription: "The unique identifier of the network interface (GUID).",
							PlanModifiers: []planmodifier.String{
								stringplanmodifier.UseStateForUnknown(),
							},
						},
						"network": schema.StringAttribute{
							Required:            true,
							MarkdownDescription: "The virtual switch or network name.",
						},
						"dhcp_guard": schema.BoolAttribute{
							Optional:            true,
							Computed:            true,
							Default:             booldefault.StaticBool(false),
							MarkdownDescription: "Enable DHCP guard.",
						},
						"router_guard": schema.BoolAttribute{
							Optional:            true,
							Computed:            true,
							Default:             booldefault.StaticBool(false),
							MarkdownDescription: "Enable router guard.",
						},
						"mac_spoof_guard": schema.BoolAttribute{
							Optional:            true,
							Computed:            true,
							Default:             booldefault.StaticBool(false),
							MarkdownDescription: "Enable MAC address spoofing guard.",
						},
						"mac_address": schema.StringAttribute{
							Optional:            true,
							Computed:            true,
							Default:             stringdefault.StaticString("Dynamic"),
							MarkdownDescription: "MAC address ('Dynamic' or a specific MAC address).",
						},
						"min_bandwidth_mbps": schema.Int64Attribute{
							Optional:            true,
							MarkdownDescription: "Minimum bandwidth in Mbps.",
						},
						"max_bandwidth_mbps": schema.Int64Attribute{
							Optional:            true,
							MarkdownDescription: "Maximum bandwidth in Mbps.",
						},
						"ipconfig": schema.SingleNestedAttribute{
							Optional:            true,
							MarkdownDescription: "Static IP configuration for the network interface.",
							Attributes: map[string]schema.Attribute{
								"ipv4": schema.SingleNestedAttribute{
									Optional:            true,
									MarkdownDescription: "IPv4 configuration.",
									Attributes: map[string]schema.Attribute{
										"address": schema.StringAttribute{
											Required:            true,
											MarkdownDescription: "IPv4 address with prefix (e.g., '192.168.1.10/24').",
										},
										"gateway": schema.StringAttribute{
											Required:            true,
											MarkdownDescription: "Default gateway address.",
										},
										"dns": schema.ListAttribute{
											Required:            true,
											ElementType:         types.StringType,
											MarkdownDescription: "DNS server addresses (max 2).",
										},
									},
								},
								"ipv6": schema.SingleNestedAttribute{
									Optional:            true,
									MarkdownDescription: "IPv6 configuration.",
									Attributes: map[string]schema.Attribute{
										"address": schema.StringAttribute{
											Required:            true,
											MarkdownDescription: "IPv6 address with prefix.",
										},
										"gateway": schema.StringAttribute{
											Required:            true,
											MarkdownDescription: "Default gateway address.",
										},
										"dns": schema.ListAttribute{
											Required:            true,
											ElementType:         types.StringType,
											MarkdownDescription: "DNS server addresses (max 2).",
										},
									},
								},
								"search_suffix": schema.StringAttribute{
									Optional:            true,
									MarkdownDescription: "DNS search suffix.",
								},
							},
						},
					},
				},
			},

			// Guest Specialization
			"specialization_family": schema.StringAttribute{
				Optional:            true,
				MarkdownDescription: "OS family for specialization: 'linux' or 'windows'. Required if guest config options are set.",
				Validators: []validator.String{
					stringvalidator.OneOf("linux", "windows"),
				},
			},
			"user": schema.SingleNestedAttribute{
				Optional:            true,
				MarkdownDescription: "Local user account configuration.",
				Attributes: map[string]schema.Attribute{
					"username": schema.StringAttribute{
						Required:            true,
						MarkdownDescription: "Local administrator username.",
					},
					"password": schema.StringAttribute{
						Required:            true,
						Sensitive:           true,
						MarkdownDescription: "Local administrator password.",
					},
				},
			},
			"domain_join": schema.SingleNestedAttribute{
				Optional:            true,
				MarkdownDescription: "Domain join configuration.",
				Attributes: map[string]schema.Attribute{
					"domain_name": schema.StringAttribute{
						Required:            true,
						MarkdownDescription: "The domain name to join.",
					},
					"organizational_unit": schema.StringAttribute{
						Optional:            true,
						MarkdownDescription: "The organizational unit (OU) for the computer account.",
					},
					"username": schema.StringAttribute{
						Required:            true,
						MarkdownDescription: "Username with domain join privileges.",
					},
					"password": schema.StringAttribute{
						Required:            true,
						Sensitive:           true,
						MarkdownDescription: "Password for domain join.",
					},
				},
			},
			"ansible": schema.SingleNestedAttribute{
				Optional:            true,
				MarkdownDescription: "Ansible configuration for Linux VMs.",
				Attributes: map[string]schema.Attribute{
					"username": schema.StringAttribute{
						Required:            true,
						MarkdownDescription: "Ansible SSH username.",
					},
					"ssh_key": schema.StringAttribute{
						Required:            true,
						Sensitive:           true,
						MarkdownDescription: "Ansible SSH public key.",
					},
				},
			},

			// Behavior
			"host_recovery_action": schema.StringAttribute{
				Optional:            true,
				Computed:            true,
				Default:             stringdefault.StaticString("resume"),
				MarkdownDescription: "Action on host recovery: 'none', 'resume', or 'always-start'.",
				Validators: []validator.String{
					stringvalidator.OneOf("none", "resume", "always-start"),
				},
			},
			"host_stop_action": schema.StringAttribute{
				Optional:            true,
				Computed:            true,
				Default:             stringdefault.StaticString("save"),
				MarkdownDescription: "Action on host stop: 'save', 'stop', or 'shut-down'.",
				Validators: []validator.String{
					stringvalidator.OneOf("save", "stop", "shut-down"),
				},
			},
			"integration_svcs": schema.SingleNestedAttribute{
				Optional:            true,
				MarkdownDescription: "Hyper-V integration services configuration.",
				Attributes: map[string]schema.Attribute{
					"shutdown": schema.BoolAttribute{
						Optional:            true,
						Computed:            true,
						Default:             booldefault.StaticBool(true),
						MarkdownDescription: "Enable shutdown integration service.",
					},
					"time": schema.BoolAttribute{
						Optional:            true,
						Computed:            true,
						Default:             booldefault.StaticBool(true),
						MarkdownDescription: "Enable time synchronization integration service.",
					},
					"data_exchange": schema.BoolAttribute{
						Optional:            true,
						Computed:            true,
						Default:             booldefault.StaticBool(true),
						MarkdownDescription: "Enable data exchange (KVP) integration service. Required for guest configuration.",
					},
					"heartbeat": schema.BoolAttribute{
						Optional:            true,
						Computed:            true,
						Default:             booldefault.StaticBool(true),
						MarkdownDescription: "Enable heartbeat integration service.",
					},
					"vss_backup": schema.BoolAttribute{
						Optional:            true,
						Computed:            true,
						Default:             booldefault.StaticBool(true),
						MarkdownDescription: "Enable VSS backup integration service.",
					},
					"guest_services": schema.BoolAttribute{
						Optional:            true,
						Computed:            true,
						Default:             booldefault.StaticBool(false),
						MarkdownDescription: "Enable guest services integration service.",
					},
				},
			},
		},
	}
}

func (r *VirtualMachineResource) Configure(ctx context.Context, req resource.ConfigureRequest, resp *resource.ConfigureResponse) {
	// Prevent panic if the provider has not been configured.
	if req.ProviderData == nil {
		return
	}

	client, ok := req.ProviderData.(*client.Client)

	if !ok {
		resp.Diagnostics.AddError(
			"Unexpected Resource Configure Type",
			fmt.Sprintf("Expected *client.Client, got: %T. Please report this issue to the provider developers.", req.ProviderData),
		)
		return
	}

	r.client = client
}

func (r *VirtualMachineResource) Create(ctx context.Context, req resource.CreateRequest, resp *resource.CreateResponse) {
	var data VirtualMachineResourceModel

	// Read Terraform plan data into the model
	resp.Diagnostics.Append(req.Plan.Get(ctx, &data)...)

	if resp.Diagnostics.HasError() {
		return
	}

	tflog.Debug(ctx, "Creating virtual machine", map[string]interface{}{
		"name": data.Name.ValueString(),
	})

	// TODO: Implement VM creation logic
	// 1. Create VM with VmSpec
	// 2. Wait for job completion
	// 3. Create boot disk with image
	// 4. Create additional disks
	// 5. Create network interfaces
	// 6. Apply guest configuration via initialize endpoint
	// 7. Read back state and populate IDs

	resp.Diagnostics.AddError(
		"Not Implemented",
		"VM creation is not yet implemented. This is a scaffold.",
	)
}

func (r *VirtualMachineResource) Read(ctx context.Context, req resource.ReadRequest, resp *resource.ReadResponse) {
	var data VirtualMachineResourceModel

	// Read Terraform prior state data into the model
	resp.Diagnostics.Append(req.State.Get(ctx, &data)...)

	if resp.Diagnostics.HasError() {
		return
	}

	tflog.Debug(ctx, "Reading virtual machine", map[string]interface{}{
		"id": data.ID.ValueString(),
	})

	// TODO: Implement VM read logic
	// 1. Get VM by ID
	// 2. Get associated disks
	// 3. Get associated NICs
	// 4. Map API response to model

	// Save updated data into Terraform state
	resp.Diagnostics.Append(resp.State.Set(ctx, &data)...)
}

func (r *VirtualMachineResource) Update(ctx context.Context, req resource.UpdateRequest, resp *resource.UpdateResponse) {
	var data VirtualMachineResourceModel

	// Read Terraform plan data into the model
	resp.Diagnostics.Append(req.Plan.Get(ctx, &data)...)

	if resp.Diagnostics.HasError() {
		return
	}

	tflog.Debug(ctx, "Updating virtual machine", map[string]interface{}{
		"id": data.ID.ValueString(),
	})

	// TODO: Implement VM update logic
	// 1. Compare planned state with current state
	// 2. Update VM properties (CPU, memory, etc.)
	// 3. Add/remove/update disks as needed
	// 4. Add/remove/update network interfaces as needed
	// 5. Re-apply guest configuration if changed

	resp.Diagnostics.AddError(
		"Not Implemented",
		"VM update is not yet implemented. This is a scaffold.",
	)
}

func (r *VirtualMachineResource) Delete(ctx context.Context, req resource.DeleteRequest, resp *resource.DeleteResponse) {
	var data VirtualMachineResourceModel

	// Read Terraform prior state data into the model
	resp.Diagnostics.Append(req.State.Get(ctx, &data)...)

	if resp.Diagnostics.HasError() {
		return
	}

	tflog.Debug(ctx, "Deleting virtual machine", map[string]interface{}{
		"id": data.ID.ValueString(),
	})

	// TODO: Implement VM deletion logic
	// 1. Delete VM (which should cascade to disks and NICs)
	// 2. Wait for job completion

	resp.Diagnostics.AddError(
		"Not Implemented",
		"VM deletion is not yet implemented. This is a scaffold.",
	)
}

func (r *VirtualMachineResource) ImportState(ctx context.Context, req resource.ImportStateRequest, resp *resource.ImportStateResponse) {
	resource.ImportStatePassthroughID(ctx, path.Root("id"), req, resp)
}

// Attribute type definitions for nested objects
func DynamicMemoryAttrTypes() map[string]attr.Type {
	return map[string]attr.Type{
		"memory_gb_min":       types.Float64Type,
		"memory_gb_max":       types.Float64Type,
		"memory_prcnt_buffer": types.Int64Type,
	}
}

func TPMAttrTypes() map[string]attr.Type {
	return map[string]attr.Type{
		"key_protector": types.StringType,
	}
}

func BootDiskAttrTypes() map[string]attr.Type {
	return map[string]attr.Type{
		"id":            types.StringType,
		"source_image":  types.StringType,
		"expand_to_gb":  types.Float64Type,
		"storage_class": types.StringType,
	}
}

func DiskAttrTypes() map[string]attr.Type {
	return map[string]attr.Type{
		"id":            types.StringType,
		"size_gb":       types.Float64Type,
		"storage_class": types.StringType,
	}
}

func NetworkInterfaceAttrTypes() map[string]attr.Type {
	return map[string]attr.Type{
		"id":                types.StringType,
		"network":           types.StringType,
		"dhcp_guard":        types.BoolType,
		"router_guard":      types.BoolType,
		"mac_spoof_guard":   types.BoolType,
		"mac_address":       types.StringType,
		"min_bandwidth_mbps": types.Int64Type,
		"max_bandwidth_mbps": types.Int64Type,
		"ipconfig":          types.ObjectType{AttrTypes: IPConfigAttrTypes()},
	}
}

func IPConfigAttrTypes() map[string]attr.Type {
	return map[string]attr.Type{
		"ipv4":          types.ObjectType{AttrTypes: IPAddressConfigAttrTypes()},
		"ipv6":          types.ObjectType{AttrTypes: IPAddressConfigAttrTypes()},
		"search_suffix": types.StringType,
	}
}

func IPAddressConfigAttrTypes() map[string]attr.Type {
	return map[string]attr.Type{
		"address": types.StringType,
		"gateway": types.StringType,
		"dns":     types.ListType{ElemType: types.StringType},
	}
}

func UserAttrTypes() map[string]attr.Type {
	return map[string]attr.Type{
		"username": types.StringType,
		"password": types.StringType,
	}
}

func DomainJoinAttrTypes() map[string]attr.Type {
	return map[string]attr.Type{
		"domain_name":         types.StringType,
		"organizational_unit": types.StringType,
		"username":            types.StringType,
		"password":            types.StringType,
	}
}

func AnsibleAttrTypes() map[string]attr.Type {
	return map[string]attr.Type{
		"username": types.StringType,
		"ssh_key":  types.StringType,
	}
}

func IntegrationServicesAttrTypes() map[string]attr.Type {
	return map[string]attr.Type{
		"shutdown":       types.BoolType,
		"time":           types.BoolType,
		"data_exchange":  types.BoolType,
		"heartbeat":      types.BoolType,
		"vss_backup":     types.BoolType,
		"guest_services": types.BoolType,
	}
}

// Helper function to check for API errors and add diagnostics
func (r *VirtualMachineResource) addAPIError(diags *diag.Diagnostics, summary string, err error) {
	diags.AddError(
		summary,
		fmt.Sprintf("API error: %s", err.Error()),
	)
}
