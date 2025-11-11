# syntax=docker/dockerfile:1
FROM mcr.microsoft.com/powershell:7.4-ubuntu-22.04

RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        xorriso \
        genisoimage \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /github/workspace

ENTRYPOINT ["pwsh", "-NoLogo", "-NoProfile", "-File"]
