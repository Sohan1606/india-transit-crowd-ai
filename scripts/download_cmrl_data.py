#!/usr/bin/env python3
"""Fetch the pinned CMRL archive files for the Chennai observed-demand family.

CMRL data are copyrighted by the operator, so this project does not bundle them.
Run this before prepare_chennai_data.py / train_chennai_models.py.
"""
from __future__ import annotations
import argparse, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ml.data_pipeline.cmrl import (  # noqa: E402
    CMRL_CHECKSUMS, CMRL_DAILY_FILE, CMRL_STATION_FILE, CMRL_UPSTREAM_COMMIT, download_cmrl_source,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--outdir", type=Path, default=ROOT / "data/raw/india/cmrl")
    parser.add_argument("--commit", default=CMRL_UPSTREAM_COMMIT)
    parser.add_argument("--no-verify", action="store_true",
                        help="Skip the recorded checksum (not recommended; provenance must be re-reviewed).")
    args = parser.parse_args()
    for relative in (CMRL_STATION_FILE, CMRL_DAILY_FILE):
        output = args.outdir / Path(relative).name
        digest = None if args.no_verify else CMRL_CHECKSUMS.get(relative) if args.commit == CMRL_UPSTREAM_COMMIT else None
        download_cmrl_source(relative, output, expected_sha256=digest, commit=args.commit)
        print(f"{relative} -> {output.relative_to(ROOT)}  ({output.stat().st_size:,} bytes)")
    print("Pinned upstream revision:", args.commit)


if __name__ == "__main__":
    main()
