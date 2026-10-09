"""GpBinaryV18 serialization (Protocol18.cs).

Protocol 1.8 uses compressed variable-length integers (ZigZag + LEB128),
sub-type optimizations for small ints (INT1, INT2, INT_ZERO, etc.),
and little-endian byte order for fixed numeric types.
"""
from __future__ import annotations

import struct
from enum import IntEnum
from typing import Any

from . import custom_types as ct
from .buffer import ByteReader, ByteWriter
from .gpbinary16 import (
    PhotonByte, PhotonShort, PhotonLong, PhotonDouble,
    IntArray, StringArray, TypedArray, Hashtable,
    OperationRequest, OperationResponse, EventData,
)


class GpType18(IntEnum):
    UNKNOWN = 0
    BOOLEAN = 2
    BYTE = 3
    SHORT = 4
    FLOAT = 5
    DOUBLE = 6
    STRING = 7
    NULL = 8
    COMPRESSED_INT = 9
    COMPRESSED_LONG = 10
    INT1 = 11
    INT1_ = 12
    INT2 = 13
    INT2_ = 14
    L1 = 15
    L1_ = 16
    L2 = 17
    L2_ = 18
    CUSTOM = 19
    DICTIONARY = 20
    HASHTABLE = 21
    OBJECT_ARRAY = 23
    OPERATION_REQUEST = 24
    OPERATION_RESPONSE = 25
    EVENT_DATA = 26
    BOOLEAN_FALSE = 27
    BOOLEAN_TRUE = 28
    SHORT_ZERO = 29
    INT_ZERO = 30
    LONG_ZERO = 31
    FLOAT_ZERO = 32
    DOUBLE_ZERO = 33
    BYTE_ZERO = 34
    ARRAY = 64
    BOOLEAN_ARRAY = 66
    BYTE_ARRAY = 67
    SHORT_ARRAY = 68
    FLOAT_ARRAY = 69
    DOUBLE_ARRAY = 70
    STRING_ARRAY = 71
    COMPRESSED_INT_ARRAY = 73
    COMPRESSED_LONG_ARRAY = 74
    CUSTOM_TYPE_ARRAY = 83
    DICTIONARY_ARRAY = 84
    HASHTABLE_ARRAY = 85
    CUSTOM_TYPE_SLIM = 128


def encode_zigzag_32(n: int) -> int:
    return ((n << 1) ^ (n >> 31)) & 0xFFFFFFFF


def decode_zigzag_32(n: int) -> int:
    return (n >> 1) ^ (-(n & 1))


def encode_zigzag_64(n: int) -> int:
    return ((n << 1) ^ (n >> 63)) & 0xFFFFFFFFFFFFFFFF


def decode_zigzag_64(n: int) -> int:
    return (n >> 1) ^ (-(n & 1))


def write_compressed_uint32(w: ByteWriter, val: int) -> None:
    val &= 0xFFFFFFFF
    while val >= 0x80:
        w.u8((val & 0x7F) | 0x80)
        val >>= 7
    w.u8(val & 0x7F)


def read_compressed_uint32(r: ByteReader) -> int:
    num = 0
    shift = 0
    while shift < 35:
        b = r.u8()
        num |= (b & 0x7F) << shift
        shift += 7
        if not (b & 0x80):
            break
    return num


def write_compressed_uint64(w: ByteWriter, val: int) -> None:
    val &= 0xFFFFFFFFFFFFFFFF
    while val >= 0x80:
        w.u8((val & 0x7F) | 0x80)
        val >>= 7
    w.u8(val & 0x7F)


def read_compressed_uint64(r: ByteReader) -> int:
    num = 0
    shift = 0
    while shift < 70:
        b = r.u8()
        num |= (b & 0x7F) << shift
        shift += 7
        if not (b & 0x80):
            break
    return num


def write_int_length(w: ByteWriter, length: int) -> None:
    write_compressed_uint32(w, length)


def read_int_length(r: ByteReader) -> int:
    return read_compressed_uint32(r)


def write_compressed_int32(w: ByteWriter, value: int, write_type: bool = True) -> None:
    if write_type:
        if value == 0:
            w.u8(GpType18.INT_ZERO)
            return
        if value > 0:
            if value <= 255:
                w.u8(GpType18.INT1)
                w.u8(value)
                return
            if value <= 65535:
                w.u8(GpType18.INT2)
                w.raw(struct.pack('<H', value))
                return
        elif value >= -65535:
            if value >= -255:
                w.u8(GpType18.INT1_)
                w.u8(-value)
                return
            if value >= -65535:
                w.u8(GpType18.INT2_)
                w.raw(struct.pack('<H', -value))
                return
        w.u8(GpType18.COMPRESSED_INT)

    write_compressed_uint32(w, encode_zigzag_32(value))


def read_compressed_int32(r: ByteReader) -> int:
    val = read_compressed_uint32(r)
    return decode_zigzag_32(val)


def write_compressed_int64(w: ByteWriter, value: int, write_type: bool = True) -> None:
    if write_type:
        if value == 0:
            w.u8(GpType18.LONG_ZERO)
            return
        if value > 0:
            if value <= 255:
                w.u8(GpType18.L1)
                w.u8(value)
                return
            if value <= 65535:
                w.u8(GpType18.L2)
                w.raw(struct.pack('<H', value))
                return
        elif value >= -65535:
            if value >= -255:
                w.u8(GpType18.L1_)
                w.u8(-value)
                return
            if value >= -65535:
                w.u8(GpType18.L2_)
                w.raw(struct.pack('<H', -value))
                return
        w.u8(GpType18.COMPRESSED_LONG)

    write_compressed_uint64(w, encode_zigzag_64(value))


def read_compressed_int64(r: ByteReader) -> int:
    val = read_compressed_uint64(r)
    return decode_zigzag_64(val)


def serialize_value(w: ByteWriter, value: Any, write_type: bool = True) -> None:
    if value is None:
        if write_type:
            w.u8(GpType18.NULL)
        return

    if isinstance(value, bool):
        if write_type:
            w.u8(GpType18.BOOLEAN_TRUE if value else GpType18.BOOLEAN_FALSE)
        else:
            w.u8(1 if value else 0)
        return

    if isinstance(value, PhotonByte):
        val = int(value) & 0xFF
        if write_type:
            if val == 0:
                w.u8(GpType18.BYTE_ZERO)
                return
            w.u8(GpType18.BYTE)
        w.u8(val)
        return

    if isinstance(value, PhotonShort):
        val = int(value)
        if write_type:
            if val == 0:
                w.u8(GpType18.SHORT_ZERO)
                return
            w.u8(GpType18.SHORT)
        w.raw(struct.pack('<h', val))
        return

    if isinstance(value, PhotonLong):
        write_compressed_int64(w, int(value), write_type)
        return

    if isinstance(value, PhotonDouble):
        val = float(value)
        if write_type:
            if val == 0.0:
                w.u8(GpType18.DOUBLE_ZERO)
                return
            w.u8(GpType18.DOUBLE)
        w.raw(struct.pack('<d', val))
        return

    if isinstance(value, int):
        write_compressed_int32(w, value, write_type)
        return

    if isinstance(value, float):
        val = float(value)
        if write_type:
            if val == 0.0:
                w.u8(GpType18.FLOAT_ZERO)
                return
            w.u8(GpType18.FLOAT)
        w.raw(struct.pack('<f', val))
        return

    if isinstance(value, str):
        if write_type:
            w.u8(GpType18.STRING)
        data = value.encode('utf-8')
        write_int_length(w, len(data))
        w.raw(data)
        return

    if isinstance(value, (bytes, bytearray)):
        if write_type:
            w.u8(GpType18.BYTE_ARRAY)
        write_int_length(w, len(value))
        w.raw(value)
        return

    if isinstance(value, IntArray):
        if write_type:
            w.u8(GpType18.COMPRESSED_INT_ARRAY)
        write_int_length(w, len(value))
        for item in value:
            write_compressed_int32(w, int(item), write_type=False)
        return

    if isinstance(value, StringArray):
        if write_type:
            w.u8(GpType18.STRING_ARRAY)
        write_int_length(w, len(value))
        for item in value:
            s_data = str(item).encode('utf-8')
            write_int_length(w, len(s_data))
            w.raw(s_data)
        return

    if isinstance(value, Hashtable):
        if write_type:
            w.u8(GpType18.HASHTABLE)
        write_int_length(w, len(value))
        for k, v in value.items():
            serialize_value(w, k, write_type=True)
            serialize_value(w, v, write_type=True)
        return

    if isinstance(value, dict):
        if write_type:
            w.u8(GpType18.DICTIONARY)
        w.u8(0)  # key type object
        w.u8(0)  # value type object
        write_int_length(w, len(value))
        for k, v in value.items():
            serialize_value(w, k, write_type=True)
            serialize_value(w, v, write_type=True)
        return

    if ct.by_type(type(value)) is not None or isinstance(value, ct.UnknownCustomType):
        type_code, data = ct.serialize_custom(value)
        if write_type:
            w.u8(128 + (type_code & 0x7F))
        write_compressed_uint32(w, len(data))
        w.raw(data)
        return

    if isinstance(value, (list, tuple)):
        if write_type:
            w.u8(GpType18.OBJECT_ARRAY)
        write_int_length(w, len(value))
        for item in value:
            serialize_value(w, item, write_type=True)
        return

    if isinstance(value, OperationRequest):
        if write_type:
            w.u8(GpType18.OPERATION_REQUEST)
        w.u8(value.op_code)
        serialize_parameter_table(w, value.parameters)
        return

    if isinstance(value, OperationResponse):
        if write_type:
            w.u8(GpType18.OPERATION_RESPONSE)
        w.u8(value.op_code)
        w.raw(struct.pack('<h', value.return_code))
        if value.debug_message:
            w.u8(GpType18.STRING)
            s_bytes = value.debug_message.encode('utf-8')
            write_int_length(w, len(s_bytes))
            w.raw(s_bytes)
        else:
            w.u8(GpType18.NULL)
        serialize_parameter_table(w, value.parameters)
        return

    if isinstance(value, EventData):
        if write_type:
            w.u8(GpType18.EVENT_DATA)
        w.u8(value.code)
        serialize_parameter_table(w, value.parameters)
        return

    raise TypeError(f"Cannot serialize object of type {type(value)} with GpBinaryV18")




def serialize_parameter_table(w: ByteWriter, params: dict[int, Any]) -> None:
    if not params:
        w.u8(0)
        return
    w.u8(len(params))
    for k, v in params.items():
        w.u8(int(k) & 0xFF)
        serialize_value(w, v, write_type=True)


def deserialize_value(r: ByteReader, gp_type: int | None = None) -> Any:
    if gp_type is None:
        gp_type = r.u8()

    if gp_type >= 128:
        type_code = gp_type - 128
        length = read_compressed_uint32(r)
        data = r.raw(length)
        return ct.deserialize_custom(type_code, data)

    t = GpType18(gp_type)

    if t == GpType18.NULL:
        return None
    if t == GpType18.BOOLEAN_TRUE:
        return True
    if t == GpType18.BOOLEAN_FALSE:
        return False
    if t == GpType18.BOOLEAN:
        return r.u8() > 0
    if t == GpType18.BYTE_ZERO:
        return PhotonByte(0)
    if t == GpType18.BYTE:
        return PhotonByte(r.u8())
    if t == GpType18.SHORT_ZERO:
        return PhotonShort(0)
    if t == GpType18.SHORT:
        return PhotonShort(struct.unpack('<h', r.raw(2))[0])
    if t == GpType18.INT_ZERO:
        return 0
    if t == GpType18.INT1:
        return r.u8()
    if t == GpType18.INT1_:
        return -r.u8()
    if t == GpType18.INT2:
        return struct.unpack('<H', r.raw(2))[0]
    if t == GpType18.INT2_:
        return -struct.unpack('<H', r.raw(2))[0]
    if t == GpType18.COMPRESSED_INT:
        return read_compressed_int32(r)
    if t == GpType18.LONG_ZERO:
        return PhotonLong(0)
    if t == GpType18.L1:
        return PhotonLong(r.u8())
    if t == GpType18.L1_:
        return PhotonLong(-r.u8())
    if t == GpType18.L2:
        return PhotonLong(struct.unpack('<H', r.raw(2))[0])
    if t == GpType18.L2_:
        return PhotonLong(-struct.unpack('<H', r.raw(2))[0])
    if t == GpType18.COMPRESSED_LONG:
        return PhotonLong(read_compressed_int64(r))
    if t == GpType18.FLOAT_ZERO:
        return 0.0
    if t == GpType18.FLOAT:
        return struct.unpack('<f', r.raw(4))[0]
    if t == GpType18.DOUBLE_ZERO:
        return PhotonDouble(0.0)
    if t == GpType18.DOUBLE:
        return PhotonDouble(struct.unpack('<d', r.raw(8))[0])
    if t == GpType18.STRING:
        length = read_int_length(r)
        if length == 0:
            return ""
        return r.raw(length).decode('utf-8', errors='replace')
    if t == GpType18.BYTE_ARRAY:
        length = read_int_length(r)
        return r.raw(length)
    if t == GpType18.SHORT_ARRAY:
        length = read_int_length(r)
        if length == 0:
            return []
        return list(struct.unpack(f'<{length}h', r.raw(length * 2)))
    if t == GpType18.FLOAT_ARRAY:
        length = read_int_length(r)
        if length == 0:
            return []
        return list(struct.unpack(f'<{length}f', r.raw(length * 4)))
    if t == GpType18.DOUBLE_ARRAY:
        length = read_int_length(r)
        if length == 0:
            return []
        return list(struct.unpack(f'<{length}d', r.raw(length * 8)))
    if t == GpType18.BOOLEAN_ARRAY:
        length = read_int_length(r)
        num_bytes = (length + 7) // 8
        raw_bytes = r.raw(num_bytes)
        bools = []
        for i in range(length):
            byte_val = raw_bytes[i // 8]
            bit = (byte_val >> (i % 8)) & 1
            bools.append(bool(bit))
        return bools
    if t == GpType18.COMPRESSED_INT_ARRAY:
        length = read_int_length(r)
        return IntArray([read_compressed_int32(r) for _ in range(length)])
    if t == GpType18.COMPRESSED_LONG_ARRAY:
        length = read_int_length(r)
        return [read_compressed_int64(r) for _ in range(length)]
    if t == GpType18.STRING_ARRAY:
        length = read_int_length(r)
        items = []
        for _ in range(length):
            s_len = read_int_length(r)
            items.append(r.raw(s_len).decode('utf-8', errors='replace') if s_len > 0 else "")
        return StringArray(items)
    if t == GpType18.HASHTABLE:
        length = read_int_length(r)
        ht = Hashtable()
        for _ in range(length):
            k = deserialize_value(r)
            v = deserialize_value(r)
            if k is not None:
                ht[k] = v
        return ht
    if t == GpType18.HASHTABLE_ARRAY:
        length = read_int_length(r)
        return [deserialize_value(r, GpType18.HASHTABLE) for _ in range(length)]
    if t == GpType18.DICTIONARY:
        key_type = r.u8()
        val_type = r.u8()
        length = read_int_length(r)
        d = {}
        for _ in range(length):
            k = deserialize_value(r, key_type if key_type != 0 else None)
            v = deserialize_value(r, val_type if val_type != 0 else None)
            if k is not None:
                d[k] = v
        return d
    if t == GpType18.OBJECT_ARRAY:
        length = read_int_length(r)
        return [deserialize_value(r) for _ in range(length)]
    if t == GpType18.CUSTOM_TYPE_ARRAY:
        length = read_int_length(r)
        type_code = r.u8()
        items = []
        for _ in range(length):
            item_len = read_int_length(r)
            items.append(ct.deserialize_custom(type_code, r.raw(item_len)))
        return items
    if t == GpType18.ARRAY:
        elem_type = r.u8()
        length = read_int_length(r)
        return [deserialize_value(r, elem_type if elem_type != 0 else None) for _ in range(length)]
    if t == GpType18.OPERATION_REQUEST:
        return deserialize_operation_request(r)
    if t == GpType18.OPERATION_RESPONSE:
        return deserialize_operation_response(r)
    if t == GpType18.EVENT_DATA:
        return deserialize_event(r)
    if t == GpType18.CUSTOM:
        type_code = r.u8()
        length = read_int_length(r)
        data = r.raw(length)
        return ct.deserialize_custom(type_code, data)

    raise ValueError(f"Unknown GpType18: {gp_type}")


def deserialize_parameter_table(r: ByteReader) -> dict[int, Any]:
    count = r.u8()
    params = {}
    for _ in range(count):
        k = r.u8()
        v = deserialize_value(r)
        params[k] = v
    return params


def serialize_operation_request(w: ByteWriter, req: OperationRequest) -> None:
    w.u8(req.op_code)
    serialize_parameter_table(w, req.parameters)


def deserialize_operation_request(r: ByteReader) -> OperationRequest:
    op_code = r.u8()
    params = deserialize_parameter_table(r)
    return OperationRequest(op_code, params)


def serialize_operation_response(w: ByteWriter, resp: OperationResponse) -> None:
    w.u8(resp.op_code)
    w.raw(struct.pack('<h', resp.return_code))
    if resp.debug_message:
        w.u8(GpType18.STRING)
        s_bytes = resp.debug_message.encode('utf-8')
        write_int_length(w, len(s_bytes))
        w.raw(s_bytes)
    else:
        w.u8(GpType18.NULL)
    serialize_parameter_table(w, resp.parameters)


def deserialize_operation_response(r: ByteReader) -> OperationResponse:
    op_code = r.u8()
    return_code = struct.unpack('<h', r.raw(2))[0]
    msg_type = r.u8()
    debug_msg = deserialize_value(r, msg_type) if msg_type != GpType18.NULL else ""
    params = deserialize_parameter_table(r)
    return OperationResponse(op_code, return_code, debug_msg or "", params)


def serialize_event(w: ByteWriter, evt: EventData) -> None:
    w.u8(evt.code)
    serialize_parameter_table(w, evt.parameters)


def deserialize_event(r: ByteReader) -> EventData:
    code = r.u8()
    params = deserialize_parameter_table(r)
    return EventData(code, params)
