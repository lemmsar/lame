<!-- SPDX-License-Identifier: LGPL-2.0-or-later -->
# Binary releases

`RELEASE_VERSION` identifies the fork revision, starting at `4.0-r1`. It does
not change the upstream C API version `4.0` or `libmp3lame.so.0`. Increment the
revision for every published correction, including packaging changes. Published
tags and assets are immutable by project policy; never force-update them.

The [native release workflow](.github/workflows/release.yml) builds and tests
both architectures on pull requests. The pinned official GCC 16.2 container
provides a Debian 13 environment on native x86_64 and ARM64 runners. Debian
GCC 14/Clang 19 and SHA-256-pinned upstream Clang 23.1.3 are comparison candidates.
The package inventory records exact installed Debian versions, and the
benchmark report records compiler versions, flags, CPU, input hashes and raw
timings. Updating a toolchain requires another pull request and comparison.

`scripts/build-release.sh` builds generic x86-64 or ARMv8-A code. It compares
ordinary and LTO builds without PGO or optional NEON changes. Every candidate
must pass encoder, allocation-failure, resampling, CLI PCM and Unicode checks
before timing. The benchmark uses deterministic synthetic input, interleaves
candidates and retains the baseline when the measured improvement is below 3%.
This is a workload-specific selection, not a claim of a universally fastest
compiler. Representative music, listening tests and native Pi measurements are
separate validation tasks.

The selected executable uses a relative `$ORIGIN/../lib` runtime search path.
The packager validates the extracted executable and library and tests FFmpeg
encoding and decoding. Runtime dependencies come from Debian 13; do not install
these binaries on Debian 12 or a 32-bit system. The NetPi source installer is
the fallback for other supported GNU/Linux systems.

## Publish a revision

1. Update `RELEASE_VERSION` and `RELEASE_NOTES.md`, and submit a pull request.
2. Require the encoder validation and both native binary jobs to pass. Review
   the benchmark artifacts and extracted-package validation output.
3. Merge the verified changes into `main`. Create the matching annotated tag
   on that commit, for example `git tag -a v4.0-r1 -m 'LAME 4.0 revision 1'`.
4. Push the tag. The workflow rebuilds and revalidates both binaries, checks
   that their source identity matches the tag, and generates the complete Git
   source archive, `release.json` and `SHA256SUMS`.
5. The workflow creates a draft release, attaches every asset, then publishes
   it as a prerelease. It fails if the release already exists. On a failed
   draft upload, investigate and finish the draft with the same verified
   artifacts; never replace published assets.
6. Copy the verified `release.json` into NetPi's `third_party/lame/`, refresh its
   vendored source using `scripts/export-netpi-patch.py`, and test installation
   and rollback before merging the integration.
7. Record real Raspberry Pi encode/decode, playback, throughput and thermal
   checks before promoting the prerelease to stable. Repository visibility is
   independent of release status; private repositories require authorized
   downloads through GitHub CLI or a token.

Distribute the full corresponding source and existing copyright, modification,
license and warranty notices with every binary release. `SOURCE.txt` in each
archive names the source asset and commit. See [COPYING](COPYING) and
[LICENSE](LICENSE). The release includes no system package replacements.
