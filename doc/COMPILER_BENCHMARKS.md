<!-- SPDX-License-Identifier: LGPL-2.0-or-later -->
# Comparing release compilers

Compiler selection is specific to the CPU, build options and input corpus.
The benchmark selects a candidate only after the encoder and frontend
regressions pass. Decoding checks and signal error measurements do not establish
perceptual equivalence; listening remains a separate quality check.

## Toolchain sources

Debian 13 provides both [GCC 14](https://packages.debian.org/trixie/gcc-14)
and [Clang 19](https://packages.debian.org/trixie/clang-19) for amd64 and arm64.
They are useful distribution-supported reference candidates. The upstream
[GCC release list](https://gcc.gnu.org/releases.html) and
[LLVM releases](https://github.com/llvm/llvm-project/releases) provide newer
stable candidates. Pin the exact release, package/container identity and
download checksum; a moving snapshot is not a substitute for a stable release.

For native ARM CI, GitHub documents the
[`ubuntu-24.04-arm` runner](https://docs.github.com/en/actions/reference/runners/github-hosted-runners).
Run a Debian 13 arm64 container on an ARM host, and a Debian 13 amd64 container
on an x86_64 host. For the packaged reference compilers, install
`gcc-14 clang-19 make libc6-dev binutils pkg-config ffmpeg python3` in that
container. Clang LTO also requires a matching supported linker such as `lld-19`.
Record the actual installed versions, not just the package names.

An ARM cloud runner measures its own CPU, not a Raspberry Pi 3's Cortex-A53.
QEMU is useful for execution and output validation but cannot select a compiler
on the basis of target-device speed. The benchmark rejects known emulator
controls and mismatching executable architectures; the caller must still use
native hardware. Virtual-machine scheduling can add measurement noise.

## Build comparable candidates

Use a clean source snapshot and separate out-of-tree build directories. The
benchmark expects both shared and static libraries and the CLI frontend:

```sh
CC=gcc-14 \
CFLAGS='-O3 -ffast-math -fomit-frame-pointer -std=gnu11 -march=x86-64' \
/path/to/lame/configure --disable-decoder --disable-nasm \
  --enable-static --enable-shared --disable-neon --disable-ieeehack
make -j2
```

Use `-march=armv8-a` on ARM64. Do not use `-march=native`, Cortex-specific flags
or NEON changes while comparing compilers for a generic release. Keep
floating-point and configure options identical. If comparing LTO, identify it
in the candidate name, add `-flto` to CFLAGS and LDFLAGS, and select the matching
Clang linker explicitly. A compiler comparison and an LTO comparison are
different variables and should remain visible in the result.

## Run the benchmark

```sh
python3 scripts/benchmark-compilers.py \
  --candidate gcc-14=/tmp/build-gcc14 \
  --candidate clang-19=/tmp/build-clang19 \
  --output /tmp/compiler-benchmark.json \
  --seconds 20 --warmups 1 --repeats 5
```

The first candidate is the baseline. All candidates must be configured from
the same source directory as the script. The script runs `make check-netpi`
and `test_frontend.py` for every candidate, then measures V0 and CBR 320 kbps
encoding on stereo 44.1 kHz tonal, transient and noise-containing signals.
Corpus generation uses integer arithmetic and a fixed random seed; the input
hashes identify the exact samples used. Warmup runs are excluded, candidate
order rotates between repetitions, and timing is pinned to one allowed CPU.
`--cpu` can select another permitted CPU.

The JSON contains the source identity, CPU, compiler versions, flags, executable
and library hashes, input hashes, raw elapsed/user/system times and medians.
Each candidate must produce the same bytes across its repeated runs. Output
hashes and diagnostic decode error metrics allow comparison across candidates;
different compiler outputs need further quality review, not an assumption that
the faster result sounds better. Decoded frame count, finite samples and a
gross-corruption check are enforced. Validation logs are retained next to the
JSON. Failed runs have `status: failed` and no recommended candidate.

The score is the geometric mean of each case's median CPU time divided by the
baseline's median. Lower is faster. The recommendation retains the baseline
unless the leading candidate improves that score by at least 3 percent
(`--min-speedup-percent`). This is an explicit selection policy, not a
statistical confidence interval. Inspect the raw ranges and repeat a comparison
when system load makes the result uncertain.

Elapsed time includes process startup, reading PCM and writing the MP3. Corpus
generation, decoding and regression checks are outside the timing window.
This tool compares the CLI encoder; the release packaging checks must also
verify the shared library with the target FFmpeg. Preserve benchmark results
alongside the corresponding release binaries and source archive.
