#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.0-or-later
"""Check both binary identities and attach the exact corresponding Git source."""

import gzip
import hashlib
import importlib.util
import json
import re
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path


def main():
    source = Path(__file__).resolve().parents[1]
    output = Path(sys.argv[1]).resolve()
    version = (source / "RELEASE_VERSION").read_text().strip()
    if not re.fullmatch(r"4\.0-r[1-9][0-9]*", version):
        raise ValueError("Invalid release version")
    commit = subprocess.check_output(
        ["git", "-C", str(source), "rev-parse", "HEAD"], text=True
    ).strip()
    if subprocess.check_output(["git", "-C", str(source), "diff", "HEAD", "--"]):
        raise ValueError("Corresponding source must be committed")
    assets = []
    spec = importlib.util.spec_from_file_location("release_package", source / "scripts/package-release.py")
    packager = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(packager)
    for architecture in ("arm64", "x86_64"):
        name = f"lame-{version}-linux-{architecture}-debian13.tar.gz"
        archive = output / name
        with tarfile.open(archive, "r:gz") as package:
            manifest_file = package.extractfile(f"{name.removesuffix('.tar.gz')}/manifest.json")
            if manifest_file is None:
                raise ValueError(f"Missing manifest in {name}")
            manifest = json.load(manifest_file)
        target = {
            "os": "linux", "architecture": architecture,
            "distribution": "debian", "distribution_version": "13",
        }
        if (manifest["source_commit"] != commit or manifest["version"] != version
                or manifest["target"] != target or manifest["upstream_version"] != "4.0"):
            raise ValueError(f"Binary/source identity mismatch: {name}")
        report = json.loads((output / f"benchmark-{architecture}.json").read_text())
        if (report["source"]["commit"] != commit or report["source"]["dirty"]
                or report.get("status") != "passed" or not report.get("recommended_candidate")):
            raise ValueError(f"Benchmark/source identity mismatch: {name}")
        selected = next(candidate for candidate in report["candidates"]
                        if candidate["name"] == report["recommended_candidate"])
        if (not selected["validation_passed"]
                or manifest["toolchain"] != {key: selected[key] for key in ("compiler", "cflags", "ldflags")}
                or manifest["build_inputs"] != {
                    "executable_sha256": selected["binary_sha256"],
                    "library_sha256": selected["library_sha256"],
                }):
            raise ValueError(f"Packaged encoder differs from the benchmark selection: {name}")
        with tempfile.TemporaryDirectory(prefix="lame-release-final-") as temporary:
            root = packager.extract_archive(archive, Path(temporary), name.removesuffix(".tar.gz"))
            packager.verify_files(root, manifest)
        assets.append({"name": name, "target": target,
                       "sha256": hashlib.sha256(archive.read_bytes()).hexdigest()})
    source_name = f"lame-{version}-source.tar.gz"
    archive_data = subprocess.check_output(
        ["git", "-C", str(source), "archive", "--format=tar", f"--prefix=lame-{version}/", commit]
    )
    with (output / source_name).open("wb") as stream, gzip.GzipFile(
        fileobj=stream, mode="wb", filename="", mtime=0
    ) as compressed:
        compressed.write(archive_data)
    index = {
        "schema_version": 1, "repository": "lemmsar/lame", "tag": f"v{version}",
        "version": version, "upstream_version": "4.0", "source_commit": commit,
        "assets": assets,
        "source": {"name": source_name,
                   "sha256": hashlib.sha256((output / source_name).read_bytes()).hexdigest()},
    }
    (output / "release.json").write_text(json.dumps(index, indent=2) + "\n")
    files = sorted(path for path in output.iterdir() if path.is_file() and path.name != "SHA256SUMS")
    (output / "SHA256SUMS").write_text("".join(
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n" for path in files
    ))


if __name__ == "__main__":
    main()
