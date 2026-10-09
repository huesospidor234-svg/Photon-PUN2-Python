"""PhotonView: the network identity attached to a spawned object."""

from ..protocol.constants import MAX_VIEW_IDS
from .registry import collect_rpcs


class PhotonView:
    """One networked object. `target` is the plain Python object it wraps."""

    def __init__(self, view_id: int, target=None, *, local_actor_nr: int = 0,
                 prefab_name: str = "", instantiation_data=None):
        self.view_id = view_id
        self.target = target
        self.local_actor_nr = local_actor_nr
        self.prefab_name = prefab_name
        self.instantiation_data = instantiation_data
        self.controller_actor_nr = self.owner_actor_nr
        self.group = 0
        self.synchronization = True
        self.rpcs = collect_rpcs(target) if target is not None else {}
        self._last_sent: list | None = None

    @property
    def owner_actor_nr(self) -> int:
        """Scene objects carry sub-id only, so owner 0 falls out naturally."""
        return self.view_id // MAX_VIEW_IDS

    @property
    def sub_id(self) -> int:
        return self.view_id % MAX_VIEW_IDS

    @property
    def is_scene_view(self) -> bool:
        return self.owner_actor_nr == 0

    @property
    def is_mine(self) -> bool:
        return self.owner_actor_nr == self.local_actor_nr

    def call_rpc(self, method_name: str, args: list, info):
        method = self.rpcs.get(method_name)
        if method is None:
            return None
        return method(*args, info) if _wants_info(method) else method(*args)

    def serialize(self, stream, info) -> None:
        handler = getattr(self.target, "on_photon_serialize_view", None)
        if handler is not None:
            handler(stream, info)

    def __repr__(self):
        return f"PhotonView({self.view_id}, owner={self.owner_actor_nr})"


def _wants_info(method) -> bool:
    """PUN appends a PhotonMessageInfo only when the method declares it."""
    code = getattr(method, "__code__", None)
    if code is None:
        return False
    names = code.co_varnames[:code.co_argcount]
    return bool(names) and names[-1] == "info"
