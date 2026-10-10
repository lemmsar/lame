#!/usr/bin/env python3
"""Export the committed fork delta for NetPi's authenticated-free device builds."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

SOURCE = Path(__file__).resolve().parents[1]
BASE = "upstream/lame-4.0"


def git(*arguments):
    return subprocess.check_output(["git", "-C", str(SOURCE), *arguments])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    if git("status", "--porcelain").strip():
        parser.error("commit all source changes before exporting")
    patch = git("diff", "--binary", BASE, "HEAD")
    if not patch:
        parser.error("the selected commit has no changes from upstream")
    args.destination.mkdir(parents=True, exist_ok=True)
    (args.destination / "netpi.patch").write_bytes(patch)
    manifest = {
        "repository": "https://github.com/lemmsar/lame",
        "upstream_commit": git("rev-parse", BASE).decode().strip(),
        "fork_commit": git("rev-parse", "HEAD").decode().strip(),
        "upstream_url": "https://deb.debian.org/debian/pool/main/l/lame/lame_4.0.orig.tar.gz",
        "upstream_sha256": "3df5124d5ad3a98312ffd7ba6a9b36230e4f8a3e66d3ce0f425e336c32d216eb",
        "patch_sha256": hashlib.sha256(patch).hexdigest(),
    }
    (args.destination / "source.json").write_text(json.dumps(manifest, indent=2) + "\n")
    for name in ("COPYING", "LICENSE", "README.netpi"):
        shutil.copyfile(SOURCE / name, args.destination / name)
    print("Exported " + manifest["fork_commit"] + " to " + str(args.destination))


if __name__ == "__main__":
    main()
