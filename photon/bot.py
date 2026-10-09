"""PhotonBot: the one class an application needs.

Wraps the Realtime client and the PUN layer, drives the 100 ms serialization
timer, and exposes connect/join/instantiate/rpc in a single place.
"""

import asyncio

from .protocol.constants import (
    PUN_VERSION,
    SERIALIZATION_RATE_MS,
    EventCaching,
    ReceiverGroup,
)
from .protocol.custom_types import Quaternion, Vector3
from .pun.network import PhotonNetwork
from .pun.serialize import IDENTITY, ZERO
from .pun.view import PhotonView
from .realtime import operations as ops
from .realtime.client import ClientState, LoadBalancingClient
from .realtime.room import Player, Room


class PhotonBot:
    def __init__(self, app_id: str, game_version: str = "1.0", *,
                 region: str = "eu", nick_name: str = "",
                 user_id: str | None = None,
                 auth_type: int | None = None,
                 auth_get_parameters: str | None = None,
                 auth_post_data=None,
                 protocol_version: tuple[int, int] = (1, 6)):
        # The server reads the PUN version off the app version string, so a
        # bare game version would make us look like a plain Realtime client.
        self.client = LoadBalancingClient(
            app_id, f"{game_version}_{PUN_VERSION}", region=region,
            nick_name=nick_name, user_id=user_id,
            auth_type=auth_type,
            auth_get_parameters=auth_get_parameters,
            auth_post_data=auth_post_data,
            protocol_version=protocol_version)
        self.network = PhotonNetwork(self.client)

    # --- registration ---------------------------------------------------------

    def register_prefab(self, name: str, factory) -> None:
        self.network.prefabs.register(name, factory)

    def on_event(self, handler) -> None:
        self.client.event_handlers.append(handler)

    # --- state ----------------------------------------------------------------

    @property
    def state(self) -> ClientState:
        return self.client.state

    @property
    def room(self) -> Room | None:
        return self.client.room

    @property
    def local_player(self) -> Player:
        return self.client.local_player

    @property
    def players(self) -> dict[int, Player]:
        return self.client.room.players if self.client.room else {}

    @property
    def server_time(self) -> int:
        return self.network.server_time

    # --- lifecycle ------------------------------------------------------------

    async def connect(self) -> None:
        await self.client.connect_to_master()

    async def join_lobby(self, name: str | None = None) -> None:
        await self.client.join_lobby(name)

    async def create_room(self, name: str, *, max_players: int = 0,
                          is_visible: bool = True,
                          is_open: bool = True) -> Room:
        room = await self.client.create_room(name, ops.RoomOptions(
            max_players=max_players, is_visible=is_visible, is_open=is_open))
        self.network.start_sync(SERIALIZATION_RATE_MS)
        return room

    async def join_room(self, name: str) -> Room:
        room = await self.client.join_room(name)
        self.network.start_sync(SERIALIZATION_RATE_MS)
        return room

    async def join_or_create_room(self, name: str, *, max_players: int = 0) -> Room:
        room = await self.client.join_or_create_room(
            name, ops.RoomOptions(max_players=max_players))
        self.network.start_sync(SERIALIZATION_RATE_MS)
        return room

    async def set_room_properties(self, properties: dict,
                                  expected: dict | None = None) -> None:
        await self.client.set_room_properties(properties, expected)

    async def set_player_properties(self, properties: dict) -> None:
        await self.client.set_player_properties(properties)

    async def leave_room(self) -> None:
        self.network.stop_sync()
        self.network.views.clear()
        await self.client.leave_room()

    async def disconnect(self) -> None:
        self.network.stop_sync()
        await self.client.disconnect()

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, *_):
        await self.disconnect()

    # --- gameplay -------------------------------------------------------------

    def instantiate(self, prefab_name: str, position: Vector3 = ZERO,
                    rotation: Quaternion = IDENTITY, **options) -> PhotonView:
        return self.network.instantiate(prefab_name, position, rotation, **options)

    def destroy(self, view: PhotonView) -> None:
        self.network.destroy(view)

    def rpc(self, view: PhotonView, method_name: str, *args,
            receivers: int = ReceiverGroup.OTHERS,
            target_actors: list[int] | None = None,
            caching: int = EventCaching.DO_NOT_CACHE) -> None:
        self.network.rpc(view, method_name, *args, receivers=receivers,
                         target_actors=target_actors, caching=caching)

    def raise_event(self, event_code: int, content=None, **options) -> None:
        self.client.raise_event(event_code, content, **options)

    async def run_forever(self) -> None:
        await asyncio.Event().wait()
