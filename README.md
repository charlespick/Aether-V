# Aether-V
Next-gen VMM for Hyper-V - wip

> [!IMPORTANT]
> This project is currently undergoing it's biggest migration yet on the `server` branch. Referances to HLVMM is just a remanant of the old project name. `hlvmm` will continue to be used in source code, variables, namespaces, and such but we will be slowly transitioning to Aether-V and `aetherv` in Docs and new code. 

> This renaming and overhaul marks a fundamental change in the direction of the project. Building on the strong foundation in secure, resiliant Hyper-V KVP powered configuration injection of HLVMM, Aether-V is the server portion of the project designed to be lightweight to maintain, and unifying workflows that were previously spread out across build systems, AWX/Ansible, and other systems. 

> [!TIP]
> During this transition, continue to use the project on the `main` branch. 

![HLVMM In AWX](Docs/AWXSurvey.png)

**Advantages of using HLVMM**

* You don't need an SCVMM License or SQL Server instance.
* Tighter integration with modern automation tools - Ansible, NetBox, just to
name a few.
* Not another thing to maintain in your environment, developed for homelabbing,
just as powerful in the enterprise.
* Lightweight - all provisioning occurs on the hosts. Combine with AWX/Ansible
Tower or another automation system for centralized management.
* Secrets in provisioning artifacts are not exposed outside the VM. Instead of
mounting a specialized provisioning ISO with domain join and local administrator
passwords, HLVMM submits provisioning data to the virtual machine using Hyper-V's 
KVP integration, encrypted with a key only the VM has access to after the
provisioning process has finished. 

**How does it work?**

1. Host copies image and provisioning media, configures and starts VM
2. Guest initiates secure communication and gets it's data
3. Once host sends it's data, it's done
4. Guest finishes everything internally, doesn't need to signal anything to
the host with a shut down

**How do I get started?**

1. Build a golden image.
    
    Windows: `sysprep` your installation after you have installed everything you
    want. Activate Windows with AVMA if you're licensed for it, or extend the
    provisioning service to do this for you.
    
    Linux: Make sure cloud-init is ready and configured for "nocloud" (ISO/CD-ROM)
    provisioning. Make sure KVP Daemons are installed if not included with your
    distro by default. 
2. Deploy the Aether-V service (containerized) - ISOs are built automatically
   at container build time and deployed to hosts on startup.
3. Publish the golden images to your Hyper-V hosts.
4. Use the Aether-V web UI, REST API, or Terraform provider (future) to manage VMs. 

**How can I extend the capabilities of the customization phase?**

While I'm actively developing properties and fields you can customize VMs with,
if you have a custom need, you can easily extend the functionality of the project
to fit your unique needs. 
1. Extend ProvisioningService.sh/ps1 with added params and logic
2. Add additional phases if you need additional reboots
3. Extend your calling hooks (Ansible playbooks or other scripts to use the 
new fields)
