terraform {
  required_providers {
    aetherv = {
      source = "registry.terraform.io/charlespick/aetherv"
    }
  }
}

provider "aetherv" {
  # Configuration can be set via environment variables:
  # AETHERV_SERVER_URL
  # AETHERV_CLIENT_ID
  # AETHERV_CLIENT_SECRET
  # AETHERV_TENANT_ID
}

# Example: Look up available hosts
data "aetherv_hosts" "all" {}

# Example: Look up available images
data "aetherv_images" "linux" {
  os_family = "linux"
}

# Example: Look up available networks on a specific host
data "aetherv_networks" "host1" {
  host = "hyperv-host-01"
}

# Example: Create a Linux VM
resource "aetherv_virtual_machine" "example" {
  name    = "tf-example-vm"
  host    = "hyperv-host-01"
  # cluster = "my-cluster"  # Use instead of host for failover support

  cpu_cores         = 2
  startup_memory_gb = 4.0

  # Optional: Enable dynamic memory
  # dynamic_memory {
  #   memory_gb_min       = 2.0
  #   memory_gb_max       = 8.0
  #   memory_prcnt_buffer = 20
  # }

  # Security settings (Gen2 VMs)
  secure_boot = "Microsoft UEFI Certificate Authority"
  # trusted_platform_module {
  #   key_protector = "..."
  # }

  # Boot disk from golden image
  boot_disk {
    source_image  = "ubuntu-22.04-template"
    expand_to_gb  = 50.0
    storage_class = "fast-ssd"
  }

  # Additional data disk
  # disk {
  #   size_gb       = 100.0
  #   storage_class = "standard"
  # }

  # Network interface with static IP
  network_if {
    network        = "VM-Network"
    mac_spoof_guard = true

    ipconfig {
      ipv4 {
        address = "192.168.1.100/24"
        gateway = "192.168.1.1"
        dns     = ["192.168.1.10", "192.168.1.11"]
      }
      search_suffix = "example.local"
    }
  }

  # Guest OS specialization
  specialization_family = "linux"

  user {
    username = "admin"
    password = var.admin_password
  }

  # Ansible configuration for Linux
  ansible {
    username = "ansible"
    ssh_key  = var.ansible_ssh_key
  }

  # VM behavior settings
  host_recovery_action = "resume"
  host_stop_action     = "save"

  integration_svcs {
    shutdown      = true
    time          = true
    data_exchange = true
    heartbeat     = true
    vss_backup    = false
    guest_services = false
  }
}

# Variables
variable "admin_password" {
  type      = string
  sensitive = true
}

variable "ansible_ssh_key" {
  type      = string
  sensitive = true
}

# Outputs
output "vm_id" {
  value = aetherv_virtual_machine.example.id
}
