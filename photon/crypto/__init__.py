"""Diffie-Hellman key exchange + AES-256-CBC payload encryption.

Mandatory for the first authentication: OpAuthenticate without a token and
OpGetRegions both go out encrypted. Photon uses Oakley group 1 with generator
22, SHA-256 over the shared secret, AES-256-CBC with a zero IV and PKCS7.

Big-integer wire format ("Photon big int") is little-endian magnitude — the
reverse of .NET's BigInteger.ToByteArray, with the sign byte stripped.
"""

import hashlib
import secrets

OAKLEY_PRIME_768 = int.from_bytes(bytes([
    255, 255, 255, 255, 255, 255, 255, 255, 32, 54,
    58, 166, 233, 66, 76, 244, 198, 126, 94, 98,
    118, 181, 133, 228, 69, 194, 81, 109, 109, 53,
    225, 79, 55, 20, 95, 242, 109, 10, 43, 48,
    27, 67, 58, 205, 179, 25, 149, 239, 221, 4,
    52, 142, 121, 8, 74, 81, 34, 155, 19, 59,
    166, 190, 11, 2, 116, 204, 103, 138, 8, 78,
    2, 41, 209, 28, 220, 128, 139, 98, 198, 196,
    52, 194, 104, 33, 162, 218, 15, 201, 255, 255,
    255, 255, 255, 255, 255, 255,
][::-1]), "big")

GENERATOR = 22
SECRET_BITS = 160
BLOCK_SIZE = 16
ZERO_IV = bytes(BLOCK_SIZE)


def to_photon_bigint(value: int) -> bytes:
    """Big-endian magnitude, matching MsBigIntArrayToPhotonBigIntArray.

    .NET's BigInteger.ToByteArray is little-endian two's complement; Photon
    reverses it and strips the leading sign byte, which leaves exactly the
    minimal big-endian magnitude.
    """
    length = max(1, (value.bit_length() + 7) // 8)
    return value.to_bytes(length, "big")


def from_photon_bigint(data: bytes) -> int:
    return int.from_bytes(data, "big")


def pkcs7_pad(data: bytes) -> bytes:
    pad = BLOCK_SIZE - len(data) % BLOCK_SIZE
    return data + bytes([pad]) * pad


def pkcs7_unpad(data: bytes) -> bytes:
    if not data or len(data) % BLOCK_SIZE:
        raise ValueError("ciphertext is not block-aligned")
    pad = data[-1]
    if not 1 <= pad <= BLOCK_SIZE or data[-pad:] != bytes([pad]) * pad:
        raise ValueError("bad PKCS7 padding")
    return data[:-pad]


class DiffieHellmanCryptoProvider:
    """Client half of the Photon key exchange."""

    def __init__(self, secret: int | None = None):
        if secret is None:
            secret = self._random_secret()
        self.secret = secret
        self.public_key_int = pow(GENERATOR, secret, OAKLEY_PRIME_768)
        self.shared_key: bytes | None = None
        self._cipher_key: bytes | None = None

    @staticmethod
    def _random_secret() -> int:
        while True:
            # .NET reads the bytes as a signed little-endian BigInteger, so the
            # value can land outside the valid range and get redrawn.
            candidate = int.from_bytes(secrets.token_bytes(SECRET_BITS // 8),
                                       "little", signed=True)
            if 2 <= candidate < OAKLEY_PRIME_768 - 1:
                return candidate

    @property
    def public_key(self) -> bytes:
        return to_photon_bigint(self.public_key_int)

    @property
    def is_initialized(self) -> bool:
        return self._cipher_key is not None

    def derive_shared_key(self, other_public_key: bytes) -> None:
        other = from_photon_bigint(other_public_key)
        shared = pow(other, self.secret, OAKLEY_PRIME_768)
        self.shared_key = to_photon_bigint(shared)
        self._cipher_key = hashlib.sha256(self.shared_key).digest()

    def encrypt(self, data: bytes) -> bytes:
        return _aes_cbc_encrypt(self._require_key(), pkcs7_pad(data))

    def decrypt(self, data: bytes) -> bytes:
        return pkcs7_unpad(_aes_cbc_decrypt(self._require_key(), data))

    def _require_key(self) -> bytes:
        if self._cipher_key is None:
            raise RuntimeError("shared key has not been derived yet")
        return self._cipher_key


try:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    def _aes_cbc_encrypt(key: bytes, data: bytes) -> bytes:
        encryptor = Cipher(algorithms.AES(key), modes.CBC(ZERO_IV)).encryptor()
        return encryptor.update(data) + encryptor.finalize()

    def _aes_cbc_decrypt(key: bytes, data: bytes) -> bytes:
        decryptor = Cipher(algorithms.AES(key), modes.CBC(ZERO_IV)).decryptor()
        return decryptor.update(data) + decryptor.finalize()

    HAVE_NATIVE_AES = True
except ImportError:  # pragma: no cover - exercised only without cryptography
    from .aes_pure import aes_cbc_decrypt as _aes_cbc_decrypt
    from .aes_pure import aes_cbc_encrypt as _aes_cbc_encrypt

    HAVE_NATIVE_AES = False
