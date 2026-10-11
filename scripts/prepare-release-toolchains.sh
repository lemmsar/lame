#!/usr/bin/env bash
# SPDX-License-Identifier: LGPL-2.0-or-later
# Run inside the pinned Debian 13 GCC container used by release.yml.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends gcc-14 clang-19 lld-19 llvm-19 \
    ffmpeg python3 patchelf binutils curl ca-certificates xz-utils pkg-config \
    libtinfo6 libxml2 zlib1g util-linux

version=23.1.3
case "$(uname -m)" in
    x86_64)
        architecture=X64
        checksum=ca9fe385a5d9e2d88132dc0e23a00e9f87f38fa75f67207b5e457d208e71d013
        ;;
    aarch64)
        architecture=ARM64
        checksum=56d005e339c979a696ed6c244e6472e16f3b1371e48987a07e6145bda7ee0d03
        ;;
    *) echo 'Release builds require native x86_64 or ARM64 Linux.' >&2; exit 1 ;;
esac
archive="${LLVM_ARCHIVE:-/tmp/LLVM-$version-Linux-$architecture.tar.xz}"
if [[ ! -f "$archive" ]]; then
    curl --fail --location --retry 3 --proto '=https' \
        "https://github.com/llvm/llvm-project/releases/download/llvmorg-$version/LLVM-$version-Linux-$architecture.tar.xz" \
        --output "$archive"
fi
echo "$checksum  $archive" | sha256sum --check --strict
mkdir -p /opt/llvm-23
tar -xJf "$archive" --strip-components=1 -C /opt/llvm-23
/opt/llvm-23/bin/clang --version
/usr/local/bin/gcc --version
