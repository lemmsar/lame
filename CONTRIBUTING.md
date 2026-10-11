<!-- SPDX-License-Identifier: LGPL-2.0-or-later -->
# Contributing

This repository maintains an unofficial fork of LAME 4.0. Open an issue or pull
request here for fork-specific work. Link the relevant upstream report and a
fixed upstream revision when adapting a change. Keep original copyright and
license notices, and describe any local differences from the upstream patch.

New fork scripts, tests and maintained documentation use
`SPDX-License-Identifier: LGPL-2.0-or-later`. Modified upstream files carry a
short `lemmsar/lame` change notice with the change date, as described in `COPYING`.
Follow [STYLEGUIDE](STYLEGUIDE) for existing C code and keep refactoring separate
from encoder behavior changes.

## Build and run the regression suite

The regression harness targets GNU/Linux with a C compiler, GNU make, GNU
linker wrapping support and Bash. It needs both the static and shared encoder
libraries. FFmpeg is needed for decode checks and installer tests; Python 3.11
or later is needed for the build-tooling tests.

From the source root:

```sh
lame_source=$(pwd)
mkdir -p build/test
cd build/test
"$lame_source/configure" --disable-frontend --disable-decoder --disable-nasm \
  --enable-static --enable-shared --disable-neon --disable-ieeehack
make -j2 check-netpi
```

`check-netpi` builds the encoder and runs `tests/netpi/run-tests.sh` with the
configured compiler and flags. The historical `make test` target performs a
reference-file byte comparison; ordinary `make check` does not run the added
fork regressions.

The harness injects allocation failures, checks cleanup and retry output,
checks resampling duration, exercises the public encoder API over rates and
channel layouts, and checks VBR quantization bounds. NEON-specific comparisons
run on builds that enable NEON and report a skip on the scalar build.

To preserve the generated MP3 fixtures and check them with FFmpeg, run from the
configured build directory:

```sh
NETPI_ENCODING_OUTPUT_DIR="$PWD/encoded" make check-netpi
for file in encoded/*.mp3; do
  ffmpeg -v error -xerror -i "$file" -f null -
done
```

From the source root, run the build-option tests and the longer real installer
test:

```sh
python3 tests/netpi/test_build_profiles.py
python3 tests/netpi/test_installer.py
```

The installer test uses a temporary writable prefix. It compiles several
variants, checks reused and replaced installations, and runs LTO/PGO builds.

For a command line encoder built with the [README](README.md) instructions,
check Unicode tags and decoding with:

```sh
python3 tests/netpi/test_frontend.py /path/to/build/frontend/lame
```

This test requires FFmpeg and FFprobe. The distribution CI job runs it against
the executable built from the extracted source archive.

## Sanitizers and ARM64

Use a separate build directory for each configuration. For the sanitizer
configuration, set these variables before configuring, then use the same
library configuration and `make check-netpi` command above:

```sh
export CFLAGS='-O1 -g -fno-omit-frame-pointer -fsanitize=address,undefined -fno-pie'
export LDFLAGS='-fsanitize=address,undefined -no-pie'
export ASAN_OPTIONS=detect_leaks=1
export UBSAN_OPTIONS=halt_on_error=1
```

The [CI workflow](.github/workflows/ci.yml) is the executable reference for the
native, IEEE-hack, sanitizer, AArch64/QEMU and installer configurations. ARM64
runs use a cross compiler, QEMU and its matching runtime libraries. Both scalar
and opt-in NEON builds run the suite, then compare complete output streams.

Changes to quantization, psychoacoustics, resampling or floating-point behavior
also need representative audio evaluation. Report listening results separately
from decode validity and byte equality. Report Raspberry Pi timing and thermal
measurements separately from QEMU results. Include compiler flags, CPU, input
hashes and the baseline used for any performance claim.

## Generated build files

Normal builds use the checked-in `configure`, `config.h.in` and `Makefile.in`
files. Regenerate them when changing `configure.ac` or `Makefile.am`. The
maintained generator versions are **Autoconf 2.73** and **Automake 1.18.1**.
Put those versions on `PATH`, check their versions, then run from the source
root:

```sh
autoconf --version
automake --version
aclocal -I m4
autoheader
autoconf
automake --add-missing --copy
```

Use the bundled Libtool macros for this regeneration; updating the Libtool
support files is a separate change. Include regenerated files with the source
change, inspect the diff, and verify a fresh out-of-tree build. New distributed
scripts, tests and documents also need entries in `Makefile.am` and its
generated `Makefile.in`. Check the archive with `make dist` and build/test from
an extracted archive so required files are present outside a Git checkout.

## Patch and issue contents

Describe the observable failure, the corrected behavior and the verification
performed. Include a small regression input or a deterministic generator when
possible. Keep contributed audio redistributable and free of personal data.
Record the revision, architecture, compiler, configuration and failing command.

Maintain session ownership and cleanup behavior described in [HACKING](HACKING).
In-process global table initialization still needs coordination with other
encoder instances; the fork does not promise concurrent initialization safety.

The optional `scripts/export-netpi-patch.py DESTINATION` command exports a clean,
committed fork delta against `upstream/lame-4.0`, together with source identity
and license documentation, for application integrations. Changes to that
exporter or to binary files require checking that the consumer can apply the
resulting patch.

Documentation updated 2026-10-11.
