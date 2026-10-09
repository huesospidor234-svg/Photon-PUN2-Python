"""Event 200: RPC call encoding and dispatch."""

from dataclasses import dataclass

from ..protocol.constants import (
    RPC_KEY_METHOD_NAME,
    RPC_KEY_PARAMETERS,
    RPC_KEY_PREFIX,
    RPC_KEY_SHORTCUT,
    RPC_KEY_TIMESTAMP,
    RPC_KEY_VIEW_ID,
)
from ..protocol.gpbinary16 import Hashtable, PhotonByte, PhotonShort


@dataclass
class RpcInfo:
    sender_actor_nr: int
    timestamp: int
    view_id: int


def build_rpc(view_id: int, method_name: str, args: list | None, *,
              timestamp: int, level_prefix: int = 0,
              shortcut: int | None = None) -> Hashtable:
    """Omitted keys are how PUN keeps RPCs small; the server tolerates neither
    a null prefix nor an empty parameter array, so both are dropped entirely.

    The keys must go on the wire as bytes: C# looks them up as (byte)0, and an
    Int32 key of the same value is a different key to a Hashtable."""
    content = Hashtable({PhotonByte(RPC_KEY_VIEW_ID): view_id})
    if level_prefix > 0:
        content[PhotonByte(RPC_KEY_PREFIX)] = PhotonShort(level_prefix)
    content[PhotonByte(RPC_KEY_TIMESTAMP)] = timestamp
    if shortcut is not None:
        content[PhotonByte(RPC_KEY_SHORTCUT)] = PhotonByte(shortcut)
    else:
        content[PhotonByte(RPC_KEY_METHOD_NAME)] = method_name
    if args:
        content[PhotonByte(RPC_KEY_PARAMETERS)] = list(args)
    return content


def parse_rpc(content: dict) -> tuple[int, str | None, int | None, list, int]:
    """-> (view_id, method_name, shortcut, args, timestamp)"""
    return (content[RPC_KEY_VIEW_ID],
            content.get(RPC_KEY_METHOD_NAME),
            content.get(RPC_KEY_SHORTCUT),
            list(content.get(RPC_KEY_PARAMETERS) or []),
            content.get(RPC_KEY_TIMESTAMP, 0))


def dispatch_rpc(views, rpc_registry, content: dict, sender_actor_nr: int):
    view_id, method_name, shortcut, args, timestamp = parse_rpc(content)
    view = views.get(view_id)
    if view is None:
        return None
    resolved = rpc_registry.resolve(method_name, shortcut)
    if resolved is None:
        return None
    return view.call_rpc(resolved, args, RpcInfo(sender_actor_nr, timestamp, view_id))
