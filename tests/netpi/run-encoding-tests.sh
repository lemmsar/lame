#!/usr/bin/env bash
# SPDX-License-Identifier: LGPL-2.0-or-later
# Run against a configured build with --disable-decoder.
set -eu

test_source_dir=$(CDPATH='' cd -- "$(dirname -- "$0")/../.." && pwd)
test_build_dir=$(CDPATH='' cd -- "${1:?usage: run-encoding-tests.sh BUILD_DIR}" && pwd)
test_output_dir=$(mktemp -d)
trap 'rm -rf "$test_output_dir"' EXIT HUP INT TERM
read -r -a test_cc <<< "${CC:-cc}"

# CFLAGS/LDFLAGS intentionally accept the compiler's usual space-separated flags.
# shellcheck disable=SC2086
"${test_cc[@]}" ${CFLAGS:-} -std=c99 -Wall -Wextra -Werror \
    -I"$test_source_dir/include" "$test_source_dir/tests/netpi/test_encoding.c" \
    -L"$test_build_dir/libmp3lame/.libs" -Wl,-rpath,"$test_build_dir/libmp3lame/.libs" \
    ${LDFLAGS:-} -lmp3lame -lm -o "$test_output_dir/test_encoding"

# Include vbrquantize.c in the white-box test, then resolve its private dependencies.
set --
if [ -f "$test_build_dir/libmp3lame/.libs/libmp3lame.a" ]; then
    set -- "$test_build_dir/libmp3lame/.libs/libmp3lame.a"
else
    for test_object in "$test_build_dir"/libmp3lame/.libs/*.o; do
        case "$test_object" in */vbrquantize.o) continue ;; esac
        set -- "$@" "$test_object"
    done
fi
for test_archive in "$test_build_dir"/libmp3lame/vector/.libs/*.a \
                    "$test_build_dir"/libmp3lame/i386/.libs/*.a; do
    if [ -f "$test_archive" ]; then
        set -- "$@" "$test_archive"
    fi
done
# shellcheck disable=SC2086
"${test_cc[@]}" ${CFLAGS:-} -DHAVE_CONFIG_H \
    -I"$test_build_dir" -I"$test_source_dir/include" -I"$test_source_dir/libmp3lame" \
    "$test_source_dir/tests/netpi/test_vbr_quantize.c" "$@" \
    ${LDFLAGS:-} -lm -o "$test_output_dir/test_vbr_quantize"

if [ -n "${NETPI_TEST_RUNNER:-}" ]; then
    "$NETPI_TEST_RUNNER" "$test_output_dir/test_vbr_quantize"
else
    "$test_output_dir/test_vbr_quantize"
fi

set --
if [ -n "${NETPI_ENCODING_OUTPUT_DIR:-}" ]; then
    mkdir -p -- "$NETPI_ENCODING_OUTPUT_DIR"
    set -- "$NETPI_ENCODING_OUTPUT_DIR"
fi
if [ -n "${NETPI_TEST_RUNNER:-}" ]; then
    "$NETPI_TEST_RUNNER" "$test_output_dir/test_encoding" "$@"
else
    "$test_output_dir/test_encoding" "$@"
fi
