# syntax=docker/dockerfile:1

FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    bash \
    bc \
    binutils \
    bison \
    build-essential \
    ca-certificates \
    cpio \
    curl \
    file \
    flex \
    git \
    kmod \
    libelf-dev \
    libncurses-dev \
    libssl-dev \
    patch \
    perl \
    python3 \
    rsync \
    unzip \
    wget \
    xz-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /work

CMD ["/bin/bash"]