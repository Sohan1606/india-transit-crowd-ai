"""What an entity id is made of, as declared by the dataset that produced it.

A family whose series are identified by more than one column - a corridor and a station, or a line, an
origin, a destination and a published time slot - must not have that structure restated in front-end or
route code for every city. Registration records the levels and their per-entity values in the dataset
sidecar; this module only reads them back, so the API can publish the choices the data actually supports
and a client can build dependent selectors from them. A family whose entity id is a single station has
no hierarchy at all and keeps behaving exactly as it did.
"""

from __future__ import annotations

import re
from typing import Any

#: The separator `scripts/register_demand_dataset.py` uses when it composes a multi-column entity id.
KEY_SEPARATOR = " / "
_SLOT_LEVEL = re.compile(r"^(time|slot|time_slot|period_slot)$", re.I)


def _source(source_metadata: Any) -> dict[str, Any]:
    return source_metadata if isinstance(source_metadata, dict) else {}


def hierarchy(source_metadata: Any) -> list[dict[str, str]]:
    """Ordered levels of the entity key, parent first, as recorded at registration."""
    levels = _source(source_metadata).get("entity_hierarchy") or []
    return [dict(level) for level in levels if isinstance(level, dict) and level.get("column")]


def entity_attributes(source_metadata: Any) -> dict[str, dict[str, str]]:
    block = _source(source_metadata).get("entity_attributes")
    return block if isinstance(block, dict) else {}


def attributes_for(source_metadata: Any, entity_id: Any) -> dict[str, str]:
    return dict(entity_attributes(source_metadata).get(str(entity_id)) or {})


def published_values(source_metadata: Any, column: str) -> list[str]:
    values = {str(attrs[column]) for attrs in entity_attributes(source_metadata).values() if attrs.get(column) is not None}
    return sorted(values)


def slot_values(source_metadata: Any) -> list[str]:
    """The time slots a family publishes, taken from the slot level of its own entity key."""
    for level in hierarchy(source_metadata):
        if _SLOT_LEVEL.match(level["column"]):
            return published_values(source_metadata, level["column"])
    return []


def metadata_block(source_metadata: Any) -> dict[str, Any]:
    """The fields a family adds to /api/metadata when its data declares a hierarchy.

    `supported_time_slots` is present only when the slot is part of the series identity: a prediction is
    then made for one of those slots, and a request outside them is a request for a series that does not
    exist rather than something to interpolate.
    """
    levels = hierarchy(source_metadata)
    if not levels:
        return {}
    block: dict[str, Any] = {
        "entity_hierarchy": levels,
        "entities_with_declared_attributes": len(entity_attributes(source_metadata)),
        "entity_selection": ("The entity is identified by the ordered levels below; each /api/stations entry "
                             "carries its own attribute values, so a client selects a series by descending the "
                             "levels instead of picking from a flat station list."),
    }
    routes = _source(source_metadata).get("route_context") or {}
    if isinstance(routes, dict) and routes.get("routes"):
        block["route_context"] = routes
    slots = slot_values(source_metadata)
    if slots:
        block["supported_time_slots"] = slots
        block["time_slot_note"] = ("The source publishes demand only at these slots, and the slot is part of the "
                                   "series identity: a forecast is the same slot of a later day, never an "
                                   "interpolation between published slots.")
    return block


def choices_under(source_metadata: Any, requested: Any) -> dict[str, list[str]]:
    """For an unknown composite id, the values that exist beneath the levels the request did name.

    A request that gets this far has named a real line and a real station but an unpublished slot (or a
    destination that is not on that line); returning the published alternatives is more useful - and more
    honest about the data's shape - than a bare 'unknown entity'.
    """
    attrs = entity_attributes(source_metadata)
    levels = [level["column"] for level in hierarchy(source_metadata)]
    parts = [part.strip() for part in str(requested).split(KEY_SEPARATOR)]
    depth = len(parts) - 1
    if not attrs or not levels or KEY_SEPARATOR not in str(requested) or depth < 1 or depth >= len(levels):
        return {}

    def named(key: str, level: int) -> str:
        values = attrs[key]
        if levels[level] in values:
            return str(values[levels[level]])
        pieces = key.split(KEY_SEPARATOR)
        return pieces[level] if level < len(pieces) else ""

    kept = [key for key in attrs if all(named(key, level) == parts[level] for level in range(depth))]
    if not kept:
        return {}
    column = levels[depth]
    return {column: sorted({named(key, depth) for key in kept if named(key, depth)})}
