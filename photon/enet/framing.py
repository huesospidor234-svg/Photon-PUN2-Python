"""Datagram framing — the 12-byte UDP header wrapping a batch of commands."""

import zlib
from typing import NamedTuple

from ..protocol.buffer import ByteReader
from ..protocol.constants import (
    DATAGRAM_HEADER_LENGTH,
    FLAG_CRC_ENABLED,
    FLAG_PLAIN,
)
from .commands import Command, unpack_command


def crc32_photon(data: bytes) -> int:
    """Photon omits the final XOR that zlib.crc32 applies (SupportClass.CalculateCrc)."""
    return zlib.crc32(data) ^ 0xFFFFFFFF


class Datagram(NamedTuple):
    peer_id: int
    challenge: int
    server_sent_time: int
    commands: list[Command]


def pack_datagram(peer_id: int, challenge: int, sent_time: int,
                  commands: list[Command], crc_enabled: bool = False) -> bytes:
    body = b"".join(cmd.pack() for cmd in commands)
    header = bytearray(DATAGRAM_HEADER_LENGTH + (4 if crc_enabled else 0))
    header[0:2] = (peer_id & 0xFFFF).to_bytes(2, "big")
    header[2] = FLAG_CRC_ENABLED if crc_enabled else FLAG_PLAIN
    header[3] = len(commands)
    header[4:8] = (sent_time & 0xFFFFFFFF).to_bytes(4, "big")
    header[8:12] = (challenge & 0xFFFFFFFF).to_bytes(4, "big")

    if not crc_enabled:
        return bytes(header) + body

    # CRC is computed over the whole datagram with its own slot zeroed.
    full = bytes(header) + body
    header[12:16] = (crc32_photon(full) & 0xFFFFFFFF).to_bytes(4, "big")
    return bytes(header) + body


def unpack_datagram(data: bytes, expected_challenge: int | None = None) -> Datagram:
    if len(data) < DATAGRAM_HEADER_LENGTH:
        raise ValueError(f"datagram too short: {len(data)} bytes")

    peer_id = int.from_bytes(data[0:2], "big", signed=True)
    flags = data[2]
    if flags == 1:
        raise ValueError("datagram-level encryption is not supported")
    command_count = data[3]
    server_sent_time = int.from_bytes(data[4:8], "big", signed=True)
    challenge = int.from_bytes(data[8:12], "big", signed=True)

    if expected_challenge is not None and challenge != expected_challenge:
        raise ValueError(f"challenge mismatch: got {challenge}, want {expected_challenge}")

    offset = DATAGRAM_HEADER_LENGTH
    if flags == FLAG_CRC_ENABLED:
        received = int.from_bytes(data[12:16], "big", signed=False)
        zeroed = data[:12] + b"\x00\x00\x00\x00" + data[16:]
        if crc32_photon(zeroed) != received:
            raise ValueError("CRC mismatch")
        offset += 4

    r = ByteReader(data, offset)
    commands = [unpack_command(r) for _ in range(command_count)]
    return Datagram(peer_id, challenge, server_sent_time, commands)
