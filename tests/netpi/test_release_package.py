#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.0-or-later
"""Check release archive reproducibility, contents, hashes and path restrictions."""

import importlib.util
import io
import json
import os
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "package_release", SOURCE / "scripts/package-release.py"
)
PACKAGE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PACKAGE)


class ReleasePackageTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="lame-release-test-")
        self.addCleanup(self.temporary.cleanup)
        self.work = Path(self.temporary.name)
        self.name = PACKAGE.release_name("4.0-r1", "x86_64")
        self.root = self.work / self.name
        for relative, content in (
            ("bin/lame", b"executable"),
            ("lib/libmp3lame.so.0", b"library"),
            ("SOURCE.txt", b"corresponding source information"),
        ):
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        self.manifest = {
            "files": {
                path.relative_to(self.root).as_posix(): PACKAGE.digest(path)
                for path in self.root.rglob("*")
                if path.is_file()
            }
        }
        (self.root / "manifest.json").write_text(json.dumps(self.manifest))

    def test_archive_is_deterministic_and_relocatable(self):
        first, second = self.work / "first.tar.gz", self.work / "second.tar.gz"
        PACKAGE.make_archive(self.root, first, 1234567890)
        for path in self.root.rglob("*"):
            path.chmod(0o777)
            os.utime(path, (1700000000, 1700000000))
        PACKAGE.make_archive(self.root, second, 1234567890)
        self.assertEqual(first.read_bytes(), second.read_bytes())
        with tarfile.open(first) as archive:
            for member in archive.getmembers():
                self.assertTrue(member.isfile() or member.isdir())
                self.assertEqual(
                    (member.uid, member.gid, member.mtime), (0, 0, 1234567890)
                )
        extracted = PACKAGE.extract_archive(first, self.work / "elsewhere", self.name)
        PACKAGE.verify_files(extracted, self.manifest)
        self.assertEqual((extracted / "bin/lame").stat().st_mode & 0o777, 0o755)
        self.assertEqual(
            (extracted / "lib/libmp3lame.so.0").stat().st_mode & 0o777, 0o644
        )

    def test_checksums_and_complete_file_list_are_enforced(self):
        PACKAGE.verify_files(self.root, self.manifest)
        library = self.root / "lib/libmp3lame.so.0"
        library.write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "checksum mismatch"):
            PACKAGE.verify_files(self.root, self.manifest)
        library.write_bytes(b"library")
        (self.root / "unexpected").write_text("unlisted")
        with self.assertRaisesRegex(ValueError, "file list"):
            PACKAGE.verify_files(self.root, self.manifest)

    def test_package_names_reject_path_injection(self):
        for version in ("../4.0-r1", "4.0-r1/extra", "4.0-r1\n", "4.0-r0", "4.0-r01"):
            with self.subTest(version=version), self.assertRaises(ValueError):
                PACKAGE.release_name(version, "x86_64")
        for path in (
            "/tmp/file",
            "../file",
            "safe/../file",
            "safe//file",
            "safe/./file",
            "safe\\file",
            "safe\x00file",
        ):
            with self.subTest(path=path), self.assertRaises(ValueError):
                PACKAGE.relative_path(path)

    def test_archive_rejects_links_traversal_duplicates_and_wrong_root(self):
        cases = (
            ("../escape", tarfile.REGTYPE, False),
            (f"{self.name}/../../escape", tarfile.REGTYPE, False),
            (f"{self.name}/link", tarfile.SYMTYPE, False),
            (f"{self.name}/link", tarfile.LNKTYPE, False),
            (f"{self.name}/device", tarfile.CHRTYPE, False),
            ("other-root/file", tarfile.REGTYPE, False),
            (f"{self.name}/duplicate", tarfile.REGTYPE, True),
        )
        for index, (name, kind, duplicate) in enumerate(cases):
            with self.subTest(name=name, kind=kind):
                archive = self.work / f"bad-{index}.tar.gz"
                with tarfile.open(archive, "w:gz") as tar:
                    member = tarfile.TarInfo(name)
                    member.type = kind
                    if kind in (tarfile.SYMTYPE, tarfile.LNKTYPE):
                        member.linkname = "/tmp/outside"
                    tar.addfile(member, io.BytesIO())
                    if duplicate:
                        tar.addfile(member, io.BytesIO())
                destination = self.work / f"extract-{index}"
                with self.assertRaises(ValueError):
                    PACKAGE.extract_archive(archive, destination, self.name)
                self.assertFalse(destination.exists())

    def test_source_identity_rejects_uncommitted_changes(self):
        checkout = self.work / "checkout"
        checkout.mkdir()
        subprocess.run(["git", "init", "-q", str(checkout)], check=True)
        source = checkout / "source.c"
        source.write_text("original\n")
        subprocess.run(["git", "-C", str(checkout), "add", "source.c"], check=True)
        subprocess.run(
            [
                "git",
                "-C",
                str(checkout),
                "-c",
                "user.name=Release test",
                "-c",
                "user.email=release-test@example.invalid",
                "commit",
                "-qm",
                "fixture",
            ],
            check=True,
        )
        with patch.dict(os.environ, {"SOURCE_DATE_EPOCH": "1234567890"}):
            commit, epoch = PACKAGE.source_identity(checkout)
            self.assertRegex(commit, r"^[0-9a-f]{40}$")
            self.assertEqual(epoch, 1234567890)
        source.write_text("uncommitted\n")
        with self.assertRaisesRegex(ValueError, "commit all tracked"):
            PACKAGE.source_identity(checkout)

    def test_compiler_with_arguments_is_recorded(self):
        compiler = self.work / "compiler"
        compiler.write_text(
            "#!/bin/sh\nprintf 'Example compiler 14.2\\nCopyright notice\\n'\n"
        )
        compiler.chmod(0o755)
        build = self.work / "build"
        build.mkdir()
        (build / "Makefile").write_text(
            f"CC = {compiler} -std=gnu23\nCFLAGS = -O3 -ffast-math\n"
            f"LDFLAGS = -flto\nabs_top_srcdir = {self.root}\n"
        )
        actual = PACKAGE.build_configuration(build, self.root)
        self.assertEqual(
            actual,
            {
                "compiler": "Example compiler 14.2\nCopyright notice",
                "cflags": "-O3 -ffast-math",
                "ldflags": "-flto",
            },
        )


if __name__ == "__main__":
    unittest.main()
