"""India transit discovery catalog with prediction availability tied to evidence."""
from __future__ import annotations
from copy import deepcopy
from typing import Any

from ml.data_pipeline.source import BMRCL_SYSTEM_ID


_SYSTEMS: list[dict[str, Any]] = [
    {
        "system_id": BMRCL_SYSTEM_ID,
        "system_name": "Namma Metro",
        "city": "Bengaluru",
        "state": "Karnataka",
        "mode": "METRO",
        "operator": "BMRCL",
        "prediction_available": True,
        "prediction_status": "VERIFIED_OBSERVED_DEMAND",
        "observed_demand_status": "Verified station-wise hourly boardings; bundled historical snapshot only.",
        "demand_source_url": "https://github.com/Vonter/bmrcl-ridership-hourly",
        "network_reference_url": "https://github.com/Vonter/bmrcl-ridership-hourly",
        "network_reference_kind": "station names included in verified observed-demand source",
        "network_reference_note": "No live train positions, line map, occupancy or current timetable is bundled.",
        "prediction_unavailable_reason": None,
    },
    {
        "system_id": "delhi-dtc-bus",
        "system_name": "Delhi city buses",
        "city": "Delhi",
        "state": "Delhi",
        "mode": "BUS",
        "operator": "DTC / Delhi Transport Department",
        "prediction_available": False,
        "prediction_status": "UNAVAILABLE_NO_VERIFIED_DEMAND_MODEL",
        "observed_demand_status": "No verified, reusable city-bus passenger-count history is bundled.",
        "demand_source_url": "https://otd.delhi.gov.in/data/static/",
        "network_reference_url": "https://otd.delhi.gov.in/data/static/",
        "network_reference_kind": "official static GTFS bus schedules, routes and stops",
        "network_reference_note": "OTD lists static files for download (bus times are estimates); basic information is required and its terms require users to state purpose/manner/time and may require permission. GTFS is not observed demand. Real-time APIs require authorization/private-key access; none is assumed here.",
        "prediction_unavailable_reason": "No compatible, verified observed passenger-demand history and trained DTC model are available. Public static GTFS cannot be used as a demand target.",
    },
    {
        "system_id": "delhi-dmrc-metro",
        "system_name": "Delhi Metro",
        "city": "Delhi",
        "state": "Delhi",
        "mode": "METRO",
        "operator": "DMRC",
        "prediction_available": False,
        "prediction_status": "UNAVAILABLE_NO_VERIFIED_DEMAND_MODEL",
        "observed_demand_status": "Station-entry/exit history is not bundled; access to Delhi Transport Stack footfall data is approval-based.",
        "demand_source_url": "https://otd.delhi.gov.in/data/staticDMRC/",
        "network_reference_url": "https://otd.delhi.gov.in/data/staticDMRC/",
        "network_reference_kind": "official static DMRC GTFS schedules, routes and stations",
        "network_reference_note": "OTD static DMRC files support discovery only; its terms govern reuse. Separate hourly station-footfall data on Delhi Transport Stack is approval-based. No private-key access, real-time positions or demand values are assumed.",
        "prediction_unavailable_reason": "No public, verified station-hour demand dataset and trained DMRC model are available in this build. Static DMRC GTFS is not demand.",
    },
    {
        "system_id": "mumbai-best-bus",
        "system_name": "BEST city buses",
        "city": "Mumbai",
        "state": "Maharashtra",
        "mode": "BUS",
        "operator": "BEST",
        "prediction_available": False,
        "prediction_status": "UNAVAILABLE_NO_VERIFIED_DEMAND_MODEL",
        "observed_demand_status": "No compatible observed passenger-count dataset is bundled.",
        "demand_source_url": "https://github.com/croyla/mumbai-gtfs",
        "network_reference_url": "https://github.com/croyla/mumbai-gtfs",
        "network_reference_kind": "community GTFS schedule reference (BEST/TMT/KDMT)",
        "network_reference_note": "The repository is publicly accessible and its LICENSE is MIT-0, but the upstream source and separate data-rights grant are not documented in the feed README. Schedules are not observed ridership; no GTFS file is redistributed here.",
        "prediction_unavailable_reason": "No verified observed passenger-demand history is available; the community GTFS reference is schedule-only and its provenance needs review.",
    },
    {
        "system_id": "mumbai-tmt-bus",
        "system_name": "Thane city buses",
        "city": "Thane / Mumbai Metropolitan Region",
        "state": "Maharashtra",
        "mode": "BUS",
        "operator": "TMT",
        "prediction_available": False,
        "prediction_status": "UNAVAILABLE_NO_VERIFIED_DEMAND_MODEL",
        "observed_demand_status": "No compatible observed passenger-count dataset is bundled.",
        "demand_source_url": "https://github.com/croyla/mumbai-gtfs",
        "network_reference_url": "https://github.com/croyla/mumbai-gtfs",
        "network_reference_kind": "community GTFS schedule reference (BEST/TMT/KDMT)",
        "network_reference_note": "The repository is publicly accessible and its LICENSE is MIT-0, but the upstream source and separate data-rights grant are not documented in the feed README. Schedules are not observed ridership; no GTFS file is redistributed here.",
        "prediction_unavailable_reason": "No verified observed passenger-demand history is available; the community GTFS reference is schedule-only and its provenance needs review.",
    },
    {
        "system_id": "mumbai-kdmt-bus",
        "system_name": "Kalyan-Dombivli city buses",
        "city": "Kalyan-Dombivli",
        "state": "Maharashtra",
        "mode": "BUS",
        "operator": "KDMT",
        "prediction_available": False,
        "prediction_status": "UNAVAILABLE_NO_VERIFIED_DEMAND_MODEL",
        "observed_demand_status": "No compatible observed passenger-count dataset is bundled.",
        "demand_source_url": "https://github.com/croyla/mumbai-gtfs",
        "network_reference_url": "https://github.com/croyla/mumbai-gtfs",
        "network_reference_kind": "community GTFS schedule reference (BEST/TMT/KDMT)",
        "network_reference_note": "The repository is publicly accessible and its LICENSE is MIT-0, but the upstream source and separate data-rights grant are not documented in the feed README. Schedules are not observed ridership; no GTFS file is redistributed here.",
        "prediction_unavailable_reason": "No verified observed passenger-demand history is available; the community GTFS reference is schedule-only and its provenance needs review.",
    },
    {
        "system_id": "pune-pmpml-bus",
        "system_name": "PMPML city buses",
        "city": "Pune",
        "state": "Maharashtra",
        "mode": "BUS",
        "operator": "PMPML",
        "prediction_available": False,
        "prediction_status": "UNAVAILABLE_NO_VERIFIED_DEMAND_MODEL",
        "observed_demand_status": "No verified passenger-count history is bundled.",
        "demand_source_url": "https://github.com/croyla/pmpml-gtfs/",
        "network_reference_url": "https://github.com/croyla/pmpml-gtfs/",
        "network_reference_kind": "community GTFS generated from Apli-PMPML/Chartr API data",
        "network_reference_note": "The public repository carries an MIT No Attribution code license and documents a public API key value, but a separate authoritative feed-data reuse grant is not established. Routes/stops/schedules support discovery only, not demand or occupancy; no feed is redistributed here.",
        "prediction_unavailable_reason": "No compatible, verified observed passenger-demand history and trained PMPML model are available. GTFS schedules are not a demand target.",
    },
    {
        "system_id": "chennai-cmrl-metro",
        "system_name": "Chennai Metro",
        "city": "Chennai",
        "state": "Tamil Nadu",
        "mode": "METRO",
        "operator": "CMRL",
        "prediction_available": False,
        "prediction_status": "UNAVAILABLE_NO_COMPATIBLE_STATION_HOUR_HISTORY",
        "observed_demand_status": "Monthly system-total ridership is publicly catalogued; the official passenger-flow portal is a visualization, with bulk historical reuse unresolved.",
        "demand_source_url": "https://data.opencity.in/dataset/chennai-metro-monthly-usage-data/resource/c63ef5a0-e7d2-49b3-9c88-5ca5ce309fcf",
        "network_reference_url": "https://commuters-data.chennaimetrorail.org/passengerflow",
        "network_reference_kind": "official passenger-flow visualization; no bulk source integrated",
        "network_reference_note": "Monthly system totals are too coarse for a next-hour station model. Dashboard history and reuse rights require confirmation.",
        "prediction_unavailable_reason": "No verified, reusable station-hour observation file is available for this model; monthly system totals are insufficient for next-hour station predictions.",
    },
    {
        "system_id": "hyderabad-hmrl-metro",
        "system_name": "Hyderabad Metro",
        "city": "Hyderabad",
        "state": "Telangana",
        "mode": "METRO",
        "operator": "HMRL",
        "prediction_available": False,
        "prediction_status": "UNAVAILABLE_NO_VERIFIED_DEMAND_MODEL",
        "observed_demand_status": "No compatible observed passenger-count history is bundled.",
        "demand_source_url": "https://hmrl.co.in/hyderabad-metro-rail-data-goes-live-on-google-maps/",
        "network_reference_url": "https://hmrl.co.in/hyderabad-metro-rail-data-goes-live-on-google-maps/",
        "network_reference_kind": "official GTFS schedule/network announcement (HMRL / Telangana)",
        "network_reference_note": "HMRL reported publication of a 3-corridor GTFS covering 118 stations and 6,958 weekly scheduled trips; the announcement does not specify the feed's reuse license or pinned revision. Schedule discovery only—not observed demand or live occupancy.",
        "prediction_unavailable_reason": "No verified observed passenger-demand history and trained HMRL model are available. GTFS schedules are not a demand target.",
    },
    {
        "system_id": "kochi-kmrl-metro",
        "system_name": "Kochi Metro",
        "city": "Kochi",
        "state": "Kerala",
        "mode": "METRO",
        "operator": "KMRL",
        "prediction_available": False,
        "prediction_status": "UNAVAILABLE_NO_VERIFIED_DEMAND_MODEL",
        "observed_demand_status": "No compatible observed passenger-count history is bundled.",
        "demand_source_url": "https://kochimetro.org/open-data/",
        "network_reference_url": "https://kochimetro.org/open-data/",
        "network_reference_kind": "official GTFS-static routes, schedules and fares",
        "network_reference_note": "Official GTFS-static routes, schedules and fares are available under KMRL's posted terms: free use/adaptation/redistribution (including commercial use) with required KMRL attribution and no endorsement claim. Schedules are not observed passenger demand.",
        "prediction_unavailable_reason": "No verified observed passenger-demand history and trained KMRL model are available. GTFS schedules are not a demand target.",
    },
]

OBSERVED_DEMAND_CANDIDATES: list[dict[str, Any]] = [
    {
        "city": "Mumbai",
        "system": "Monorail / Metro 2A and 7",
        "source_title": "MMRDA daily ridership: Metro 2A, Metro 7 and Monorail (2024-10-01 to 2025-09-21)",
        "url": "https://www.data.gov.in/resource/ridership-data-monorail-01-10-2024-21-09-2025",
        "published_granularity": "daily line-level fields (date, line, Paper QR, NCMC/other-trip categories, total ridership)",
        "access_status": "data.gov.in page reviewed; 13 KB CSV download is listed and granularity is Daily. OGD terms point to the resource license metadata/GODL-India, but a resource-specific license field was not visible in the reviewed view; recheck before redistribution.",
        "forecast_suitability": "candidate for a separate daily line-level analysis only; no station identifier or hourly resolution for this next-hour station model", 
        "prediction_enabled": False,
    },
    {
        "city": "Chennai",
        "system": "CMRL",
        "source_title": "OpenCity CMRL monthly usage data",
        "url": "https://data.opencity.in/dataset/chennai-metro-monthly-usage-data/resource/c63ef5a0-e7d2-49b3-9c88-5ca5ce309fcf",
        "published_granularity": "monthly system totals from 2023-24 through June 2026",
        "access_status": "active 2.9 KB CSV listed; resource metadata shows license 'Other (Public Domain)'. Re-fetch and validate the file and metadata before ingestion.",
        "forecast_suitability": "monthly system trend/total analysis only; no station keys and too coarse for hourly station forecasts",
        "prediction_enabled": False,
    },
    {
        "city": "Delhi",
        "system": "DMRC",
        "source_title": "Delhi Metro: Hourly Footfall data at metro stations — Delhi Transport Stack",
        "url": "https://delhi.transportstack.in/data-services",
        "published_granularity": "hourly station entry and exit counts per catalogue description; file is listed as approval-based Excel",
        "access_status": "approval-based; not downloaded. Dataset-specific reuse terms and a reproducible export require confirmation; no API/private key is assumed.",
        "forecast_suitability": "promising station-hour candidate only after authorized access, rights review, source audit and complete station/time coverage validation",
        "prediction_enabled": False,
    },
]


SYSTEM_CATALOG = {item["system_id"]: item for item in _SYSTEMS}


def list_systems(service=None) -> list[dict[str, Any]]:
    """Return discovery metadata with availability derived from loaded artifacts."""
    items = deepcopy(_SYSTEMS)
    for item in items:
        if item["system_id"] == BMRCL_SYSTEM_ID:
            ready = bool(service and service.ready and service.system_id == BMRCL_SYSTEM_ID)
            item["prediction_available"] = ready
            item["prediction_status"] = "AVAILABLE" if ready else "UNAVAILABLE_ARTIFACT_OR_DATA_NOT_READY"
            item["prediction_unavailable_reason"] = None if ready else (
                service.unavailable_detail if service else "Model artifacts and normalized observed-demand data are not loaded."
            )
            item["station_count"] = len(service.stations) if ready else None
            item["data_period"] = service.metadata()["dataset"]["source_periods"] if ready else []
        else:
            item["station_count"] = None
            item["data_period"] = []
    return items


def known_system(system_id: str) -> dict[str, Any] | None:
    item = SYSTEM_CATALOG.get(str(system_id))
    return deepcopy(item) if item else None
