#!/usr/bin/env python3
"""Build a private, identified LAME library without replacing system packages."""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1]
UPSTREAM_SHA256 = "3df5124d5ad3a98312ffd7ba6a9b36230e4f8a3e66d3ce0f425e336c32d216eb"


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def source_digest():
    checksum = hashlib.sha256()
    for path in sorted(SOURCE.rglob("*")):
        relative = path.relative_to(SOURCE)
        if any(
            part in (".git", "autom4te.cache", "__pycache__", ".pytest_cache", ".ruff_cache")
            for part in relative.parts
        ) or relative.parts[0].startswith(("build", ".build")):
            continue
        if path.name.endswith("~"):
            continue
        if path.is_file():
            checksum.update(
                str(relative).encode() + b"\0" + bytes.fromhex(digest(path))
            )
    return checksum.hexdigest()


def output(command):
    return subprocess.check_output(command, text=True).strip()


def check(library):
    # A fresh process cannot reuse a dlopen handle from an earlier installation.
    subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            (
                "import ctypes,sys; lib=ctypes.CDLL(sys.argv[1]); "
                "lib.get_lame_version.restype=ctypes.c_char_p; "
                "sys.exit(0 if lib.get_lame_version()==b'4.0' else 1)"
            ),
            str(library),
        ],
        check=True,
        timeout=5,
        env={
            k: v
            for k, v in os.environ.items()
            if k not in ("LD_PRELOAD", "LD_TRACE_LOADED_OBJECTS")
        },
    )
    with tempfile.TemporaryDirectory(prefix="lame-check-") as temporary:
        target = Path(temporary) / "check.mp3"
        environment = {
            k: v
            for k, v in os.environ.items()
            if k not in ("LD_PRELOAD", "LD_TRACE_LOADED_OBJECTS")
        }
        environment["LD_PRELOAD"] = str(library)
        trace = subprocess.run(
            [shutil.which("ffmpeg")],
            capture_output=True,
            text=True,
            env={**environment, "LD_TRACE_LOADED_OBJECTS": "1"},
            check=True,
            timeout=10,
        )
        if str(library) + " (" not in trace.stdout:
            raise RuntimeError("FFmpeg did not load the private library")
        subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=997:sample_rate=44100:duration=0.2",
                "-ac",
                "2",
                "-c:a",
                "libmp3lame",
                "-q:a",
                "0",
                str(target),
            ],
            env=environment,
            check=True,
            timeout=30,
        )
        subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(target), "-f", "null", "-"],
            check=True,
            timeout=30,
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", type=Path, default=Path("/opt/netpi/lame-4.0"))
    parser.add_argument(
        "--profile", choices=("generic", "cortex-a53"), default="generic"
    )
    parser.add_argument("--fp-model", choices=("fast", "strict"), default="fast")
    parser.add_argument("--lto", action="store_true")
    parser.add_argument("--neon", action="store_true")
    parser.add_argument("--fast-log", choices=("auto", "yes", "no"), default="auto")
    parser.add_argument("--ieee-hack", action="store_true")
    parser.add_argument(
        "--pgo-corpus",
        type=Path,
        help="train with all WAV/FLAC files under this directory before rebuilding",
    )
    parser.add_argument("--jobs", type=int, default=2)
    parser.add_argument("--force", "--rebuild", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if not args.prefix.is_absolute() or args.jobs < 1:
        parser.error("--prefix must be absolute and --jobs must be positive")
    if args.prefix.resolve().is_relative_to(SOURCE):
        parser.error("install outside the source directory")
    if any(character.isspace() or character == ":" for character in str(args.prefix)):
        parser.error(
            "--prefix cannot contain whitespace or colons (LD_PRELOAD restriction)"
        )
    library = args.prefix / "lib/libmp3lame.so.0"
    if args.check:
        check(library.resolve(strict=True))
        return
    compiler = os.environ.get("CC", "gcc")
    for tool in (compiler, "make", "ffmpeg", "install", "ln", "mv"):
        if not shutil.which(tool):
            parser.error("missing required tool: " + tool)
    target = output([compiler, "-dumpmachine"])
    if args.profile == "cortex-a53" and not target.startswith("aarch64"):
        parser.error(
            "the cortex-a53 profile requires an AArch64 compiler and native execution"
        )
    flags = "-O3 -fomit-frame-pointer"
    flags += " " + os.environ.get("CFLAGS", "")
    flags += " -ffast-math" if args.fp_model == "fast" else " -fno-fast-math"
    if args.profile == "cortex-a53":
        flags += " -mcpu=cortex-a53"
    if args.lto:
        flags += " -flto"
    ldflags = os.environ.get("LDFLAGS", "") + (" -flto" if args.lto else "")
    configure = [
        "--disable-frontend",
        "--disable-decoder",
        "--disable-static",
        "--enable-shared",
        "--disable-nasm",
        "--enable-ieeehack" if args.ieee_hack else "--disable-ieeehack",
        "--enable-neon" if args.neon else "--disable-neon",
        "--enable-fast-log=" + args.fast_log,
    ]
    corpus = []
    if args.pgo_corpus:
        corpus = sorted(
            p.resolve()
            for p in args.pgo_corpus.rglob("*")
            if p.is_file() and p.suffix.lower() in (".wav", ".flac")
        )
        if not corpus:
            parser.error("--pgo-corpus must contain WAV or FLAC files")
    specification = {
        "upstream_sha256": UPSTREAM_SHA256,
        "source_sha256": source_digest(),
        "compiler": shutil.which(compiler),
        "compiler_version": output([compiler, "--version"]),
        "target": target,
        "configure": configure,
        "cflags": flags.strip(),
        "ldflags": ldflags.strip(),
        "profile": args.profile,
        "fp_model": args.fp_model,
        "training": [
            {"name": str(p.relative_to(args.pgo_corpus.resolve())), "sha256": digest(p)}
            for p in corpus
        ],
        "toolchain_environment": {
            key: os.environ.get(key, "")
            for key in (
                "CPPFLAGS",
                "LIBS",
                "AR",
                "RANLIB",
                "NM",
                "STRIP",
                "AS",
                "LD",
                "OBJDUMP",
                "PKG_CONFIG",
                "PKG_CONFIG_PATH",
                "LIBRARY_PATH",
                "CPATH",
                "C_INCLUDE_PATH",
            )
        },
    }
    build_id = hashlib.sha256(
        json.dumps(specification, sort_keys=True).encode()
    ).hexdigest()
    if not args.force and library.is_symlink():
        try:
            current = library.resolve(strict=True)
            manifest = json.loads((current.parent / "manifest.json").read_text())
            if not isinstance(manifest, dict):
                raise TypeError("invalid build manifest")
            if manifest.get("build_id") == build_id and manifest.get(
                "binary_sha256"
            ) == digest(current):
                check(current)
                print("LAME build already verified: " + build_id)
                return
        except (
            OSError,
            ValueError,
            TypeError,
            RuntimeError,
            subprocess.SubprocessError,
        ):
            print("Existing build cannot be reused; rebuilding", file=sys.stderr)
    with tempfile.TemporaryDirectory(prefix="lame-netpi-build-") as temporary:
        build = Path(temporary)
        environment = {
            **os.environ,
            "CC": compiler,
            "CONFIG_SITE": "/dev/null",
            "LC_ALL": "C",
        }

        def compile_library(extra=""):
            # Configure reuses conftest.c for different programs. Never collect or
            # consume its profiles; only the actual library is instrumented.
            env = {**environment, "CFLAGS": flags, "LDFLAGS": ldflags}
            with (build / "configure-output.log").open("a") as log:
                subprocess.run(
                    [str(SOURCE / "configure"), *configure],
                    cwd=build,
                    env=env,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    check=True,
                )
            with (build / "build-output.log").open("a") as log:
                subprocess.run(
                    [
                        "make",
                        "-j",
                        str(args.jobs),
                        "CFLAGS=" + flags + extra,
                        "LDFLAGS=" + ldflags + extra,
                    ],
                    cwd=build,
                    env=env,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    check=True,
                )

        try:
            if corpus:
                profiles = build / "profiles"
                profiles.mkdir()
                compile_library(" -fprofile-generate=" + str(profiles))
                training_lib = build / "libmp3lame/.libs/libmp3lame.so.0.0.0"
                for track in corpus:
                    for channels in (1, 2):
                        subprocess.run(
                            [
                                "ffmpeg",
                                "-v",
                                "error",
                                "-i",
                                str(track),
                                "-ac",
                                str(channels),
                                "-c:a",
                                "libmp3lame",
                                "-q:a",
                                "0",
                                "-f",
                                "null",
                                "-",
                            ],
                            env={**environment, "LD_PRELOAD": str(training_lib)},
                            check=True,
                        )
                # Profiles live outside .libs so make clean preserves them.
                subprocess.run(
                    ["make", "clean"], cwd=build, stdout=subprocess.DEVNULL, check=True
                )
                compile_library(
                    " -fprofile-use="
                    + str(profiles)
                    + " -fprofile-correction -Werror=missing-profile"
                )
            else:
                compile_library()
            built = build / "libmp3lame/.libs/libmp3lame.so.0.0.0"
            check(built)
            if source_digest() != specification["source_sha256"]:
                raise RuntimeError(
                    "source changed during the build; rerun with a stable source tree"
                )
            if any(
                digest(track) != expected["sha256"]
                for track, expected in zip(
                    corpus, specification["training"], strict=True
                )
            ):
                raise RuntimeError(
                    "training audio changed during the build; rerun with a stable corpus"
                )
            binary_hash = digest(built)
            destination = args.prefix / "builds" / (build_id + "-" + binary_hash)
            manifest = {
                **specification,
                "build_id": build_id,
                "binary_sha256": binary_hash,
                "pgo": bool(corpus),
            }
            (build / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
            writable = args.prefix
            while not writable.exists():
                writable = writable.parent
            privilege = [] if os.access(writable, os.W_OK) else ["sudo"]

            def install(*command):
                subprocess.run([*privilege, *map(str, command)], check=True)

            install("install", "-d", "-m", "0755", destination.parent, library.parent)
            installed = destination / "libmp3lame.so.0"
            if not destination.exists():
                staging = Path(
                    subprocess.check_output(
                        [
                            *privilege,
                            "mktemp",
                            "-d",
                            str(destination.parent / ".pending.XXXXXXXX"),
                        ],
                        text=True,
                    ).strip()
                )
                try:
                    install("install", "-d", "-m", "0755", staging)
                    install("install", "-m", "0644", built, staging / "libmp3lame.so.0")
                    for name in (
                        "manifest.json",
                        "config.log",
                        "configure-output.log",
                        "build-output.log",
                    ):
                        install("install", "-m", "0644", build / name, staging / name)
                    # A complete directory becomes visible at once. A concurrent
                    # identical publisher may win; validate its result below.
                    promoted = subprocess.run(
                        [*privilege, "mv", "-T", str(staging), str(destination)],
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    if promoted.returncode and not destination.is_dir():
                        raise RuntimeError("cannot publish build: " + promoted.stderr)
                finally:
                    if staging.exists():
                        install("rm", "-rf", "--", staging)
            if digest(installed) != binary_hash:
                raise RuntimeError(
                    "immutable build path contains different library bytes"
                )
            try:
                recorded = json.loads((destination / "manifest.json").read_text())
            except (OSError, ValueError):
                recorded = None
            if recorded != manifest:
                # A verified matching binary can safely retain its path while
                # missing/corrupt metadata is repaired with an atomic file swap.
                pending_manifest = destination / f".manifest.{os.getpid()}.json"
                install(
                    "install", "-m", "0644", build / "manifest.json", pending_manifest
                )
                install("mv", "-fT", pending_manifest, destination / "manifest.json")
            check(installed)
            link = library.parent / f".libmp3lame.so.0.{os.getpid()}"
            install("ln", "-s", os.path.relpath(installed, library.parent), link)
            install("mv", "-fT", link, library)
            print("Installed verified LAME 4.0: " + str(installed))
        except (subprocess.SubprocessError, OSError, RuntimeError):
            logs = Path(tempfile.mkdtemp(prefix="lame-build-failure-"))
            for name in ("config.log", "configure-output.log", "build-output.log"):
                if (build / name).exists():
                    shutil.copy2(build / name, logs / name)
            print("Build logs retained at " + str(logs), file=sys.stderr)
            raise


if __name__ == "__main__":
    main()
