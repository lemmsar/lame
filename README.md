<!-- SPDX-License-Identifier: LGPL-2.0-or-later -->
# LAME 4.0 maintenance fork

This unofficial fork maintains the LAME 4.0 MP3 encoder for NetPi and other
users of `libmp3lame`. It fixes encoding and allocation failures, adds regression
tests, and provides optional ARM64 and compiler optimization settings. The
public C API signatures and `4.0` version string are preserved. Keep the build manifest
or source revision to identify this fork's binaries.

## Source and changes

The starting point is the unmodified [LAME 4.0 source release](https://deb.debian.org/debian/pool/main/l/lame/lame_4.0.orig.tar.gz),
identified by the Git tag `upstream/lame-4.0` and this SHA-256:

```text
3df5124d5ad3a98312ffd7ba6a9b36230e4f8a3e66d3ce0f425e336c32d216eb
```

The upstream project is [LAME](https://lame.sourceforge.io/). Existing copyright
and license notices are retained. The original introductory documents are
preserved in [doc/upstream](doc/upstream/README): they describe the historical
upstream release, while the instructions here describe this fork.

| Area | Maintained change | Related upstream report or source |
| --- | --- | --- |
| VBR recovery | Preserve each band's minimum scalefactor when a frame runs out of bits | [Bug #490](https://sourceforge.net/p/lame/bugs/490/) |
| CBR/ABR | Disable incompatible amplified noise shaping in these modes | [Bug #516](https://sourceforge.net/p/lame/bugs/516/) |
| Resampling | Resample whenever the integer sample rates differ | [Patch #101](https://sourceforge.net/p/lame/patches/101/) |
| ARM64 | Add optional NEON Huffman bit counting | [Upstream source at SVN r7051](https://svn.code.sf.net/p/lame/svn/!svn/bc/7051/trunk/lame/libmp3lame/vector/neon_choose_table.c) |
| Reliability | Propagate allocation errors, clean up partial initialization, support retry, and remove undefined signed shifts | Regression tests in [tests/netpi](tests/netpi) |
| Quantization | Retain the chosen candidate's bit count and honor the IEEE-hack configuration value | Regression tests in [tests/netpi](tests/netpi) |
| Build tooling | Record build inputs, install immutable libraries, and offer explicit optimization profiles | [README.netpi](README.netpi) |

V0 and Joint Stereo presets are preserved. Floating-point and quantization
corrections can change encoded bytes; the automated checks do not establish an
audible quality improvement.

## Build the library and command line encoder

The checked-in `configure` script supports an ordinary Autotools build. A C
compiler and make are required. This example omits the optional decoder and
NASM assembler dependency:

```sh
mkdir build
cd build
../configure --disable-decoder --disable-nasm
make -j2
./frontend/lame --version
```

Use `../configure --help` to inspect other upstream build options. Build and
installation options for inherited Windows and other platform projects remain
in the source tree; this fork's automated validation covers Linux x86_64 and
AArch64. [CONTRIBUTING.md](CONTRIBUTING.md) gives the library-only regression
build and test commands.

For a private library used by FFmpeg on Linux, see [README.netpi](README.netpi).
That optional installer requires GNU/Linux, GCC, GNU tools, Python 3.11 or later,
and a dynamically linked FFmpeg with `libmp3lame` support. It executes the new
library on the build machine, so use it natively on the target device. The
ordinary source build does not require that installer.

## Validation and limits

[CI](.github/workflows/ci.yml) runs encoder regressions, allocation-failure and
retry tests, ASan/UBSan, and FFmpeg decoding checks. AArch64 tests run under QEMU;
scalar and NEON bit counts and complete encoded streams are compared. Installer
tests exercise build identity, reuse, recovery, force rebuilds, LTO and PGO.

Native Raspberry Pi throughput, temperature, playback interference and
level-matched ABX listening remain separate target-device validation tasks.
QEMU execution and byte comparisons establish neither a native ARM speedup nor
an audible improvement. NEON, LTO, PGO, Cortex-A53 tuning and nondefault fast-log
settings are explicit options to evaluate with representative inputs. The
fast-log default is `auto`, preserving upstream architecture defaults.

Legacy initialization writes shared quantization tables within a process.
Concurrent instance initialization is not guaranteed to be thread-safe. NetPi
runs a separate FFmpeg process for each conversion. Other integrations must
account for the shared initialization state.

## Documentation and contributions

- [CONTRIBUTING.md](CONTRIBUTING.md): development, tests, generated files and patches.
- [README.netpi](README.netpi): Linux private-library installation and profiles.
- [HACKING](HACKING): encoder layout, state ownership and initialization constraints.
- [include/lame.h](include/lame.h): public encoder API.
- [STYLEGUIDE](STYLEGUIDE): inherited C style conventions.

Report fork-specific issues and submit pull requests in this repository. Include
the source revision, compiler, architecture, build options and a minimal input
or reproducible signal generator. The project builds and tests independently of
the NetPi application.

## License

[COPYING](COPYING) preserves the GNU Library General Public License version 2
text. Source-file notices identify the applicable terms; the encoder files
permit version 2 or a later version. The fork's new scripts, tests and maintained
documentation are provided under `LGPL-2.0-or-later`. Existing upstream and
third-party notices remain in force. [LICENSE](LICENSE) contains usage guidance
and points to the complete license terms.

Fork documentation updated 2026-10-11.
