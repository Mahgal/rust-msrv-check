# rust-msrv-check

Does your Rust workspace's MSRV match the toolchain you actually have?

## The problem

Rust 1.100 is out, and workspaces drift: one crate bumps its
`rust-version` (MSRV) and CI on the pinned toolchain starts failing with a
cryptic error. This tool walks a workspace, reads every `Cargo.toml`, and
compares each crate's `rust-version` against the installed `rustc` — or a
version you name — before CI finds out for you.

## Quick start

```bash
python msrv_check.py .                    # uses installed rustc
python msrv_check.py . --rustc 1.85.0     # compare against a pinned version
python msrv_check.py . --format json      # machine-readable output
```

## Example output

```
$ python msrv_check.py . --rustc 1.85.0
rustc 1.85.0 — 3 crate(s) checked
  [FAIL] api: needs rustc >= 1.100 but installed is 1.85.0

$ python msrv_check.py . --rustc 1.100.0
rustc 1.100.0 — 3 crate(s) checked
OK — every crate's MSRV is satisfied.
```

Exit code is `0` when every crate's MSRV is satisfied, `1` when any crate
needs a newer rustc, `2` on bad input. Crates without a `rust-version` and
crates on edition 2015/2018 produce warnings, not failures.

## Notes

- Stdlib only (uses `tomllib`, so Python 3.11+).
- `target/` and `.git/` are skipped; workspace members and standalone
  crates are both checked.
