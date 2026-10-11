#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.0-or-later
"""Validate prebuilt generic-ISA encoders and compare their native CLI speed."""

import argparse
import array
import hashlib
import json
import math
import os
import platform
import re
import resource
import shlex
import statistics
import struct
import subprocess
import sys
import tempfile
import time
import wave
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1]
MODES = {"v0": ["-V", "0"], "cbr320": ["--cbr", "-b", "320"]}
RATE = 44100


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def capture(command, **kwargs):
    return subprocess.check_output(command, text=True, **kwargs).strip()


def source_identity():
    try:
        paths = capture(
            [
                "git",
                "-C",
                str(SOURCE),
                "ls-files",
                "-z",
                "--cached",
                "--others",
                "--exclude-standard",
            ],
            stderr=subprocess.DEVNULL,
        ).split("\0")
        commit = capture(["git", "-C", str(SOURCE), "rev-parse", "HEAD"])
        dirty = bool(capture(["git", "-C", str(SOURCE), "status", "--porcelain"]))
    except (OSError, subprocess.CalledProcessError):
        paths = [
            str(path.relative_to(SOURCE))
            for path in SOURCE.rglob("*")
            if path.is_file()
            and not any(
                part.startswith((".", "build")) or part == "__pycache__"
                for part in path.relative_to(SOURCE).parts
            )
        ]
        commit, dirty = None, None
    checksum = hashlib.sha256()
    for name in sorted(set(paths)):
        path = SOURCE / name
        if name and path.is_file():
            checksum.update(name.encode() + b"\0" + bytes.fromhex(digest(path)))
    return {"commit": commit, "sha256": checksum.hexdigest(), "dirty": dirty}


def native_host():
    machine = platform.machine().lower()
    architecture = {
        "aarch64": "arm64",
        "arm64": "arm64",
        "x86_64": "x86_64",
        "amd64": "x86_64",
    }.get(machine)
    if platform.system() != "Linux" or architecture is None:
        raise ValueError("native Linux x86_64 or arm64 is required")
    cpu_text = Path("/proc/cpuinfo").read_text()
    if os.environ.get("NETPI_TEST_RUNNER") or any(
        value for key, value in os.environ.items() if key.startswith("QEMU_")
    ):
        raise ValueError("QEMU/NETPI_TEST_RUNNER timing is not a native benchmark")
    if (architecture == "arm64" and "vendor_id" in cpu_text) or "QEMU" in cpu_text:
        raise ValueError(
            "CPU information indicates emulation; native timing is required"
        )
    cpu = {}
    for line in cpu_text.splitlines():
        key, separator, value = line.partition(":")
        if separator and key.strip() in (
            "model name",
            "vendor_id",
            "CPU implementer",
            "CPU architecture",
            "CPU variant",
            "CPU part",
            "CPU revision",
            "Hardware",
            "Features",
            "flags",
        ):
            cpu.setdefault(key.strip(), set()).add(value.strip())
    return {
        "architecture": architecture,
        "cpu": {key: sorted(values) for key, values in cpu.items()},
        "kernel": platform.release(),
        "os": platform.freedesktop_os_release(),
        "affinity": sorted(os.sched_getaffinity(0)),
        "python": platform.python_version(),
        "execution": "native (known emulator controls rejected; run only on native hardware)",
    }


def make_variables(path):
    variables = {}
    for line in path.read_text().splitlines():
        match = re.match(r"^([A-Za-z_][A-Za-z_0-9]*) = (.*)$", line)
        if match:
            variables[match[1]] = match[2]
    return variables


def load_candidate(specification, architecture):
    name, separator, location = specification.partition("=")
    if not separator or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", name):
        raise ValueError("--candidate must be NAME=BUILD_DIR with a simple unique name")
    build = Path(location).resolve(strict=True)
    variables = make_variables(build / "Makefile")
    if Path(variables["abs_top_srcdir"]).resolve() != SOURCE:
        raise ValueError(f"{name}: candidate must be configured from {SOURCE}")
    flags = {
        key: variables.get(key, "")
        for key in ("CC", "CFLAGS", "CPPFLAGS", "LDFLAGS", "LIBS")
    }
    baseline = "armv8-a" if architecture == "arm64" else "x86-64"
    if "-march=" + baseline not in shlex.split(flags["CFLAGS"]):
        raise ValueError(
            f"{name}: explicit -march={baseline} is required for reproducible generic ISA"
        )
    for variable, value in flags.items():
        for option in shlex.split(value):
            key, _, argument = option.partition("=")
            if (key == "-march" and argument != baseline) or (
                key in ("-mcpu", "-mtune") and argument != "generic"
            ):
                raise ValueError(
                    f"{name}: non-generic CPU option in {variable}: {option}"
                )
    executable = build / "frontend/lame"
    if executable.read_bytes()[:4] != b"\x7fELF":
        executable = build / "frontend/.libs/lame"
    header = executable.read_bytes()[:20]
    expected_machine = 183 if architecture == "arm64" else 62
    if (
        header[:6] != b"\x7fELF\x02\x01"
        or int.from_bytes(header[18:20], "little") != expected_machine
    ):
        raise ValueError(
            f"{name}: encoder ELF architecture does not match the native host"
        )
    library = (build / "libmp3lame/.libs/libmp3lame.so.0").resolve(strict=True)
    return {
        "name": name,
        "build_dir": str(build),
        "executable": str(executable),
        "library": str(library),
        "binary_sha256": digest(executable),
        "library_sha256": digest(library),
        "compiler": capture([*shlex.split(flags["CC"]), "--version"]),
        "compiler_target": capture([*shlex.split(flags["CC"]), "-dumpmachine"]),
        "cc": flags["CC"],
        "cflags": flags["CFLAGS"],
        "ldflags": flags["LDFLAGS"],
        "build_flags": flags,
        "config_log_sha256": digest(build / "config.log"),
        "validation_passed": False,
        "measurements": [],
    }


def environment(candidate):
    result = {
        key: value
        for key, value in os.environ.items()
        if key
        not in (
            "LD_PRELOAD",
            "LD_LIBRARY_PATH",
            "LD_TRACE_LOADED_OBJECTS",
            "MAKEFLAGS",
            "MFLAGS",
        )
    }
    result.update(candidate["build_flags"])
    result.update(LC_ALL="C.UTF-8", OMP_NUM_THREADS="1")
    result["LD_LIBRARY_PATH"] = str(Path(candidate["library"]).parent)
    return result


def validate(candidate, directory):
    log = directory / f"{candidate['name']}-validation.log"
    candidate["validation_log"] = str(log)
    with log.open("w") as output:
        for command in (
            ["make", "-C", candidate["build_dir"], "check-netpi"],
            [
                sys.executable,
                str(SOURCE / "tests/netpi/test_frontend.py"),
                candidate["executable"],
            ],
        ):
            output.write(shlex.join(command) + "\n")
            output.flush()
            subprocess.run(
                command,
                env=environment(candidate),
                stdout=output,
                stderr=subprocess.STDOUT,
                check=True,
                timeout=900,
            )
    candidate["validation_log_sha256"] = digest(log)
    candidate["validation_passed"] = True
    # A stale build may have been rebuilt by make check-netpi.
    candidate["binary_sha256"] = digest(Path(candidate["executable"]))
    candidate["library_sha256"] = digest(Path(candidate["library"]))


def sine(phase):
    """Integer-only periodic approximation: corpus bytes are platform independent."""
    position = (phase >> 16) & 0x7FFF
    product = position * (32768 - position)
    value = 16 * product * 32767 // (5 * 32768**2 - 4 * product)
    return -value if phase & 0x80000000 else value


def generate_corpus(directory, seconds):
    frames = round(seconds * RATE)
    corpus = []
    for kind in ("tonal", "transients", "noise"):
        data = bytearray()
        phases = [0, 0x40000000, 0x20000000]
        random_state = 0xA341316C
        decay = 0
        previous_noise = 0
        for index in range(frames):
            note = (index // (RATE // 2)) % 4
            frequencies = (
                (220, 277, 330),
                (196, 247, 294),
                (174, 220, 262),
                (196, 262, 330),
            )[note]
            for voice, frequency in enumerate(frequencies):
                phases[voice] = (phases[voice] + (frequency << 32) // RATE) & 0xFFFFFFFF
            chord = sum(sine(phase) for phase in phases) // 6
            right_chord = sum(sine(phase + 0x08000000) for phase in phases) // 6
            random_state = (1664525 * random_state + 1013904223) & 0xFFFFFFFF
            noise = (random_state >> 16) - 32768
            if index % (RATE // 4) == 0:
                decay = 32767
            decay = decay * 32740 // 32768
            if kind == "tonal":
                left, right = chord, right_chord
            elif kind == "transients":
                left = chord // 2 + noise * decay // 65536
                right = right_chord // 2 + previous_noise * decay // 65536
            else:
                left = chord // 2 + (noise + previous_noise) // 4
                right = right_chord // 2 + (noise - previous_noise) // 4
            # Short fades avoid a discontinuity at the container boundary.
            fade = min(index, frames - 1 - index, RATE // 100)
            left, right = left * fade // (RATE // 100), right * fade // (RATE // 100)
            data.extend(struct.pack("<hh", left, right))
            previous_noise = noise
        path = directory / f"{kind}.wav"
        with wave.open(str(path), "wb") as stream:
            stream.setparams((2, 2, RATE, frames, "NONE", "not compressed"))
            stream.writeframes(data)
        corpus.append(
            {
                "name": kind,
                "path": str(path),
                "sha256": digest(path),
                "frames": frames,
                "channels": 2,
                "sample_rate": RATE,
                "seconds": frames / RATE,
            }
        )
    return corpus


def timed_encode(candidate, track, mode, output):
    command = [
        candidate["executable"],
        "--silent",
        "--noreplaygain",
        *MODES[mode],
        track["path"],
        str(output),
    ]
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    start = time.perf_counter()
    subprocess.run(
        command,
        env=environment(candidate),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        check=True,
        timeout=max(120, track["seconds"] * 30),
    )
    wall = time.perf_counter() - start
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    user, system = after.ru_utime - before.ru_utime, after.ru_stime - before.ru_stime
    return {
        "wall_seconds": wall,
        "user_seconds": user,
        "system_seconds": system,
        "cpu_seconds": user + system,
    }


def decode_metrics(track, output):
    raw = subprocess.check_output(
        [
            "ffmpeg",
            "-v",
            "error",
            "-xerror",
            "-i",
            str(output),
            "-f",
            "f32le",
            "-acodec",
            "pcm_f32le",
            "-",
        ]
    )
    decoded = array.array("f")
    decoded.frombytes(raw)
    with wave.open(track["path"], "rb") as stream:
        original = array.array("h")
        original.frombytes(stream.readframes(stream.getnframes()))
    if sys.byteorder != "little":
        decoded.byteswap()
        original.byteswap()
    if len(decoded) != len(original) or not all(
        math.isfinite(value) for value in decoded
    ):
        raise RuntimeError(f"invalid decoded PCM length or sample: {output}")
    energy = sum((value / 32768) ** 2 for value in original)
    error = sum((a - b / 32768) ** 2 for a, b in zip(decoded, original, strict=True))
    if error >= energy:
        raise RuntimeError(
            f"decoded waveform failed the gross-corruption check: {output}"
        )
    return {
        "decoded_samples": len(decoded),
        "finite": True,
        "rms_error": math.sqrt(error / len(decoded)),
        "snr_db": 10 * math.log10(energy / error) if error else None,
        "peak": max(map(abs, decoded)),
    }


def measure(candidates, corpus, args, directory):
    records = {}
    for track in corpus:
        for mode in MODES:
            for candidate in candidates:
                record = {"corpus": track["name"], "mode": mode, "samples": []}
                candidate["measurements"].append(record)
                records[candidate["name"], track["name"], mode] = record
            for repetition in range(-args.warmups, args.repeats):
                # Rotate the first candidate to spread drift across compilers.
                offset = (repetition + args.warmups) % len(candidates)
                for candidate in candidates[offset:] + candidates[:offset]:
                    output = (
                        directory / f"{candidate['name']}-{track['name']}-{mode}.mp3"
                    )
                    timing = timed_encode(candidate, track, mode, output)
                    record = records[candidate["name"], track["name"], mode]
                    encoded_hash = digest(output)
                    if "output_sha256" not in record:
                        record.update(
                            output_sha256=encoded_hash,
                            output_bytes=output.stat().st_size,
                            decode=decode_metrics(track, output),
                        )
                    elif record["output_sha256"] != encoded_hash:
                        raise RuntimeError(
                            f"non-deterministic encoded output: {candidate['name']}"
                        )
                    if repetition >= 0:
                        record["samples"].append(timing)
            print(f"Measured {track['name']} / {mode}", flush=True)
    for candidate in candidates:
        for record in candidate["measurements"]:
            for metric in ("wall_seconds", "cpu_seconds"):
                values = [sample[metric] for sample in record["samples"]]
                record["median_" + metric] = statistics.median(values)
                record["range_" + metric] = [min(values), max(values)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--candidate",
        action="append",
        required=True,
        help="NAME=BUILD_DIR; first candidate is baseline",
    )
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--seconds", type=float, default=20)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--min-speedup-percent", type=float, default=3)
    parser.add_argument(
        "--cpu",
        type=int,
        help="pin timing to this allowed CPU (default: first allowed CPU)",
    )
    args = parser.parse_args()
    if (
        not math.isfinite(args.seconds)
        or args.seconds < 1
        or args.warmups < 1
        or args.repeats < 3
        or not 0 <= args.min_speedup_percent < 100
    ):
        parser.error(
            "seconds >= 1, warmups >= 1, repeats >= 3 and speedup in [0,100) are required"
        )
    args.output = args.output.resolve()
    if args.output.is_relative_to(SOURCE):
        parser.error("write benchmark output outside the source directory")
    try:
        host = native_host()
        candidates = [
            load_candidate(value, host["architecture"]) for value in args.candidate
        ]
        if len(candidates) < 2 or len(
            {candidate["name"] for candidate in candidates}
        ) != len(candidates):
            raise ValueError("at least two uniquely named candidates are required")
        cpu = args.cpu if args.cpu is not None else min(host["affinity"])
        if cpu not in host["affinity"]:
            raise ValueError("--cpu must belong to the process's allowed CPU affinity")
    except (ValueError, OSError, KeyError) as error:
        parser.error(str(error))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    logs = args.output.parent / (args.output.stem + "-logs")
    logs.mkdir(exist_ok=True)
    report = {
        "schema_version": 1,
        "source": source_identity(),
        "host": host,
        "settings": {
            "seconds": args.seconds,
            "warmups": args.warmups,
            "repeats": args.repeats,
            "modes": MODES,
            "cpu": cpu,
            "min_speedup_percent": args.min_speedup_percent,
        },
        "ffmpeg": capture(["ffmpeg", "-version"]),
        "candidates": candidates,
        "quality_scope": "Regression and decode checks; SNR is diagnostic, not a listening-quality score.",
        "timing_scope": "Native CLI startup and encoding; input generation, validation and decoding are excluded.",
        "recommended_candidate": None,
    }
    try:
        for candidate in candidates:
            print("Validating " + candidate["name"], flush=True)
            validate(candidate, logs)
        # Pin only after regression tests; all encoder subprocesses inherit it.
        os.sched_setaffinity(0, {cpu})
        with tempfile.TemporaryDirectory(prefix="lame-compiler-corpus-") as temporary:
            directory = Path(temporary)
            corpus = generate_corpus(directory, args.seconds)
            report["corpus"] = [
                {key: value for key, value in track.items() if key != "path"}
                for track in corpus
            ]
            measure(candidates, corpus, args, directory)
        baseline = candidates[0]
        for candidate in candidates:
            ratios = [
                sample["median_cpu_seconds"] / reference["median_cpu_seconds"]
                for sample, reference in zip(
                    candidate["measurements"], baseline["measurements"], strict=True
                )
            ]
            candidate["score"] = math.exp(statistics.mean(map(math.log, ratios)))
        ranking = sorted(candidates, key=lambda candidate: candidate["score"])
        report["ranking"] = [candidate["name"] for candidate in ranking]
        winner = (
            ranking[0]
            if ranking[0]["score"] < 1 - args.min_speedup_percent / 100
            else baseline
        )
        report["recommended_candidate"] = winner["name"]
        report["recommendation_scope"] = (
            "This CPU and corpus only; retain baseline below the configured speedup threshold. No Raspberry Pi claim follows from a different ARM CPU."
        )
        if source_identity() != report["source"]:
            raise RuntimeError("source changed during validation or measurement")
        for candidate in candidates:
            if (
                digest(Path(candidate["executable"])) != candidate["binary_sha256"]
                or digest(Path(candidate["library"])) != candidate["library_sha256"]
            ):
                raise RuntimeError("candidate binary changed during measurement")
        report["status"] = "passed"
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        report["status"] = "failed"
        report["recommended_candidate"] = None
        report["error"] = str(error)
        raise
    finally:
        os.sched_setaffinity(0, set(host["affinity"]))
        args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
        print("Benchmark report: " + str(args.output), flush=True)


if __name__ == "__main__":
    main()
