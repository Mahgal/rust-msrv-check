"""Tests for msrv_check.py (stdlib only)."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import msrv_check as msrv  # noqa: E402


def write_workspace(tmp: Path, crates: dict[str, str]) -> Path:
    root = tmp / "ws"
    root.mkdir()
    (root / "Cargo.toml").write_text(
        '[workspace]\nmembers = [%s]\n' % ", ".join(f'"{n}"' for n in crates),
        encoding="utf-8")
    for name, toml in crates.items():
        d = root / name
        d.mkdir()
        (d / "Cargo.toml").write_text(toml, encoding="utf-8")
    return root


class TestParse(unittest.TestCase):
    def test_parse_full(self):
        self.assertEqual(msrv.parse_version("1.100.0"), (1, 100, 0))

    def test_parse_short(self):
        self.assertEqual(msrv.parse_version("1.85"), (1, 85, 0))

    def test_parse_invalid(self):
        with self.assertRaises(ValueError):
            msrv.parse_version("stable")


class TestCheck(unittest.TestCase):
    def test_msrv_satisfied(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = write_workspace(Path(tmp), {
                "a": '[package]\nname = "a"\nversion = "0.1.0"\n'
                     'edition = "2021"\nrust-version = "1.85"\n',
            })
            result = msrv.check(root, "1.100.0")
            self.assertTrue(result["ok"])
            self.assertEqual(result["crates"], 2)  # workspace root + member

    def test_msrv_exceeded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = write_workspace(Path(tmp), {
                "a": '[package]\nname = "a"\nversion = "0.1.0"\n'
                     'edition = "2021"\nrust-version = "1.100"\n',
            })
            result = msrv.check(root, "1.85.0")
            self.assertFalse(result["ok"])
            self.assertIn("needs rustc >= 1.100", result["problems"][0])

    def test_missing_rust_version_warns_but_ok(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = write_workspace(Path(tmp), {
                "a": '[package]\nname = "a"\nversion = "0.1.0"\nedition = "2021"\n',
            })
            result = msrv.check(root, "1.85.0")
            self.assertTrue(result["ok"])
            self.assertTrue(any("no rust-version" in w for w in result["warnings"]))


class TestCli(unittest.TestCase):
    def test_cli_exit_codes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = write_workspace(Path(tmp), {
                "a": '[package]\nname = "a"\nversion = "0.1.0"\n'
                     'edition = "2021"\nrust-version = "1.90"\n',
            })
            ok = subprocess.run(
                [sys.executable, "msrv_check.py", str(root), "--rustc", "1.100.0"],
                cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(ok.returncode, 0, ok.stdout)
            bad = subprocess.run(
                [sys.executable, "msrv_check.py", str(root), "--rustc", "1.85.0"],
                cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(bad.returncode, 1)
            self.assertIn("FAIL", bad.stdout)


class TestEdgeCases(unittest.TestCase):
    def test_malformed_rust_version_is_problem(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = write_workspace(Path(tmp), {
                "a": '[package]\nname = "a"\nversion = "0.1.0"\n'
                     'edition = "2021"\nrust-version = "stable"\n',
            })
            result = msrv.check(root, "1.85.0")
            self.assertFalse(result["ok"])
            self.assertIn("invalid rust-version", result["problems"][0])

    def test_workspace_inherited_rust_version_not_resolved(self):
        # rust-version.workspace = true is valid Cargo, but this tool only
        # does exact-version comparison and does not resolve inheritance.
        with tempfile.TemporaryDirectory() as tmp:
            root = write_workspace(Path(tmp), {
                "a": '[package]\nname = "a"\nversion = "0.1.0"\n'
                     'edition = "2021"\nrust-version.workspace = true\n',
            })
            result = msrv.check(root, "1.85.0")
            self.assertFalse(result["ok"])
            self.assertIn("invalid rust-version", result["problems"][0])

    def test_malformed_toml_is_problem(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = write_workspace(Path(tmp), {
                "a": '[package\nname = "a"\n',  # missing closing bracket
            })
            result = msrv.check(root, "1.85.0")
            self.assertFalse(result["ok"])
            self.assertIn("cannot parse Cargo.toml", result["problems"][0])

    def test_missing_file_read_crate_reports_error(self):
        crate = msrv.read_crate(Path("/nonexistent/Cargo.toml"))
        self.assertIn("error", crate)

    def test_empty_dir_reports_zero_crates_and_ok(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = msrv.check(Path(tmp), "1.85.0")
            self.assertEqual(result["crates"], 0)
            self.assertTrue(result["ok"])

    def test_target_dir_is_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = write_workspace(Path(tmp), {
                "a": '[package]\nname = "a"\nversion = "0.1.0"\n'
                     'edition = "2021"\nrust-version = "1.85"\n',
            })
            target = root / "target"
            target.mkdir()
            (target / "Cargo.toml").write_text(
                '[package]\nname = "evil"\nversion = "0.1.0"\n'
                'edition = "2021"\nrust-version = "1.100"\n', encoding="utf-8")
            result = msrv.check(root, "1.85.0")
            self.assertTrue(result["ok"])
            self.assertEqual(result["crates"], 2)  # root + a only

    def test_old_edition_warns_but_ok(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = write_workspace(Path(tmp), {
                "a": '[package]\nname = "a"\nversion = "0.1.0"\n'
                     'edition = "2018"\nrust-version = "1.85"\n',
            })
            result = msrv.check(root, "1.85.0")
            self.assertTrue(result["ok"])
            self.assertTrue(any("edition 2018 is old" in w
                                for w in result["warnings"]))

    def test_json_output_is_valid(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = write_workspace(Path(tmp), {
                "a": '[package]\nname = "a"\nversion = "0.1.0"\n'
                     'edition = "2021"\nrust-version = "1.100"\n',
            })
            proc = subprocess.run(
                [sys.executable, "msrv_check.py", str(root),
                 "--rustc", "1.85.0", "--format", "json"],
                cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(proc.returncode, 1)
            data = json.loads(proc.stdout)
            self.assertEqual(data["rustc"], "1.85.0")
            self.assertFalse(data["ok"])
            self.assertIn("needs rustc >= 1.100", data["problems"][0])

    def test_invalid_rustc_flag_exits_2(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = write_workspace(Path(tmp), {
                "a": '[package]\nname = "a"\nversion = "0.1.0"\n'
                     'edition = "2021"\nrust-version = "1.85"\n',
            })
            proc = subprocess.run(
                [sys.executable, "msrv_check.py", str(root), "--rustc", "stable"],
                cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(proc.returncode, 2)
            self.assertIn("error:", proc.stderr)

    def test_no_rustc_on_path_without_flag_exits_2(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = write_workspace(Path(tmp), {
                "a": '[package]\nname = "a"\nversion = "0.1.0"\n'
                     'edition = "2021"\nrust-version = "1.85"\n',
            })
            with mock.patch.dict(os.environ, {"PATH": tmp}):
                self.assertEqual(msrv.main([str(root)]), 2)


if __name__ == "__main__":
    unittest.main()
