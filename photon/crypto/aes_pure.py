"""Pure-Python AES-CBC fallback, used only when `cryptography` is absent.

Photon encrypts two operations per session, so speed is irrelevant here.
"""

_SBOX = bytearray(256)
_INV_SBOX = bytearray(256)


def _build_tables() -> None:
    p = q = 1
    while True:
        p = p ^ ((p << 1) & 0xFF) ^ (0x1B if p & 0x80 else 0)
        q ^= q << 1
        q ^= q << 2
        q ^= q << 4
        q &= 0xFF
        if q & 0x80:
            q ^= 0x09
        value = q ^ ((q << 1) | (q >> 7)) ^ ((q << 2) | (q >> 6)) \
            ^ ((q << 3) | (q >> 5)) ^ ((q << 4) | (q >> 4))
        value = (value ^ 0x63) & 0xFF
        _SBOX[p] = value
        _INV_SBOX[value] = p
        if p == 1:
            break
    _SBOX[0] = 0x63
    _INV_SBOX[0x63] = 0


_build_tables()

_RCON = [0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80, 0x1B, 0x36,
         0x6C, 0xD8, 0xAB, 0x4D]


def _xtime(a: int) -> int:
    a <<= 1
    return (a ^ 0x1B) & 0xFF if a & 0x100 else a


def _mul(a: int, b: int) -> int:
    result = 0
    while b:
        if b & 1:
            result ^= a
        a = _xtime(a)
        b >>= 1
    return result


def _expand_key(key: bytes) -> list[list[int]]:
    nk = len(key) // 4
    rounds = nk + 6
    words = [list(key[4 * i:4 * i + 4]) for i in range(nk)]
    for i in range(nk, 4 * (rounds + 1)):
        temp = list(words[i - 1])
        if i % nk == 0:
            temp = temp[1:] + temp[:1]
            temp = [_SBOX[b] for b in temp]
            temp[0] ^= _RCON[i // nk - 1]
        elif nk > 6 and i % nk == 4:
            temp = [_SBOX[b] for b in temp]
        words.append([words[i - nk][j] ^ temp[j] for j in range(4)])
    return [sum(words[4 * r:4 * r + 4], []) for r in range(rounds + 1)]


def _add_round_key(state: list[int], round_key: list[int]) -> None:
    for i in range(16):
        state[i] ^= round_key[i]


def _shift_rows(s: list[int]) -> list[int]:
    return [s[0], s[5], s[10], s[15],
            s[4], s[9], s[14], s[3],
            s[8], s[13], s[2], s[7],
            s[12], s[1], s[6], s[11]]


def _inv_shift_rows(s: list[int]) -> list[int]:
    return [s[0], s[13], s[10], s[7],
            s[4], s[1], s[14], s[11],
            s[8], s[5], s[2], s[15],
            s[12], s[9], s[6], s[3]]


def _mix_columns(s: list[int], inverse: bool = False) -> list[int]:
    coefficients = (14, 11, 13, 9) if inverse else (2, 3, 1, 1)
    out = [0] * 16
    for c in range(4):
        col = s[4 * c:4 * c + 4]
        for r in range(4):
            out[4 * c + r] = (
                _mul(col[0], coefficients[(0 - r) % 4])
                ^ _mul(col[1], coefficients[(1 - r) % 4])
                ^ _mul(col[2], coefficients[(2 - r) % 4])
                ^ _mul(col[3], coefficients[(3 - r) % 4])
            )
    return out


def _encrypt_block(block: bytes, round_keys: list[list[int]]) -> bytes:
    state = list(block)
    _add_round_key(state, round_keys[0])
    for rnd in range(1, len(round_keys) - 1):
        state = [_SBOX[b] for b in state]
        state = _shift_rows(state)
        state = _mix_columns(state)
        _add_round_key(state, round_keys[rnd])
    state = [_SBOX[b] for b in state]
    state = _shift_rows(state)
    _add_round_key(state, round_keys[-1])
    return bytes(state)


def _decrypt_block(block: bytes, round_keys: list[list[int]]) -> bytes:
    state = list(block)
    _add_round_key(state, round_keys[-1])
    for rnd in range(len(round_keys) - 2, 0, -1):
        state = _inv_shift_rows(state)
        state = [_INV_SBOX[b] for b in state]
        _add_round_key(state, round_keys[rnd])
        state = _mix_columns(state, inverse=True)
    state = _inv_shift_rows(state)
    state = [_INV_SBOX[b] for b in state]
    _add_round_key(state, round_keys[0])
    return bytes(state)


def aes_cbc_encrypt(key: bytes, data: bytes, iv: bytes = bytes(16)) -> bytes:
    round_keys = _expand_key(key)
    previous = iv
    out = bytearray()
    for i in range(0, len(data), 16):
        block = bytes(a ^ b for a, b in zip(data[i:i + 16], previous))
        previous = _encrypt_block(block, round_keys)
        out += previous
    return bytes(out)


def aes_cbc_decrypt(key: bytes, data: bytes, iv: bytes = bytes(16)) -> bytes:
    round_keys = _expand_key(key)
    previous = iv
    out = bytearray()
    for i in range(0, len(data), 16):
        chunk = data[i:i + 16]
        plain = _decrypt_block(chunk, round_keys)
        out += bytes(a ^ b for a, b in zip(plain, previous))
        previous = chunk
    return bytes(out)
