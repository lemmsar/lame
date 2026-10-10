"""Exercise actual builds, replacement identity, LTO, and profile training."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


SOURCE = Path(__file__).resolve().parents[2]


def main():
    with tempfile.TemporaryDirectory(prefix="lame-installer-test-") as temporary:
        root = Path(temporary)
        prefix = root / "install"
        active = prefix / "lib/libmp3lame.so.0"

        def build(*flags, environment=None):
            subprocess.run(
                [
                    sys.executable,
                    str(SOURCE / "scripts/build-netpi.py"),
                    "--prefix",
                    str(prefix),
                    "--jobs",
                    "2",
                    *flags,
                ],
                check=True,
                env=environment,
            )
            target = active.resolve(strict=True)
            manifest = json.loads((target.parent / "manifest.json").read_text())
            assert (target.parent / "config.log").is_file()
            return target, manifest

        original, before = build()
        stamp = active.lstat().st_mtime_ns
        same, after = build()
        assert original == same and before == after
        assert stamp == active.lstat().st_mtime_ns, (
            "unchanged build must not be reinstalled"
        )
        build("--check")
        build("--force")
        assert original.is_file(), "existing jobs must keep their immutable library"
        current = active.resolve(strict=True)
        (current.parent / "manifest.json").write_text("{broken")
        repaired, repaired_manifest = build()
        assert (
            repaired_manifest["build_id"] == before["build_id"] and repaired.is_file()
        )
        active.unlink()
        active.symlink_to(prefix / "missing-build")
        recovered, _ = build()
        assert recovered.is_file()
        changed, manifest = build(
            environment={**os.environ, "CPPFLAGS": "-DNETPI_BUILD_TEST=1"}
        )
        assert manifest["build_id"] != before["build_id"] and changed != original
        lto, manifest = build("--lto", "--fp-model", "strict")
        assert "-flto" in manifest["cflags"]
        assert manifest["fp_model"] == "strict" and lto != original
        corpus = root / "corpus"
        corpus.mkdir()
        subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-f",
                "lavfi",
                "-i",
                "anoisesrc=sample_rate=44100:duration=0.5:seed=17",
                str(corpus / "noise.wav"),
            ],
            check=True,
        )
        pgo, manifest = build("--pgo-corpus", str(corpus))
        assert manifest["pgo"] and len(manifest["training"]) == 1 and pgo != original
        again, _ = build("--pgo-corpus", str(corpus))
        assert again == pgo
        assert original.is_file() and changed.is_file() and lto.is_file()
        print(
            "Installer: identity, reuse, force, flags, LTO, PGO and old builds verified"
        )


if __name__ == "__main__":
    main()
