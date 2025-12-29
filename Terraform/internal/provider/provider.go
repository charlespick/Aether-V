// Copyright (c) Aether-V
// SPDX-License-Identifier: MPL-2.0

package provider

import (
	"context"
	"os"

	"github.com/aetherv/aether-v/terraform/internal/client"
	"github.com/hashicorp/terraform-plugin-framework/datasource"
	"github.com/hashicorp/terraform-plugin-framework/path"
	"github.com/hashicorp/terraform-plugin-framework/provider"
	"github.com/hashicorp/terraform-plugin-framework/provider/schema"
	"github.com/hashicorp/terraform-plugin-framework/resource"
	"github.com/hashicorp/terraform-plugin-framework/types"
)

// Ensure AethervProvider satisfies various provider interfaces.
var _ provider.Provider = &AethervProvider{}

// AethervProvider defines the provider implementation.
type AethervProvider struct {
	// version is set to the provider version on release, "dev" when the
	// provider is built and ran locally, and "test" when running acceptance
	// testing.
	version string
}

// AethervProviderModel describes the provider data model.
type AethervProviderModel struct {
	ServerURL    types.String `tfsdk:"server_url"`
	ClientID     types.String `tfsdk:"client_id"`
	ClientSecret types.String `tfsdk:"client_secret"`
	TenantID     types.String `tfsdk:"tenant_id"`
}

func (p *AethervProvider) Metadata(ctx context.Context, req provider.MetadataRequest, resp *provider.MetadataResponse) {
	resp.TypeName = "aetherv"
	resp.Version = p.version
}

func (p *AethervProvider) Schema(ctx context.Context, req provider.SchemaRequest, resp *provider.SchemaResponse) {
	resp.Schema = schema.Schema{
		Description: "Interact with Aether-V virtual machine infrastructure.",
		Attributes: map[string]schema.Attribute{
			"server_url": schema.StringAttribute{
				Description: "The URL of the Aether-V server. Can also be set via the AETHERV_SERVER_URL environment variable.",
				Optional:    true,
			},
			"client_id": schema.StringAttribute{
				Description: "The OAuth2 client ID for authentication. Can also be set via the AETHERV_CLIENT_ID environment variable.",
				Optional:    true,
			},
			"client_secret": schema.StringAttribute{
				Description: "The OAuth2 client secret for authentication. Can also be set via the AETHERV_CLIENT_SECRET environment variable.",
				Optional:    true,
				Sensitive:   true,
			},
			"tenant_id": schema.StringAttribute{
				Description: "The tenant ID for authentication. Can also be set via the AETHERV_TENANT_ID environment variable.",
				Optional:    true,
			},
		},
	}
}

func (p *AethervProvider) Configure(ctx context.Context, req provider.ConfigureRequest, resp *provider.ConfigureResponse) {
	var config AethervProviderModel

	resp.Diagnostics.Append(req.Config.Get(ctx, &config)...)

	if resp.Diagnostics.HasError() {
		return
	}

	// Default values from environment variables
	serverURL := os.Getenv("AETHERV_SERVER_URL")
	clientID := os.Getenv("AETHERV_CLIENT_ID")
	clientSecret := os.Getenv("AETHERV_CLIENT_SECRET")
	tenantID := os.Getenv("AETHERV_TENANT_ID")

	// Override with explicit configuration if provided
	if !config.ServerURL.IsNull() {
		serverURL = config.ServerURL.ValueString()
	}
	if !config.ClientID.IsNull() {
		clientID = config.ClientID.ValueString()
	}
	if !config.ClientSecret.IsNull() {
		clientSecret = config.ClientSecret.ValueString()
	}
	if !config.TenantID.IsNull() {
		tenantID = config.TenantID.ValueString()
	}

	// Validate required configuration
	if serverURL == "" {
		resp.Diagnostics.AddAttributeError(
			path.Root("server_url"),
			"Missing Aether-V Server URL",
			"The provider cannot create the Aether-V API client as there is a missing or empty value for the Aether-V server URL. "+
				"Set the server_url value in the configuration or use the AETHERV_SERVER_URL environment variable.",
		)
	}

	if clientID == "" {
		resp.Diagnostics.AddAttributeError(
			path.Root("client_id"),
			"Missing Aether-V Client ID",
			"The provider cannot create the Aether-V API client as there is a missing or empty value for the OAuth2 client ID. "+
				"Set the client_id value in the configuration or use the AETHERV_CLIENT_ID environment variable.",
		)
	}

	if clientSecret == "" {
		resp.Diagnostics.AddAttributeError(
			path.Root("client_secret"),
			"Missing Aether-V Client Secret",
			"The provider cannot create the Aether-V API client as there is a missing or empty value for the OAuth2 client secret. "+
				"Set the client_secret value in the configuration or use the AETHERV_CLIENT_SECRET environment variable.",
		)
	}

	if tenantID == "" {
		resp.Diagnostics.AddAttributeError(
			path.Root("tenant_id"),
			"Missing Aether-V Tenant ID",
			"The provider cannot create the Aether-V API client as there is a missing or empty value for the tenant ID. "+
				"Set the tenant_id value in the configuration or use the AETHERV_TENANT_ID environment variable.",
		)
	}

	if resp.Diagnostics.HasError() {
		return
	}

	// Create the API client
	apiClient, err := client.NewClient(ctx, serverURL, clientID, clientSecret, tenantID)
	if err != nil {
		resp.Diagnostics.AddError(
			"Unable to Create Aether-V API Client",
			"An unexpected error occurred when creating the Aether-V API client. "+
				"If the error is not clear, please contact the provider developers.\n\n"+
				"Aether-V Client Error: "+err.Error(),
		)
		return
	}

	// Make the client available during DataSource and Resource type Configure methods.
	resp.DataSourceData = apiClient
	resp.ResourceData = apiClient
}

func (p *AethervProvider) Resources(ctx context.Context) []func() resource.Resource {
	return []func() resource.Resource{
		NewVirtualMachineResource,
	}
}

func (p *AethervProvider) DataSources(ctx context.Context) []func() datasource.DataSource {
	return []func() datasource.DataSource{
		NewHostsDataSource,
		NewNetworksDataSource,
		NewImagesDataSource,
	}
}

// New is a helper function to simplify provider server and testing implementation.
func New(version string) func() provider.Provider {
	return func() provider.Provider {
		return &AethervProvider{
			version: version,
		}
	}
}
