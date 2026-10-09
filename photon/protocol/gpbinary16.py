"""GpBinaryV16 serialization (Protocol16.cs).

Everything multi-byte is big-endian. Note the two length conventions:
lengths are int16 except ByteArray, which uses int32 (Protocol16.cs:802).
"""

from typing import Any

from . import custom_types as ct
from .buffer import ByteReader, ByteWriter
from .constants import GpType


class PhotonByte(int):
    """Force an int onto the wire as GpType.BYTE."""


class PhotonShort(int):
    """Force an int onto the wire as GpType.SHORT."""


class PhotonLong(int):
    """Force an int onto the wire as GpType.LONG."""


class PhotonDouble(float):
    """Force a float onto the wire as GpType.DOUBLE."""


class IntArray(list):
    """A list of ints serialized as GpType.ARRAY of INTEGER."""


class StringArray(list):
    """A list of str serialized as GpType.STRING_ARRAY."""


class TypedArray:
    """A homogeneous array (GpType.ARRAY) with an explicit element type."""

    __slots__ = ("element_type", "items")

    def __init__(self, element_type: int, items: list):
        self.element_type = element_type
        self.items = items

    def __eq__(self, other):
        return (isinstance(other, TypedArray)
                and self.element_type == other.element_type
                and self.items == other.items)

    def __iter__(self):
        return iter(self.items)

    def __len__(self):
        return len(self.items)

    def __getitem__(self, index):
        return self.items[index]

    def __repr__(self):
        return f"TypedArray({self.element_type!r}, {self.items!r})"


class Hashtable(dict):
    """A dict serialized as GpType.HASHTABLE (keys and values each typed)."""


class OperationRequest:
    __slots__ = ("op_code", "parameters")

    def __init__(self, op_code: int, parameters: dict[int, Any] | None = None):
        self.op_code = op_code
        self.parameters = parameters if parameters is not None else {}


class OperationResponse:
    __slots__ = ("op_code", "return_code", "debug_message", "parameters")

    def __init__(self, op_code: int, return_code: int = 0,
                 debug_message: str | None = None,
                 parameters: dict[int, Any] | None = None):
        self.op_code = op_code
        self.return_code = return_code
        self.debug_message = debug_message
        self.parameters = parameters if parameters is not None else {}

    def __repr__(self):
        return (f"OperationResponse(op={self.op_code}, rc={self.return_code}, "
                f"msg={self.debug_message!r}, params={self.parameters!r})")


class EventData:
    __slots__ = ("code", "parameters")

    def __init__(self, code: int, parameters: dict[int, Any] | None = None):
        self.code = code
        self.parameters = parameters if parameters is not None else {}

    def __repr__(self):
        return f"EventData(code={self.code}, params={self.parameters!r})"


MAX_SHORT_LENGTH = 32767


def _write_length(w: ByteWriter, length: int, what: str) -> None:
    if length > MAX_SHORT_LENGTH:
        raise ValueError(f"{what} too long for a int16 length: {length}")
    w.i16(length)


def _code_of_value(value: Any) -> int:
    """The GpType a Python value maps to."""
    if value is None:
        return GpType.NULL
    # bool before int: bool is a subclass of int.
    if isinstance(value, bool):
        return GpType.BOOLEAN
    if isinstance(value, PhotonByte):
        return GpType.BYTE
    if isinstance(value, PhotonShort):
        return GpType.SHORT
    if isinstance(value, PhotonLong):
        return GpType.LONG
    if isinstance(value, PhotonDouble):
        return GpType.DOUBLE
    if isinstance(value, int):
        return GpType.INTEGER
    if isinstance(value, float):
        return GpType.FLOAT
    if isinstance(value, str):
        return GpType.STRING
    if isinstance(value, (bytes, bytearray)):
        return GpType.BYTE_ARRAY
    if isinstance(value, StringArray):
        return GpType.STRING_ARRAY
    if isinstance(value, (IntArray, TypedArray)):
        return GpType.ARRAY
    if isinstance(value, Hashtable):
        return GpType.HASHTABLE
    # Custom types are NamedTuples, so they must be matched before the
    # generic list/tuple branch would swallow them as an object[].
    if isinstance(value, ct.UnknownCustomType) or ct.by_type(type(value)) is not None:
        return GpType.CUSTOM
    if isinstance(value, (list, tuple)):
        return GpType.OBJECT_ARRAY
    if isinstance(value, dict):
        return GpType.HASHTABLE
    if isinstance(value, EventData):
        return GpType.EVENT_DATA
    if isinstance(value, OperationRequest):
        return GpType.OPERATION_REQUEST
    if isinstance(value, OperationResponse):
        return GpType.OPERATION_RESPONSE
    raise TypeError(f"cannot serialize {type(value).__name__}")


def serialize(w: ByteWriter, value: Any, set_type: bool = True) -> None:
    code = _code_of_value(value)

    if code == GpType.NULL:
        if set_type:
            w.u8(GpType.NULL)
        return

    if code == GpType.CUSTOM:
        _serialize_custom(w, value, set_type)
        return

    if set_type:
        w.u8(code)

    if code == GpType.BOOLEAN:
        w.u8(1 if value else 0)
    elif code == GpType.BYTE:
        w.u8(value)
    elif code == GpType.SHORT:
        w.i16(value)
    elif code == GpType.INTEGER:
        w.i32(value)
    elif code == GpType.LONG:
        w.i64(value)
    elif code == GpType.FLOAT:
        w.f32(value)
    elif code == GpType.DOUBLE:
        w.f64(value)
    elif code == GpType.STRING:
        _serialize_string(w, value)
    elif code == GpType.BYTE_ARRAY:
        w.i32(len(value))  # int32, unlike every other length
        w.raw(bytes(value))
    elif code == GpType.STRING_ARRAY:
        _write_length(w, len(value), "string[]")
        for item in value:
            _serialize_string(w, item)
    elif code == GpType.ARRAY:
        _serialize_typed_array(w, value)
    elif code == GpType.OBJECT_ARRAY:
        _write_length(w, len(value), "object[]")
        for item in value:
            serialize(w, item, True)
    elif code == GpType.HASHTABLE:
        _write_length(w, len(value), "Hashtable")
        for k, v in value.items():
            serialize(w, k, True)
            serialize(w, v, True)
    elif code == GpType.EVENT_DATA:
        w.u8(value.code)
        serialize_parameter_table(w, value.parameters)
    elif code == GpType.OPERATION_REQUEST:
        w.u8(value.op_code)
        serialize_parameter_table(w, value.parameters)
    elif code == GpType.OPERATION_RESPONSE:
        _serialize_operation_response_body(w, value)
    else:
        raise TypeError(f"unhandled GpType {code}")


def _serialize_string(w: ByteWriter, value: str) -> None:
    encoded = value.encode("utf-8")
    _write_length(w, len(encoded), "String")
    w.raw(encoded)


def _serialize_typed_array(w: ByteWriter, value) -> None:
    if isinstance(value, IntArray):
        element_type, items = GpType.INTEGER, list(value)
    else:
        element_type, items = value.element_type, value.items
    _write_length(w, len(items), "Array")
    w.u8(element_type)
    for item in items:
        serialize(w, item, False)


def _serialize_custom(w: ByteWriter, value: Any, set_type: bool) -> None:
    if isinstance(value, ct.UnknownCustomType):
        if set_type:
            w.u8(GpType.CUSTOM)
        w.u8(value.code)
        _write_length(w, len(value.data), "Custom type")
        w.raw(value.data)
        return

    info = ct.by_type(type(value))
    if set_type:
        w.u8(GpType.CUSTOM)
    w.u8(info.code)
    length_at = w.reserve(2)
    start = w.position
    info.serialize(w, value)
    w.patch_i16(length_at, w.position - start)


def serialize_parameter_table(w: ByteWriter, parameters: dict[int, Any] | None) -> None:
    """Parameter table: int16 BE count, then key byte + typed value per entry."""
    if not parameters:
        w.i16(0)
        return
    _write_length(w, len(parameters), "ParameterTable")
    for key, value in parameters.items():
        w.u8(key)
        serialize(w, value, True)


def _serialize_operation_response_body(w: ByteWriter, resp: OperationResponse) -> None:
    w.u8(resp.op_code)
    w.i16(resp.return_code)
    if resp.debug_message:
        w.u8(GpType.STRING)
        _serialize_string(w, resp.debug_message)
    else:
        w.u8(GpType.NULL)
    serialize_parameter_table(w, resp.parameters)


def serialize_operation_request(w: ByteWriter, op_code: int,
                                parameters: dict[int, Any] | None,
                                set_type: bool = False) -> None:
    if set_type:
        w.u8(GpType.OPERATION_REQUEST)
    w.u8(op_code)
    serialize_parameter_table(w, parameters)


def serialize_event(w: ByteWriter, code: int,
                    parameters: dict[int, Any] | None,
                    set_type: bool = False) -> None:
    if set_type:
        w.u8(GpType.EVENT_DATA)
    w.u8(code)
    serialize_parameter_table(w, parameters)


# --- deserialization ---------------------------------------------------------

def deserialize(r: ByteReader, type_code: int) -> Any:
    if type_code in (GpType.NULL, GpType.UNKNOWN):
        return None
    if type_code == GpType.BOOLEAN:
        return r.u8() != 0
    if type_code == GpType.BYTE:
        return PhotonByte(r.u8())
    if type_code == GpType.SHORT:
        return PhotonShort(r.i16())
    if type_code == GpType.INTEGER:
        return r.i32()
    if type_code == GpType.LONG:
        return PhotonLong(r.i64())
    if type_code == GpType.FLOAT:
        return r.f32()
    if type_code == GpType.DOUBLE:
        return PhotonDouble(r.f64())
    if type_code == GpType.STRING:
        return _deserialize_string(r)
    if type_code == GpType.BYTE_ARRAY:
        return r.raw(r.i32())
    if type_code == GpType.STRING_ARRAY:
        return StringArray(_deserialize_string(r) for _ in range(r.i16()))
    if type_code == GpType.INTEGER_ARRAY:
        return IntArray(r.i32() for _ in range(r.i32()))
    if type_code == GpType.ARRAY:
        return _deserialize_typed_array(r)
    if type_code == GpType.OBJECT_ARRAY:
        return [deserialize(r, r.u8()) for _ in range(r.i16())]
    if type_code == GpType.HASHTABLE:
        return _deserialize_hashtable(r)
    if type_code == GpType.DICTIONARY:
        return _deserialize_dictionary(r)
    if type_code == GpType.CUSTOM:
        return _deserialize_custom(r)
    if type_code == GpType.EVENT_DATA:
        return deserialize_event(r)
    if type_code == GpType.OPERATION_REQUEST:
        return OperationRequest(r.u8(), deserialize_parameter_table(r))
    if type_code == GpType.OPERATION_RESPONSE:
        return deserialize_operation_response(r)
    raise ValueError(f"unknown GpType {type_code} at offset {r.pos}")


def _deserialize_string(r: ByteReader) -> str:
    return r.raw(r.i16()).decode("utf-8")


def _deserialize_typed_array(r: ByteReader):
    count = r.i16()
    element_type = r.u8()
    items = [deserialize(r, element_type) for _ in range(count)]
    if element_type == GpType.INTEGER:
        return IntArray(items)
    return TypedArray(element_type, items)


def _deserialize_hashtable(r: ByteReader) -> Hashtable:
    count = r.i16()
    result = Hashtable()
    for _ in range(count):
        key = deserialize(r, r.u8())
        value = deserialize(r, r.u8())
        result[key] = value
    return result


def _deserialize_dictionary(r: ByteReader) -> dict:
    key_type = r.u8()
    value_type = r.u8()
    nested_value_header = None
    if value_type == GpType.DICTIONARY:
        nested_value_header = (r.u8(), r.u8())
    count = r.i16()
    result = {}
    for _ in range(count):
        key = deserialize(r, r.u8() if key_type == GpType.UNKNOWN else key_type)
        if value_type == GpType.UNKNOWN:
            value = deserialize(r, r.u8())
        elif nested_value_header is not None:
            value = _deserialize_dictionary_elements(r, *nested_value_header)
        else:
            value = deserialize(r, value_type)
        result[key] = value
    return result


def _deserialize_dictionary_elements(r: ByteReader, key_type: int, value_type: int) -> dict:
    count = r.i16()
    result = {}
    for _ in range(count):
        key = deserialize(r, r.u8() if key_type == GpType.UNKNOWN else key_type)
        value = deserialize(r, r.u8() if value_type == GpType.UNKNOWN else value_type)
        result[key] = value
    return result


def _deserialize_custom(r: ByteReader) -> Any:
    code = r.u8()
    length = r.i16()
    if length < 0:
        raise ValueError(f"negative custom type length {length} at {r.pos}")
    info = ct.by_code(code)
    if info is None:
        return ct.UnknownCustomType(code, r.raw(length))
    end = r.pos + length
    value = info.deserialize(r, length)
    r.pos = end
    return value


def deserialize_parameter_table(r: ByteReader) -> dict[int, Any]:
    count = r.i16()
    result = {}
    for _ in range(count):
        key = r.u8()
        result[key] = deserialize(r, r.u8())
    return result


def deserialize_operation_request(r: ByteReader) -> OperationRequest:
    return OperationRequest(r.u8(), deserialize_parameter_table(r))


def deserialize_operation_response(r: ByteReader) -> OperationResponse:
    op_code = r.u8()
    return_code = r.i16()
    debug_message = deserialize(r, r.u8())
    return OperationResponse(op_code, return_code, debug_message,
                             deserialize_parameter_table(r))


def deserialize_event(r: ByteReader) -> EventData:
    return EventData(r.u8(), deserialize_parameter_table(r))
