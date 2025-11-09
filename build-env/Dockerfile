# Build Environment Container for Aether-V
# This container pre-installs ISO creation tools and PowerShell
# Used as the CI runner environment to build ISOs before building the server container
# This dramatically reduces build times by avoiding repeated apt-get install steps

FROM ubuntu:22.04

# Prevent interactive prompts during package installation
ENV DEBIAN_FRONTEND=noninteractive

# Install ISO creation tools and PowerShell in one layer
# These are the tools needed OUTSIDE the Docker build to create ISOs
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    # ISO creation tools
    xorriso \
    genisoimage \
    mkisofs \
    # PowerShell dependencies
    wget \
    apt-transport-https \
    software-properties-common \
    ca-certificates \
    && \
    # Install PowerShell
    wget -q https://packages.microsoft.com/config/ubuntu/22.04/packages-microsoft-prod.deb && \
    dpkg -i packages-microsoft-prod.deb && \
    rm packages-microsoft-prod.deb && \
    apt-get update && \
    apt-get install -y powershell && \
    # Clean up to keep image small
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /workspace

# This container is meant to be used as a CI runner environment
# It provides the tools needed to build ISOs from the repository
CMD ["/bin/bash"]
