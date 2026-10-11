# SPDX-License-Identifier: LGPL-2.0-or-later
"""Check profile flag validation without requiring an ARM compiler or a build."""

import importlib.util
import os
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[2]
BUILDER = SOURCE / "scripts/build-netpi.py"
SPEC = importlib.util.spec_from_file_location("build_netpi", BUILDER)
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)


class BuildProfileTests(unittest.TestCase):
    def test_cortex_rejects_cpu_selection_in_all_compiler_flag_variables(self):
        for variable in ("CFLAGS", "CPPFLAGS", "LDFLAGS", "LIBS"):
            for option in (
                "-march=armv9-a",
                "-mtune=cortex-a72",
                "-mcpu=native",
                "-mcpu=cortex-a53",
            ):
                with (
                    self.subTest(variable=variable, option=option),
                    self.assertRaisesRegex(ValueError, variable),
                ):
                    builder.build_flags(
                        "cortex-a53", "fast", True, {variable: "-g " + option}
                    )

    def test_cortex_rejects_quoted_and_separated_cpu_options(self):
        for flags in (
            "'-march=armv9-a'",
            '-g\t"-mtune=cortex-a72"\n-Wall',
            "-mcpu cortex-a72",
            "-march armv9-a",
            "-mtune native",
        ):
            with (
                self.subTest(flags=flags),
                self.assertRaisesRegex(ValueError, "CPU selection"),
            ):
                builder.build_flags("cortex-a53", "fast", False, {"CFLAGS": flags})

    def test_cortex_rejects_malformed_flag_quoting(self):
        with self.assertRaisesRegex(ValueError, "invalid CFLAGS"):
            builder.build_flags(
                "cortex-a53", "fast", False, {"CFLAGS": "-DNAME='unfinished"}
            )

    def test_cortex_preserves_other_flags_and_sets_cpu(self):
        environment = {
            "CFLAGS": "-g -DNAME='-march=example' -I/tmp/include",
            "CPPFLAGS": "-DCPU_LABEL=-mcpu=cortex-a72",
            "LDFLAGS": "-Wl,--as-needed -L/tmp/lib",
            "LIBS": "-lm",
        }
        original = environment.copy()
        flags, ldflags = builder.build_flags("cortex-a53", "strict", True, environment)
        self.assertIn(environment["CFLAGS"], flags)
        self.assertEqual(
            shlex.split(flags)[-3:], ["-fno-fast-math", "-mcpu=cortex-a53", "-flto"]
        )
        self.assertEqual(ldflags, environment["LDFLAGS"] + " -flto")
        self.assertEqual(environment, original)

    def test_generic_preserves_native_flags_verbatim(self):
        environment = {
            "CFLAGS": "-O2 -march=native -mtune=native -mcpu=native -DNAME='a b'",
            "CPPFLAGS": "-march=native",
            "LDFLAGS": "-mcpu=native",
            "LIBS": "-mtune=native",
        }
        original = environment.copy()
        for fp_model, last_flag in (
            ("fast", "-ffast-math"),
            ("strict", "-fno-fast-math"),
        ):
            with self.subTest(fp_model=fp_model):
                flags, ldflags = builder.build_flags(
                    "generic", fp_model, False, environment
                )
                self.assertEqual(
                    flags,
                    "-O3 -fomit-frame-pointer "
                    + environment["CFLAGS"]
                    + " "
                    + last_flag,
                )
                self.assertEqual(ldflags, environment["LDFLAGS"])
        self.assertEqual(environment, original)

    def test_cli_reports_conflict_before_running_any_build_tools(self):
        with tempfile.TemporaryDirectory(prefix="lame-profile-test-") as temporary:
            prefix = Path(temporary) / "install"
            for variable in ("CFLAGS", "CPPFLAGS", "LDFLAGS", "LIBS"):
                with self.subTest(variable=variable):
                    environment = {
                        key: value
                        for key, value in os.environ.items()
                        if key not in ("CFLAGS", "CPPFLAGS", "LDFLAGS", "LIBS")
                    }
                    # Empty PATH makes any accidental build-tool lookup fail.
                    environment.update(PATH="", **{variable: "-march=armv9-a"})
                    result = subprocess.run(
                        [
                            sys.executable,
                            str(BUILDER),
                            "--prefix",
                            str(prefix),
                            "--profile",
                            "cortex-a53",
                            "--lto",
                        ],
                        env=environment,
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    self.assertEqual(result.returncode, 2, result.stderr)
                    self.assertIn(variable, result.stderr)
                    self.assertIn("-march=armv9-a", result.stderr)
                    self.assertIn("--profile generic", result.stderr)
                    self.assertNotIn("Traceback", result.stderr)
                    self.assertNotIn("missing required tool", result.stderr)
                    self.assertFalse(prefix.exists())


if __name__ == "__main__":
    unittest.main()
