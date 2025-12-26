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
var _ datasource.DataSource = &NetworksDataSource{}

// NewNetworksDataSource creates a new NetworksDataSource.
func NewNetworksDataSource() datasource.DataSource {
	return &NetworksDataSource{}
}

// NetworksDataSource defines the data source implementation.
type NetworksDataSource struct {
	client *client.Client
}

// NetworksDataSourceModel describes the data source data model.
type NetworksDataSourceModel struct {
	Host     types.String          `tfsdk:"host"`
	Networks []VirtualSwitchModel  `tfsdk:"networks"`
}

// VirtualSwitchModel describes a virtual switch.
type VirtualSwitchModel struct {
	Name        types.String `tfsdk:"name"`
	SwitchType  types.String `tfsdk:"switch_type"`
	Host        types.String `tfsdk:"host"`
}

func (d *NetworksDataSource) Metadata(ctx context.Context, req datasource.MetadataRequest, resp *datasource.MetadataResponse) {
	resp.TypeName = req.ProviderTypeName + "_networks"
}

func (d *NetworksDataSource) Schema(ctx context.Context, req datasource.SchemaRequest, resp *datasource.SchemaResponse) {
	resp.Schema = schema.Schema{
		MarkdownDescription: "Retrieves information about available virtual switches/networks.",

		Attributes: map[string]schema.Attribute{
			"host": schema.StringAttribute{
				Optional:            true,
				MarkdownDescription: "Filter networks by host. If not specified, returns networks from all hosts.",
			},
			"networks": schema.ListNestedAttribute{
				Computed:            true,
				MarkdownDescription: "List of available virtual switches.",
				NestedObject: schema.NestedAttributeObject{
					Attributes: map[string]schema.Attribute{
						"name": schema.StringAttribute{
							Computed:            true,
							MarkdownDescription: "The virtual switch name.",
						},
						"switch_type": schema.StringAttribute{
							Computed:            true,
							MarkdownDescription: "The switch type (External, Internal, Private).",
						},
						"host": schema.StringAttribute{
							Computed:            true,
							MarkdownDescription: "The host this switch belongs to.",
						},
					},
				},
			},
		},
	}
}

func (d *NetworksDataSource) Configure(ctx context.Context, req datasource.ConfigureRequest, resp *datasource.ConfigureResponse) {
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

func (d *NetworksDataSource) Read(ctx context.Context, req datasource.ReadRequest, resp *datasource.ReadResponse) {
	var data NetworksDataSourceModel

	// Read Terraform configuration data into the model
	resp.Diagnostics.Append(req.Config.Get(ctx, &data)...)

	if resp.Diagnostics.HasError() {
		return
	}

	tflog.Debug(ctx, "Reading networks data source", map[string]interface{}{
		"host_filter": data.Host.ValueString(),
	})

	// TODO: Implement networks data source read
	// 1. Call GET /api/v1/networks or /api/v1/inventory
	// 2. Filter by host if specified
	// 3. Parse response and populate model

	resp.Diagnostics.AddWarning(
		"Not Implemented",
		"Networks data source read is not yet implemented. Returning empty data.",
	)

	data.Networks = []VirtualSwitchModel{}

	// Save data into Terraform state
	resp.Diagnostics.Append(resp.State.Set(ctx, &data)...)
}
