// Copyright (c) Aether-V
// SPDX-License-Identifier: MPL-2.0

package provider

import (
	"context"
	"fmt"

	"github.com/aetherv/aether-v/terraform/internal/client"
	"github.com/hashicorp/terraform-plugin-framework/datasource"
	"github.com/hashicorp/terraform-plugin-framework/datasource/schema"
	"github.com/hashicorp/terraform-plugin-framework/types"
	"github.com/hashicorp/terraform-plugin-log/tflog"
)

// Ensure provider defined types fully satisfy framework interfaces.
var _ datasource.DataSource = &HostsDataSource{}

// NewHostsDataSource creates a new HostsDataSource.
func NewHostsDataSource() datasource.DataSource {
	return &HostsDataSource{}
}

// HostsDataSource defines the data source implementation.
type HostsDataSource struct {
	client *client.Client
}

// HostsDataSourceModel describes the data source data model.
type HostsDataSourceModel struct {
	Hosts    []HostModel    `tfsdk:"hosts"`
	Clusters []ClusterModel `tfsdk:"clusters"`
}

// HostModel describes a Hyper-V host.
type HostModel struct {
	Name           types.String `tfsdk:"name"`
	Status         types.String `tfsdk:"status"`
	TotalMemoryGB  types.Float64 `tfsdk:"total_memory_gb"`
	AvailableMemoryGB types.Float64 `tfsdk:"available_memory_gb"`
	CPUCount       types.Int64  `tfsdk:"cpu_count"`
	VMCount        types.Int64  `tfsdk:"vm_count"`
}

// ClusterModel describes a failover cluster.
type ClusterModel struct {
	Name  types.String   `tfsdk:"name"`
	Nodes []types.String `tfsdk:"nodes"`
}

func (d *HostsDataSource) Metadata(ctx context.Context, req datasource.MetadataRequest, resp *datasource.MetadataResponse) {
	resp.TypeName = req.ProviderTypeName + "_hosts"
}

func (d *HostsDataSource) Schema(ctx context.Context, req datasource.SchemaRequest, resp *datasource.SchemaResponse) {
	resp.Schema = schema.Schema{
		MarkdownDescription: "Retrieves information about available Hyper-V hosts and clusters.",

		Attributes: map[string]schema.Attribute{
			"hosts": schema.ListNestedAttribute{
				Computed:            true,
				MarkdownDescription: "List of available Hyper-V hosts.",
				NestedObject: schema.NestedAttributeObject{
					Attributes: map[string]schema.Attribute{
						"name": schema.StringAttribute{
							Computed:            true,
							MarkdownDescription: "The hostname.",
						},
						"status": schema.StringAttribute{
							Computed:            true,
							MarkdownDescription: "The host connection status.",
						},
						"total_memory_gb": schema.Float64Attribute{
							Computed:            true,
							MarkdownDescription: "Total memory in GB.",
						},
						"available_memory_gb": schema.Float64Attribute{
							Computed:            true,
							MarkdownDescription: "Available memory in GB.",
						},
						"cpu_count": schema.Int64Attribute{
							Computed:            true,
							MarkdownDescription: "Number of CPU cores.",
						},
						"vm_count": schema.Int64Attribute{
							Computed:            true,
							MarkdownDescription: "Number of VMs on this host.",
						},
					},
				},
			},
			"clusters": schema.ListNestedAttribute{
				Computed:            true,
				MarkdownDescription: "List of failover clusters.",
				NestedObject: schema.NestedAttributeObject{
					Attributes: map[string]schema.Attribute{
						"name": schema.StringAttribute{
							Computed:            true,
							MarkdownDescription: "The cluster name.",
						},
						"nodes": schema.ListAttribute{
							Computed:            true,
							ElementType:         types.StringType,
							MarkdownDescription: "List of nodes in the cluster.",
						},
					},
				},
			},
		},
	}
}

func (d *HostsDataSource) Configure(ctx context.Context, req datasource.ConfigureRequest, resp *datasource.ConfigureResponse) {
	// Prevent panic if the provider has not been configured.
	if req.ProviderData == nil {
		return
	}

	client, ok := req.ProviderData.(*client.Client)

	if !ok {
		resp.Diagnostics.AddError(
			"Unexpected Data Source Configure Type",
			fmt.Sprintf("Expected *client.Client, got: %T. Please report this issue to the provider developers.", req.ProviderData),
		)
		return
	}

	d.client = client
}

func (d *HostsDataSource) Read(ctx context.Context, req datasource.ReadRequest, resp *datasource.ReadResponse) {
	var data HostsDataSourceModel

	tflog.Debug(ctx, "Reading hosts data source")

	// TODO: Implement hosts data source read
	// 1. Call GET /api/v1/hosts or /api/v1/inventory
	// 2. Parse response and populate model

	resp.Diagnostics.AddWarning(
		"Not Implemented",
		"Hosts data source read is not yet implemented. Returning empty data.",
	)

	data.Hosts = []HostModel{}
	data.Clusters = []ClusterModel{}

	// Save data into Terraform state
	resp.Diagnostics.Append(resp.State.Set(ctx, &data)...)
}
