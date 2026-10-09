"""PhotonStream: the write-then-read buffer objects fill during sync."""


class PhotonStream:
    def __init__(self, is_writing: bool, data: list | None = None):
        self.is_writing = is_writing
        self._data: list = list(data or [])
        self._index = 0

    @property
    def is_reading(self) -> bool:
        return not self.is_writing

    @property
    def count(self) -> int:
        return len(self._data)

    def send_next(self, value) -> None:
        self._data.append(value)

    def receive_next(self):
        value = self._data[self._index]
        self._index += 1
        return value

    def peek_next(self):
        return self._data[self._index]

    def serialize(self, value):
        """Write on the owner, read on the observers — one call site, both ways."""
        if self.is_writing:
            self.send_next(value)
            return value
        return self.receive_next()

    def to_list(self) -> list:
        return list(self._data)


def delta_compress(current: list, previous: list | None) -> tuple[list, list[int] | None]:
    """Blank out values equal to the last frame's.

    Returns (values, null_value_indices). `null_value_indices` is None when
    nothing was elided, which is the signal to send the batch uncompressed.
    """
    if previous is None or len(previous) != len(current):
        return list(current), None

    values = list(current)
    elided: list[int] = []
    for index, value in enumerate(current):
        if value is not None and value == previous[index]:
            values[index] = None
            elided.append(index)
    if not elided:
        return list(current), None
    return values, elided


def delta_decompress(values: list, null_indices: list[int] | None,
                     previous: list | None) -> list:
    """Refill elided slots from the last received frame."""
    if null_indices is None or previous is None:
        return list(values)
    restored = list(values)
    for index in null_indices:
        if index < len(previous) and index < len(restored):
            restored[index] = previous[index]
    return restored


import struct

class PhotonBinaryWriter:
    """Low-level binary serializer matching Protocol 1.8 / PhotonStream wire format."""
    def __init__(self):
        self._buf = bytearray()

    def write_byte(self, value: int) -> 'PhotonBinaryWriter':
        self._buf.append(value & 0xFF)
        return self

    def write_bool(self, value: bool) -> 'PhotonBinaryWriter':
        self._buf.append(1 if value else 0)
        return self

    def write_int16(self, value: int, endian: str = '<') -> 'PhotonBinaryWriter':
        self._buf.extend(struct.pack(f'{endian}h', value))
        return self

    def write_uint16(self, value: int, endian: str = '<') -> 'PhotonBinaryWriter':
        self._buf.extend(struct.pack(f'{endian}H', value))
        return self

    def write_int32(self, value: int, endian: str = '<') -> 'PhotonBinaryWriter':
        self._buf.extend(struct.pack(f'{endian}i', value))
        return self

    def write_uint32(self, value: int, endian: str = '<') -> 'PhotonBinaryWriter':
        self._buf.extend(struct.pack(f'{endian}I', value))
        return self

    def write_float(self, value: float, endian: str = '<') -> 'PhotonBinaryWriter':
        self._buf.extend(struct.pack(f'{endian}f', value))
        return self

    def write_double(self, value: float, endian: str = '<') -> 'PhotonBinaryWriter':
        self._buf.extend(struct.pack(f'{endian}d', value))
        return self

    def write_vector3(self, x: float, y: float, z: float, endian: str = '<') -> 'PhotonBinaryWriter':
        self._buf.extend(struct.pack(f'{endian}fff', x, y, z))
        return self

    def write_quaternion(self, x: float, y: float, z: float, w: float, endian: str = '<') -> 'PhotonBinaryWriter':
        self._buf.extend(struct.pack(f'{endian}ffff', x, y, z, w))
        return self

    def write_varint32(self, value: int) -> 'PhotonBinaryWriter':
        """ZigZag32 + LEB128 encoding."""
        zz = ((value << 1) ^ (value >> 31)) & 0xFFFFFFFF
        while zz >= 0x80:
            self._buf.append((zz & 0x7F) | 0x80)
            zz >>= 7
        self._buf.append(zz & 0x7F)
        return self

    def write_string(self, text: str) -> 'PhotonBinaryWriter':
        utf8 = text.encode('utf-8')
        length = len(utf8)
        while length >= 0x80:
            self._buf.append((length & 0x7F) | 0x80)
            length >>= 7
        self._buf.append(length & 0x7F)
        self._buf.extend(utf8)
        return self

    def write_raw(self, raw_bytes: bytes | bytearray) -> 'PhotonBinaryWriter':
        self._buf.extend(raw_bytes)
        return self

    def to_bytes(self) -> bytes:
        return bytes(self._buf)

    def to_hex(self) -> str:
        return self._buf.hex().upper()

    def __len__(self) -> int:
        return len(self._buf)
