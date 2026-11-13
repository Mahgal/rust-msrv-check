"""Tests for msrv_check.py (stdlib only)."""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
