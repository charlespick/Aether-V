# Roadmap

- [x] Define roadmap
- [X] New name
- [x] Create containerized, k8s ready, python service to handle auth, orchestration, api, future terraform integration, and web ui
- [x] Ci to build the container while on the `server` branch and publish to GHCR
- [x] Docs and examples for deploying on k8s during development
- [ ] Ensure auth works - OIDC interactive and API token
- [x] Ensure webui works
- [ ] Ensure inventory display works
- [ ] Ensure job queue and new/delete VM actions work
- [ ] Ensure "worker" process disbatch and orchestration works - should mirror existing Ansible playbooks
- [x] Move ISO building and scripts/ISO deployment into the service - build ISOs when needed on service startup, deploy scripts and ISOs to hosts at startup if version mismatch
- [x] Clean up legacy Ansible, CI tasks, docs
- [ ] Handle image management
- [ ] Write Terraform provider to interface with API

## Design principals
* As lightweight as possible to maintain as a project - no state management, no databases or schema migration management
* Delegate outwards - auth, configuration, HA, etc delegated to external systems - refer to the 
[service architecture document](./service-architecture.md)
* Maintain exact orchestration parity with existing Ansible playbooks during initial migration
* This service should replicate the concepts of auth, job management, and interfacing that were previously provided by AWX with Ansible, while providing a strong platform for new features such as the inventory view, Terraform integration, etc
* Host setup is now done on the fly - ISOs are built at container build time and stored in the container with the scripts. Scripts and ISOs are transferred to hosts at service startup if version mismatch detected. No more need for CI jobs publishing ISOs, host setup tasks, or manual installation scripts