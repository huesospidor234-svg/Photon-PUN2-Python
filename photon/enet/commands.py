"""ENet command pack/unpack (NCommand.cs).

Header is 12 bytes; some command types carry extra fixed fields before the
payload, which is why `header_length` varies between 12, 16, 20 and 32.
"""

from typing import NamedTuple

from ..protocol.buffer import ByteReader, ByteWriter
from ..protocol.constants import (
    ACK_COMMAND_LENGTH,
    COMMAND_HEADER_LENGTH,
    COMMAND_RESERVED_BYTE,
    CONNECT_COMMAND_LENGTH,
    FRAGMENT_HEADER_LENGTH,
    INTERNAL_CHANNEL,
    CommandFlags,
    CommandType,
)


_UNRELIABLE_HEADER_LENGTH = 16


def header_length(command_type: int) -> int:
    if command_type in (CommandType.ACK, CommandType.ACK_UNSEQUENCED):
        return ACK_COMMAND_LENGTH
    if command_type in (CommandType.SEND_UNRELIABLE, CommandType.SEND_UNSEQUENCED):
        return _UNRELIABLE_HEADER_LENGTH
    if command_type in (CommandType.SEND_FRAGMENT,
                        CommandType.SEND_FRAGMENT_UNSEQUENCED):
        return FRAGMENT_HEADER_LENGTH
    return COMMAND_HEADER_LENGTH


class Command:
    """One ENet command. Mutable — the peer updates the resend bookkeeping."""

    __slots__ = (
        "command_type", "channel_id", "flags", "reserved_byte",
        "reliable_sequence_number", "unreliable_sequence_number",
        "unsequenced_group_number",
        "start_sequence_number", "fragment_count", "fragment_number",
        "total_length", "fragment_offset", "fragments_remaining",
        "ack_reliable_sequence_number", "ack_sent_time",
        "payload",
        "sent_time", "sent_count", "round_trip_timeout", "timeout_time",
    )

    def __init__(self, command_type: int, channel_id: int = 0,
                 payload: bytes = b"", flags: int = CommandFlags.RELIABLE):
        self.command_type = command_type
        self.channel_id = channel_id
        self.flags = flags
        self.reserved_byte = COMMAND_RESERVED_BYTE
        self.reliable_sequence_number = 0
        self.unreliable_sequence_number = 0
        self.unsequenced_group_number = 0
        self.start_sequence_number = 0
        self.fragment_count = 0
        self.fragment_number = 0
        self.total_length = 0
        self.fragment_offset = 0
        self.fragments_remaining = 0
        self.ack_reliable_sequence_number = 0
        self.ack_sent_time = 0
        self.payload = payload
        self.sent_time = 0
        self.sent_count = 0
        self.round_trip_timeout = 0
        self.timeout_time = 0

    @property
    def is_reliable(self) -> bool:
        return bool(self.flags & CommandFlags.RELIABLE)

    @property
    def is_unsequenced(self) -> bool:
        return bool(self.flags & CommandFlags.UNRELIABLE_UNSEQUENCED)

    @property
    def size(self) -> int:
        return header_length(self.command_type) + len(self.payload)

    def pack(self) -> bytes:
        w = ByteWriter()
        w.u8(self.command_type)
        w.u8(self.channel_id)
        w.u8(self.flags)
        w.u8(self.reserved_byte)
        w.i32(self.size)
        w.i32(self.reliable_sequence_number)

        ct = self.command_type
        if ct in (CommandType.ACK, CommandType.ACK_UNSEQUENCED):
            w.i32(self.ack_reliable_sequence_number)
            w.i32(self.ack_sent_time)
        elif ct == CommandType.SEND_UNRELIABLE:
            w.i32(self.unreliable_sequence_number)
        elif ct == CommandType.SEND_UNSEQUENCED:
            w.i32(self.unsequenced_group_number)
        elif ct in (CommandType.SEND_FRAGMENT,
                    CommandType.SEND_FRAGMENT_UNSEQUENCED):
            w.i32(self.start_sequence_number)
            w.i32(self.fragment_count)
            w.i32(self.fragment_number)
            w.i32(self.total_length)
            w.i32(self.fragment_offset)

        w.raw(self.payload)
        return w.to_bytes()

    def __repr__(self):
        return (f"Command(type={self.command_type}, ch={self.channel_id}, "
                f"flags={self.flags}, relSeq={self.reliable_sequence_number}, "
                f"payload={len(self.payload)}B)")


def unpack_command(r: ByteReader) -> Command:
    command_type = r.u8()
    channel_id = r.u8()
    flags = r.u8()
    reserved = r.u8()
    size = r.i32()
    reliable_seq = r.i32()

    if size < COMMAND_HEADER_LENGTH:
        raise ValueError(f"command size {size} below header length")

    cmd = Command(command_type, channel_id, b"", flags)
    cmd.reserved_byte = reserved
    cmd.reliable_sequence_number = reliable_seq

    payload_length = 0
    if command_type in (CommandType.ACK, CommandType.ACK_UNSEQUENCED):
        cmd.ack_reliable_sequence_number = r.i32()
        cmd.ack_sent_time = r.i32()
    elif command_type in (CommandType.SEND_RELIABLE,
                          CommandType.SEND_RELIABLE_UNSEQUENCED):
        payload_length = size - COMMAND_HEADER_LENGTH
    elif command_type == CommandType.SEND_UNRELIABLE:
        cmd.unreliable_sequence_number = r.i32()
        payload_length = size - _UNRELIABLE_HEADER_LENGTH
    elif command_type == CommandType.SEND_UNSEQUENCED:
        cmd.unsequenced_group_number = r.i32()
        payload_length = size - _UNRELIABLE_HEADER_LENGTH
    elif command_type in (CommandType.SEND_FRAGMENT,
                          CommandType.SEND_FRAGMENT_UNSEQUENCED):
        cmd.start_sequence_number = r.i32()
        cmd.fragment_count = r.i32()
        cmd.fragment_number = r.i32()
        cmd.total_length = r.i32()
        cmd.fragment_offset = r.i32()
        cmd.fragments_remaining = cmd.fragment_count
        payload_length = size - FRAGMENT_HEADER_LENGTH
    else:
        # VERIFY_CONNECT, PING, DISCONNECT, SERVER_TIME: body is opaque here.
        payload_length = size - COMMAND_HEADER_LENGTH

    if payload_length < 0:
        raise ValueError(f"negative payload length for command type {command_type}")
    if payload_length:
        cmd.payload = r.raw(payload_length)
    return cmd


def make_ack(command_to_ack: Command, sent_time: int) -> Command:
    """ACK carries its own relSeq=0; the acked seq goes in the body."""
    ack_type = (CommandType.ACK_UNSEQUENCED if command_to_ack.is_unsequenced
                else CommandType.ACK)
    ack = Command(ack_type, command_to_ack.channel_id, b"", CommandFlags.UNRELIABLE)
    ack.reliable_sequence_number = 0
    ack.ack_reliable_sequence_number = command_to_ack.reliable_sequence_number
    ack.ack_sent_time = sent_time
    return ack


def make_connect(mtu: int, channel_count: int) -> Command:
    """CONNECT's 32-byte body is a fixed literal (NCommand.cs:157-176)."""
    body = bytearray(32)
    body[2] = (mtu >> 8) & 0xFF
    body[3] = mtu & 0xFF
    body[6] = 128          # 0x00008000 window size
    body[11] = channel_count
    body[22] = 19          # 0x1388 = 5000
    body[23] = 136
    body[27] = 2
    body[31] = 2
    cmd = Command(CommandType.CONNECT, INTERNAL_CHANNEL, bytes(body),
                  CommandFlags.RELIABLE)
    assert cmd.size == CONNECT_COMMAND_LENGTH
    return cmd


class VerifyConnect(NamedTuple):
    peer_id: int


def parse_verify_connect(cmd: Command) -> VerifyConnect:
    """First 2 bytes of the VERIFY_CONNECT body are the assigned peer ID."""
    if len(cmd.payload) < 2:
        raise ValueError("VERIFY_CONNECT body too short")
    return VerifyConnect(int.from_bytes(cmd.payload[:2], "big", signed=True))
