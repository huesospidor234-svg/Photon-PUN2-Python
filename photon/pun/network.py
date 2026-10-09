"""PhotonNetwork: the PUN facade over a LoadBalancingClient.

Owns view IDs, the two PUN timers (33 ms service, 100 ms serialization) and the
routing of PUN events onto registered objects.
"""

import asyncio
import logging

from ..protocol.constants import (
    SERIALIZATION_RATE_MS,
    EventCaching,
    EventCode,
    ParameterCode,
    PunEvent,
    ReceiverGroup,
)
from ..protocol.custom_types import Quaternion, Vector3
from ..protocol.gpbinary16 import Hashtable, IntArray, PhotonByte
from ..realtime.client import LoadBalancingClient
from . import rpc as rpc_module
from . import serialize as ser
from .registry import PrefabRegistry, RpcRegistry, ViewRegistry
from .stream import PhotonStream, delta_compress, delta_decompress
from .view import PhotonView

# Destroy(204) and DestroyPlayer(207) carry a single value under key 0.
DESTROY_KEY = 0

log = logging.getLogger(__name__)


class PhotonNetwork:
    def __init__(self, client: LoadBalancingClient):
        self.client = client
        self.views = ViewRegistry()
        self.prefabs = PrefabRegistry()
        self.rpcs = RpcRegistry()
        self.level_prefix = 0
        self._received: dict[int, list] = {}
        self._sync_task: asyncio.Task | None = None
        client.event_handlers.append(self.on_event)

    @property
    def local_actor_nr(self) -> int:
        return self.client.local_player.actor_number

    @property
    def server_time(self) -> int:
        return self.client.connection.core.server_time_ms

    # --- lifecycle ------------------------------------------------------------

    def start_sync(self, interval_ms: int = SERIALIZATION_RATE_MS) -> None:
        if self._sync_task is None:
            self._sync_task = asyncio.create_task(self._sync_loop(interval_ms / 1000))

    def stop_sync(self) -> None:
        if self._sync_task is not None:
            self._sync_task.cancel()
            self._sync_task = None

    async def _sync_loop(self, interval: float) -> None:
        loop = asyncio.get_running_loop()
        deadline = loop.time()
        while True:
            self.send_serialize()
            deadline += interval
            await asyncio.sleep(max(0.0, deadline - loop.time()))

    # --- spawning -------------------------------------------------------------

    def instantiate(self, prefab_name: str, position: Vector3 = ser.ZERO,
                    rotation: Quaternion = ser.IDENTITY, *, group: int = 0,
                    data: list | None = None, view_count: int = 1,
                    scene_object: bool = False) -> PhotonView:
        owner = 0 if scene_object else self.local_actor_nr
        view_ids = [self.views.allocate_id(owner) for _ in range(view_count)]
        context = ser.InstantiateContext(
            prefab_name=prefab_name, view_ids=view_ids, position=position,
            rotation=rotation, group=group, data=list(data or []),
            timestamp=self.server_time, owner_actor_nr=owner,
            level_prefix=self.level_prefix)

        view = self._materialize(context)
        caching = (EventCaching.ADD_TO_ROOM_CACHE_GLOBAL if scene_object
                   else EventCaching.ADD_TO_ROOM_CACHE)
        self.client.raise_event(PunEvent.INSTANTIATION,
                                ser.build_instantiate(context), caching=caching)
        return view

    def _materialize(self, context: ser.InstantiateContext) -> PhotonView:
        target = self.prefabs.create(context.prefab_name, context)
        view = PhotonView(context.view_id, target,
                          local_actor_nr=self.local_actor_nr,
                          prefab_name=context.prefab_name,
                          instantiation_data=context.data)
        view.group = context.group
        self.views.add(view)
        for extra_id in context.view_ids[1:]:
            self.views.add(PhotonView(extra_id, target,
                                      local_actor_nr=self.local_actor_nr,
                                      prefab_name=context.prefab_name))
        return view

    def destroy(self, view: PhotonView) -> None:
        self._remove_views_of(view.view_id)
        self.client.raise_event(PunEvent.DESTROY,
                                Hashtable({PhotonByte(DESTROY_KEY): view.view_id}),
                                receivers=ReceiverGroup.ALL)

    def destroy_player_objects(self, actor_number: int) -> None:
        for view in self.views.owned_by(actor_number):
            self.views.remove(view.view_id)
        self.client.raise_event(PunEvent.DESTROY_PLAYER,
                                Hashtable({PhotonByte(DESTROY_KEY): actor_number}),
                                receivers=ReceiverGroup.ALL)

    def _remove_views_of(self, instantiation_id: int) -> None:
        removed = self.views.remove(instantiation_id)
        if removed is None:
            return
        if removed.target is not None:
            for view_id, view in list(self.views.views.items()):
                if view.target is removed.target:
                    self.views.remove(view_id)
                self._received.pop(view_id, None)
        self._received.pop(instantiation_id, None)

    # --- RPC ------------------------------------------------------------------

    def rpc(self, view: PhotonView | int, method_name: str | None = None, *args,
            shortcut: int | None = None,
            receivers: int = ReceiverGroup.OTHERS,
            target_actors: list[int] | None = None,
            caching: int = EventCaching.DO_NOT_CACHE) -> None:
        view_id = view.view_id if hasattr(view, "view_id") else int(view)
        
        # When shortcut is provided, method_name is optional. If method_name is set but
        # represents an argument, or if passed as None, normalize args correctly.
        if shortcut is not None:
            if method_name is not None and not args:
                # E.g. net.rpc(view_id, "chat_msg", shortcut=28)
                all_args = [method_name]
                actual_method = None
            elif method_name is not None:
                # E.g. net.rpc(view_id, arg1, arg2, shortcut=28)
                all_args = [method_name, *args]
                actual_method = None
            else:
                all_args = list(args)
                actual_method = None
        else:
            actual_method = str(method_name or "")
            all_args = list(args)

        content = rpc_module.build_rpc(view_id, actual_method or "", all_args,
                                       timestamp=self.server_time,
                                       level_prefix=self.level_prefix,
                                       shortcut=shortcut)
        # ALL means "including me", which PUN implements by calling locally.
        if receivers == ReceiverGroup.ALL and target_actors is None:
            rpc_module.dispatch_rpc(self.views, self.rpcs, content,
                                    self.local_actor_nr)
            receivers = ReceiverGroup.OTHERS
        if target_actors is not None and not isinstance(target_actors, IntArray):
            target_actors = IntArray(target_actors)
        self.client.raise_event(PunEvent.RPC, content, receivers=receivers,
                                target_actors=target_actors, caching=caching)

    # --- view synchronization -------------------------------------------------

    def send_serialize(self, reliable: bool = False) -> None:
        entries = []
        for view in self.views.views.values():
            if not view.synchronization or not view.is_mine or view.target is None:
                continue
            stream = PhotonStream(is_writing=True)
            view.serialize(stream, rpc_module.RpcInfo(self.local_actor_nr,
                                                      self.server_time, view.view_id))
            values = stream.to_list()
            if not values:
                continue
            # Reliable batches must be self-contained: a dropped unreliable
            # frame would leave the peer's baseline out of step with ours.
            if reliable:
                sent, nulls = list(values), None
            else:
                sent, nulls = delta_compress(values, view._last_sent)
                if nulls is not None and len(nulls) == len(values):
                    continue  # nothing changed at all
            view._last_sent = list(values)
            entries.append(ser.build_view_data(view.view_id, sent, nulls))

        if not entries:
            return
        batch = ser.build_sync_batch(self.server_time, entries, self.level_prefix)
        event_code = (PunEvent.SEND_SERIALIZE_RELIABLE if reliable
                      else PunEvent.SEND_SERIALIZE)
        self.client.raise_event(event_code, batch, reliable=reliable)

    # --- inbound --------------------------------------------------------------

    def on_event(self, event) -> None:
        sender = event.parameters.get(ParameterCode.ACTOR_NR, 0)
        content = event.parameters.get(ParameterCode.DATA)
        if event.code == PunEvent.RPC:
            rpc_module.dispatch_rpc(self.views, self.rpcs, content, sender)
        elif event.code == PunEvent.INSTANTIATION:
            self._materialize(ser.parse_instantiate(content, sender))
        elif event.code == PunEvent.DESTROY:
            inst_id = content.get(DESTROY_KEY) if isinstance(content, dict) else content
            if inst_id is not None:
                self._remove_views_of(int(inst_id))
        elif event.code == PunEvent.DESTROY_PLAYER:
            act_nr = content.get(DESTROY_KEY) if isinstance(content, dict) else content
            if act_nr is not None:
                self._on_destroy_player(int(act_nr))
        elif event.code in (PunEvent.SEND_SERIALIZE,
                            PunEvent.SEND_SERIALIZE_RELIABLE):
            self._on_serialize(content, sender)
        elif event.code == EventCode.LEAVE:
            if sender > 0:
                self._on_destroy_player(sender)

    def _on_destroy_player(self, actor_number: int) -> None:
        if actor_number <= 0 and actor_number != -1:
            return
        targets = (list(self.views.views.values()) if actor_number == -1
                   else self.views.owned_by(actor_number))
        for view in targets:
            self.views.remove(view.view_id)
            self._received.pop(view.view_id, None)

    def _on_serialize(self, batch, sender: int) -> None:
        try:
            if not isinstance(batch, (list, tuple)):
                return
            timestamp, _, entries = ser.parse_sync_batch(batch)
            for entry in entries:
                try:
                    view_id, _, nulls, values = ser.parse_view_data(entry)
                    if not view_id or view_id <= 0:
                        continue
                    restored = delta_decompress(values, nulls, self._received.get(view_id))
                    self._received[view_id] = restored
                    view = self.views.get(view_id)
                    if view is not None and not view.is_mine:
                        view.serialize(PhotonStream(is_writing=False, data=restored),
                                       rpc_module.RpcInfo(sender, timestamp, view_id))
                except Exception:
                    pass
        except Exception:
            pass
