"""Message envelope — the 2-byte header wrapping every operation/event payload."""

from typing import NamedTuple

from .constants import ENCRYPTION_FLAG, MESSAGE_MAGIC, MESSAGE_MAGIC_ALT, MessageType


class ParsedMessage(NamedTuple):
    msg_type: int
    encrypted: bool
    body: bytes


def wrap_message(msg_type: int, body: bytes, encrypted: bool = False) -> bytes:
    type_byte = msg_type | ENCRYPTION_FLAG if encrypted else msg_type
    return bytes((MESSAGE_MAGIC, type_byte)) + body


def parse_message(data: bytes) -> ParsedMessage:
    if len(data) < 2:
        raise ValueError(f"message too short: {len(data)} bytes")
    magic = data[0]
    if magic not in (MESSAGE_MAGIC, MESSAGE_MAGIC_ALT):
        raise ValueError(f"bad message magic 0x{magic:02X}")
    type_byte = data[1]
    return ParsedMessage(type_byte & 0x7F, bool(type_byte & ENCRYPTION_FLAG), data[2:])


__all__ = ["MessageType", "ParsedMessage", "parse_message", "wrap_message"]
