"""Guest configuration generator.

This module generates guest configuration dictionaries from Pydantic models
for VM provisioning operations. The generated configuration is encrypted and
transmitted to the guest VM via Hyper-V KVP for OS-level customization.
"""
from typing import Dict, Any, Optional
import logging

from .pydantic_models import VmSpec, NicSpec, DiskSpec, GuestConfigSpec

logger = logging.getLogger(__name__)


def generate_guest_config(
    vm_spec: VmSpec,
    nic_spec: Optional[NicSpec] = None,
    disk_spec: Optional[DiskSpec] = None,
    guest_config_spec: Optional[GuestConfigSpec] = None,
) -> Dict[str, Any]:
    """Generate guest configuration dictionary from Pydantic models.
    
    This function is the replacement for the auto-composed schema approach.
    It takes structured Pydantic models and generates a guest configuration
    dictionary that will be transmitted to the guest agent via KVP.
    
    The returned keys match the field names expected by the PowerShell host
    agent and ultimately map to KVP keys (e.g., guest_v4_ip_addr maps to
    hlvmm.data.guest_v4_ip_addr in the guest registry).
    
    Args:
        vm_spec: VM hardware specification (required, used for logging context)
        nic_spec: Network adapter specification (optional, reserved for future use)
        disk_spec: Disk specification (optional, reserved for future use)
        guest_config_spec: Guest configuration specification (optional, contains
                          all guest-level configuration including credentials,
                          domain join, static IP, and Ansible settings)
        
    Returns:
        Dictionary containing guest configuration keys. If no guest_config_spec
        is provided, returns an empty dict (no guest initialization will occur).
        
    Notes:
        - This function does NOT validate the models (they are already validated)
        - This function does NOT encrypt the output (handled by KVP transmission layer)
        - This function does NOT interact with the host agent
        - The returned dict contains only the keys that should be sent to the guest
        - nic_spec and disk_spec are accepted but not currently used; they are
          included for future extensibility and API consistency
    
    Example:
        >>> vm = VmSpec(vm_name="web-01", gb_ram=4, cpu_cores=2)
        >>> guest = GuestConfigSpec(
        ...     guest_la_uid="Administrator",
        ...     guest_la_pw="SecurePass123!",
        ... )
        >>> config = generate_guest_config(vm, guest_config_spec=guest)
        >>> assert "guest_la_uid" in config
        >>> assert "guest_la_pw" in config
    """
    # If no guest config spec provided, return empty dict (no guest init)
    if guest_config_spec is None:
        logger.debug(
            "No guest config spec provided for VM '%s', returning empty config",
            vm_spec.vm_name,
        )
        return {}
    
    # Start with VM metadata (always included when guest config is present)
    config: Dict[str, Any] = {}
    
    # Add local administrator credentials (always required for guest config)
    config["guest_la_uid"] = guest_config_spec.guest_la_uid
    config["guest_la_pw"] = guest_config_spec.guest_la_pw
    
    # Add domain join configuration if provided (all-or-none)
    if guest_config_spec.guest_domain_join_target:
        config["guest_domain_join_target"] = guest_config_spec.guest_domain_join_target
        config["guest_domain_join_uid"] = guest_config_spec.guest_domain_join_uid
        config["guest_domain_join_pw"] = guest_config_spec.guest_domain_join_pw
        config["guest_domain_join_ou"] = guest_config_spec.guest_domain_join_ou
        
        logger.debug(
            "Added domain join config for VM '%s' to domain '%s'",
            vm_spec.vm_name,
            guest_config_spec.guest_domain_join_target,
        )
    
    # Add Ansible configuration if provided (all-or-none)
    if guest_config_spec.cnf_ansible_ssh_user:
        config["cnf_ansible_ssh_user"] = guest_config_spec.cnf_ansible_ssh_user
        config["cnf_ansible_ssh_key"] = guest_config_spec.cnf_ansible_ssh_key
        
        logger.debug(
            "Added Ansible SSH config for VM '%s' (user: %s)",
            vm_spec.vm_name,
            guest_config_spec.cnf_ansible_ssh_user,
        )
    
    # Add static IP configuration if provided (all-or-none)
    if guest_config_spec.guest_v4_ip_addr:
        config["guest_v4_ip_addr"] = guest_config_spec.guest_v4_ip_addr
        config["guest_v4_cidr_prefix"] = guest_config_spec.guest_v4_cidr_prefix
        config["guest_v4_default_gw"] = guest_config_spec.guest_v4_default_gw
        config["guest_v4_dns1"] = guest_config_spec.guest_v4_dns1
        
        # Optional DNS2 (not part of all-or-none set)
        if guest_config_spec.guest_v4_dns2:
            config["guest_v4_dns2"] = guest_config_spec.guest_v4_dns2
        
        # Optional DNS suffix (not part of all-or-none set)
        if guest_config_spec.guest_net_dns_suffix:
            config["guest_net_dns_suffix"] = guest_config_spec.guest_net_dns_suffix
        
        logger.debug(
            "Added static IP config for VM '%s' (IP: %s/%s)",
            vm_spec.vm_name,
            guest_config_spec.guest_v4_ip_addr,
            guest_config_spec.guest_v4_cidr_prefix,
        )
    
    logger.info(
        "Generated guest config for VM '%s' with %d keys",
        vm_spec.vm_name,
        len(config),
    )
    
    return config


def generate_guest_config_from_dicts(
    vm_dict: Dict[str, Any],
    nic_dict: Optional[Dict[str, Any]] = None,
    disk_dict: Optional[Dict[str, Any]] = None,
    guest_config_dict: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Generate guest config from dictionary inputs.
    
    This is a convenience wrapper around generate_guest_config() that accepts
    dictionaries instead of Pydantic models. Useful for integration with
    existing code that works with dicts.
    
    Args:
        vm_dict: VM spec as dictionary
        nic_dict: NIC spec as dictionary (optional)
        disk_dict: Disk spec as dictionary (optional)
        guest_config_dict: Guest config spec as dictionary (optional)
        
    Returns:
        Guest configuration dictionary
        
    Raises:
        ValidationError: If any of the input dicts fail Pydantic validation
    """
    # Convert dicts to Pydantic models
    vm_spec = VmSpec(**vm_dict)
    
    nic_spec = None
    if nic_dict:
        nic_spec = NicSpec(**nic_dict)
    
    disk_spec = None
    if disk_dict:
        disk_spec = DiskSpec(**disk_dict)
    
    guest_config_spec = None
    if guest_config_dict:
        guest_config_spec = GuestConfigSpec(**guest_config_dict)
    
    # Generate and return guest config
    return generate_guest_config(vm_spec, nic_spec, disk_spec, guest_config_spec)
