"""Events 201/206: batched view synchronization, and event 202: Instantiate."""

from dataclasses import dataclass, field

from ..protocol.constants import (
    INST_KEY_DATA,
    INST_KEY_GROUP,
    INST_KEY_INSTANTIATION_ID,
    INST_KEY_LEVEL_PREFIX,
    INST_KEY_POSITION,
    INST_KEY_PREFAB_NAME,
    INST_KEY_ROTATION,
    INST_KEY_TIMESTAMP,
    INST_KEY_VIEW_IDS,
    SYNC_COMPRESSED,
    SYNC_FIRST_VALUE,
    SYNC_NULL_VALUES,
    SYNC_VIEW_ID,
)
from ..protocol.custom_types import Quaternion, Vector3
from ..protocol.gpbinary16 import Hashtable, IntArray, PhotonByte, PhotonShort

IDENTITY = Quaternion(0.0, 0.0, 0.0, 1.0)
ZERO = Vector3(0.0, 0.0, 0.0)


@dataclass
class InstantiateContext:
    prefab_name: str
    view_ids: list[int]
    position: Vector3 = ZERO
    rotation: Quaternion = IDENTITY
    group: int = 0
    data: list = field(default_factory=list)
    timestamp: int = 0
    owner_actor_nr: int = 0
    level_prefix: int = 0

    @property
    def view_id(self) -> int:
        return self.view_ids[0]


def build_instantiate(context: InstantiateContext) -> Hashtable:
    """A zero position, identity rotation or group 0 is omitted, not sent.

    Keys go on the wire as bytes: C# reads them as (byte)0, and an Int32 key of
    the same value would be a different key to a Hashtable."""
    content = Hashtable({PhotonByte(INST_KEY_PREFAB_NAME): context.prefab_name})
    if context.position != ZERO:
        content[PhotonByte(INST_KEY_POSITION)] = context.position
    if context.rotation != IDENTITY:
        content[PhotonByte(INST_KEY_ROTATION)] = context.rotation
    if context.group != 0:
        content[PhotonByte(INST_KEY_GROUP)] = PhotonByte(context.group)
    if len(context.view_ids) > 1:
        content[PhotonByte(INST_KEY_VIEW_IDS)] = IntArray(context.view_ids)
    if context.data:
        content[PhotonByte(INST_KEY_DATA)] = list(context.data)
    if context.level_prefix > 0:
        content[PhotonByte(INST_KEY_LEVEL_PREFIX)] = PhotonShort(context.level_prefix)
    content[PhotonByte(INST_KEY_TIMESTAMP)] = context.timestamp
    content[PhotonByte(INST_KEY_INSTANTIATION_ID)] = context.view_ids[0]
    return content


def parse_instantiate(content: dict, sender_actor_nr: int) -> InstantiateContext:
    instantiation_id = content[INST_KEY_INSTANTIATION_ID]
    view_ids = list(content.get(INST_KEY_VIEW_IDS) or [instantiation_id])
    return InstantiateContext(
        prefab_name=content[INST_KEY_PREFAB_NAME],
        view_ids=view_ids,
        position=content.get(INST_KEY_POSITION, ZERO),
        rotation=content.get(INST_KEY_ROTATION, IDENTITY),
        group=content.get(INST_KEY_GROUP, 0),
        data=list(content.get(INST_KEY_DATA) or []),
        timestamp=content.get(INST_KEY_TIMESTAMP, 0),
        owner_actor_nr=sender_actor_nr,
        level_prefix=content.get(INST_KEY_LEVEL_PREFIX, 0),
    )


def build_view_data(view_id: int, values: list,
                    null_indices: list[int] | None) -> list:
    """One view's slot inside a sync batch: [id, compressed, nulls, *values]."""
    entry = [None] * SYNC_FIRST_VALUE
    entry[SYNC_VIEW_ID] = view_id
    entry[SYNC_COMPRESSED] = null_indices is not None
    entry[SYNC_NULL_VALUES] = IntArray(null_indices) if null_indices else None
    entry.extend(values)
    return entry


def parse_view_data(entry) -> tuple[int, bool, list[int] | None, list]:
    if isinstance(entry, dict):
        view_id = entry.get(SYNC_VIEW_ID, entry.get(0, 0))
        compressed = bool(entry.get(SYNC_COMPRESSED, entry.get(1, False)))
        nulls = entry.get(SYNC_NULL_VALUES, entry.get(2))
        null_indices = list(nulls) if nulls is not None and hasattr(nulls, '__iter__') else None
        values = entry.get(3, [])
        if not isinstance(values, list):
            values = [values]
        return int(view_id), compressed, null_indices, values

    if not isinstance(entry, (list, tuple)):
        try:
            return int(entry), False, None, []
        except (ValueError, TypeError):
            return 0, False, None, []

    if len(entry) == 0:
        return 0, False, None, []

    view_id = int(entry[SYNC_VIEW_ID]) if len(entry) > SYNC_VIEW_ID else 0
    compressed = bool(entry[SYNC_COMPRESSED]) if len(entry) > SYNC_COMPRESSED else False
    nulls = entry[SYNC_NULL_VALUES] if len(entry) > SYNC_NULL_VALUES else None
    null_indices = list(nulls) if nulls is not None and hasattr(nulls, '__iter__') else None
    values = list(entry[SYNC_FIRST_VALUE:]) if len(entry) > SYNC_FIRST_VALUE else []

    return view_id, compressed, null_indices, values


def build_sync_batch(timestamp: int, entries: list,
                     level_prefix: int = 0) -> list:
    """[timestamp, levelPrefix|None, *perViewEntries]"""
    return [timestamp, PhotonShort(level_prefix) if level_prefix > 0 else None,
            *entries]


def parse_sync_batch(batch) -> tuple[int, int, list]:
    """-> (timestamp, level_prefix, per-view entries)"""
    if not isinstance(batch, (list, tuple)) or len(batch) < 2:
        return 0, 0, []
    timestamp = batch[0] if isinstance(batch[0], int) else 0
    level_prefix = batch[1] or 0
    raw_entries = list(batch[2:])

    entries = []
    if raw_entries:
        if isinstance(raw_entries[0], (list, tuple, dict)):
            entries = raw_entries
        else:
            # Flat single-view entry: [view_id, is_compressed, null_values, *values]
            entries = [raw_entries]

    return timestamp, level_prefix, entries
