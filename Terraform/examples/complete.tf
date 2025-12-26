# This is a complete configuration example of the aetherv_virtual_machine resource that shows all the capabilities of the schema and replaces the previous loosely typed example.
resource "aetherv_virtual_machine" "example" {
# ID as GUID - State only
  name       = "example-vm" # Mutation forces replacement
  host       = "hyperv-host-01" # Mutation forces replacement
# cluster    = "example-cluster"  # Use instead of host for failover support, mutation forces replacement
  
  cpu_cores  = 4
  startup_memory_gb = 8.0
  dynamic_memory { # Optional: Enable dynamic memory
    memory_gb_min       = 4.0
    memory_gb_max       = 16.0
    memory_prcnt_buffer = 20
  }

  secure_boot = "Microsoft Windows" # Optional: other options include "Microsoft UEFI Certificate Authority", "Open Source Shielded VM", or "Disabled", mutation forces replacement
  trusted_platform_module { # Optional
    key_protector = "host-guardian-service" # Optional: other options depend on your environment
  }
  shielded_vm = true # Optional: requires secure_boot and trusted_platform_module, mutation forces replacement

  boot_disk {
  # ID as GUID - State only
    source_image   = "windows-server-2019-image" # Mutation forces replacement
    expand_to_gb   = 60.0 # Can only ever expand, otherwise forces replacement
    storage_class  = "premium-ssd" # Optional: derived from hostresources configuration
  }
  disk {
  # ID as GUID - State only
    size_gb        = 100.0 # Can only ever expand, otherwise forces replacement
    storage_class  = "standard-hdd" # Optional: derived from hostresources configuration, mutation forces replacement
  }
  disk { # Add disks with additional blocks
    size_gb        = 100.0
    storage_class  = "standard-hdd"
  }

  network_if {
  # ID as GUID - State only
    name               = "eth0"
    network            = "DMZ-Network" # Network configured in hostresources

    mac_address        = "Dynamic" # Optional: can also specify a MAC address in AA:BB:CC:DD:EE:FF format, default is Dynamic
    ipconfig { # Optional: otherwise uses DHCP, mutation forces replacement
      ipv4 {
        address  = "129.129.129.129/24"
        gateway  = "129.129.129.1"
        dns      = ["1.1.1.1", "1.0.0.1"]
      }
      ipv6 {
        address  = "2001:0db8:85a3:0000:0000:8a2e:0370:7334/64"
        gateway  = "2001:0db8:85a3:0000:0000:8a2e:0370:1"
        dns      = ["2001:4860:4860::8888", "2001:4860:4860::8844"]
      }
      search_suffix = "example.com"
    }

    dhcp_guard        = true
    router_guard      = true
    mac_spoof_guard   = true

    min_bandwidth_mbps = 100
    max_bandwidth_mbps = 1000
  }
  network_if { # Add network interfaces with additional blocks
    name               = "eth1"
    network            = "Service-Network"
    ipconfig {
      ipv4 {
        address  = "192.168.1.6/24"
        gateway  = "192.168.1.1"
        dns      = ["1.1.1.1", "1.0.0.1"]
      }
      search_suffix = "example.com"
    }
  }

  specialization_family = "windows" # Required if any guest config options are set, other option is "linux", mutation forces replacement
  user { # Mutation forces replacement
    username = "adminuser"
    password = "sensitive-password"
  }
  domain_join { # For Windows VMs only, mutation forces replacement
    domain_name          = "example.com"
    organizational_unit  = "OU=Computers,DC=example,DC=com"
    username             = "domain-admin"
    password             = "sensitive-domain-password"
  }
  # ansible { # For Linux VMs only, Mutation forces replacement
  #   username = "ansible-user"
  #   ssh_key  = file("~/.ssh/id_rsa.pub")
  # }

  host_recovery_action = "always-start" # Optional: other options are "none", "resume"
  host_stop_action     = "shut-down"   # Optional: other options are "save", "stop"
  integration_svcs { # Optional: Configure integration services, defaults are Hyper-V defaults
    shutdown        = true
    time            = true
    data_exchange   = true # Required if any guest config options are set
    heartbeat       = true
    vss_backup      = true
    guest_services  = true
  }
}
