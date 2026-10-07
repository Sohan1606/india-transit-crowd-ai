"""Tests for the data-declared entity hierarchy: an API contract, not a per-city list.

A family whose series are identified by several columns (corridor + station, or line + origin +
destination + published slot) publishes those levels from its own dataset sidecar. These tests pin the
generic behaviour: levels are read back as declared, per-entity attributes reach the discovery endpoint,
a slot level becomes the family's published time slots, and an id that names real parents but an
unpublished final level is refused with the values that do exist.
"""

from __future__ import annotations

import json

import pytest

from backend.app.inference import hierarchy


SIDECAR = {
    "entity_hierarchy": [
        {"column": "Metro_Line", "label": "Metro Line"},
        {"column": "Source_Station", "label": "Source Station"},
        {"column": "Destination_Station", "label": "Destination Station"},
        {"column": "Time", "label": "Time"},
    ],
    "entity_attributes": {
        "Line 1 / Versova / Ghatkopar / 08:00:00": {
            "Metro_Line": "Line 1", "Line_Name": "Versova-Andheri-Ghatkopar",
            "Operational_Status": "Operational", "Source_Station": "Versova",
            "Destination_Station": "Ghatkopar", "Time": "08:00:00", "Stations_On_Line": "12",
            "Travel_Direction": "Versova -> Ghatkopar"},
        "Line 1 / Versova / Ghatkopar / 18:00:00": {
            "Metro_Line": "Line 1", "Line_Name": "Versova-Andheri-Ghatkopar",
            "Operational_Status": "Operational", "Source_Station": "Versova",
            "Destination_Station": "Ghatkopar", "Time": "18:00:00", "Stations_On_Line": "12",
            "Travel_Direction": "Versova -> Ghatkopar"},
        "Line 2B / NDCC / Diamond Metro / 08:00:00": {
            "Metro_Line": "Line 2B", "Line_Name": "NDMC Metro",
            "Operational_Status": "Under Construction", "Source_Station": "NDCC",
            "Destination_Station": "Diamond Metro", "Time": "08:00:00", "Stations_On_Line": "20",
            "Travel_Direction": "NDCC -> Diamond Metro"},
    },
}


def test_levels_are_returned_in_the_order_the_dataset_declared():
    assert [level["column"] for level in hierarchy.hierarchy(SIDECAR)] == [
        "Metro_Line", "Source_Station", "Destination_Station", "Time"]


def test_attributes_attach_to_the_entity_id_that_names_them():
    attrs = hierarchy.attributes_for(SIDECAR, "Line 1 / Versova / Ghatkopar / 18:00:00")
    assert attrs["Operational_Status"] == "Operational"
    assert attrs["Time"] == "18:00:00"
    assert attrs["Travel_Direction"] == "Versova -> Ghatkopar"
    assert hierarchy.attributes_for(SIDECAR, "no such entity") == {}


def test_the_slot_level_of_the_key_is_the_family_published_time_slots():
    block = hierarchy.metadata_block(SIDECAR)
    assert block["supported_time_slots"] == ["08:00:00", "18:00:00"]
    assert block["entities_with_declared_attributes"] == 3
    assert "same slot of a later day" in block["time_slot_note"]


def test_a_family_without_a_hierarchy_publishes_nothing_new():
    assert hierarchy.hierarchy({"column_mapping": {"entity": "station_id"}}) == []
    assert hierarchy.metadata_block({"column_mapping": {}}) == {}
    assert hierarchy.choices_under({}, "anything") == {}


def test_an_unpublished_final_level_is_answered_with_the_values_that_exist():
    alternatives = hierarchy.choices_under(SIDECAR, "Line 1 / Versova / Ghatkopar / 07:00:00")
    assert alternatives == {"Time": ["08:00:00", "18:00:00"]}
    # A request that names no recognised level at all is not given advice about a level it did not name.
    assert hierarchy.choices_under(SIDECAR, "Nowhere") == {}
    # A complete id that simply does not exist has no deeper level to enumerate.
    assert hierarchy.choices_under(SIDECAR, "Line 9 / A / B / 08:00:00") == {}


def test_a_flat_key_cannot_be_cascaded():
    flat = {"entity_attributes": {"CSMT": {"Source_Station": "CSMT"}}}
    assert hierarchy.choices_under(flat, "CSMT / 08:00:00") == {}


def test_the_sidecar_is_the_only_source_of_these_fields(tmp_path):
    """Whatever the file says is published; an absent or empty sidecar degrades to the old contract."""
    sidecar = tmp_path / "family_demand_timeseries.metadata.json"
    sidecar.write_text(json.dumps(SIDECAR), encoding="utf-8")
    assert hierarchy.metadata_block(json.loads(sidecar.read_text(encoding="utf-8")))["supported_time_slots"] == [
        "08:00:00", "18:00:00"]
    assert hierarchy.metadata_block({}) == {}
    assert hierarchy.metadata_block(None) == {}


@pytest.mark.parametrize("column", ["Time", "time_slot", "Slot"])
def test_a_slot_level_is_recognised_whatever_the_file_calls_it(column):
    sidecar = {"entity_hierarchy": [{"column": column, "label": "X"}],
               "entity_attributes": {"a / 08:00": {column: "08:00"}, "a / 18:00": {column: "18:00"}}}
    assert hierarchy.metadata_block(sidecar)["supported_time_slots"] == ["08:00", "18:00"]
