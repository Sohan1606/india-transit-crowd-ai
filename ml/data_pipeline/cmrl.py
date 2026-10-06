"""Chennai Metro (CMRL) observed passenger-flow source adapter.

Upstream: https://github.com/PratyushBalaji/chennai-metro-ridership-tracker — a
GitHub-Actions collector that appends the official CMRL public passenger-flow
dashboard figures day by day. The dashboard itself only exposes the previous day,
so this repository is the archive; every value is an observed count published by
Chennai Metro Rail Limited, not a model output.

Target semantics, established rather than assumed
-------------------------------------------------
The report does not label ``stationData`` as entries or entries+exits. The adapter
therefore measures it: for each date, ``sum(station Total) / daily totalTickets``
is ~1.0 (not ~2.0), and the two interchange stations are duplicated across the two
corridors. A station value is therefore one boarding event per journey at that
station, i.e. **station entries**, not a footfall of entries+exits. The computed
ratio range is written into the metadata so the inference is auditable.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
import urllib.request
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from typing import Any

import pandas as pd

from ml.data_pipeline.source import CANONICAL_COLUMNS, SourceError

CMRL_SYSTEM_ID = "chennai-cmrl-metro"
CMRL_SOURCE_ID = "cmrl-passenger-flow-daily"
CMRL_TIMEZONE = "Asia/Kolkata"
CMRL_UPSTREAM_COMMIT = "72ee5eadb6ca890bfd9900d6464a1a371566c86b"
CMRL_UPSTREAM_REPOSITORY = "https://github.com/PratyushBalaji/chennai-metro-ridership-tracker"
CMRL_STATION_FILE = "Ridership/ChennaiMetro_Station_Ridership.csv"
CMRL_DAILY_FILE = "Ridership/ChennaiMetro_Daily_Ridership.csv"
CMRL_LICENSE = "Upstream data notice: CMRL copyright; not redistributed by this project"
CMRL_LICENSE_NOTE = (
    "The upstream repository is MIT-licensed for its CODE only and states explicitly that the "
    "licence grants no rights in the CMRL-published data, which remains copyrighted by Chennai "
    "Metro Rail Limited, and that the project is for research/educational use. This project "
    "therefore does not bundle or redistribute CMRL data: it is downloaded at preparation time "
    "from the pinned upstream revision and verified against a recorded SHA-256."
)
# Recorded at the pinned revision (verified by scripts/download_cmrl_data.py).
CMRL_CHECKSUMS = {
    CMRL_STATION_FILE: "2630ea1b083e491c225ec49760156b01302e8bfbd4383784045576306a709190",
    CMRL_DAILY_FILE: "6f16712ee90aebeefa52ca49e4dc3f3c6e076368b4ab60a1783260e6adba02bc",
}

# Station-code labels published by the upstream collector (taken from the CMRL
# dashboard's own station categories). Used only to name an entity; never to
# create or modify a count.
CMRL_STATION_NAMES = {
    "SWD": "Wimco Nagar Depot", "SWN": "Wimco Nagar", "STV": "Thiruvotriyur", "STT": "Thiruvotriyur Theradi",
    "SKP": "Kaladipet", "STG": "Tollgate", "SNW": "New Washermanpet", "STR": "Tondiarpet",
    "STC": "Thiagaraya College", "SWA": "Washermanpet", "SMA": "Mannadi", "SHC": "High Court",
    "SGE": "Government Estate", "SLI": "LIC", "STL": "Thousand Lights", "SGM": "AG-DMS",
    "STE": "Teynampet", "SCR": "Nandanam", "SSA": "Saidapet", "SLM": "Little Mount", "SGU": "Guindy",
    "SOT": "Ota - Nanganallur Road", "SME": "Meenambakkam", "SAP": "Chennai Airport", "SEG": "Egmore",
    "SNP": "Nehru Park", "SKM": "Kilpauk", "SPC": "Pachaiappa's College", "SSN": "Shenoy Nagar",
    "SAE": "Anna Nagar East", "SAT": "Anna Nagar Tower", "STI": "Thirumangalam", "SKO": "Koyambedu",
    "SCM": "CMBT", "SAR": "Arumbakkam", "SVA": "Vadapalani", "SAN": "Ashok Nagar",
    "SSI": "Ekkattuthangal", "SMM": "St. Thomas Mount", "SCC": "Chennai Central", "SAL": "Alandur",
}
CMRL_LINE_NAMES = {"01": "Blue Line", "02": "Green Line"}


# Station labels exactly as the CMRL passenger-flow API spells them, mapped to the
# operator's 3-letter codes. Kept verbatim because the API returns names, while the
# archived CSVs and this adapter key on codes; two labels carry double spaces or a
# leading "St." and must not be normalised by hand.
CMRL_API_STATION_CODES: dict[str, str] = {
    'WIMCO NAGAR DEPOT': "SWD",
    'WIMCO NAGAR METRO': "SWN",
    'THIRUVOTRIYUR METRO': "STV",
    'THIRUVOTRIYUR THERADI METRO': "STT",
    'KALADIPET METRO': "SKP",
    'TOLLGATE METRO': "STG",
    'NEW WASHERMENPET METRO': "SNW",
    'TONDIARPET METRO': "STR",
    'THIYAGARAYA COLLEGE METRO': "STC",
    'WASHERMANPET': "SWA",
    'MANNADI': "SMA",
    'HIGH COURT': "SHC",
    'GOVERNMENT ESTATE': "SGE",
    'LIC': "SLI",
    'THOUSAND LIGHT': "STL",
    'AG-DMS': "SGM",
    'TEYNAMPET': "STE",
    'NANDANAM': "SCR",
    'SAIDAPET': "SSA",
    'LITTLE MOUNT': "SLM",
    'GUINDY': "SGU",
    'OTA - NANGANALLUR ROAD': "SOT",
    'MEENAMBAKKAM': "SME",
    'CHENNAI AIRPORT': "SAP",
    'EGMORE': "SEG",
    'NEHRU PARK': "SNP",
    'KILPAUK': "SKM",
    'PACHAIAPPA S COLLEGE': "SPC",
    'SHENOY NAGAR': "SSN",
    'ANNA NAGAR EAST': "SAE",
    'ANNA NAGAR TOWER': "SAT",
    'THIRUMANGALAM': "STI",
    'KOYAMBEDU': "SKO",
    'CMBT': "SCM",
    'ARUMBAKKAM': "SAR",
    'VADAPALANI': "SVA",
    'ASHOK NAGAR': "SAN",
    'EKKATTUTHANGAL': "SSI",
    'St. THOMAS MOUNT': "SMM",
    'CENTRAL  METRO': "SCC",
    'ALANDUR': "SAL",
}


def resolve_station_code(label: str) -> str | None:
    """Map an API station label to its code, tolerating whitespace and punctuation drift."""
    text = str(label).strip()
    if text in CMRL_API_STATION_CODES:
        return CMRL_API_STATION_CODES[text]
    def canonical(value: str) -> str:
        value = re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()
        return re.sub(r"\s+metro$", "", value)
    wanted = canonical(text)
    for name, code in CMRL_API_STATION_CODES.items():
        if canonical(name) == wanted:
            return code
    return None


def _slug(value: str) -> str:
    ascii_value = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", ascii_value.lower()).strip("-")


def _read_csv(path: Path, expected_prefix: str) -> pd.DataFrame:
    if not path.is_file():
        raise SourceError(
            f"Missing {path.name}. Run scripts/download_cmrl_data.py first: this project does not "
            "redistribute CMRL data, it fetches the pinned public archive on demand."
        )
    text = path.read_text(encoding="utf-8-sig")
    if not text.strip():
        raise SourceError(f"{path.name} is empty.")
    return pd.read_csv(StringIO(text))


class CMRLStationDailyAdapter:
    """Normalize CMRL station-day entries into the shared canonical record contract."""

    source_id = CMRL_SOURCE_ID

    def load(self, station_path: Path, daily_path: Path | None = None) -> tuple[pd.DataFrame, dict[str, Any]]:
        station = _read_csv(station_path, "Date")
        expected_first = {"Date", "Line", "Station", "Total"}
        if not expected_first.issubset(station.columns):
            raise SourceError(
                "CMRL station file schema changed: expected the columns "
                f"{sorted(expected_first)} plus payment-mode breakdowns, found {list(station.columns)[:6]}."
            )
        dates = pd.to_datetime(station["Date"], format="%Y-%m-%d", errors="coerce")
        counts = pd.to_numeric(station["Total"], errors="coerce")
        codes = station["Station"].astype("string").str.strip().str.upper()
        lines = station["Line"].astype("string").str.strip().str.zfill(2)
        bad = dates.isna() | counts.isna() | codes.isna() | codes.eq("") | counts.lt(0) | (counts % 1 != 0)
        if bad.any():
            raise SourceError(f"CMRL station file has {int(bad.sum())} invalid rows; refusing to drop demand observations.")
        unknown = sorted(set(codes.dropna()) - set(CMRL_STATION_NAMES))
        if unknown:
            raise SourceError(f"CMRL station file uses unmapped station codes: {unknown}. Extend the label map only from an official source.")

        data = pd.DataFrame({
            "date": dates.dt.normalize(),
            "entity_id": [f"line-{line}-{_slug(code)}" for line, code in zip(lines, codes)],
            "entity_name": [f"{CMRL_STATION_NAMES[code]} ({CMRL_LINE_NAMES.get(line, 'Line ' + str(line))})"
                            for line, code in zip(lines, codes)],
            "line": lines,
            "demand_count": counts.astype("int64"),
        })
        duplicates = data.duplicated(["entity_id", "date"]).sum()
        if duplicates:
            raise SourceError(f"CMRL station file has {int(duplicates)} duplicate station-date rows; aggregation must be explicit.")
        data["timestamp"] = data["date"].dt.tz_localize(CMRL_TIMEZONE)

        normalized = pd.DataFrame({
            "system_id": CMRL_SYSTEM_ID, "city": "Chennai", "mode": "METRO", "operator": "CMRL",
            "entity_id": data["entity_id"], "entity_name": data["entity_name"], "entity_type": "STATION",
            "timestamp": data["timestamp"], "demand_count": data["demand_count"],
            "measure": "daily_station_entries", "source_id": self.source_id,
        }, columns=CANONICAL_COLUMNS)
        normalized = normalized.sort_values(["entity_id", "timestamp"], kind="stable").reset_index(drop=True)

        ratios: list[float] = []
        daily_total_rows = 0
        if daily_path is not None and Path(daily_path).is_file():
            daily = _read_csv(Path(daily_path), "Date")
            if {"Date", "Total"}.issubset(daily.columns):
                daily_total_rows = int(len(daily))
                system = daily.assign(date=pd.to_datetime(daily["Date"], errors="coerce")).dropna(subset=["date"])
                system_totals = pd.to_numeric(system["Total"], errors="coerce").groupby(system["date"].dt.normalize()).max()
                per_day = data.groupby("date")["demand_count"].sum()
                for date, value in per_day.items():
                    reference = system_totals.get(date)
                    if reference is not None and pd.notna(reference) and float(reference) > 0:
                        ratios.append(float(value) / float(reference))

        dates_unique = data["date"].drop_duplicates().sort_values()
        roster = data.groupby("date")["entity_id"].nunique()
        metadata = {
            "source_id": self.source_id,
            "source_title": "Chennai Metro (CMRL) official passenger-flow station data, archived daily",
            "publisher": "Chennai Metro Rail Limited (CMRL); archived daily by the upstream collector",
            "provenance": (
                "Values are the counts CMRL publishes on its public passenger-flow dashboard. The dashboard "
                "serves only the previous day, so the pinned upstream GitHub Actions archive is the historical "
                "record; each day it appends one row set from the live official API."
            ),
            "source_url": CMRL_UPSTREAM_REPOSITORY,
            "upstream_commit": CMRL_UPSTREAM_COMMIT,
            "official_dashboard_url": "https://commuters-data.chennaimetrorail.org/passengerflow",
            "official_api_base": "https://commuters-dataapi.chennaimetrorail.org/api/PassengerFlow",
            "source_file": station_path.name,
            "source_sha256": hashlib.sha256(station_path.read_bytes()).hexdigest(),
            "expected_source_sha256": CMRL_CHECKSUMS.get(CMRL_STATION_FILE),
            "license": CMRL_LICENSE,
            "license_note": CMRL_LICENSE_NOTE,
            "system": {"system_id": CMRL_SYSTEM_ID, "city": "Chennai", "mode": "METRO", "operator": "CMRL"},
            "granularity": "one calendar day per station-line entity",
            "measure": "daily_station_entries",
            "measure_definition": (
                "passengers recorded by CMRL as using the station that day on that corridor; empirically one "
                "boarding event per journey, not entries plus exits, and not onboard load or occupancy"
            ),
            "timezone": CMRL_TIMEZONE,
            "rows": int(len(normalized)),
            "entity_count": int(normalized["entity_id"].nunique()),
            "station_count": int(len(set(codes))),
            "line_ids": sorted(set(lines)),
            "date_min": dates_unique.min().strftime("%Y-%m-%d"),
            "date_max": dates_unique.max().strftime("%Y-%m-%d"),
            "unique_dates": int(len(dates_unique)),
            "expected_contiguous_dates": int((dates_unique.max() - dates_unique.min()).days + 1),
            "entities_per_date_min": int(roster.min()), "entities_per_date_max": int(roster.max()),
            "duplicate_station_dates": 0,
            "missing_station_days_filled": 0,
            "explicit_zero_observations": int(normalized["demand_count"].eq(0).sum()),
            "measure_semantics_check": {
                "method": "per-date sum(station Total) divided by the CMRL daily system total (allTicketCount)",
                "daily_total_rows_available": int(daily_total_rows),
                "ratio_mean": round(sum(ratios) / len(ratios), 4) if ratios else None,
                "ratio_min": round(min(ratios), 4) if ratios else None,
                "ratio_max": round(max(ratios), 4) if ratios else None,
                "interpretation": (
                    "A ratio near 1.0 means each journey is counted once at a station, so the field is entries/"
                    "boardings; a ratio near 2.0 would have indicated entries plus exits."
                ),
            },
            "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
            "notes": [
                "Chennai Central (SCC) and Alandur (SAL) are interchange stations reported once per corridor; the adapter keeps them as two distinct line entities instead of summing them.",
                "No station-day row is created for a date the source does not report; absent observations stay absent.",
                "Payment-mode breakdown columns are retained upstream but are not needed for the demand target and are not silently merged into it.",
            ],
        }
        return normalized, metadata


def cmrl_raw_url(relative_path: str, commit: str = CMRL_UPSTREAM_COMMIT) -> str:
    return f"https://raw.githubusercontent.com/PratyushBalaji/chennai-metro-ridership-tracker/{commit}/{relative_path}"


def download_cmrl_source(relative_path: str, output: Path,
                         expected_sha256: str | None = None, commit: str = CMRL_UPSTREAM_COMMIT) -> Path:
    """Fetch one pinned upstream archive file and verify its recorded checksum."""
    url = cmrl_raw_url(relative_path, commit)
    request = urllib.request.Request(url, headers={"User-Agent": "IndiaTransitCrowdAI/1.0 (reproducible research)"})
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            content = response.read()
    except Exception as exc:  # noqa: BLE001 - network failure must become a source error
        raise SourceError(f"Could not download the pinned CMRL archive file {relative_path} ({type(exc).__name__}).") from exc
    digest = hashlib.sha256(content).hexdigest()
    if expected_sha256 and digest != expected_sha256:
        raise SourceError(
            f"Pinned CMRL checksum mismatch for {relative_path}: expected {expected_sha256}, received {digest}. "
            "The upstream archive changed; re-review provenance before using it."
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(content)
    return output
