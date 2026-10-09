"""Message layer: operations in, events out, over an EnetPeerCore.

Sits between the raw ENet payloads and the Realtime client. Owns the message
envelope, the Diffie-Hellman handshake and payload encryption.
"""

import asyncio
import secrets

from .crypto import DiffieHellmanCryptoProvider
from .enet.peer_core import ConnectionState, EnetPeerCore, StatusCode
from .protocol import gpbinary16 as gp16
from .protocol import gpbinary18 as gp18
from .protocol.buffer import ByteReader, ByteWriter
from .protocol.constants import MessageType, PhotonCode
from .protocol.messages import parse_message, wrap_message
from .transport import ServiceLoop, UdpTransport


def build_operation(op_code: int, parameters: dict | None,
                    crypto: DiffieHellmanCryptoProvider | None = None,
                    msg_type: int = MessageType.OPERATION,
                    protocol_version: tuple[int, int] = (1, 6)) -> bytes:
    w = ByteWriter()
    if protocol_version == (1, 8):
        req = gp18.OperationRequest(op_code, parameters or {})
        gp18.serialize_operation_request(w, req)
    else:
        gp16.serialize_operation_request(w, op_code, parameters)
    body = w.to_bytes()
    if crypto is not None:
        return wrap_message(msg_type, crypto.encrypt(body), encrypted=True)
    return wrap_message(msg_type, body)


class PhotonConnection:
    """One UDP session to one Photon server."""

    def __init__(self, app_id: str, *, crc_enabled: bool = False,
                 protocol_version: tuple[int, int] = (1, 6)):
        self.app_id = app_id
        self.crc_enabled = crc_enabled
        self.protocol_version = protocol_version
        self.crypto: DiffieHellmanCryptoProvider | None = None
        self.core: EnetPeerCore | None = None
        self.incoming: asyncio.Queue = asyncio.Queue()
        self._service: ServiceLoop | None = None
        self._transport: UdpTransport | None = None
        self._connected: asyncio.Future | None = None
        self._encrypted: asyncio.Future | None = None

    @property
    def is_connected(self) -> bool:
        return self.core is not None and self.core.state is ConnectionState.CONNECTED

    async def connect(self, host: str, port: int, *, timeout: float = 10.0) -> None:
        loop = asyncio.get_running_loop()
        self.core = EnetPeerCore(self.app_id,
                                 challenge=secrets.randbits(31),
                                 crc_enabled=self.crc_enabled,
                                 protocol_version=self.protocol_version)

        self._connected = loop.create_future()
        _, self._transport = await loop.create_datagram_endpoint(
            lambda: UdpTransport(self._on_datagram), remote_addr=(host, port))
        self._service = ServiceLoop(self.core, self._transport)
        self.core.start_connect(self._service.now_ms())
        self._service.start()
        await asyncio.wait_for(self._connected, timeout)

    async def close(self) -> None:
        if self.core is not None:
            self.core.disconnect()
            if self._service is not None:
                self._service.flush()
                await self._service.stop()
        if self._transport is not None:
            self._transport.close()
        self.core = None
        self._service = None
        self._transport = None

    async def establish_encryption(self, *, timeout: float = 10.0) -> None:
        """Internal op 0: exchange DH public keys, derive the AES key."""
        loop = asyncio.get_running_loop()
        self.crypto = DiffieHellmanCryptoProvider()
        self._encrypted = loop.create_future()
        self.send_operation(PhotonCode.INIT_ENCRYPTION,
                            {PhotonCode.CLIENT_KEY: self.crypto.public_key},
                            msg_type=MessageType.INTERNAL_OPERATION_REQUEST)
        await asyncio.wait_for(self._encrypted, timeout)

    def send_operation(self, op_code: int, parameters: dict | None = None, *,
                       encrypt: bool = False,
                       msg_type: int = MessageType.OPERATION,
                       reliable: bool = True, channel: int = 0) -> None:
        crypto = self.crypto if encrypt else None
        if encrypt and (crypto is None or not crypto.is_initialized):
            raise RuntimeError("encryption requested before the key exchange")
        payload = build_operation(op_code, parameters, crypto, msg_type,
                                  protocol_version=self.protocol_version)
        self.core.enqueue_message(payload, channel=channel, reliable=reliable)
        if self._service is not None:
            self._service.flush()

    # --- inbound -------------------------------------------------------------

    def _on_datagram(self, data: bytes) -> None:
        self.core.on_datagram(data, self._service.now_ms())
        for payload in self.core.take_incoming():
            self._on_payload(payload)
        for status in self.core.take_status():
            self._on_status(status)
        self._service.flush()

    def _on_payload(self, payload: bytes) -> None:
        try:
            message = parse_message(payload)
            body = message.body
            if message.encrypted:
                body = self.crypto.decrypt(body)
            reader = ByteReader(body)
            gp = gp18 if self.protocol_version == (1, 8) else gp16

            if message.msg_type == MessageType.INIT_RESPONSE:
                self._resolve(self._connected)
            elif message.msg_type == MessageType.EVENT:
                self.incoming.put_nowait(gp.deserialize_event(reader))
            elif message.msg_type in (MessageType.OPERATION_RESPONSE,
                                      MessageType.INTERNAL_OPERATION_RESPONSE):
                response = gp.deserialize_operation_response(reader)
                if message.msg_type == MessageType.INTERNAL_OPERATION_RESPONSE:
                    self._on_internal_response(response)
                else:
                    self.incoming.put_nowait(response)
        except Exception as e:
            pass


    def _on_internal_response(self, response) -> None:
        if response.op_code != PhotonCode.INIT_ENCRYPTION:
            return
        server_key = response.parameters.get(PhotonCode.CLIENT_KEY)
        if server_key is None:
            self._fail(self._encrypted,
                       RuntimeError(f"key exchange failed: {response.debug_message}"))
            return
        self.crypto.derive_shared_key(bytes(server_key))
        self._resolve(self._encrypted)

    def _on_status(self, status: StatusCode) -> None:
        if status in (StatusCode.DISCONNECT, StatusCode.TIMEOUT_DISCONNECT):
            error = ConnectionError(f"disconnected: {status.name}")
            self._fail(self._connected, error)
            self._fail(self._encrypted, error)
        self.incoming.put_nowait(status)

    @staticmethod
    def _resolve(future: asyncio.Future | None) -> None:
        if future is not None and not future.done():
            future.set_result(None)

    @staticmethod
    def _fail(future: asyncio.Future | None, error: Exception) -> None:
        if future is not None and not future.done():
            future.set_exception(error)
