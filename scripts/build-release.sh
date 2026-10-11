#!/usr/bin/env bash
# SPDX-License-Identifier: LGPL-2.0-or-later
# Build, validate and compare native compilers before packaging one candidate.
set -euo pipefail
source_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
work_dir="${1:?usage: build-release.sh ABSOLUTE_WORK_DIR ABSOLUTE_OUTPUT_DIR}"
output_dir="${2:?output directory required}"
[[ "$work_dir" == /* && "$output_dir" == /* && ! -e "$work_dir" ]] || {
    echo 'Use a new absolute work directory and an absolute output directory.' >&2
    exit 1
}
version="$(cat "$source_dir/RELEASE_VERSION")"
[[ "$version" =~ ^4\.0-r[1-9][0-9]*$ ]]
case "$(uname -m)" in
    x86_64) arch=x86_64; isa=-march=x86-64 ;;
    aarch64) arch=arm64; isa=-march=armv8-a ;;
    *) echo 'Native x86_64 or ARM64 Linux required.' >&2; exit 1 ;;
esac
mkdir -p "$work_dir" "$output_dir"
export SOURCE_DATE_EPOCH
SOURCE_DATE_EPOCH="$(git -C "$source_dir" log -1 --format=%ct)"
export LC_ALL=C TZ=UTC
# Libtool forwards -fuse-ld but drops Clang's newer --ld-path option.
export PATH="/opt/llvm-23/bin:$PATH"
# The CLI must run on minimal Debian installations without terminal libraries.
export ac_cv_lib_termcap_initscr=no ac_cv_lib_curses_initscr=no ac_cv_lib_ncurses_initscr=no
candidates=()
for candidate in gcc14 gcc16 gcc16-lto clang19-lto clang23 clang23-lto; do
    case "$candidate" in
        gcc14) compiler=/usr/bin/gcc-14 ;;
        gcc16*) compiler=/usr/local/bin/gcc ;;
        clang19*) compiler=/usr/bin/clang-19 ;;
        clang23*) compiler=/opt/llvm-23/bin/clang ;;
    esac
    export CC="$compiler"
    export CFLAGS="-O3 -ffast-math -fomit-frame-pointer -std=gnu11 $isa"
    export LDFLAGS='-Wl,-z,relro,-z,now'
    export AR=ar RANLIB=ranlib NM=nm
    if [[ "$candidate" == *-lto ]]; then
        if [[ "$candidate" == clang* ]]; then
            CFLAGS+=' -flto=thin'
            LDFLAGS+=' -flto=thin'
            if [[ "$candidate" == clang19* ]]; then
                LDFLAGS+=' -fuse-ld=lld-19'
                AR=llvm-ar-19 RANLIB=llvm-ranlib-19 NM=llvm-nm-19
            else
                LDFLAGS+=' -fuse-ld=lld'
                AR=/opt/llvm-23/bin/llvm-ar RANLIB=/opt/llvm-23/bin/llvm-ranlib NM=/opt/llvm-23/bin/llvm-nm
            fi
        else
            CFLAGS+=' -flto'
            LDFLAGS+=' -flto'
            AR=gcc-ar RANLIB=gcc-ranlib NM=gcc-nm
        fi
    fi
    build="$work_dir/$candidate"
    mkdir "$build"
    (
        cd "$build"
        "$source_dir/configure" --prefix=/usr --disable-decoder --disable-nasm \
            --enable-static --enable-shared --enable-dynamic-frontends \
            --disable-neon --disable-ieeehack
        make -j"${RELEASE_JOBS:-2}"
    ) > "$work_dir/$candidate-build.log" 2>&1 || {
        tail -100 "$work_dir/$candidate-build.log" >&2
        exit 1
    }
    candidates+=(--candidate "$candidate=$build")
done
unset CC CFLAGS LDFLAGS AR RANLIB NM
report="$output_dir/benchmark-$arch.json"
python3 "$source_dir/scripts/benchmark-compilers.py" "${candidates[@]}" \
    --output "$report" --seconds 20 --warmups 1 --repeats 5
selected="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["recommended_candidate"])' "$report")"
case "$selected" in
    gcc14|gcc16|gcc16-lto|clang19-lto|clang23|clang23-lto) ;;
    *) echo 'Invalid benchmark recommendation.' >&2; exit 1 ;;
esac
python3 "$source_dir/scripts/package-release.py" --source-dir "$source_dir" \
    --build-dir "$work_dir/$selected" --version "$version" --output-dir "$output_dir"
tar -czf "$output_dir/validation-$arch.tar.gz" -C "$output_dir" "benchmark-$arch-logs"
dpkg-query -W > "$output_dir/build-packages-$arch.txt"
