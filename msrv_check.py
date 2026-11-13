#!/usr/bin/env python3
"""rust-msrv-check — does your Rust workspace's MSRV match the toolchain?

With Rust 1.100 out, workspaces keep drifting: one crate bumps its
``rust-version`` (MSRV) and suddenly CI on the pinned toolchain fails.
This tool walks a workspace, reads every ``Cargo.toml`` (stdlib tomllib),
and compares each crate's ``rust-version`` against the installed ``rustc``
(or a version you pass with ``--rustc``).

Usage:
    python msrv_check.py [path]            # uses installed rustc
    python msrv_check.py . --rustc 1.85.0  # compare against a pinned version
    python msrv_check.py . --format json

Exit code: 0 = every crate's MSRV is satisfied (warnings may still print),
           1 = at least one crate needs a newer rustc than installed.
Requires Python 3.11+ (tomllib) and a Rust workspace; rustc itself is
only needed when --rustc is not given.
"""

import argparse
import json
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

VERSION_RE = re.compile(r"^(\d+)\.(\d+)(?:\.(\d+))?$")


def parse_version(text: str) -> tuple[int, int, int]:
    match = VERSION_RE.match(text.strip())
    if not match:
        raise ValueError(f"not a Rust version: {text!r}")
    parts = [int(p) if p is not None else 0 for p in match.groups()]
    return tuple(parts)  # type: ignore[return-value]


def installed_rustc() -> str:
    if shutil.which("rustc") is None:
        raise RuntimeError("rustc not found on PATH; pass --rustc X.Y.Z instead")
    proc = subprocess.run(["rustc", "--version"],
                          capture_output=True, text=True, timeout=30)
    if proc.returncode != 0:
        raise RuntimeError(f"rustc --version failed: {proc.stderr.strip()}")
    # "rustc 1.100.0 (xxxx 2026-11-05)" -> "1.100.0"
    return proc.stdout.strip().split()[1]


def find_manifests(root: Path) -> list[Path]:
    manifests = []
    for path in sorted(root.rglob("Cargo.toml")):
        if ".git" in path.parts or "target" in path.parts:
            continue
        manifests.append(path)
    return manifests


def read_crate(manifest: Path) -> dict:
    try:
        data = tomllib.loads(manifest.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, OSError) as exc:
        return {"path": str(manifest), "error": str(exc)}
    package = data.get("package", {})
    workspace = data.get("workspace", {})
    return {
        "path": str(manifest),
        "name": package.get("name") or workspace.get("package", {}).get("name", "?"),
        "rust_version": package.get("rust-version")
                        or workspace.get("package", {}).get("rust-version"),
        "edition": package.get("edition"),
    }


def check(root: Path, rustc_version: str) -> dict:
    installed = parse_version(rustc_version)
    crates, problems, warnings = [], [], []
    for manifest in find_manifests(root):
        crate = read_crate(manifest)
        crates.append(crate)
        if "error" in crate:
            problems.append(f"{crate['path']}: cannot parse Cargo.toml ({crate['error']})")
            continue
        msrv = crate["rust_version"]
        if msrv is None:
            warnings.append(f"{crate['name']}: no rust-version set; MSRV is implicit")
            continue
        try:
            required = parse_version(str(msrv))
        except ValueError:
            problems.append(f"{crate['name']}: invalid rust-version {msrv!r}")
            continue
        if required > installed:
            problems.append(
                f"{crate['name']}: needs rustc >= {msrv} but installed is "
                f"{rustc_version}")
        elif crate.get("edition") in ("2015", "2018"):
            warnings.append(
                f"{crate['name']}: edition {crate['edition']} is old; "
                f"consider edition 2021/2024")
    return {
        "rustc": rustc_version,
        "crates": len(crates),
        "ok": not problems,
        "problems": problems,
        "warnings": warnings,
    }


def render_text(result: dict) -> str:
    lines = [f"rustc {result['rustc']} — {result['crates']} crate(s) checked"]
    if not result["problems"] and not result["warnings"]:
        lines.append("OK — every crate's MSRV is satisfied.")
    for problem in result["problems"]:
        lines.append(f"  [FAIL] {problem}")
    for warning in result["warnings"]:
        lines.append(f"  [WARN] {warning}")
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("path", nargs="?", type=Path, default=Path("."))
    parser.add_argument("--rustc", help="version to compare against, e.g. 1.85.0")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args(argv)

    try:
        rustc_version = args.rustc or installed_rustc()
        parse_version(rustc_version)
    except (ValueError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    result = check(args.path, rustc_version)
    if args.format == "json":
        print(json.dumps(result, indent=2))
    else:
        print(render_text(result))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
