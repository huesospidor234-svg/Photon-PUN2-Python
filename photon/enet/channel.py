"""Per-channel sequencing state (EnetChannel.cs).

Channels 0..ChannelCount-1 carry operations; channel 255 is internal
(connect/ping/servertime) and is exempt from the send window.
"""

from collections import deque

from .commands import Command


class EnetChannel:
    __slots__ = (
        "number",
        "incoming_reliable_commands", "incoming_unreliable_commands",
        "incoming_reliable_sequence_number", "incoming_unreliable_sequence_number",
        "outgoing_reliable_sequence_number", "outgoing_unreliable_sequence_number",
        "outgoing_reliable", "outgoing_unreliable",
        "highest_received_ack", "lowest_unacknowledged_sequence_number",
    )

    def __init__(self, number: int):
        self.number = number
        self.incoming_reliable_commands: dict[int, Command] = {}
        self.incoming_unreliable_commands: dict[int, Command] = {}
        self.incoming_reliable_sequence_number = 0
        self.incoming_unreliable_sequence_number = 0
        self.outgoing_reliable_sequence_number = 0
        self.outgoing_unreliable_sequence_number = 0
        self.outgoing_reliable: deque[Command] = deque()
        self.outgoing_unreliable: deque[Command] = deque()
        self.highest_received_ack = 0
        self.lowest_unacknowledged_sequence_number = 0

    def next_reliable_sequence_number(self) -> int:
        """Pre-increment: the channel's first reliable command gets 1."""
        self.outgoing_reliable_sequence_number += 1
        return self.outgoing_reliable_sequence_number

    def next_unreliable_sequence_number(self) -> int:
        self.outgoing_unreliable_sequence_number += 1
        return self.outgoing_unreliable_sequence_number

    def queue_incoming(self, command: Command) -> bool:
        """Store an incoming command for ordered dispatch. False = drop it."""
        if command.is_reliable:
            if command.reliable_sequence_number <= self.incoming_reliable_sequence_number:
                return False
            if command.reliable_sequence_number in self.incoming_reliable_commands:
                return False
            self.incoming_reliable_commands[command.reliable_sequence_number] = command
            return True

        if command.flags == 0:
            if command.reliable_sequence_number < self.incoming_reliable_sequence_number:
                return False
            if command.unreliable_sequence_number <= self.incoming_unreliable_sequence_number:
                return False
            if command.unreliable_sequence_number in self.incoming_unreliable_commands:
                return False
            self.incoming_unreliable_commands[command.unreliable_sequence_number] = command
            return True

        return False

    def clear(self) -> None:
        self.incoming_reliable_commands.clear()
        self.incoming_unreliable_commands.clear()
        self.outgoing_reliable.clear()
        self.outgoing_unreliable.clear()
