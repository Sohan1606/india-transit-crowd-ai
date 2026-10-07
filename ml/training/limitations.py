"""Honesty statements generated from a family's own record, never from a remembered city.

A model report is evidence, and a sentence about one dataset must not travel to another. The lists these
helpers build are assembled from the registered family entry, the dataset sidecar written at registration,
the span actually read, and the fit window actually used - so a family is described by what its file says
about itself (including whether its values are observations at all), and a caveat disappears when the
condition it describes is absent.
"""

from __future__ import annotations

from typing import Any

#: Classes whose values are not operator-recorded observations, whatever the column is named.
NON_OBSERVED_CLASSES = ("synthetic_development", "simulated", "modelled_output", "historical_study_output")


def _measure_text(family: dict[str, Any], metadata: dict[str, Any]) -> str:
    measure = str(family.get("measure") or metadata.get("measure") or "passenger demand")
    return measure.replace("_", " ")


def _granularity_text(family: dict[str, Any], metadata: dict[str, Any]) -> str:
    granularity = str(family.get("granularity") or metadata.get("granularity") or "period")
    return {"day": "calendar day", "hour": "hour"}.get(granularity, granularity)


def build(family: dict[str, Any], metadata: dict[str, Any] | None = None, *,
          first_observation: str | None = None, last_observation: str | None = None,
          fit_window: dict[str, Any] | None = None, horizon_text: str | None = None) -> list[str]:
    """Every limitation a reader needs to interpret this family's numbers, stated from its own record."""
    metadata = metadata or {}
    system_id = str(family.get("system_id") or metadata.get("system_id") or "this family")
    operator = str(family.get("operator") or metadata.get("operator") or "the named operator")
    mode = str(family.get("mode") or metadata.get("mode") or "transit")
    dataset_class = str(family.get("dataset_class") or metadata.get("dataset_class") or "observed")
    served_as = str(family.get("served_as") or "production")
    unit = _granularity_text(family, metadata)
    lines: list[str] = [
        f"Only the registered {operator} {mode} family '{system_id}' has a trained model in this project; "
        "no India-wide, network-wide, live, bus, or other-operator prediction is implied by its numbers.",
        f"The target is {_measure_text(family, metadata)} per {unit}. It is not onboard load, occupancy, "
        "capacity utilisation, crowding safety level, or the number of people currently on a train or platform.",
        "No weather, disruption, fare-change, event, transfer, origin-destination or service-frequency "
        "variable is joined to the model beyond the columns this dataset publishes.",
        "Tree and linear models cannot extrapolate beyond the observed feature range; forecasts far past the "
        "data frontier regress toward recent levels rather than inventing new ones.",
    ]
    if last_observation:
        frontier = str(last_observation)[:10]
        lines.append(
            f"The source series ends {frontier}."
            + (f" It begins {str(first_observation)[:10]}." if first_observation else "")
            + " A request for a date or hour after that frontier is returned as a model forecast and labelled "
              "as one; a value inside it is a historical replay of an observation, never a live reading.")
    if dataset_class in NON_OBSERVED_CLASSES or served_as == "demo":
        lines.append(
            f"This family's values are {dataset_class.replace('_', ' ')} data and are served as a "
            f"{served_as}: every response carries the synthetic disclosure, and no metric here is evidence "
            "about real passengers. The architecture is the point; the numbers are illustrative.")
    if fit_window and fit_window.get("rows_used"):
        lines.append(
            f"Models were fitted on {int(fit_window['rows_used']):,} of {int(fit_window.get('rows_available') or 0):,} "
            f"available rows ({int(fit_window.get('requested_days') or 0)} days from "
            f"{str(fit_window.get('first_fitted_timestamp'))[:10]} to {str(fit_window.get('last_fitted_timestamp'))[:10]}) "
            "because a wider fit exceeds the memory of the runner that produced them; the complete stored "
            "history is still served as observations, and every metric above describes that window.")
    if horizon_text:
        lines.append(horizon_text)
    lines.append(
        "No confidence percentage is produced. A missing observation must never be read as zero demand, and "
        "a forecast must never be read as a measurement.")
    return lines
