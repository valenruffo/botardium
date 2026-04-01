FROM mcr.microsoft.com/devcontainers/base:ubuntu-24.04

RUN apt-get update && export DEBIAN_FRONTEND=noninteractive \
    && apt-get install -y --no-install-recommends \
      build-essential \
      pkg-config \
      libssl-dev \
      libgtk-3-dev \
      libayatana-appindicator3-dev \
      librsvg2-dev \
      patchelf \
      libwebkit2gtk-4.1-dev \
      libxdo-dev \
      curl \
      wget \
      unzip \
      ca-certificates \
      xvfb \
      git \
    && rm -rf /var/lib/apt/lists/*
