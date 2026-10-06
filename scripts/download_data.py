#!/usr/bin/env python3
"""Download the pinned BMRCL/Namma Metro station-hour observed-demand extract."""
from __future__ import annotations
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ml.data_pipeline.source import BMRCL_DATA_SHA256, BMRCL_DATA_URL, SourceError, download_bmrcl_source  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "data/raw/india/bmrcl-station-hourly.csv.zip")
    parser.add_argument("--allow-updated-source", action="store_true",
                        help="Not implemented: a new upstream revision must be audited and pinned before use.")
    args = parser.parse_args()
    if args.allow_updated_source:
        parser.error("Do not bypass the pinned source checksum. Review, pin and document a new source revision first.")
    try:
        path = download_bmrcl_source(args.output)
    except SourceError as exc:
        raise SystemExit(str(exc)) from exc
    print(f"Downloaded verified BMRCL source archive: {path}")
    print(f"Pinned URL: {BMRCL_DATA_URL}")
    print(f"SHA-256: {BMRCL_DATA_SHA256}")


if __name__ == "__main__":
    main()
