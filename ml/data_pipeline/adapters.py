"""Public adapter registry for verified observed-demand sources."""
from __future__ import annotations
from pathlib import Path

import pandas as pd
from ml.data_pipeline.source import BMRCL_SOURCE_ID, BMRCLRidershipAdapter, SourceError, SourceAdapter

_ADAPTERS: dict[str, SourceAdapter] = {
    BMRCL_SOURCE_ID: BMRCLRidershipAdapter(),
}


def available_demand_adapters() -> tuple[str, ...]:
    return tuple(sorted(_ADAPTERS))


def load_observed_demand(source_id: str, path: Path) -> tuple[pd.DataFrame, dict]:
    adapter = _ADAPTERS.get(source_id)
    if adapter is None:
        raise SourceError(
            f"No verified observed-demand adapter is registered for '{source_id}'. "
            "Transit schedules and GTFS static feeds are not demand observations."
        )
    return adapter.load(path)
