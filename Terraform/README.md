# Terraform Provider for Aether-V

This directory contains the Terraform provider for managing Aether-V virtual machine infrastructure.

## Requirements

- [Go](https://golang.org/doc/install) >= 1.22
- [Terraform](https://www.terraform.io/downloads.html) >= 1.0

## Building The Provider

1. Clone the repository
2. Enter the `Terraform` directory
3. Build the provider:

```shell
make build
```

## Installing The Provider (Local Development)

```shell
make install
```

This installs the provider to `~/.terraform.d/plugins/` for local development.

## Using The Provider

### Provider Configuration

```hcl
terraform {
  required_providers {
    aetherv = {
      source = "registry.terraform.io/aetherv/aetherv"
    }
  }
}

provider "aetherv" {
  server_url    = "https://aetherv.example.com"
  client_id     = "your-client-id"
  client_secret = "your-client-secret"
  tenant_id     = "your-tenant-id"
}
```

Or use environment variables:

```shell
export AETHERV_SERVER_URL="https://aetherv.example.com"
export AETHERV_CLIENT_ID="your-client-id"
export AETHERV_CLIENT_SECRET="your-client-secret"
export AETHERV_TENANT_ID="your-tenant-id"
```

### Resources

#### aetherv_virtual_machine

Manages a complete virtual machine including disks, network interfaces, and guest configuration.

```hcl
resource "aetherv_virtual_machine" "example" {
  name              = "my-vm"
  host              = "hyperv-host-01"
  cpu_cores         = 4
  startup_memory_gb = 8.0

  boot_disk {
    source_image = "windows-2022-template"
    expand_to_gb = 100.0
  }

  network_if {
    network = "VM-Network"
  }

  specialization_family = "windows"

  user {
    username = "Administrator"
    password = var.admin_password
  }
}
```

### Data Sources

#### aetherv_hosts

Retrieves available Hyper-V hosts and clusters.

```hcl
data "aetherv_hosts" "all" {}
```

#### aetherv_images

Retrieves available golden images for boot disks.

```hcl
data "aetherv_images" "linux" {
  os_family = "linux"
}
```

#### aetherv_networks

Retrieves available virtual switches/networks.

```hcl
data "aetherv_networks" "host1" {
  host = "hyperv-host-01"
}
```

## Development

### Running Tests

```shell
make test
```

### Running Acceptance Tests

```shell
make testacc
```

### Generating Documentation

```shell
make generate
```

## Project Structure

```
Terraform/
├── main.go                          # Provider entry point
├── go.mod                           # Go module definition
├── GNUmakefile                      # Build and development tasks
├── internal/
│   ├── client/                      # API client
│   │   ├── client.go                # HTTP client with OAuth2
│   │   ├── endpoints.go             # API endpoint constants
│   │   └── resources.go             # Resource CRUD operations
│   └── provider/                    # Provider implementation
│       ├── provider.go              # Provider configuration
│       ├── vm_resource.go           # Virtual machine resource
│       ├── hosts_data_source.go     # Hosts data source
│       ├── networks_data_source.go  # Networks data source
│       └── images_data_source.go    # Images data source
└── examples/
    └── basic/
        └── main.tf                  # Example Terraform configuration
```
