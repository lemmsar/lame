# SPDX-License-Identifier: LGPL-2.0-or-later
"""Regress source-to-binary selection checks using Autoconf's padded flags."""

import copy
import importlib.util
import unittest
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "assemble", Path(__file__).resolve().parents[2] / "scripts/assemble-release.py"
)
ASSEMBLY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ASSEMBLY)


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.candidate = {
            "name": "gcc14", "compiler": "GCC 14.2.0", "cflags": " -Wall -O3 ",
            "ldflags": "", "validation_passed": True,
            "binary_sha256": "a" * 64, "library_sha256": "b" * 64,
        }
        self.report = {"recommended_candidate": "gcc14", "candidates": [self.candidate]}
        self.manifest = {
            "toolchain": {"compiler": "GCC 14.2.0", "cflags": "-Wall -O3", "ldflags": ""},
            "build_inputs": {"executable_sha256": "a" * 64, "library_sha256": "b" * 64},
        }

    def test_autoconf_padding_does_not_change_the_selection(self):
        ASSEMBLY.verify_selection(self.manifest, self.report)

    def test_different_compiler_flags_binary_or_failed_validation_are_rejected(self):
        for field, value in (
            ("compiler", "Clang 23"), ("cflags", "-O3 -march=native"),
            ("ldflags", "-flto"), ("binary_sha256", "c" * 64),
            ("library_sha256", "d" * 64), ("validation_passed", False),
        ):
            with self.subTest(field=field):
                report = copy.deepcopy(self.report)
                report["candidates"][0][field] = value
                with self.assertRaises(ValueError):
                    ASSEMBLY.verify_selection(self.manifest, report)


if __name__ == "__main__":
    unittest.main()
