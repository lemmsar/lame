#!/usr/bin/env bash
# SPDX-License-Identifier: LGPL-2.0-or-later
set -euo pipefail
source_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)"
build_dir="$(cd -- "${1:?usage: run-tests.sh BUILD_DIR}" && pwd -P)"
test_dir="$(mktemp -d)"
trap 'rm -rf -- "$test_dir"' EXIT
read -r -a compiler <<< "${CC:-cc}"
read -r -a compile_flags <<< "${CFLAGS:-}"
read -r -a link_flags <<< "${LDFLAGS:-}"
runner=()
if [[ -n "${NETPI_TEST_RUNNER:-}" ]]; then runner=("$NETPI_TEST_RUNNER"); fi
includes=(-DHAVE_CONFIG_H -I"$build_dir" -I"$source_dir/include" -I"$source_dir/libmp3lame")
archive="$build_dir/libmp3lame/.libs/libmp3lame.a"
for name in allocations resampler; do
    extra=()
    if [[ "$name" == allocations ]]; then
        extra=(-Wl,--wrap=calloc,--wrap=malloc,--wrap=free)
    fi
    "${compiler[@]}" "${compile_flags[@]}" "${includes[@]}" \
        "$source_dir/tests/netpi/test_$name.c" "$archive" "${extra[@]}" \
        "${link_flags[@]}" -lm -o "$test_dir/test_$name"
    "${runner[@]}" "$test_dir/test_$name"
done
bash "$source_dir/tests/netpi/run-encoding-tests.sh" "$build_dir"
"${compiler[@]}" "${compile_flags[@]}" "${includes[@]}" \
    "$source_dir/tests/netpi/test_neon.c" \
    "$source_dir/libmp3lame/vector/neon_choose_table.c" \
    "$source_dir/libmp3lame/tables.c" "${link_flags[@]}" -lm -o "$test_dir/test_neon"
if "${runner[@]}" "$test_dir/test_neon"; then
    :
else
    status=$?
    if [[ "$status" != 77 ]]; then exit "$status"; fi
fi
