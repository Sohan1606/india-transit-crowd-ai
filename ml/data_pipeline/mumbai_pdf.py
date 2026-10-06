"""Parse observed survey tables from the MRVC / Wilbur Smith Mumbai suburban rail report.

Source document: "Mumbai Sub-urban Rail Passenger Surveys and Analysis", Executive
Summary, prepared for Mumbai Railway Vikas Corporation Ltd. (MRVC) by Wilbur Smith
Associates. PDF created 2013-08-16, last modified 2013-09-04.

Design rules enforced here
--------------------------
1. Only figures printed in the report are emitted; nothing is interpolated or
   invented. Fields the document does not state are ``None``.
2. Observed/derived survey results are separated from the study's *modelled*
   passenger-trip forecasts (Table E-13). Forecast values are never emitted into
   the observed record set; they go to :func:`parse_modelled_forecasts` and are
   labelled ``HISTORICAL STUDY MODEL OUTPUT``.
3. No per-day dates are invented. The report gives survey *periods*, and where it
   says a survey was run on "a typical weekday" that is recorded as a period
   qualifier, never as a specific date.
4. Every table is cross-checked against the totals printed in the same table, so a
   silent parsing slip raises instead of corrupting the dataset.
"""
from __future__ import annotations

import re
from typing import Any

# Indian digit grouping (e.g. "1,43,690") and plain grouping ("143690").
NUM = r"\d[\d,]*"
_NUM_RE = re.compile(NUM)


class PdfParseError(RuntimeError):
    """The report text does not match the expected observed tables."""


def _int(token: str) -> int:
    return int(token.replace(",", ""))


def _numbers(text: str) -> list[int]:
    return [_int(m.group(0)) for m in re.finditer(rf"\b({NUM})\b", text)]


def _close(a: int | float, b: int | float, rel: float = 0.02) -> bool:
    if a == b:
        return True
    return abs(a - b) <= max(rel * abs(b), 1)


# ---------------------------------------------------------------------------
# Survey calendar (Table E-1 + narrative). Dates are survey windows, not
# observation timestamps: the report publishes aggregated typical-weekday
# results, so a single window row applies to every figure in its table.
# ---------------------------------------------------------------------------
SURVEY_PERIODS: dict[str, dict[str, Any]] = {
    "commuter_feedback": {
        "survey": "Commuter Feedback Survey",
        "start": "2011-11-22",
        "end": "2011-12-06",
        "daily_window": "08:00-22:00 (14 hrs)",
        "sample": "25,000 samples interviewed at stations and inside trains",
        "exclusions": "Started after Diwali vacation (after 13/11/2011); no surveys during Christmas vacation 23/12/2011-02/01/2012.",
    },
    "entry_exit_count": {
        "survey": "Passenger Entry/Exit count",
        "start": "2011-12-08",
        "end": "2012-02-10",
        "daily_window": "08:00-22:00 (14 hrs)",
        "sample": "All authorised and un-authorised entry points of 37 selected stations",
        "exclusions": "Report prints the end date as '10/2/2012' in Table E-1 (day/month/year).",
    },
    "alighting_distribution": {
        "survey": "Alighting Distribution Survey (37 stations)",
        "start": None,
        "end": None,
        "daily_window": "morning/evening peak period",
        "sample": "Selected platforms, Up and Down directions, slow and fast services; SCG/SCL/FCG/FCL/Vendor/PH coaches",
        "exclusions": "Table E-1 leaves the start-end date cell blank for this survey row.",
    },
    "in_train_boarding_alighting": {
        "survey": "In-Train Rail Passenger Boarding/Alighting Surveys",
        "start": "2012-02-11",
        "end": "2012-03-15",
        "daily_window": "07:00-11:30 or 16:00-20:30",
        "sample": "310 services (124 Western, 94 Central, 92 Harbour); count of passengers boarding/alighting at every station",
        "exclusions": "Table E-1 heading says 300 services in Section III and 310 in Table E-1/narrative; the narrative figure 310 is used.",
    },
    "virar_dahanu_road": {
        "survey": "Virar-Dhanu Road line surveys (secondary data + limited surveys)",
        "start": "2013-06-17",
        "end": "2013-06-18",
        "daily_window": "08:00-22:00 (14 hrs) for entry/exit",
        "sample": "Inspection/mapping, entry-exit counts, FoB counts at 8 stations",
        "exclusions": "Section added on the basis of secondary data provided by MRVC and limited surveys.",
    },
}

# Station rosters as listed in Section III (Scope of the study).
STATION_SCOPE: dict[str, list[str]] = {
    "Western Line": [
        "Churchgate", "Mumbai Central", "Dadar (Western)", "Mahim", "Bandra", "Andheri",
        "Goregaon", "Borivali", "Mira Road", "Bhayander", "Vasai Road", "Nalasopara", "Virar",
    ],
    "Virar-Dhanu Road Line": [
        "Vaitarna", "Kelve Raod", "Saphale", "Palghar", "Umroli", "Boisar", "Vangaon", "Dhanu Road",
    ],
    "Central Line": [
        "Mumbai CST", "Masjid", "Byculla", "Dadar (Central)", "Kurla", "Ghatkopar", "Bhandup",
        "Mulund", "Thane", "Dombivilli", "Kalyan", "Kasara", "Karjat", "Khopoli",
    ],
    "Harbour Line": [
        "Vadala Road", "GTB Nagar", "Chembur", "Govandi", "Vashi", "Nerul", "Belapur",
        "Kharghar", "Panvel", "Airoli", "Turbe",
    ],
}

# Network context printed on report page E-1 (narrative, not a survey count).
NETWORK_CONTEXT = {
    "route_kms": 319,
    "corridors": 3,
    "stations": {"Western Line": 36, "Central Line": 51, "Harbour Line": 28},
    "daily_services_total": 2813,
    "daily_services": {
        "Western Line": {"total": 1201, "rake_9_car": 6, "rake_12_car": 1165, "rake_15_car": 30},
        "Central Line": {"total": 875, "rake_9_car": 0, "rake_12_car": 809, "rake_15_car": 16},
        "Harbour Line": {"total": 787, "rake_9_car": 577, "rake_12_car": 210, "rake_15_car": None},
    },
    "weekday_passengers_stated": "more than 80 lakhs on a weekday",
    "rated_capacity_passengers": {"9_car": 1800, "12_car": 3522},
    "capacity_source": "MRVC (as cited in the report)",
}


TIME_LABEL = re.compile(
    r"(?:\d{1,2}[:.]\d{2}\s*(?:to|:|-)\s*\d{1,2}[:.]\d{2}|After\s*\d{1,2}[.:]\d{2})", re.I
)
PAIR = re.compile(r"(\d[\d,]*(?:\.\d+)?)(?:\s*\((\d[\d,]*)\))?")
HOUR_PROFILE_LABEL = re.compile(r"\b(?:8|9|10|11|12|13|14|15|16|17|18|19|20|21)\.00 to (?:9|10|11|12|13|14|15|16|17|18|19|20|21|22)(?:\.0)?0?")


def collapsed(pages: dict[int, str], *numbers: int) -> str:
    """Whitespace-normalised text for one or more pages (PDF layout is columnar)."""
    parts = []
    for number in numbers:
        text = pages.get(number)
        if text is None:
            raise PdfParseError(f"Expected PDF page {number} is missing from the extracted text.")
        parts.append(text)
    return re.sub(r"\s+", " ", " ".join(parts))


def _pairs(segment: str, columns: list[str]) -> dict[str, tuple[float, int | None]]:
    """Read len(columns) (value[, services]) pairs from a row segment."""
    found = [(m.group(1), m.group(2)) for m in PAIR.finditer(segment)]
    if len(found) < len(columns):
        raise PdfParseError(f"Row {segment[:60]!r}: expected {len(columns)} values, found {len(found)}.")
    out: dict[str, tuple[float, int | None]] = {}
    for name, (value, services) in zip(columns, found[: len(columns)]):
        number = float(value.replace(",", ""))
        out[name] = (int(number) if number.is_integer() else number,
                     int(services.replace(",", "")) if services else None)
    return out


def parse_hourly_travel_tables(pages: dict[int, str]) -> list[dict[str, Any]]:
    """Tables E-4..E-8: passengers travelling per hour, by line, peak direction.

    Rows are assigned to the Up (morning) or Down (evening) direction from their own
    time label, which is robust to the repeated column headers the PDF text layer emits.
    """
    specs = [
        {"table": "Table E- 4", "page": 10, "line": "Entire suburban system (3 lines)",
         "columns": ["slow", "fast", "total", "share"], "with_services": False,
         "totals": {"UP": (2291376, 0), "DOWN": (2242948, 0)},
         "basis": "in-train boarding/alighting survey of 310 services expanded coach->train then sample-services->all peak-period services; Table E-4 prints no per-hour service counts, only a column total (241 slow + 108 fast = 349 morning, 240 + 93 = 333 evening)",
         "period": "in_train_boarding_alighting", "unit": "passengers per 1-hour interval in the peak direction"},
        {"table": "Table E- 5", "page": 10, "line": "Western Line",
         "columns": ["slow", "fast", "total"], "with_services": True,
         "totals": {"UP": (1124170, 153), "DOWN": (1017897, 134)}, "sum_services": False,
         "basis": "in-train boarding/alighting survey expanded to all peak-period services",
         "period": "in_train_boarding_alighting", "unit": "passengers per 1-hour interval in the peak direction"},
        {"table": "Table E- 6", "page": 11, "line": "Virar-Dhanu Road Line",
         "columns": ["total"], "with_services": True,
         "totals": {"UP": (17298, 38), "DOWN": (19901, 39)}, "sum_services": False,
         "basis": "limited Virar-Dhanu Road surveys plus secondary data provided by MRVC",
         "period": "virar_dahanu_road", "unit": "passengers boarding/alighting per 1-hour interval"},
        {"table": "Table E- 7", "page": 11, "line": "Central Line",
         "columns": ["slow", "fast", "total"], "with_services": True,
         "totals": {"UP": (760904, 101), "DOWN": (761745, 99)}, "sum_services": False,
         "basis": "in-train boarding/alighting survey expanded to all peak-period services",
         "period": "in_train_boarding_alighting", "unit": "passengers per 1-hour interval in the peak direction"},
        {"table": "Table E- 8", "pages": (11, 12), "line": "Harbour Line (Main Harbour + Trans Harbour)",
         "columns": ["main_harbour", "trans_harbour", "total"], "with_services": True,
         "totals": {"UP": (406303, 158), "DOWN": (463306, 176)}, "sum_services": False,
         "basis": "in-train boarding/alighting survey expanded to all peak-period services",
         "period": "in_train_boarding_alighting", "unit": "passengers per 1-hour interval in the peak direction"},
    ]
    records: list[dict[str, Any]] = []
    for spec in specs:
        page_numbers = tuple(spec.get("pages") or (spec["page"],))
        text = collapsed(pages, *page_numbers)
        start = text.index(spec["table"])
        tail = text[start + len(spec["table"]):]
        # A page can carry several tables: bound this block by the next table header
        # or by the table's own "Note:" line, whichever comes first.
        stops = [i for i in (tail.find("Note:"), re.search(r"\n?Table E- \d", tail).start() if re.search(r"\n?Table E- \d", tail) else -1) if i > 0]
        if stops:
            tail = tail[: min(stops)]
        buckets: dict[str, list[dict[str, Any]]] = {"UP": [], "DOWN": []}
        for match in re.finditer(TIME_LABEL, tail):
            label = re.sub(r"\s+", " ", match.group(0)).strip()
            segment = tail[match.end(): match.end() + 120]
            nxt = TIME_LABEL.search(segment)
            if nxt:
                segment = segment[: nxt.start()]
            values = _pairs(segment, spec["columns"])
            first_hour = int(label.split(":")[0].split(".")[0].replace("After", "").strip())
            direction = "UP" if first_hour <= 11 else "DOWN"
            total_value, total_services = values["total"] if spec["with_services"] else values["total"]
            row = {
                "source_document": "Mumbai Sub-urban Rail Passenger Surveys and Analysis (Executive Summary)",
                "source_table": spec["table"].replace("Table E- ", "Table E-"), "source_page": page_numbers[0],
                "line": spec["line"], "direction": direction, "interval_label": label,
                "measure": "passengers_travelling_in_peak_direction", "unit": spec["unit"],
                "total_count": total_value, "total_services": total_services,
                "observation_type": "derived_from_sample_survey", "basis": spec["basis"],
                "survey_period_key": spec["period"],
            }
            for column in spec["columns"]:
                if column in {"total", "share"}:
                    continue
                row[f"{column}_count"], row[f"{column}_services"] = values[column]
            if "share" in spec["columns"]:
                row["share_percent"] = values["share"][0]
            buckets[direction].append(row)
        for direction, rows in buckets.items():
            expect_total, expect_services = spec["totals"][direction]
            if not rows:
                raise PdfParseError(f"{spec['table']}: no {direction} rows parsed.")
            got_total = sum(row["total_count"] for row in rows)
            got_services = sum(row["total_services"] or 0 for row in rows)
            if not _close(got_total, expect_total):
                raise PdfParseError(
                    f"{spec['table']} {direction}: hourly rows sum to {got_total:,} but the table prints {expect_total:,}."
                )
            if spec.get("sum_services", True) and expect_services and not _close(got_services, expect_services):
                raise PdfParseError(
                    f"{spec['table']} {direction}: services sum to {got_services} but the table prints {expect_services}."
                )
            records.extend(rows)
        for direction, rows in buckets.items():
            expect_total, expect_services = spec["totals"][direction]
            records.append({
                "source_document": "Mumbai Sub-urban Rail Passenger Surveys and Analysis (Executive Summary)",
                "source_table": spec["table"].replace(" ", ""), "source_page": tuple(spec.get("pages") or (spec["page"],))[0],
                "line": spec["line"], "direction": direction, "interval_label": "peak period total (as printed)",
                "measure": "passengers_travelling_peak_period_total", "unit": spec["unit"].replace("1-hour interval", "sampled peak period"),
                "total_count": expect_total, "total_services": expect_services,
                "observation_type": "derived_from_sample_survey",
                "basis": "table's own printed Total Passengers / Total Services row; per-hour train counts are not additive because a train can be running in two consecutive hours",
                "survey_period_key": spec["period"],
            })
    return records


_STATION_TABLES = {
    "Table E- 14": {"pages": (25,), "line": "Western Line", "period": "entry_exit_count",
                    "total_authorised": 4150113, "total_unauthorised": 143580, "grand_total": 4293693,
                    "expected_rows": 13},
    "Table E- 16": {"pages": (26,), "line": "Virar-Dhanu Road Line", "period": "virar_dahanu_road",
                    "total_authorised": 447849, "total_unauthorised": 81532, "grand_total": 529381,
                    "expected_rows": 9},
    "Table E- 18": {"pages": (27,), "line": "Central Line", "period": "entry_exit_count",
                    "total_authorised": 3598126, "total_unauthorised": 138364, "grand_total": 3736490,
                    "expected_rows": 14},
    "Table E- 20": {"pages": (27, 28), "line": "Harbour Line", "period": "entry_exit_count",
                    "total_authorised": 1238907, "total_unauthorised": 241033, "grand_total": 1479940,
                    "expected_rows": 11},
}

_HOURLY_PROFILE = {
    "Table E- 15": {"pages": (26,), "line": "Western Line", "total": 4293693},
    "Table E- 17": {"pages": (26,), "line": "Virar-Dhanu Road Line", "total": 529381},
    "Table E- 19": {"pages": (27,), "line": "Central Line", "total": 3736490},
    "Table E- 21": {"pages": (28,), "line": "Harbour Line", "total": 1479940},
}

_ROW = re.compile(
    r"(\d{1,2})\s+([A-Za-z][A-Za-z .'\-]{2,34}?)\s+(-?\d[\d,]*|Nil)\s+(-|Nil|\d[\d,]*)\s+(-?\d[\d,]*)\s*(?:\((\d{2,4})\))?"
)


def parse_station_entry_exit_tables(pages: dict[int, str]) -> list[dict[str, Any]]:
    """Tables E-14/16/18/20: station Entry+Exit totals for one surveyed 14-hour weekday."""
    records: list[dict[str, Any]] = []
    for table, spec in _STATION_TABLES.items():
        text = collapsed(pages, *spec["pages"])
        start = text.index(table)
        stop = re.search(r"Table E- 1[5-9]|Table E- 2[01]|The summary of hourly variation|The hourly variation", text[start + len(table):])
        block = text[start: start + len(table) + (stop.start() if stop else 4000)]
        authorised = unauthorised = 0
        seen = 0
        for match in _ROW.finditer(block):
            _, name, auth, unauth, total, services = match.groups()
            if name.strip().lower().startswith(("no of", "station", "sl")):
                continue
            auth_n = _int(auth) if auth not in ("Nil",) else 0
            unauth_n = None if unauth.strip() in {"-", "Nil"} else _int(unauth)
            total_n = _int(total)
            if auth_n + (unauth_n or 0) != total_n:
                raise PdfParseError(f"{table} {name}: {auth_n}+{unauth_n} != printed total {total_n}.")
            authorised += auth_n
            unauthorised += unauth_n or 0
            seen += 1
            records.append({
                "source_table": table.replace(" ", ""), "source_page": spec["pages"][0], "line": spec["line"],
                "station_name": re.sub(r"\s+", " ", name).strip(),
                "authorised_entry_exit": auth_n, "unauthorised_entry_exit": unauth_n,
                "total_entry_exit_14h": total_n,
                "trains_stopping_8_to_22": _int(services) if services else None,
                "direction": "BOTH", "service_type": "ALL",
                "measure": "station_entries_plus_exits_14h",
                "unit": "passengers per 14-hour survey day (08:00-22:00)",
                "time_interval": "08:00-22:00", "observation_type": "counted_at_entry_exit_points",
                "survey_period_key": spec["period"],
            })
        if seen != spec["expected_rows"]:
            raise PdfParseError(f"{table}: parsed {seen} station rows, expected {spec['expected_rows']}.")
        grand = authorised + unauthorised
        if (authorised != spec["total_authorised"] or unauthorised != spec["total_unauthorised"]
                or grand != spec["grand_total"]):
            raise PdfParseError(
                f"{table}: parsed authorised/unauthorised/grand = {authorised:,}/{unauthorised:,}/{grand:,} "
                f"but the table prints {spec['total_authorised']:,}/{spec['total_unauthorised']:,}/{spec['grand_total']:,}."
            )
    return records


def _num_with_commas(value: int) -> str:
    """Format an integer with Indian digit grouping (e.g. 4293693 -> 42,93,693)."""
    text = str(int(value))
    if len(text) <= 3:
        return text
    head, tail = text[:-3], text[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    return ",".join(groups)


def parse_hourly_entry_exit_profiles(pages: dict[int, str]) -> list[dict[str, Any]]:
    """Tables E-15/17/19/21: line-level hourly profile of station entries+exits."""
    records: list[dict[str, Any]] = []
    for table, spec in _HOURLY_PROFILE.items():
        text = collapsed(pages, *spec["pages"])
        start = text.index(table)
        stop = text.find(_num_with_commas(spec["total"]), start)
        if stop < 0:
            raise PdfParseError(f"{table}: printed total {_num_with_commas(spec['total'])} not found after the header.")
        block = text[start:stop]
        total = 0
        rows = 0
        for match in re.finditer(HOUR_PROFILE_LABEL, block):
            label = re.sub(r"\s+", " ", match.group(0)).strip()
            segment = block[match.end(): match.end() + 60]
            values = [float(v.replace(",", "")) for v in re.findall(r"\d[\d,]*(?:\.\d+)?", segment)[:2]]
            if len(values) < 2:
                raise PdfParseError(f"{table} {label}: expected a count and a share percentage.")
            count = int(values[0])
            total += count
            rows += 1
            records.append({
                "source_table": table.replace(" ", ""), "source_page": spec["pages"][0], "line": spec["line"],
                "station_name": None, "interval_label": label, "entry_exit_count": count,
                "share_percent": values[1], "measure": "station_entries_plus_exits_hourly_share",
                "unit": "passengers per hour summed over the surveyed stations on the line",
                "direction": "BOTH", "service_type": "ALL", "observation_type": "counted_at_entry_exit_points",
                "survey_period_key": "virar_dahanu_road" if "Virar-Dhanu" in spec["line"] else "entry_exit_count",
                "aggregation_level": "line_summary_of_surveyed_stations",
            })
        if rows != 14:
            raise PdfParseError(f"{table}: parsed {rows} hourly rows, expected 14.")
        if total != spec["total"]:
            raise PdfParseError(f"{table}: hourly rows sum to {total:,}, table total is {spec['total']:,}.")
    return records


# ---------------------------------------------------------------------------
# Tables E-9..E-12: peak-hour section load; narrative train crowding; E-22 queues
# ---------------------------------------------------------------------------
def parse_section_load_tables(pages: dict[int, str]) -> list[dict[str, Any]]:
    specs = {
        "Table E-9": {"page": 14, "line": "Western Line", "rows": [
            ("Up Direction, Peak hour (8:30 - 9:30)", "Fast + Slow", 143690, "Dadar-Elphinstone Rd"),
            ("Up Direction, Peak hour (8:30 - 9:30)", "Fast Services", 71110, "Dadar-Elphinstone Rd"),
            ("Up Direction, Peak hour (8:30 - 9:30)", "Slow Services", 75029, "Goregaon-Jogeshwari"),
            ("Down Direction, Peak hour (18:00 - 19:00)", "Fast + Slow", 160633, "Dadar- Matunga"),
            ("Down Direction, Peak hour (18:00 - 19:00)", "Fast Services", 89085, "Dadar- Matunga"),
            ("Down Direction, Peak hour (18:00 - 19:00)", "Slow Services", 81844, "Khar road- Andheri"),
        ]},
        "Table E-11": {"page": 19, "line": "Central Line", "rows": [
            ("Up Direction, Peak Hour (8.30-9.30)", "Fast + Slow", 106545, "Vidyavihar- Kurla"),
            ("Up Direction, Peak Hour (8.30-9.30)", "Fast Services", 64353, "Kanjurmarg- Vikroli"),
            ("Up Direction, Peak Hour (8.30-9.30)", "Slow Services", 43581, "Vidyavihar- Kurla"),
            ("Down Direction, Peak Hour (18.30-19.30)", "Fast + Slow", 102926, "Ghatkopar-Vikroli"),
            ("Down Direction, Peak Hour (18.30-19.30)", "Fast Services", 59903, "Ghatkopar-Vikroli"),
            ("Down Direction, Peak Hour (18.30-19.30)", "Slow Services", 49724, "Sion-Kurla"),
        ]},
        "Table E-12": {"page": 19, "line": "Harbour Line", "rows": [
            ("Up Direction, Peak hour (8:00-9:00)", "Main Harbour", 29190, "Vadala Road- Sewri"),
            ("Up Direction, Peak hour (8:00-9:00)", "Trans Harbour", 20500, "Thane-Airoli"),
            ("Down Direction Peak hour (18:30-19:30)", "Main Harbour", 34584, "Sewri-Wadala Road"),
            ("Down Direction Peak hour (18:30-19:30)", "Trans Harbour", 17489, "Ghansoli- Rabale"),
        ]},
        "Table E-10": {"page": 18, "line": "Virar-Dhanu Road Line", "rows": [
            ("Up \nDirection", "ALL", 3181, "Palghar-Kelve \nRoad", "08:30 - 09:30"),
            ("Down \nDirection", "ALL", 5525, "Vangaon-Boisar", "18:00 - 19:00"),
        ]},
    }
    records: list[dict[str, Any]] = []
    for table, spec in specs.items():
        text = collapsed(pages, spec["page"])
        digits_only = re.sub(r"\D", "", text)
        if table.replace("-", "- ") not in text and table not in text:
            raise PdfParseError(f"{table} header not found on PDF page {spec['page']}.")
        for row in spec["rows"]:
            peak, service, value, section = row[0], row[1], row[2], row[3]
            digits = re.sub(r"\s+", "", section)
            if str(value).replace(",", "") not in digits_only:
                raise PdfParseError(f"{table}: value {value:,} for {section} is not present on PDF page {spec['page']}.")
            if re.sub(r"[^A-Za-z]", "", digits.split("-")[0]).lower() not in re.sub(r"[^A-Za-z]", "", text).lower():
                raise PdfParseError(f"{table}: section {section!r} is not present on PDF page {spec['page']}.")
            records.append({
                "source_table": table, "source_page": spec["page"], "line": spec["line"],
                "section": re.sub(r"\s+", " ", section).strip(), "direction": re.sub(r"\s+", " ", peak).strip(),
                "service_type": service, "peak_hour_label": (re.sub(r".*\((.*)\).*", r"\1", peak) if "(" in peak else (row[4] if len(row) > 4 else "peak hour")),
                "measure": "peak_hour_section_load", "unit": "passengers in trains between the section during the peak hour",
                "section_load": value, "observation_type": "derived_from_sample_survey",
                "survey_period_key": "virar_dahanu_road" if "Virar-Dhanu" in spec["line"] else "in_train_boarding_alighting",
            })
    return records


TRAIN_CROWDING: list[dict[str, Any]] = [
    {"line": "Western Line", "service_type": "Fast", "direction": "BOTH", "average_passengers_per_train": 5560, "maximum_passengers_per_train": 5568, "rated_capacity": 3522, "source_page": 24, "source_table": "Narrative iv"},
    {"line": "Western Line", "service_type": "Slow", "direction": "BOTH", "average_passengers_per_train": 4182, "maximum_passengers_per_train": 4573, "rated_capacity": 3522, "source_page": 24, "source_table": "Narrative iv"},
    {"line": "Virar-Dhanu Road Line", "service_type": "ALL", "direction": "UP", "average_passengers_per_train": 1999, "maximum_passengers_per_train": None, "rated_capacity": None, "source_page": 24, "source_table": "Narrative iv"},
    {"line": "Virar-Dhanu Road Line", "service_type": "ALL", "direction": "DOWN", "average_passengers_per_train": 3455, "maximum_passengers_per_train": None, "rated_capacity": None, "source_page": 24, "source_table": "Narrative iv"},
    {"line": "Central Line", "service_type": "Fast", "direction": "UP", "average_passengers_per_train": 4341, "maximum_passengers_per_train": None, "rated_capacity": 3522, "source_page": 24, "source_table": "Narrative iv"},
    {"line": "Central Line", "service_type": "Slow", "direction": "UP", "average_passengers_per_train": 3632, "maximum_passengers_per_train": None, "rated_capacity": 3522, "source_page": 24, "source_table": "Narrative iv"},
    {"line": "Central Line", "service_type": "Slow", "direction": "DOWN", "average_passengers_per_train": 4498, "maximum_passengers_per_train": None, "rated_capacity": 3522, "source_page": 24, "source_table": "Narrative iv"},
    {"line": "Central Line", "service_type": "Fast", "direction": "DOWN", "average_passengers_per_train": 5446, "maximum_passengers_per_train": None, "rated_capacity": 3522, "source_page": 24, "source_table": "Narrative iv"},
    {"line": "Harbour Line", "service_type": "ALL", "direction": "UP", "average_passengers_per_train": 2558, "maximum_passengers_per_train": None, "rated_capacity": 1800, "source_page": 24, "source_table": "Narrative iv"},
    {"line": "Harbour Line", "service_type": "ALL", "direction": "DOWN", "average_passengers_per_train": 2943, "maximum_passengers_per_train": None, "rated_capacity": 1800, "source_page": 24, "source_table": "Narrative iv"},
]
for _row in TRAIN_CROWDING:
    _row.update({
        "measure": "peak_hour_passengers_per_train", "unit": "passengers per train",
        "observation_type": "derived_from_section_load", "survey_period_key": "in_train_boarding_alighting",
        "source_document": "Mumbai Sub-urban Rail Passenger Surveys and Analysis (Executive Summary)",
        "capacity_source": "Rated capacity per train stated as 1,800 (9-car) and 3,522 (12-car); Virar-Dhanu Road rake mix not stated.",
    })

PEAK_HOURS: list[dict[str, Any]] = [
    {"line": "Entire suburban system", "direction": "UP", "peak_hour_label": "08:30-09:30", "peak_hour_passengers": 632000, "source_page": 12},
    {"line": "Entire suburban system", "direction": "DOWN", "peak_hour_label": "18:00-19:00", "peak_hour_passengers": 587437, "source_page": 12},
    {"line": "Western Line", "direction": "UP", "peak_hour_label": "08:30-09:30", "peak_hour_passengers": 306000, "source_page": 12},
    {"line": "Western Line", "direction": "DOWN", "peak_hour_label": "18:00-19:00", "peak_hour_passengers": 275000, "source_page": 12},
    {"line": "Virar-Dhanu Road Line", "direction": "UP", "peak_hour_label": "08:30-09:30", "peak_hour_passengers": 4678, "source_page": 12},
    {"line": "Virar-Dhanu Road Line", "direction": "DOWN", "peak_hour_label": "18:00-19:00", "peak_hour_passengers": 7578, "source_page": 12},
    {"line": "Central Line", "direction": "UP", "peak_hour_label": "08:30-09:30", "peak_hour_passengers": 217000, "source_page": 13},
    {"line": "Central Line", "direction": "DOWN", "peak_hour_label": "18:30-19:30", "peak_hour_passengers": 192000, "source_page": 13},
    {"line": "Harbour Line", "direction": "UP", "peak_hour_label": "08:00-09:00", "peak_hour_passengers": 87000, "source_page": 13},
    {"line": "Harbour Line", "direction": "DOWN", "peak_hour_label": "18:30-19:30", "peak_hour_passengers": 101000, "source_page": 13},
    {"line": "Trans-Harbour Line", "direction": "UP", "peak_hour_label": "08:00-09:00", "peak_hour_passengers": 34000, "source_page": 14},
    {"line": "Trans-Harbour Line", "direction": "DOWN", "peak_hour_label": "18:00-19:00", "peak_hour_passengers": 33000, "source_page": 14},
]
for _row in PEAK_HOURS:
    _row.update({
        "measure": "peak_hour_passengers_travelling", "unit": "passengers per peak hour",
        "observation_type": "derived_from_sample_survey", "source_table": "Figure E-4 to E-9 (narrative values)",
        "survey_period_key": "in_train_boarding_alighting",
        "note": "Values read from the report narrative describing Figures E-4..E-9; figures whose axis labels are only available as raster images are marked derived, not machine-extracted.",
        "source_document": "Mumbai Sub-urban Rail Passenger Surveys and Analysis (Executive Summary)",
    })


QUEUE_LINE_RE = re.compile(r"(Western Line|Virar-Dhanu Road Line|Central Line|Harbour Line) \(as on (\d{2}/\d{2}/\d{4})\)")
QUEUE_ROW_RE = re.compile(r"([A-Za-z][A-Za-z .'\-]{2,26}?)\s+(\d{1,2})\s+(\d{1,2})\s+(\d{1,3})\s+(\d{1,3})(?=\s+[A-Za-z]|\s+VII|\s*$)")
QUEUE_EXPECTED_ROWS = {"Western Line": 13, "Virar-Dhanu Road Line": 8, "Central Line": 14, "Harbour Line": 11}


def parse_queue_tables(pages: dict[int, str]) -> list[dict[str, Any]]:
    """Table E-22: counters and observed queue length, each with a stated survey date."""
    text = collapsed(pages, 28, 29)
    start = text.index("Queue length observed at ticket counters")
    end = text.index("VII.", start)
    block = text[start:end]
    marks = [(m.start(), m.group(1), m.group(2)) for m in QUEUE_LINE_RE.finditer(block)]
    if len(marks) != 4:
        raise PdfParseError(f"Table E-22: found {len(marks)} line/date headers, expected 4.")
    records: list[dict[str, Any]] = []
    for index, (position, line_name, as_on) in enumerate(marks):
        stop = marks[index + 1][0] if index + 1 < len(marks) else len(block)
        segment = block[position:stop]
        year, month, day = as_on.split("/")[2], as_on.split("/")[1], as_on.split("/")[0]
        rows = 0
        for match in QUEUE_ROW_RE.finditer(segment):
            name, total_c, working_c, queue, minutes = match.groups()
            cleaned = re.sub(r"\s+", " ", name).strip()
            if cleaned.split()[0].lower() in {"station", "no", "queue", "total", "average", "time"}:
                continue
            if int(total_c) < int(working_c):
                raise PdfParseError(f"Table E-22 {cleaned}: working counters exceed total counters.")
            rows += 1
            records.append({
                "line": line_name, "station_name": cleaned,
                "total_ticket_counters": int(total_c), "working_ticket_counters": int(working_c),
                "queue_length_persons": int(queue), "average_queue_minutes": int(minutes),
                "observation_date": f"{year}-{month}-{day}",
                "measure": "queue_length_at_ticket_counters", "unit": "persons queued; average minutes in queue",
                "source_table": "Table E-22", "source_page": 28,
                "observation_type": "directly_observed", "direction": "BOTH", "service_type": "ALL",
                "survey_period_key": "queue_observation",
            })
        if rows != QUEUE_EXPECTED_ROWS[line_name]:
            raise PdfParseError(
                f"Table E-22 {line_name}: parsed {rows} station rows, expected {QUEUE_EXPECTED_ROWS[line_name]}."
            )
    return records


# ---------------------------------------------------------------------------
# Table E-13: MODELLED forecast - quarantined, never an observed label
# ---------------------------------------------------------------------------
def parse_modelled_forecasts(pages: dict[int, str]) -> dict[str, Any]:
    text = collapsed(pages, 25)
    start = text.index("Table E- 13")
    end = text.index("STATION ENTRY/EXIT COUNTS", start)
    block = text[start:end]
    rows = re.findall(r"(20\d{2})\s+(\d{1,3}\.\d{1,2})\s+(\d{1,3}\.\d{1,2})\s+(\d{1,3}\.\d{1,2})\s+(\d{1,3}\.\d{1,2})", block)
    if len(rows) != 4:
        raise PdfParseError(f"Table E-13: parsed {len(rows)} forecast rows, expected 4.")
    values = [{"year": int(y), "western_line_lakhs": float(w), "central_line_lakhs": float(c),
               "harbour_line_lakhs": float(h), "total_lakhs": float(t)} for y, w, c, h, t in rows]
    for row in values:
        parts = row["western_line_lakhs"] + row["central_line_lakhs"] + row["harbour_line_lakhs"]
        if abs(parts - row["total_lakhs"]) > 0.02:
            raise PdfParseError(f"Table E-13 {row['year']}: line values sum to {parts:.2f} but total prints {row['total_lakhs']:.2f}.")
    return {
        "classification": "HISTORICAL STUDY MODEL OUTPUT",
        "eligible_as_supervised_label": False,
        "source_table": "Table E-13", "source_page": 25,
        "source_document": "Mumbai Sub-urban Rail Passenger Surveys and Analysis (Executive Summary)",
        "measure": "daily_passenger_trips_od_forecast", "unit": "lakh daily trips",
        "produced_by": "Updated strategic Urban Travel Demand model for Greater Mumbai (originally 2008), base year 2012; 2021 and 2031 peak-hour ODs modelled then expanded to daily",
        "year_semantics": {
            "2012": "model base year (modelled estimate of the surveyed weekday pattern, expanded to a day)",
            "2016": "INTERPOLATED because the report states no model forecast was available for 2016",
            "2021": "model forecast year",
            "2031": "model forecast year",
        },
        "rejection_reason": (
            "These are travel-demand model outputs and interpolations, not counted passengers. Training a "
            "forecast model on 2012->2016->2021->2031 would use model output as ground truth (circular "
            "pseudo-labels) and cannot support a genuine future prediction."
        ),
        "permitted_use": "Retained only as a clearly labelled historical-study benchmark for context and plausibility checks.",
        "values": values,
    }


def parse_pdf(pdf_path) -> dict[str, Any]:
    """Extract every usable observed table plus the quarantined modelled forecast table."""
    import pymupdf

    document = pymupdf.open(str(pdf_path))
    pages = {number: document[number - 1].get_text() for number in range(1, document.page_count + 1)}
    hourly_travel = parse_hourly_travel_tables(pages)
    station_totals = parse_station_entry_exit_tables(pages)
    hourly_profile = parse_hourly_entry_exit_profiles(pages)
    section_load = parse_section_load_tables(pages)
    queues = parse_queue_tables(pages)
    modelled = parse_modelled_forecasts(pages)
    return {
        "hourly_travel": hourly_travel,
        "station_entry_exit_totals": station_totals,
        "hourly_entry_exit_profile": hourly_profile,
        "section_load": section_load,
        "train_crowding": [dict(row) for row in TRAIN_CROWDING],
        "peak_hours": [dict(row) for row in PEAK_HOURS],
        "queue_observations": queues,
        "network_context": NETWORK_CONTEXT,
        "survey_periods": SURVEY_PERIODS,
        "station_scope": STATION_SCOPE,
        "modelled_forecasts": modelled,
        "page_count": document.page_count,
    }
