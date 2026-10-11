#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.0-or-later
"""Package and validate a native Debian 13 LAME release from a committed checkout."""

import argparse
import gzip
import hashlib
import json
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path, PurePosixPath

UPSTREAM_VERSION = "4.0"
REPOSITORY = "https://github.com/lemmsar/lame"
LIBRARY = "lib/libmp3lame.so.0"
EXECUTABLE = "bin/lame"


def run(command, **options):
    return subprocess.run(
        command, check=True, capture_output=True, text=True, timeout=60, **options
    ).stdout.strip()


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def release_name(version, architecture):
    if not re.fullmatch(r"4\.0-r[1-9][0-9]*", version):
        raise ValueError("version must have the form 4.0-r1 (a positive fork revision)")
    if architecture not in ("x86_64", "arm64"):
        raise ValueError("unsupported release architecture")
    return f"lame-{version}-linux-{architecture}-debian13"


def native_target():
    architecture = {"x86_64": "x86_64", "aarch64": "arm64", "arm64": "arm64"}.get(
        platform.machine().lower()
    )
    release = platform.freedesktop_os_release() if sys.platform == "linux" else {}
    if (
        not architecture
        or release.get("ID") != "debian"
        or release.get("VERSION_ID") != "13"
    ):
        raise ValueError("release packaging requires native x86_64 or ARM64 Debian 13")
    return {
        "os": "linux",
        "architecture": architecture,
        "distribution": "debian",
        "distribution_version": "13",
    }


def relative_path(name):
    if not isinstance(name, str) or not name or "\\" in name or "\x00" in name:
        raise ValueError(f"unsafe package path: {name!r}")
    if any(part in ("", ".", "..") for part in name.split("/")):
        raise ValueError(f"unsafe package path: {name!r}")
    path = PurePosixPath(name)
    if path.is_absolute():
        raise ValueError(f"unsafe package path: {name!r}")
    return path


def build_configuration(build, source):
    values = {}
    for line in (build / "Makefile").read_text().splitlines():
        match = re.fullmatch(r"(CC|CFLAGS|LDFLAGS|abs_top_srcdir) = ?(.*)", line)
        if match:
            values[match[1]] = match[2].strip()
    if values.keys() != {"CC", "CFLAGS", "LDFLAGS", "abs_top_srcdir"}:
        raise ValueError("build Makefile lacks the compiler, flags or source directory")
    if Path(values["abs_top_srcdir"]).resolve() != source:
        raise ValueError(
            "build directory was configured from a different source directory"
        )
    compiler = shlex.split(values["CC"])
    if not compiler or any("$(" in value or "${" in value for value in values.values()):
        raise ValueError("build configuration contains unresolved make variables")
    return {
        "compiler": run([*compiler, "--version"], cwd=build),
        "cflags": values["CFLAGS"],
        "ldflags": values["LDFLAGS"],
    }


def source_identity(source):
    top = Path(
        run(["git", "-C", str(source), "rev-parse", "--show-toplevel"])
    ).resolve()
    if top != source:
        raise ValueError("source directory must be the Git checkout root")
    if run(["git", "-C", str(source), "status", "--porcelain", "--untracked-files=no"]):
        raise ValueError("commit all tracked source changes before packaging a release")
    commit = run(["git", "-C", str(source), "rev-parse", "HEAD"])
    epoch = os.environ.get("SOURCE_DATE_EPOCH")
    if epoch is None:
        epoch = run(["git", "-C", str(source), "show", "-s", "--format=%ct", "HEAD"])
    if not re.fullmatch(r"[0-9]+", epoch) or not 0 <= int(epoch) <= 0xFFFFFFFF:
        raise ValueError("SOURCE_DATE_EPOCH must be an unsigned 32-bit integer")
    return commit, int(epoch)


def check_elf(path, architecture):
    with path.open("rb") as stream:
        header = stream.read(20)
    machine = {"x86_64": 62, "arm64": 183}[architecture]
    if (
        header[:6] != b"\x7fELF\x02\x01"
        or len(header) < 20
        or int.from_bytes(header[18:20], "little") != machine
    ):
        raise ValueError(f"not a native {architecture} 64-bit ELF binary: {path}")


def make_archive(root, archive, epoch):
    # Normalize ownership, permissions, order and both tar/gzip timestamps.
    with (
        archive.open("xb") as output,
        gzip.GzipFile(
            filename="", mode="wb", fileobj=output, mtime=epoch
        ) as compressed,
        tarfile.open(fileobj=compressed, mode="w", format=tarfile.USTAR_FORMAT) as tar,
    ):
        for path in [root, *sorted(root.rglob("*"))]:
            if path.is_symlink() or not (path.is_file() or path.is_dir()):
                raise ValueError(
                    f"only regular files and directories may be packaged: {path}"
                )
            name = path.relative_to(root.parent).as_posix()
            relative_path(name)
            member = tarfile.TarInfo(name)
            member.mtime = epoch
            member.mode = (
                0o755 if path.is_dir() or name == f"{root.name}/{EXECUTABLE}" else 0o644
            )
            if path.is_dir():
                member.type = tarfile.DIRTYPE
                tar.addfile(member)
            else:
                member.size = path.stat().st_size
                with path.open("rb") as data:
                    tar.addfile(member, data)


def extract_archive(archive, destination, name):
    with tarfile.open(archive, "r:gz") as tar:
        seen = set()
        members = tar.getmembers()
        for member in members:
            path = relative_path(member.name)
            if path.parts[0] != name or member.name in seen:
                raise ValueError(
                    "archive has a duplicate path or unexpected root directory"
                )
            if not (member.isdir() or member.isfile()):
                raise ValueError("archive contains a link or special file")
            seen.add(member.name)
        for member in members:
            path = destination.joinpath(*PurePosixPath(member.name).parts)
            if member.isdir():
                path.mkdir(parents=True, exist_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                with tar.extractfile(member) as data, path.open("xb") as output:
                    shutil.copyfileobj(data, output)
            path.chmod(member.mode & 0o777)
    return destination / name


def verify_files(root, manifest):
    expected = manifest["files"]
    actual = {
        path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()
    }
    if actual != set(expected) | {"manifest.json"}:
        raise ValueError("archive contents do not match the manifest file list")
    for name, checksum in expected.items():
        path = root.joinpath(*relative_path(name).parts)
        if path.is_symlink() or digest(path) != checksum:
            raise ValueError(f"archive checksum mismatch: {name}")


def validate_runtime(root):
    library = root / LIBRARY
    executable = root / EXECUTABLE
    environment = {
        key: value
        for key, value in os.environ.items()
        if key
        not in ("LD_PRELOAD", "LD_LIBRARY_PATH", "LD_AUDIT", "LD_TRACE_LOADED_OBJECTS")
    }
    environment["LC_ALL"] = "C"
    trace = run([str(executable)], env={**environment, "LD_TRACE_LOADED_OBJECTS": "1"})
    match = re.search(r"libmp3lame\.so\.0\s+=>\s+(\S+)\s+\(", trace)
    if not match or Path(match[1]).resolve() != library:
        raise ValueError("relocated CLI did not load the packaged libmp3lame.so.0")
    if not re.search(
        r"\bversion 4\.0(?:\s|$)", run([str(executable), "--version"], env=environment)
    ):
        raise ValueError("relocated CLI does not report upstream version 4.0")
    run(
        [
            sys.executable,
            "-I",
            "-c",
            (
                "import ctypes,sys; library=ctypes.CDLL(sys.argv[1]); "
                "library.get_lame_version.restype=ctypes.c_char_p; "
                "assert library.get_lame_version()==b'4.0'"
            ),
            str(library),
        ],
        env=environment,
    )
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise ValueError(
            "FFmpeg with libmp3lame support is required for release validation"
        )
    private = {**environment, "LD_PRELOAD": str(library)}
    trace = run([ffmpeg], env={**private, "LD_TRACE_LOADED_OBJECTS": "1"})
    if str(library) + " (" not in trace:
        raise ValueError("FFmpeg did not load the packaged library")
    with tempfile.TemporaryDirectory(prefix="lame-release-audio-") as temporary:
        wav = Path(temporary) / "input.wav"
        run(
            [
                ffmpeg,
                "-nostdin",
                "-v",
                "error",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=997:sample_rate=44100:duration=0.25",
                "-ac",
                "2",
                str(wav),
            ],
            env=environment,
        )
        cli_mp3 = Path(temporary) / "cli.mp3"
        ffmpeg_mp3 = Path(temporary) / "ffmpeg.mp3"
        run(
            [str(executable), "--silent", "-V0", str(wav), str(cli_mp3)],
            env=environment,
        )
        run(
            [
                ffmpeg,
                "-nostdin",
                "-v",
                "error",
                "-i",
                str(wav),
                "-c:a",
                "libmp3lame",
                "-q:a",
                "0",
                str(ffmpeg_mp3),
            ],
            env=private,
        )
        for encoded in (cli_mp3, ffmpeg_mp3):
            run(
                [
                    ffmpeg,
                    "-nostdin",
                    "-v",
                    "error",
                    "-xerror",
                    "-err_detect",
                    "explode",
                    "-i",
                    str(encoded),
                    "-f",
                    "null",
                    "-",
                ],
                env=environment,
            )


def package(build, source, version, output):
    target = native_target()
    name = release_name(version, target["architecture"])
    commit, epoch = source_identity(source)
    toolchain = build_configuration(build, source)
    output.mkdir(parents=True, exist_ok=True)
    archive = output / f"{name}.tar.gz"
    if os.path.lexists(archive):
        raise ValueError(f"release archive already exists: {archive}")
    with tempfile.TemporaryDirectory(prefix=".lame-release-", dir=output) as temporary:
        work = Path(temporary)
        root = work / name
        files = {
            EXECUTABLE: build / "frontend/.libs/lame",
            LIBRARY: build / "libmp3lame/.libs/libmp3lame.so.0.0.0",
            **{
                f"share/licenses/lame/{file}": source / file
                for file in ("COPYING", "LICENSE", "README.md", "README.netpi")
            },
        }
        if (source / "include/lame.h").is_file():
            files["include/lame/lame.h"] = source / "include/lame.h"
        for name_in_archive, origin in files.items():
            destination = root / name_in_archive
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(origin, destination)
        (root / EXECUTABLE).chmod(0o755)
        for path in (root / EXECUTABLE, root / LIBRARY):
            check_elf(path, target["architecture"])
        run(["patchelf", "--set-rpath", "$ORIGIN/../lib", str(root / EXECUTABLE)])
        run(["patchelf", "--remove-rpath", str(root / LIBRARY)])
        for executable, allowed in (
            (EXECUTABLE, {"libmp3lame.so.0", "libm.so.6", "libmvec.so.1", "libc.so.6"}),
            (LIBRARY, {"libm.so.6", "libmvec.so.1", "libc.so.6"}),
        ):
            needed = set(run(["patchelf", "--print-needed", str(root / executable)]).splitlines())
            if not needed <= allowed:
                raise ValueError(f"unexpected runtime dependencies in {executable}: {needed - allowed}")
        if (
            run(["patchelf", "--print-rpath", str(root / EXECUTABLE)])
            != "$ORIGIN/../lib"
        ):
            raise ValueError("could not set the relocatable CLI library path")
        source_archive = f"lame-{version}-source.tar.gz"
        (root / "SOURCE.txt").write_text(
            f"LAME {version}: an unofficial maintenance fork of upstream LAME 4.0.\n"
            f"Source commit: {commit}\nRelease tag: v{version}\n"
            f"Corresponding source archive: {source_archive}\n"
            f"Download: {REPOSITORY}/releases/download/v{version}/{source_archive}\n\n"
            "The same release supplies the complete corresponding source, including\n"
            "build scripts and modification notices. The CLI loads the separate shared\n"
            "library in lib/, which can be replaced with a compatible rebuilt library.\n"
            "Copyright and license notices are preserved in that source archive.\n"
            "This software comes without warranty; see share/licenses/lame/COPYING\n"
            "for the complete GNU Library General Public License version 2 terms.\n",
            encoding="utf-8",
        )
        manifest = {
            "schema_version": 1,
            "version": version,
            "upstream_version": UPSTREAM_VERSION,
            "source_commit": commit,
            "target": target,
            "toolchain": toolchain,
            "build_inputs": {
                "executable_sha256": digest(files[EXECUTABLE]),
                "library_sha256": digest(files[LIBRARY]),
            },
            "library": LIBRARY,
            "executable": EXECUTABLE,
            "files": {
                path.relative_to(root).as_posix(): digest(path)
                for path in sorted(root.rglob("*"))
                if path.is_file()
            },
        }
        (root / "manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n"
        )
        candidate = work / archive.name
        make_archive(root, candidate, epoch)
        extracted = extract_archive(candidate, work / "relocated", name)
        verify_files(extracted, manifest)
        validate_runtime(extracted)
        # Publishing is separate; do not replace an already-created local asset.
        os.link(candidate, archive)
    return {"archive": str(archive), "sha256": digest(archive)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-dir", type=Path, required=True)
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = package(
            args.build_dir.resolve(strict=True),
            args.source_dir.resolve(strict=True),
            args.version,
            args.output_dir.resolve(),
        )
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        if isinstance(error, subprocess.CalledProcessError) and error.stderr:
            print(error.stderr.rstrip(), file=sys.stderr)
        parser.exit(1, f"release packaging failed: {error}\n")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
