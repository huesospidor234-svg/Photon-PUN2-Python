"""Sans-IO ENet peer core (EnetPeer.cs).

Owns all reliability, RTT and fragmentation logic. Knows nothing about
sockets or asyncio: time arrives as `now_ms`, datagrams arrive as bytes and
leave via `take_outgoing()`. That makes byte-for-byte tests possible with a
fake clock and an injected challenge.
"""

from collections import deque
from enum import IntEnum
from typing import Callable

from ..protocol.constants import (
    APP_ID_LENGTH,
    CHANNEL_COUNT,
    CLIENT_SDK_ID,
    CLIENT_VERSION,
    DISCONNECT_TIMEOUT,
    FRAGMENT_PAYLOAD_LENGTH,
    INITIAL_RESEND_TIME_MAX,
    INITIAL_ROUND_TRIP_TIME,
    INITIAL_ROUND_TRIP_TIME_VARIANCE,
    INTERNAL_CHANNEL,
    MESSAGE_MAGIC,
    MTU,
    PEER_ID_UNASSIGNED,
    PING_INTERVAL,
    PROTOCOL_VERSION,
    QUICK_RESEND_ATTEMPTS,
    SEND_WINDOW_SIZE,
    SENT_COUNT_ALLOWANCE,
    CommandFlags,
    CommandType,
    MessageType,
)
from .channel import EnetChannel
from .commands import Command, make_ack, make_connect, parse_verify_connect
from .framing import pack_datagram, unpack_datagram


def _trunc_div(a: int, b: int) -> int:
    """C# integer division truncates toward zero; Python's // floors."""
    q = abs(a) // abs(b)
    return -q if (a < 0) != (b < 0) else q


class ConnectionState(IntEnum):
    DISCONNECTED = 0
    CONNECTING = 1
    CONNECTED = 3
    DISCONNECTING = 4
    ZOMBIE = 5


class StatusCode(IntEnum):
    CONNECT = 1024
    DISCONNECT = 1025
    TIMEOUT_DISCONNECT = 1040
    DISCONNECT_BY_SERVER_TIMEOUT = 1041
    DISCONNECT_BY_SERVER_USER_LIMIT = 1042
    DISCONNECT_BY_SERVER_LOGIC = 1043
    DISCONNECT_BY_SERVER_REASON_UNKNOWN = 1039


_DISCONNECT_REASONS = {
    1: StatusCode.DISCONNECT_BY_SERVER_LOGIC,
    2: StatusCode.DISCONNECT_BY_SERVER_TIMEOUT,
    3: StatusCode.DISCONNECT_BY_SERVER_USER_LIMIT,
}


def build_init_request(app_id: str, ipv6: bool = False,
                       protocol_version: tuple[int, int] = (1, 6)) -> bytes:
    """The 41-byte Init request — a raw layout, not GpBinary (PeerBase.cs:276)."""
    buf = bytearray(9 + APP_ID_LENGTH)
    buf[0] = MESSAGE_MAGIC
    buf[1] = MessageType.INIT
    buf[2] = protocol_version[0]
    buf[3] = protocol_version[1]
    buf[4] = CLIENT_SDK_ID << 1
    buf[5] = ((CLIENT_VERSION[0] << 4) | CLIENT_VERSION[1]) & 0xFF
    buf[6] = CLIENT_VERSION[2]
    buf[7] = CLIENT_VERSION[3]
    buf[8] = 0
    if ipv6:
        buf[5] |= 0x80

    encoded = (app_id or "LoadBalancing").encode("ascii", "replace")[:APP_ID_LENGTH]
    buf[9:9 + len(encoded)] = encoded
    return bytes(buf)


class EnetPeerCore:
    def __init__(self, app_id: str, *, challenge: int,
                 crc_enabled: bool = False,
                 channel_count: int = CHANNEL_COUNT,
                 mtu: int = MTU,
                 protocol_version: tuple[int, int] = (1, 6),
                 on_message: Callable[[bytes], None] | None = None):
        self.app_id = app_id
        self.challenge = challenge
        self.crc_enabled = crc_enabled
        self.mtu = mtu
        self.channel_count = channel_count
        self.protocol_version = protocol_version


        self.peer_id = PEER_ID_UNASSIGNED
        self.state = ConnectionState.DISCONNECTED

        self.channels = {n: EnetChannel(n) for n in range(channel_count)}
        self.channels[INTERNAL_CHANNEL] = EnetChannel(INTERNAL_CHANNEL)

        self.round_trip_time = INITIAL_ROUND_TRIP_TIME
        self.round_trip_time_variance = INITIAL_ROUND_TRIP_TIME_VARIANCE
        self.last_round_trip_time = 0
        self.server_time_offset = 0
        self.server_time_offset_available = False
        self.server_sent_time = 0

        self._time_base = 0
        self._now = 0
        self._time_last_ack_receive = 0
        self._sent_reliable: list[Command] = []
        self._outgoing_acks: deque[Command] = deque()
        self._outgoing_datagrams: list[bytes] = []
        self._incoming_messages: list[bytes] = []
        self._status: list[StatusCode] = []
        self._fragment_buffers: dict[tuple[int, int], dict[int, Command]] = {}

        self.on_message = on_message

    # --- public surface ------------------------------------------------------

    def start_connect(self, now_ms: int) -> None:
        self._time_base = now_ms
        self._now = 0
        self.state = ConnectionState.CONNECTING
        self._queue_reliable(make_connect(self.mtu, self.channel_count))

    def enqueue_message(self, payload: bytes, channel: int = 0,
                        reliable: bool = True) -> None:
        command_type = CommandType.SEND_RELIABLE if reliable else CommandType.SEND_UNRELIABLE
        self._create_and_enqueue(command_type, payload, channel)

    def disconnect(self) -> None:
        if self.state in (ConnectionState.DISCONNECTED, ConnectionState.DISCONNECTING):
            return
        cmd = Command(CommandType.DISCONNECT, INTERNAL_CHANNEL, b"",
                      CommandFlags.RELIABLE)
        if self.state != ConnectionState.CONNECTED:
            cmd.flags = CommandFlags.UNRELIABLE_UNSEQUENCED
            cmd.reserved_byte = 2 if self.state == ConnectionState.ZOMBIE else 4
        self.state = ConnectionState.DISCONNECTING
        self._queue_reliable(cmd)
        self.tick(self._time_base + self._now)

    def fetch_server_timestamp(self) -> None:
        self._create_and_enqueue(CommandType.SERVER_TIME, b"", INTERNAL_CHANNEL)

    @property
    def server_time_ms(self) -> int:
        return self._now + self.server_time_offset

    def take_outgoing(self) -> list[bytes]:
        out, self._outgoing_datagrams = self._outgoing_datagrams, []
        return out

    def take_incoming(self) -> list[bytes]:
        out, self._incoming_messages = self._incoming_messages, []
        return out

    def take_status(self) -> list[StatusCode]:
        out, self._status = self._status, []
        return out

    # --- receive -------------------------------------------------------------

    def on_datagram(self, data: bytes, now_ms: int) -> None:
        self._now = now_ms - self._time_base
        if self.state == ConnectionState.DISCONNECTED:
            return

        datagram = unpack_datagram(data, self.challenge)

        self.server_sent_time = datagram.server_sent_time

        for command in datagram.commands:
            self._execute(command)
            if command.is_reliable:
                self._outgoing_acks.append(make_ack(command, datagram.server_sent_time))

        self._dispatch_channels()

    def _execute(self, command: Command) -> None:
        ct = command.command_type

        if ct in (CommandType.ACK, CommandType.ACK_UNSEQUENCED):
            self._on_ack(command)
        elif ct == CommandType.VERIFY_CONNECT:
            self._on_verify_connect(command)
        elif ct == CommandType.DISCONNECT:
            self._on_disconnect(command)
        elif ct in (CommandType.SEND_RELIABLE, CommandType.SEND_UNRELIABLE):
            if self.state == ConnectionState.CONNECTED:
                self._channel(command.channel_id).queue_incoming(command)
        elif ct == CommandType.SEND_FRAGMENT:
            if self.state == ConnectionState.CONNECTED:
                self._on_fragment(command)
        # CONNECT, PING, SERVER_TIME carry no client-side action.

    def _on_verify_connect(self, command: Command) -> None:
        if self.state != ConnectionState.CONNECTING:
            return
        self.peer_id = parse_verify_connect(command).peer_id
        self.state = ConnectionState.CONNECTED
        # Init goes out on channel 0 as a normal reliable command.
        self._create_and_enqueue(CommandType.SEND_RELIABLE,
                                 build_init_request(self.app_id, protocol_version=self.protocol_version), 0)


    def _on_disconnect(self, command: Command) -> None:
        if self.state in (ConnectionState.DISCONNECTED, ConnectionState.DISCONNECTING):
            return
        self._status.append(_DISCONNECT_REASONS.get(
            command.reserved_byte, StatusCode.DISCONNECT_BY_SERVER_REASON_UNKNOWN))
        self.state = ConnectionState.DISCONNECTED
        self._status.append(StatusCode.DISCONNECT)

    def _on_ack(self, command: Command) -> None:
        self._time_last_ack_receive = self._now
        rtt = self._now - command.ack_sent_time
        if rtt < 0 or rtt > 10000:
            rtt = self.round_trip_time * 4
        self.last_round_trip_time = rtt

        acked = self._remove_sent_reliable(
            command.ack_reliable_sequence_number, command.channel_id,
            command.command_type == CommandType.ACK_UNSEQUENCED)
        if acked is None:
            return

        channel = self._channel(acked.channel_id)
        if acked.reliable_sequence_number > channel.highest_received_ack:
            channel.highest_received_ack = acked.reliable_sequence_number

        if acked.command_type == CommandType.SERVER_TIME:
            if rtt <= self.round_trip_time:
                self.server_time_offset = self.server_sent_time + (rtt >> 1) - self._now
                self.server_time_offset_available = True
            else:
                self.fetch_server_timestamp()
            return

        self._update_rtt(rtt)
        if acked.command_type == CommandType.CONNECT and rtt >= 0:
            if rtt <= 15:
                self.round_trip_time = 15
                self.round_trip_time_variance = 5
            else:
                self.round_trip_time = rtt
        elif (acked.command_type == CommandType.DISCONNECT
              and self.state == ConnectionState.DISCONNECTING):
            self.state = ConnectionState.DISCONNECTED
            self._status.append(StatusCode.DISCONNECT)

    def _update_rtt(self, last: int) -> None:
        if last < 0:
            return
        self.round_trip_time_variance -= _trunc_div(self.round_trip_time_variance, 4)
        delta = last - self.round_trip_time
        self.round_trip_time += _trunc_div(delta, 8)
        # C# recomputes the delta against the already-updated rtt.
        delta = last - self.round_trip_time
        if last >= self.round_trip_time:
            self.round_trip_time_variance += _trunc_div(delta, 4)
        else:
            self.round_trip_time_variance -= _trunc_div(delta, 4)

    def _on_fragment(self, command: Command) -> None:
        if (command.fragment_number > command.fragment_count
                or command.fragment_offset >= command.total_length
                or command.fragment_offset + len(command.payload) > command.total_length):
            return

        key = (command.channel_id, command.start_sequence_number)
        parts = self._fragment_buffers.setdefault(key, {})
        if command.fragment_number in parts:
            return
        parts[command.fragment_number] = command

        if len(parts) < command.fragment_count:
            return

        assembled = bytearray(command.total_length)
        for part in parts.values():
            assembled[part.fragment_offset:
                      part.fragment_offset + len(part.payload)] = part.payload
        del self._fragment_buffers[key]

        whole = Command(CommandType.SEND_RELIABLE, command.channel_id,
                        bytes(assembled), CommandFlags.RELIABLE)
        # The assembled message occupies the whole fragment sequence range, so
        # dispatch must resume after the last fragment.
        whole.reliable_sequence_number = command.start_sequence_number
        whole.fragment_count = command.fragment_count
        self._channel(command.channel_id).incoming_reliable_commands[
            command.start_sequence_number] = whole

    # --- dispatch ------------------------------------------------------------

    def _dispatch_channels(self) -> None:
        progressed = True
        while progressed:
            progressed = False
            for channel in self.channels.values():
                if self._dispatch_one(channel):
                    progressed = True

    def _dispatch_one(self, channel: EnetChannel) -> bool:
        nxt = channel.incoming_reliable_commands.pop(
            channel.incoming_reliable_sequence_number + 1, None)
        if nxt is not None:
            if nxt.fragment_count:
                channel.incoming_reliable_sequence_number = (
                    nxt.reliable_sequence_number + nxt.fragment_count - 1)
            else:
                channel.incoming_reliable_sequence_number = nxt.reliable_sequence_number
            self._deliver(nxt)
            return True

        if channel.incoming_unreliable_commands:
            eligible = [
                seq for seq, cmd in channel.incoming_unreliable_commands.items()
                if seq > channel.incoming_unreliable_sequence_number
                and cmd.reliable_sequence_number <= channel.incoming_reliable_sequence_number
            ]
            if eligible:
                seq = min(eligible)
                cmd = channel.incoming_unreliable_commands.pop(seq)
                channel.incoming_unreliable_sequence_number = seq
                self._deliver(cmd)
                return True
        return False

    def _deliver(self, command: Command) -> None:
        if not command.payload:
            return
        self._incoming_messages.append(command.payload)
        if self.on_message is not None:
            self.on_message(command.payload)

    # --- send ----------------------------------------------------------------

    def tick(self, now_ms: int) -> None:
        self._now = now_ms - self._time_base
        if self.state == ConnectionState.DISCONNECTED:
            return

        commands: list[Command] = []
        budget = self.mtu - (16 if self.crc_enabled else 12)

        def fits(cmd: Command) -> bool:
            return sum(c.size for c in commands) + cmd.size <= budget

        while self._outgoing_acks and fits(self._outgoing_acks[0]):
            commands.append(self._outgoing_acks.popleft())

        if self._collect_resends(commands, fits):
            return

        if (self.state == ConnectionState.CONNECTED
                and not self._sent_reliable
                and self._now - self._time_last_ack_receive > PING_INTERVAL):
            self._queue_reliable(Command(CommandType.PING, INTERNAL_CHANNEL, b"",
                                         CommandFlags.RELIABLE))

        self._update_send_window()
        for channel in self.channels.values():
            limit = channel.lowest_unacknowledged_sequence_number + SEND_WINDOW_SIZE
            self._collect_channel(channel.outgoing_reliable, commands, fits,
                                  channel.number, limit)
            self._collect_channel(channel.outgoing_unreliable, commands, fits,
                                  channel.number, limit)

        if not commands:
            return

        self._outgoing_datagrams.append(pack_datagram(
            self.peer_id, self.challenge, self._now, commands, self.crc_enabled))

    def _collect_resends(self, commands: list[Command], fits) -> bool:
        """Returns True when a resend timeout forced a disconnect."""
        for command in list(self._sent_reliable):
            if self._now <= command.sent_time + command.round_trip_timeout:
                continue
            if (command.sent_count > SENT_COUNT_ALLOWANCE
                    or self._now > command.timeout_time):
                self.state = ConnectionState.ZOMBIE
                self._sent_reliable.remove(command)
                self._status.append(StatusCode.TIMEOUT_DISCONNECT)
                return True
            if fits(command):
                commands.append(command)
                self._mark_sent(command, already_queued=True)
        return False

    def _collect_channel(self, queue: deque[Command], commands: list[Command],
                         fits, channel_number: int, limit: int) -> None:
        while queue:
            command = queue[0]
            if (command.is_reliable and channel_number != INTERNAL_CHANNEL
                    and command.reliable_sequence_number >= limit):
                return
            if not fits(command):
                return
            queue.popleft()
            commands.append(command)
            if command.is_reliable:
                self._mark_sent(command)

    def _mark_sent(self, command: Command, already_queued: bool = False) -> None:
        command.sent_time = self._now
        if command.round_trip_timeout == 0:
            command.round_trip_timeout = min(
                self.round_trip_time + 4 * self.round_trip_time_variance,
                INITIAL_RESEND_TIME_MAX)
            command.timeout_time = self._now + DISCONNECT_TIMEOUT
        elif (command.sent_count >= QUICK_RESEND_ATTEMPTS
              or len(self._sent_reliable) >= SEND_WINDOW_SIZE):
            command.round_trip_timeout = min(command.round_trip_timeout * 2,
                                             INITIAL_RESEND_TIME_MAX * 2)
        command.sent_count += 1
        if not already_queued:
            self._sent_reliable.append(command)

    def _update_send_window(self) -> None:
        lowest: dict[int, int] = {}
        for command in self._sent_reliable:
            if command.is_unsequenced or command.channel_id == INTERNAL_CHANNEL:
                continue
            lowest.setdefault(command.channel_id, command.reliable_sequence_number)
        for channel in self.channels.values():
            channel.lowest_unacknowledged_sequence_number = lowest.get(
                channel.number, channel.highest_received_ack + 1)

    # --- queueing ------------------------------------------------------------

    def _channel(self, number: int) -> EnetChannel:
        channel = self.channels.get(number)
        if channel is None:
            raise ValueError(f"command for non-existing channel {number}")
        return channel

    def _queue_reliable(self, command: Command) -> None:
        channel = self._channel(command.channel_id)
        if command.reliable_sequence_number == 0:
            command.reliable_sequence_number = channel.next_reliable_sequence_number()
        channel.outgoing_reliable.append(command)

    def _queue_unreliable(self, command: Command) -> None:
        channel = self._channel(command.channel_id)
        # Unreliable commands carry the channel's *current* reliable seq and
        # must not advance it.
        command.reliable_sequence_number = channel.outgoing_reliable_sequence_number
        command.unreliable_sequence_number = channel.next_unreliable_sequence_number()
        channel.outgoing_unreliable.append(command)

    def _create_and_enqueue(self, command_type: int, payload: bytes,
                            channel_number: int) -> None:
        channel = self._channel(channel_number)
        flags = (CommandFlags.UNRELIABLE
                 if command_type == CommandType.SEND_UNRELIABLE
                 else CommandFlags.RELIABLE)

        if len(payload) <= FRAGMENT_PAYLOAD_LENGTH:
            command = Command(command_type, channel_number, payload, flags)
            if command.is_reliable:
                self._queue_reliable(command)
            else:
                self._queue_unreliable(command)
            return

        size = FRAGMENT_PAYLOAD_LENGTH
        fragment_count = (len(payload) + size - 1) // size
        start_sequence = channel.outgoing_reliable_sequence_number + 1
        for index, offset in enumerate(range(0, len(payload), size)):
            chunk = payload[offset:offset + size]
            fragment = Command(CommandType.SEND_FRAGMENT, channel_number, chunk,
                               CommandFlags.RELIABLE)
            fragment.fragment_number = index
            fragment.start_sequence_number = start_sequence
            fragment.fragment_count = fragment_count
            fragment.total_length = len(payload)
            fragment.fragment_offset = offset  # byte offset, not fragment index
            self._queue_reliable(fragment)

    def _remove_sent_reliable(self, sequence_number: int, channel_id: int,
                              unsequenced: bool) -> Command | None:
        for command in self._sent_reliable:
            if (command.reliable_sequence_number == sequence_number
                    and command.channel_id == channel_id
                    and command.is_unsequenced == unsequenced):
                self._sent_reliable.remove(command)
                return command
        return None
