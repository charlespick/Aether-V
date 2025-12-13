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
var _ datasource.DataSource = &ImagesDataSource{}

// NewImagesDataSource creates a new ImagesDataSource.
func NewImagesDataSource() datasource.DataSource {
	return &ImagesDataSource{}
}

// ImagesDataSource defines the data source implementation.
type ImagesDataSource struct {
	client *client.Client
}

// ImagesDataSourceModel describes the data source data model.
type ImagesDataSourceModel struct {
	OSFamily types.String  `tfsdk:"os_family"`
	Images   []ImageModel  `tfsdk:"images"`
}

// ImageModel describes a golden image.
type ImageModel struct {
	Name     types.String  `tfsdk:"name"`
	Path     types.String  `tfsdk:"path"`
	SizeGB   types.Float64 `tfsdk:"size_gb"`
	OSFamily types.String  `tfsdk:"os_family"`
	Host     types.String  `tfsdk:"host"`
}

func (d *ImagesDataSource) Metadata(ctx context.Context, req datasource.MetadataRequest, resp *datasource.MetadataResponse) {
	resp.TypeName = req.ProviderTypeName + "_images"
}

func (d *ImagesDataSource) Schema(ctx context.Context, req datasource.SchemaRequest, resp *datasource.SchemaResponse) {
	resp.Schema = schema.Schema{
		MarkdownDescription: "Retrieves information about available golden images for VM boot disks.",

		Attributes: map[string]schema.Attribute{
			"os_family": schema.StringAttribute{
				Optional:            true,
				MarkdownDescription: "Filter images by OS family: 'linux' or 'windows'.",
			},
			"images": schema.ListNestedAttribute{
				Computed:            true,
				MarkdownDescription: "List of available golden images.",
				NestedObject: schema.NestedAttributeObject{
					Attributes: map[string]schema.Attribute{
						"name": schema.StringAttribute{
							Computed:            true,
							MarkdownDescription: "The image name (used in boot_disk.source_image).",
						},
						"path": schema.StringAttribute{
							Computed:            true,
							MarkdownDescription: "The full path to the image file.",
						},
						"size_gb": schema.Float64Attribute{
							Computed:            true,
							MarkdownDescription: "The image size in GB.",
						},
						"os_family": schema.StringAttribute{
							Computed:            true,
							MarkdownDescription: "The OS family: 'linux' or 'windows'.",
						},
						"host": schema.StringAttribute{
							Computed:            true,
							MarkdownDescription: "The host where this image is available.",
						},
					},
				},
			},
		},
	}
}

func (d *ImagesDataSource) Configure(ctx context.Context, req datasource.ConfigureRequest, resp *datasource.ConfigureResponse) {
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

func (d *ImagesDataSource) Read(ctx context.Context, req datasource.ReadRequest, resp *datasource.ReadResponse) {
	var data ImagesDataSourceModel

	// Read Terraform configuration data into the model
	resp.Diagnostics.Append(req.Config.Get(ctx, &data)...)

	if resp.Diagnostics.HasError() {
		return
	}

	tflog.Debug(ctx, "Reading images data source", map[string]interface{}{
		"os_family_filter": data.OSFamily.ValueString(),
	})

	// TODO: Implement images data source read
	// 1. Call GET /api/v1/images or /api/v1/inventory
	// 2. Filter by os_family if specified
	// 3. Parse response and populate model

	resp.Diagnostics.AddWarning(
		"Not Implemented",
		"Images data source read is not yet implemented. Returning empty data.",
	)

	data.Images = []ImageModel{}

	// Save data into Terraform state
	resp.Diagnostics.Append(resp.State.Set(ctx, &data)...)
}
