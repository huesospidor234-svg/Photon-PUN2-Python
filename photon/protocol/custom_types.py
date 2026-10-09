"""Custom type registry — the Unity types PUN puts on the wire.

Type codes are the ASCII letters used by PUN/Realtime:
  Vector2 = 'W' (87), Vector3 = 'V' (86), Quaternion = 'Q' (81), Player = 'P' (80)
Vector2 is 'W' and Vector3 is 'V' — verified in CustomTypesUnity.cs:38-40.
Quaternion components go out in w,x,y,z order (CustomTypesUnity.cs:133).
"""

from typing import Any, Callable, NamedTuple

from .buffer import ByteReader, ByteWriter


class Vector2(NamedTuple):
    x: float = 0.0
    y: float = 0.0


class Vector3(NamedTuple):
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0


class Quaternion(NamedTuple):
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    w: float = 1.0


class PlayerRef(NamedTuple):
    """A Photon Player on the wire — serialized as its actor number."""
    actor_number: int


CODE_VECTOR2 = ord("W")      # 87
CODE_VECTOR3 = ord("V")      # 86
CODE_QUATERNION = ord("Q")   # 81
CODE_PLAYER = ord("P")       # 80


class CustomTypeInfo(NamedTuple):
    code: int
    py_type: type
    serialize: Callable[[ByteWriter, Any], None]
    deserialize: Callable[[ByteReader, int], Any]


_BY_CODE: dict[int, CustomTypeInfo] = {}
_BY_TYPE: dict[type, CustomTypeInfo] = {}


def register(code: int, py_type: type, serialize, deserialize) -> None:
    info = CustomTypeInfo(code, py_type, serialize, deserialize)
    _BY_CODE[code] = info
    _BY_TYPE[py_type] = info


def by_code(code: int) -> CustomTypeInfo | None:
    return _BY_CODE.get(code)


def by_type(py_type: type) -> CustomTypeInfo | None:
    return _BY_TYPE.get(py_type)


def deserialize_custom(code: int, data: bytes) -> Any:
    info = by_code(code)
    if info is None:
        return UnknownCustomType(code, data)
    r = ByteReader(data)
    return info.deserialize(r, len(data))


def serialize_custom(value: Any) -> tuple[int, bytes]:
    if isinstance(value, UnknownCustomType):
        return value.code, value.data
    info = by_type(type(value))
    if info is None:
        raise TypeError(f"Unregistered custom type: {type(value)}")
    w = ByteWriter()
    info.serialize(w, value)
    return info.code, w.to_bytes()



class UnknownCustomType(NamedTuple):
    """An unregistered custom type, kept verbatim so it can be echoed back."""
    code: int
    data: bytes


def _ser_vector2(w: ByteWriter, v: Vector2) -> None:
    w.f32(v.x)
    w.f32(v.y)


def _deser_vector2(r: ByteReader, length: int) -> Vector2:
    if length != 8:
        r.raw(length)
        return Vector2()
    return Vector2(r.f32(), r.f32())


def _ser_vector3(w: ByteWriter, v: Vector3) -> None:
    w.f32(v.x)
    w.f32(v.y)
    w.f32(v.z)


def _deser_vector3(r: ByteReader, length: int) -> Vector3:
    if length != 12:
        r.raw(length)
        return Vector3()
    return Vector3(r.f32(), r.f32(), r.f32())


def _ser_quaternion(w: ByteWriter, q: Quaternion) -> None:
    w.f32(q.w)
    w.f32(q.x)
    w.f32(q.y)
    w.f32(q.z)


def _deser_quaternion(r: ByteReader, length: int) -> Quaternion:
    if length != 16:
        r.raw(length)
        return Quaternion()
    qw, qx, qy, qz = r.f32(), r.f32(), r.f32(), r.f32()
    return Quaternion(qx, qy, qz, qw)


def _ser_player(w: ByteWriter, p: PlayerRef) -> None:
    w.i32(p.actor_number)


def _deser_player(r: ByteReader, length: int) -> PlayerRef:
    if length != 4:
        r.raw(length)
        return PlayerRef(0)
    return PlayerRef(r.i32())


register(CODE_VECTOR2, Vector2, _ser_vector2, _deser_vector2)
register(CODE_VECTOR3, Vector3, _ser_vector3, _deser_vector3)
register(CODE_QUATERNION, Quaternion, _ser_quaternion, _deser_quaternion)
register(CODE_PLAYER, PlayerRef, _ser_player, _deser_player)
