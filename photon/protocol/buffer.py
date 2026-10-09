"""Big-endian byte reader/writer.

Every multi-byte value in GpBinaryV16 and in the ENet framing is big-endian.
Centralising the struct formats here keeps that invariant in one place.
"""

import struct


_I8 = struct.Struct(">b")
_U8 = struct.Struct(">B")
_I16 = struct.Struct(">h")
_U16 = struct.Struct(">H")
_I32 = struct.Struct(">i")
_U32 = struct.Struct(">I")
_I64 = struct.Struct(">q")
_F32 = struct.Struct(">f")
_F64 = struct.Struct(">d")


class ByteWriter:
    __slots__ = ("buf",)

    def __init__(self, buf: bytearray | None = None):
        self.buf = bytearray() if buf is None else buf

    def __len__(self) -> int:
        return len(self.buf)

    @property
    def position(self) -> int:
        return len(self.buf)

    def u8(self, v: int) -> None:
        self.buf.append(v & 0xFF)

    def i8(self, v: int) -> None:
        self.buf += _I8.pack(v)

    def i16(self, v: int) -> None:
        self.buf += _I16.pack(v)

    def u16(self, v: int) -> None:
        self.buf += _U16.pack(v)

    def i32(self, v: int) -> None:
        self.buf += _I32.pack(v)

    def u32(self, v: int) -> None:
        self.buf += _U32.pack(v)

    def i64(self, v: int) -> None:
        self.buf += _I64.pack(v)

    def f32(self, v: float) -> None:
        self.buf += _F32.pack(v)

    def f64(self, v: float) -> None:
        self.buf += _F64.pack(v)

    def raw(self, data: bytes) -> None:
        self.buf += data

    def reserve(self, count: int) -> int:
        """Append `count` placeholder bytes, returning their offset for patching."""
        offset = len(self.buf)
        self.buf += bytes(count)
        return offset

    def patch_i16(self, offset: int, v: int) -> None:
        self.buf[offset:offset + 2] = _I16.pack(v)

    def patch_i32(self, offset: int, v: int) -> None:
        self.buf[offset:offset + 4] = _I32.pack(v)

    def to_bytes(self) -> bytes:
        return bytes(self.buf)


class ByteReader:
    __slots__ = ("data", "pos")

    def __init__(self, data: bytes, pos: int = 0):
        self.data = data
        self.pos = pos

    @property
    def available(self) -> int:
        return len(self.data) - self.pos

    def _take(self, n: int) -> bytes:
        end = self.pos + n
        if end > len(self.data):
            raise EOFError(f"need {n} bytes at {self.pos}, have {self.available}")
        chunk = self.data[self.pos:end]
        self.pos = end
        return chunk

    def u8(self) -> int:
        return self._take(1)[0]

    def i8(self) -> int:
        return _I8.unpack(self._take(1))[0]

    def i16(self) -> int:
        return _I16.unpack(self._take(2))[0]

    def u16(self) -> int:
        return _U16.unpack(self._take(2))[0]

    def i32(self) -> int:
        return _I32.unpack(self._take(4))[0]

    def u32(self) -> int:
        return _U32.unpack(self._take(4))[0]

    def i64(self) -> int:
        return _I64.unpack(self._take(8))[0]

    def f32(self) -> float:
        return _F32.unpack(self._take(4))[0]

    def f64(self) -> float:
        return _F64.unpack(self._take(8))[0]

    def raw(self, n: int) -> bytes:
        return self._take(n)
