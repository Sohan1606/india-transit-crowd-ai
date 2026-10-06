"""Verified India transit source adapters and canonical demand records.

The adapter boundary is intentionally separate from the model: each source must
prove its observed-demand measure, temporal resolution, entity keys and lineage
before it can enter the shared normalized-record contract. Schedule-only GTFS
feeds are catalogued separately and must never be passed to this demand adapter.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Protocol

import pandas as pd


BMRCL_SYSTEM_ID = "bengaluru-namma-metro"
BMRCL_SOURCE_ID = "bmrcl-ridership-hourly"
BMRCL_REPOSITORY = "https://github.com/Vonter/bmrcl-ridership-hourly"
BMRCL_DATA_URL = (
    "https://raw.githubusercontent.com/Vonter/bmrcl-ridership-hourly/"
    "6c44579b5ff3428a88bddc44baf84e436a940612/data/station-hourly.csv.zip"
)
BMRCL_DATA_SHA256 = "a0469f3365c53ca25d9aed5396775fc1c6018cfc0b93e245e8bc3e1c9524bd81"
BMRCL_UPSTREAM_COMMIT = "6c44579b5ff3428a88bddc44baf84e436a940612"
BMRCL_LICENSE = "ODbL-1.0"
BMRCL_LICENSE_URL = "https://opendatacommons.org/licenses/odbl/1-0/"
BMRCL_TIMEZONE = "Asia/Kolkata"

CANONICAL_COLUMNS = [
    "system_id", "city", "mode", "operator", "entity_id", "entity_name",
    "entity_type", "timestamp", "demand_count", "measure", "source_id",
]


class SourceError(RuntimeError):
    """An upstream source is unavailable, changed schema, or failed provenance checks."""


class SourceAdapter(Protocol):
    source_id: str

    def load(self, path: Path) -> tuple[pd.DataFrame, dict]: ...


@dataclass(frozen=True)
class BMRCLRidershipAdapter:
    """Normalize the published BMRCL station-hour entries extract."""

    source_id: str = BMRCL_SOURCE_ID

    @staticmethod
    def _station_id(name: str) -> str:
        ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
        slug = re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-")
        if not slug:
            raise SourceError(f"Station name cannot be converted to a stable ID: {name!r}")
        return slug

    @staticmethod
    def _read(path: Path) -> pd.DataFrame:
        if not path.is_file():
            raise SourceError(f"BMRCL source file not found: {path}")
        try:
            if zipfile.is_zipfile(path):
                with zipfile.ZipFile(path) as archive:
                    candidates = [name for name in archive.namelist() if name.lower().endswith(".csv") and not name.startswith("__MACOSX/")]
                    if len(candidates) != 1:
                        raise SourceError("Expected exactly one CSV file in the BMRCL source archive.")
                    with archive.open(candidates[0]) as stream:
                        return pd.read_csv(stream, sep=";", encoding="utf-8-sig")
            return pd.read_csv(path, sep=";", encoding="utf-8-sig")
        except (OSError, zipfile.BadZipFile, UnicodeError, pd.errors.ParserError) as exc:
            raise SourceError(f"Could not parse the BMRCL station-hour file ({type(exc).__name__}).") from exc

    def load(self, path: Path) -> tuple[pd.DataFrame, dict]:
        raw = self._read(path)
        expected = {"Date", "Hour", "Station", "Ridership"}
        if set(raw.columns) != expected:
            raise SourceError(
                "BMRCL source schema changed: expected exactly "
                f"{sorted(expected)}, received {sorted(map(str, raw.columns))}."
            )
        if raw.empty:
            raise SourceError("The BMRCL source extract contains no observations.")

        source = raw.rename(columns={
            "Date": "_date", "Hour": "_hour", "Station": "entity_name", "Ridership": "demand_count",
        }).copy()
        source["entity_name"] = source["entity_name"].astype("string").str.strip()
        dates = pd.to_datetime(source["_date"], format="%Y-%m-%d", errors="coerce")
        hour_numeric = pd.to_numeric(source["_hour"], errors="coerce")
        count = pd.to_numeric(source["demand_count"], errors="coerce")
        invalid = (
            dates.isna()
            | hour_numeric.isna()
            | ~hour_numeric.between(0, 23)
            | (hour_numeric % 1 != 0)
            | source["entity_name"].isna()
            | source["entity_name"].eq("")
            | count.isna()
            | ~count.map(lambda value: pd.notna(value) and float(value) not in (float("inf"), float("-inf")))
            | count.lt(0)
        )
        if invalid.any():
            raise SourceError(f"The BMRCL source has {int(invalid.sum())} invalid rows; refusing to silently drop demand records.")

        source["_hour"] = hour_numeric.astype("int16")
        source["demand_count"] = count.astype("int64")
        if (source["demand_count"] != count).any():
            raise SourceError("BMRCL ridership values must be whole passenger counts.")
        source["entity_id"] = source["entity_name"].map(self._station_id)
        collision = source.groupby("entity_id")["entity_name"].nunique()
        if collision.gt(1).any():
            raise SourceError("Two different BMRCL station names map to the same normalized entity ID.")

        local_time = dates + pd.to_timedelta(source["_hour"], unit="h")
        source["timestamp"] = local_time.dt.tz_localize(BMRCL_TIMEZONE)
        if source.duplicated(["entity_id", "timestamp"]).any():
            raise SourceError("The BMRCL source contains duplicate station-hour keys; aggregation is not assumed safe.")

        normalized = pd.DataFrame({
            "system_id": BMRCL_SYSTEM_ID,
            "city": "Bengaluru",
            "mode": "METRO",
            "operator": "BMRCL",
            "entity_id": source["entity_id"],
            "entity_name": source["entity_name"],
            "entity_type": "STATION",
            "timestamp": source["timestamp"],
            "demand_count": source["demand_count"],
            "measure": "hourly_station_boardings",
            "source_id": self.source_id,
        }, columns=CANONICAL_COLUMNS)
        normalized = normalized.sort_values(["entity_id", "timestamp"], kind="stable").reset_index(drop=True)

        station_names = source[["entity_id", "entity_name"]].drop_duplicates().sort_values("entity_id")
        daily_station_counts = source.assign(_date=dates.dt.strftime("%Y-%m-%d")).groupby("_date")["entity_id"].nunique()
        raw_bytes = path.read_bytes()
        metadata = {
            "source_id": self.source_id,
            "source_title": "BMRCL/Namma Metro station-wise hourly ridership (boardings)",
            "publisher": "Bengaluru Metro Rail Corporation Ltd (BMRCL); upstream compilation by Vonter",
            "provenance": "The upstream repository states that its source records were received through RTI. The bundled station-hour file is republished from that repository; it is not a live BMRCL feed.",
            "source_url": BMRCL_REPOSITORY,
            "source_data_url": BMRCL_DATA_URL,
            "upstream_commit": BMRCL_UPSTREAM_COMMIT,
            "source_file": path.name,
            "source_sha256": hashlib.sha256(raw_bytes).hexdigest(),
            "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
            "license": BMRCL_LICENSE,
            "license_url": BMRCL_LICENSE_URL,
            "attribution": "BMRCL; station-hour ridership data obtained through RTI and compiled/published by Vonter in bmrcl-ridership-hourly. Adapted normalized demand database is made available under ODbL-1.0.",
            "underlying_rights_note": "The upstream repository notes that some individual contents of its database may be copyrighted by BMRCL. No BMRCL endorsement or blanket waiver of underlying rights is implied.",
            "system": {"system_id": BMRCL_SYSTEM_ID, "city": "Bengaluru", "mode": "METRO", "operator": "BMRCL"},
            "granularity": "one observed station-hour",
            "measure": "passengers boarded/entered at a station during the source hour; not onboard load or physical occupancy",
            "timezone": BMRCL_TIMEZONE,
            "source_periods": [
                {"start_inclusive": "2025-08-01", "end_inclusive": "2025-08-18"},
                {"start_inclusive": "2025-09-01", "end_inclusive": "2025-09-30"},
            ],
            "rows": int(len(normalized)),
            "station_count": int(station_names["entity_id"].nunique()),
            "station_ids": station_names["entity_id"].tolist(),
            "station_names": station_names["entity_name"].tolist(),
            "date_min": dates.min().strftime("%Y-%m-%d"),
            "date_max": dates.max().strftime("%Y-%m-%d"),
            "unique_source_dates": int(dates.dt.date.nunique()),
            "explicit_zero_observations": int(normalized["demand_count"].eq(0).sum()),
            "duplicate_station_hours": 0,
            "stations_per_date_min": int(daily_station_counts.min()),
            "stations_per_date_max": int(daily_station_counts.max()),
            "missing_hours_filled": 0,
            "notes": [
                "Source DATA.md documents station ridership for 1–18 August 2025 and 1–30 September 2025; 19–31 August has no rows.",
                "The source data dictionary describes Ridership as passengers boarded at the station during that hour.",
                "Present zero rows are preserved as observed zero counts. Missing station-hour rows remain missing and are never zero-filled.",
                "The station roster is not constant across the August observations; the adapter does not manufacture earlier station records.",
                "The archive is a dated historical snapshot, not a live feed or a nationwide dataset.",
            ],
        }
        return normalized, metadata


def download_bmrcl_source(output: Path, expected_sha256: str = BMRCL_DATA_SHA256) -> Path:
    """Fetch the pinned, small source archive and verify its published checksum."""
    output.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(BMRCL_DATA_URL, headers={"User-Agent": "IndiaTransitCrowdAI/1.0 (reproducible academic project)"})
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            content = response.read()
    except Exception as exc:
        raise SourceError(f"Could not download the pinned BMRCL source archive ({type(exc).__name__}).") from exc
    digest = hashlib.sha256(content).hexdigest()
    if digest != expected_sha256:
        raise SourceError(f"Pinned BMRCL source checksum mismatch: expected {expected_sha256}, received {digest}.")
    output.write_bytes(content)
    return output


def write_source_metadata(metadata: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
