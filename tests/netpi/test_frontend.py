#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.0-or-later
# Added by lemmsar/lame, 2026-10-11: CLI Unicode tag and decoding regressions.
"""Build the frontend first, then pass its executable as the sole argument."""

import argparse
import json
import math
import os
import struct
import subprocess
import tempfile
import wave
from pathlib import Path


def run(command):
    environment = dict(os.environ, LC_ALL="C.UTF-8")
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=environment,
        check=False,
    )
    if result.returncode:
        raise AssertionError(
            f"Command failed ({result.returncode}): {command!r}\n"
            f"{result.stdout}{result.stderr}"
        )
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("lame", type=Path, help="built frontend/lame executable")
    args = parser.parse_args()
    lame = str(args.lame.resolve(strict=True))
    expected = {
        "title": "음악 제목 café",
        "artist": "연주자 테스트",
        "album": "앨범 한글",
        "comment": "댓글 확인 한글",
        "composer": "작곡가 한글",
        "검증": "사용자 정의 한글",
    }
    with tempfile.TemporaryDirectory(prefix="lame-frontend-") as directory:
        work = Path(directory)
        source = work / "input.wav"
        with wave.open(str(source), "wb") as wav:
            wav.setnchannels(2)
            wav.setsampwidth(2)
            wav.setframerate(44100)
            samples = bytearray()
            for index in range(11025):
                sample = round(12000 * math.sin(2 * math.pi * 440 * index / 44100))
                samples.extend(struct.pack("<hh", sample, sample))
            wav.writeframes(samples)

        for encoding in ("utf8", "utf16"):
            output = work / f"{encoding}.mp3"
            run(
                [
                    lame,
                    "--silent",
                    "--id3v2-only",
                    f"--id3v2-{encoding}",
                    "--tt",
                    expected["title"],
                    "--ta",
                    expected["artist"],
                    "--tl",
                    expected["album"],
                    "--tc",
                    expected["comment"],
                    "--tv",
                    f"TCOM={expected['composer']}",
                    "--tv",
                    f"TXXX=검증={expected['검증']}",
                    str(source),
                    str(output),
                ]
            )
            probe = run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-show_entries",
                    "format_tags",
                    "-of",
                    "json",
                    str(output),
                ]
            )
            tags = json.loads(probe.stdout)["format"]["tags"]
            for key, value in expected.items():
                if tags.get(key) != value:
                    raise AssertionError(
                        f"{encoding} tag {key!r}: expected {value!r}, "
                        f"got {tags.get(key)!r}"
                    )
            run(
                [
                    "ffmpeg",
                    "-v",
                    "error",
                    "-xerror",
                    "-i",
                    str(output),
                    "-f",
                    "null",
                    "-",
                ]
            )
            print(
                f"{encoding}: Unicode title, artist, album, comment, custom fields and decode passed"
            )


if __name__ == "__main__":
    main()
