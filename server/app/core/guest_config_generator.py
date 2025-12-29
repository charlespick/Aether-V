"""Guest configuration generator.

This module generates guest configuration dictionaries from the flat
ManagedDeploymentRequest model for VM provisioning operations. The generated
configuration is encrypted and transmitted to the guest VM via Hyper-V KVP
for OS-level customization.

Architecture Note:
    This function is ONLY used by the Managed Deployment Service to extract
    guest configuration fields from the flat ManagedDeploymentRequest payload.
    
    For independent resource API calls (Terraform flow), the initialize endpoint
    accepts a pre-formed guest configuration dictionary directly. Callers using
    the independent APIs are responsible for forming the guest config dict themselves.
"""
from typing import Dict, Any
import logging

from .pydantic_models import ManagedDeploymentRequest

logger = logging.getLogger(__name__)


def generate_guest_config(request: ManagedDeploymentRequest) -> Dict[str, Any]:
    """Generate guest configuration dictionary from flat ManagedDeploymentRequest.
    
    Extracts guest configuration fields from the flat request payload and
    composes them into a dictionary suitable for KVP transmission.
    
    This function is used internally by the Managed Deployment Service to
    automatically compose the guest config payload from the form submission.
    External callers using independent resource APIs should form their own
    guest config dictionaries.
    
    The returned keys match the field names expected by the PowerShell host
    agent and ultimately map to KVP keys (e.g., guest_v4_ip_addr maps to
    hlvmm.data.guest_v4_ip_addr in the guest registry).
    
    Args:
        request: The flat ManagedDeploymentRequest containing all form fields
        
    Returns:
        Dictionary containing guest configuration keys for KVP transmission.
        Always includes guest_la_uid and guest_la_pw.
        
    Notes:
        - This function does NOT validate the model (already validated by Pydantic)
        - This function does NOT encrypt the output (handled by KVP transmission layer)
        - This function does NOT interact with the host agent
    
    Example:
        >>> request = ManagedDeploymentRequest(
        ...     target_host="hyperv-01", vm_name="web-01", gb_ram=4, cpu_cores=2,
        ...     network="Production", guest_la_uid="Administrator", guest_la_pw="Pass123!",
        ... )
        >>> config = generate_guest_config(request)
        >>> assert "guest_la_uid" in config
        >>> assert "guest_la_pw" in config
    """
    config: Dict[str, Any] = {}
    
    # Local administrator credentials (always required)
    config["guest_la_uid"] = request.guest_la_uid
    config["guest_la_pw"] = request.guest_la_pw
    
    # Domain join configuration if provided (all-or-none validated by model)
    if request.guest_domain_join_target:
        config["guest_domain_join_target"] = request.guest_domain_join_target
        config["guest_domain_join_uid"] = request.guest_domain_join_uid
        config["guest_domain_join_pw"] = request.guest_domain_join_pw
        config["guest_domain_join_ou"] = request.guest_domain_join_ou
        
        logger.debug(
            "Added domain join config for VM '%s' to domain '%s'",
            request.vm_name,
            request.guest_domain_join_target,
        )
    
    # Ansible configuration if provided (all-or-none validated by model)
    if request.cnf_ansible_ssh_user:
        config["cnf_ansible_ssh_user"] = request.cnf_ansible_ssh_user
        config["cnf_ansible_ssh_key"] = request.cnf_ansible_ssh_key
        
        logger.debug(
            "Added Ansible SSH config for VM '%s' (user: %s)",
            request.vm_name,
            request.cnf_ansible_ssh_user,
        )
    
    # Static IP configuration if provided (all-or-none validated by model)
    if request.guest_v4_ip_addr:
        config["guest_v4_ip_addr"] = request.guest_v4_ip_addr
        config["guest_v4_cidr_prefix"] = request.guest_v4_cidr_prefix
        config["guest_v4_default_gw"] = request.guest_v4_default_gw
        config["guest_v4_dns1"] = request.guest_v4_dns1
        
        # Optional DNS2 (not part of all-or-none set)
        if request.guest_v4_dns2:
            config["guest_v4_dns2"] = request.guest_v4_dns2
        
        # Optional DNS suffix (not part of all-or-none set)
        if request.guest_net_dns_suffix:
            config["guest_net_dns_suffix"] = request.guest_net_dns_suffix
        
        logger.debug(
            "Added static IP config for VM '%s' (IP: %s/%s)",
            request.vm_name,
            request.guest_v4_ip_addr,
            request.guest_v4_cidr_prefix,
        )
    
    logger.info(
        "Generated guest config for VM '%s' with %d keys",
        request.vm_name,
        len(config),
    )
    
    return config
