"""LoadBalancingClient: NameServer -> Master -> GameServer, and room state.

Each server hop tears down the whole connection and builds a new one, exactly
as the C# client does — a Photon peer is bound to one server for its lifetime.
"""

import asyncio
import logging
import traceback
from enum import IntEnum
from typing import Any

from ..enet.peer_core import StatusCode
from ..protocol.constants import (
    ActorProperty,
    EventCode,
    GamePropertyKey,
    JoinMode,
    ParameterCode,
)
from ..protocol.gpbinary16 import EventData, OperationResponse, PhotonByte
from ..session import PhotonConnection
from . import operations as ops
from .room import Player, Room

log = logging.getLogger(__name__)

NAME_SERVER_HOST = "ns.photonengine.io"
NAME_SERVER_PORT = 5058


class ClientState(IntEnum):
    DISCONNECTED = 0
    CONNECTING_TO_NAME_SERVER = 1
    CONNECTED_TO_NAME_SERVER = 2
    CONNECTING_TO_MASTER = 3
    CONNECTED_TO_MASTER = 4
    JOINING_LOBBY = 5
    JOINED_LOBBY = 6
    JOINING = 7
    CONNECTING_TO_GAME_SERVER = 8
    JOINED = 9


class PhotonError(Exception):
    def __init__(self, op_code: int, return_code: int, message: str | None):
        super().__init__(f"op {op_code} failed: {return_code} {message!r}")
        self.op_code = op_code
        self.return_code = return_code
        self.message = message


def split_address(address: str) -> tuple[str, int]:
    host, _, port = address.rpartition(":")
    return host, int(port)


class LoadBalancingClient:
    def __init__(self, app_id: str, app_version: str, *,
                 user_id: str | None = None, region: str = "eu",
                 nick_name: str = "",
                 protocol_version: tuple[int, int] = (1, 6),
                 auth_type: int | None = None,
                 auth_get_parameters: str | None = None,
                 auth_post_data: Any = None):
        self.app_id = app_id
        self.app_version = app_version
        self.user_id = user_id
        self.region = region
        self.nick_name = nick_name
        self.protocol_version = protocol_version
        self.auth_type = auth_type
        self.auth_get_parameters = auth_get_parameters
        self.auth_post_data = auth_post_data

        self.state = ClientState.DISCONNECTED
        self.connection: PhotonConnection | None = None
        self.token = None
        self.master_address: str | None = None
        self.game_address: str | None = None
        self.room: Room | None = None
        self.local_player = Player(0, is_local=True)

        self.event_handlers: list = []
        self._pending: dict[int, asyncio.Future] = {}
        self._pump: asyncio.Task | None = None

    # --- connection lifecycle -------------------------------------------------

    async def connect_to_name_server(self) -> None:
        self.state = ClientState.CONNECTING_TO_NAME_SERVER
        await self._open(NAME_SERVER_HOST, NAME_SERVER_PORT)
        await self.connection.establish_encryption()
        self.state = ClientState.CONNECTED_TO_NAME_SERVER

    async def connect_to_master(self) -> None:
        """Authenticate on the NameServer, then hop to the returned Master."""
        if self.state is ClientState.DISCONNECTED:
            await self.connect_to_name_server()

        response = await self.authenticate()
        self.master_address = response.parameters[ParameterCode.ADDRESS]

        self.state = ClientState.CONNECTING_TO_MASTER
        host, port = split_address(self.master_address)
        await self._open(host, port)
        await self.authenticate()
        self.state = ClientState.CONNECTED_TO_MASTER

    async def authenticate(self) -> OperationResponse:
        """A token means re-auth on a new server, which goes out unencrypted."""
        op_code, parameters, encrypt = ops.op_authenticate(
            self.app_id, self.app_version, region=self.region,
            user_id=self.user_id, token=self.token,
            nick_name=self.nick_name,
            auth_type=self.auth_type,
            auth_get_parameters=self.auth_get_parameters,
            auth_post_data=self.auth_post_data)
        response = await self.send_operation(op_code, parameters, encrypt=encrypt)
        incoming_id = response.parameters.get(ParameterCode.USER_ID)
        if incoming_id:
            self.user_id = incoming_id
        incoming_token = response.parameters.get(ParameterCode.TOKEN)
        if incoming_token is not None:
            self.token = incoming_token
        return response

    async def get_regions(self) -> dict[str, str]:
        op_code, parameters, encrypt = ops.op_get_regions(self.app_id)
        response = await self.send_operation(op_code, parameters, encrypt=encrypt)
        return dict(zip(response.parameters[ParameterCode.REGION],
                        response.parameters[ParameterCode.ADDRESS]))

    async def join_lobby(self, name: str | None = None, lobby_type: int = 0) -> None:
        self.state = ClientState.JOINING_LOBBY
        await self.send_operation(*ops.op_join_lobby(name, lobby_type)[:2])
        self.state = ClientState.JOINED_LOBBY

    async def create_room(self, name: str, options: ops.RoomOptions | None = None) -> Room:
        return await self._enter_room(ops.op_create_room, ops.EnterRoomParams(
            room_name=name, room_options=options or ops.RoomOptions()))

    async def join_room(self, name: str) -> Room:
        return await self._enter_room(ops.op_join_room,
                                      ops.EnterRoomParams(room_name=name))

    async def join_or_create_room(self, name: str,
                                  options: ops.RoomOptions | None = None) -> Room:
        return await self._enter_room(ops.op_join_room, ops.EnterRoomParams(
            room_name=name, room_options=options or ops.RoomOptions(),
            join_mode=JoinMode.CREATE_IF_NOT_EXISTS))

    async def _enter_room(self, builder, params: ops.EnterRoomParams) -> Room:
        self.state = ClientState.JOINING
        response = await self.send_operation(*builder(params)[:2])
        self.game_address = response.parameters[ParameterCode.ADDRESS]
        params.room_name = response.parameters.get(ParameterCode.ROOM_NAME,
                                                   params.room_name)

        self.state = ClientState.CONNECTING_TO_GAME_SERVER
        host, port = split_address(self.game_address)
        await self._open(host, port)
        await self.authenticate()

        params.on_game_server = True
        if self.nick_name:
            params.player_properties = {PhotonByte(ActorProperty.PLAYER_NAME): self.nick_name}
        op_code, parameters, encrypt = builder(params)
        response = await self.send_operation(op_code, parameters, encrypt=encrypt)

        self.room = Room(params.room_name or "")
        actor_nr = response.parameters[ParameterCode.ACTOR_NR]
        self.local_player = self.room.add_player(actor_nr, is_local=True)
        # Cache the nick we sent, since the server doesn't echo it back.
        if self.nick_name:
            self.local_player.cache_properties({ActorProperty.PLAYER_NAME: self.nick_name})
        for existing in response.parameters.get(ParameterCode.ACTOR_LIST, []):
            self.room.add_player(existing)
        self.room.cache_properties(response.parameters.get(ParameterCode.GAME_PROPERTIES))

        # On join, 249 maps every actor number to that actor's properties —
        # it is not the local player's property set.
        for player_nr, properties in (
                response.parameters.get(ParameterCode.PLAYER_PROPERTIES) or {}).items():
            self.room.add_player(player_nr).cache_properties(properties)
        self.state = ClientState.JOINED
        return self.room

    async def set_room_properties(self, properties: dict,
                                  expected: dict | None = None) -> None:
        await self.send_operation(*ops.op_set_properties_of_room(properties, expected)[:2])
        if self.room is not None:
            self.room.cache_properties(properties)

    async def set_player_properties(self, properties: dict, actor_nr: int = 0) -> None:
        actor_nr = actor_nr or self.local_player.actor_number
        await self.send_operation(*ops.op_set_properties_of_actor(actor_nr, properties)[:2])
        if self.room is not None:
            self.room.add_player(actor_nr).cache_properties(properties)

    async def leave_room(self, become_inactive: bool = False) -> None:
        await self.send_operation(*ops.op_leave_room(become_inactive)[:2])
        self.room = None
        self.state = ClientState.CONNECTED_TO_MASTER

    async def disconnect(self) -> None:
        if self._pump is not None:
            self._pump.cancel()
            self._pump = None
        if self.connection is not None:
            await self.connection.close()
            self.connection = None
        self.state = ClientState.DISCONNECTED

    async def _open(self, host: str, port: int) -> None:
        """Tear down the previous peer and build a fresh one for this server."""
        if self._pump is not None:
            self._pump.cancel()
        if self.connection is not None:
            await self.connection.close()
        self.connection = PhotonConnection(self.app_id, protocol_version=self.protocol_version)
        await self.connection.connect(host, port)
        self._pump = asyncio.create_task(self._pump_incoming())


    # --- operations and events ------------------------------------------------

    async def send_operation(self, op_code: int, parameters: dict | None = None, *,
                             encrypt: bool = False,
                             timeout: float = 10.0) -> OperationResponse:
        future = asyncio.get_running_loop().create_future()
        self._pending[op_code] = future
        self.connection.send_operation(op_code, parameters, encrypt=encrypt)
        try:
            return await asyncio.wait_for(future, timeout)
        finally:
            self._pending.pop(op_code, None)

    def raise_event(self, event_code: int, content=None, *, reliable: bool = True,
                    **options) -> None:
        op_code, parameters, encrypt = ops.op_raise_event(event_code, content, **options)
        self.connection.send_operation(op_code, parameters, reliable=reliable)

    async def _pump_incoming(self) -> None:
        while True:
            try:
                item = await self.connection.incoming.get()
                if isinstance(item, OperationResponse):
                    self._on_response(item)
                elif isinstance(item, EventData):
                    self._on_event(item)
                elif isinstance(item, StatusCode):
                    if item in (StatusCode.DISCONNECT, StatusCode.TIMEOUT_DISCONNECT,
                                StatusCode.DISCONNECT_BY_SERVER_USER_LIMIT,
                                StatusCode.DISCONNECT_BY_SERVER_LOGIC,
                                StatusCode.DISCONNECT_BY_SERVER_REASON_UNKNOWN):
                        self.state = ClientState.DISCONNECTED
            except Exception as e:
                import traceback
                print(f"[CLIENT PUMP ERROR] {e}\n{traceback.format_exc()}", flush=True)

    def _on_response(self, response: OperationResponse) -> None:
        # Any response may carry a fresh token, and the GameServer only accepts
        # the one handed out by the Master's join/create reply.
        token = response.parameters.get(ParameterCode.TOKEN)
        if token is not None:
            self.token = token

        future = self._pending.get(response.op_code)
        if future is None or future.done():
            return
        if response.return_code != 0:
            future.set_exception(PhotonError(response.op_code, response.return_code,
                                             response.debug_message))
        else:
            future.set_result(response)

    def _on_event(self, event: EventData) -> None:
        if self.room is not None:
            try:
                self._apply_room_event(event)
            except Exception as e:
                import traceback
                print(f"[APPLY ROOM EVENT ERROR] {e}\n{traceback.format_exc()}", flush=True)
        for handler in list(self.event_handlers):
            try:
                handler(event)
            except Exception as e:
                import traceback
                print(f"[EVENT HANDLER ERROR] {e}\n{traceback.format_exc()}", flush=True)

    def _apply_room_event(self, event: EventData) -> None:
        parameters = event.parameters
        if event.code == EventCode.JOIN:
            actor_nr = parameters.get(ParameterCode.ACTOR_NR)
            if actor_nr is not None:
                for existing in parameters.get(ParameterCode.ACTOR_LIST, []):
                    self.room.add_player(existing)
                player = self.room.add_player(actor_nr)
                player.cache_properties(parameters.get(ParameterCode.PLAYER_PROPERTIES))
        elif event.code == EventCode.LEAVE:
            actor_nr = parameters.get(ParameterCode.ACTOR_NR)
            if actor_nr is not None:
                self.room.remove_player(actor_nr)
            actor_list = parameters.get(ParameterCode.ACTOR_LIST)
            if isinstance(actor_list, (list, tuple)):
                # Sync remaining players with the authoritative actor list from server
                for a in list(self.room.players.keys()):
                    if a not in actor_list:
                        self.room.remove_player(a)
            master_id = parameters.get(ParameterCode.MASTER_CLIENT_ID, parameters.get(203, parameters.get(248)))
            if master_id is not None:
                self.room.master_client_id = master_id
        elif event.code == EventCode.PROPERTIES_CHANGED:
            properties = parameters.get(ParameterCode.PROPERTIES, {})
            target = parameters.get(ParameterCode.TARGET_ACTOR_NR, 0)
            if target:
                self.room.add_player(target).cache_properties(properties)
            else:
                self.room.cache_properties(properties)
                if isinstance(properties, dict):
                    m_id = properties.get(248, properties.get(GamePropertyKey.MASTER_CLIENT_ID))
                    if m_id is not None:
                        self.room.master_client_id = m_id