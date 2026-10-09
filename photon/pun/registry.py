"""Registries that stand in for Unity's reflection, prefab pool and scene graph."""

from collections.abc import Callable

from ..protocol.constants import MAX_VIEW_IDS


class PrefabRegistry:
    """Maps a prefab name to a factory called when a remote Instantiate arrives."""

    def __init__(self):
        self._factories: dict[str, Callable] = {}

    def register(self, name: str, factory: Callable) -> None:
        self._factories[name] = factory

    def create(self, name: str, context):
        factory = self._factories.get(name)
        return None if factory is None else factory(context)

    def __contains__(self, name: str) -> bool:
        return name in self._factories


class ViewRegistry:
    """Owns every live view and hands out view IDs.

    A view ID is `owner_actor_number * 1000 + sub_id`, so the owner is
    recoverable from the ID alone and two clients can never collide.
    """

    def __init__(self):
        self.views: dict[int, object] = {}
        self._last_used_sub_id = 0

    def add(self, view) -> None:
        self.views[view.view_id] = view

    def remove(self, view_id: int):
        return self.views.pop(view_id, None)

    def get(self, view_id: int):
        return self.views.get(view_id)

    def allocate_id(self, actor_number: int) -> int:
        """Scan forward from the last handout, wrapping once, like PUN does."""
        for offset in range(1, MAX_VIEW_IDS):
            sub_id = (self._last_used_sub_id + offset) % MAX_VIEW_IDS
            if sub_id == 0:
                continue
            view_id = actor_number * MAX_VIEW_IDS + sub_id
            if view_id not in self.views:
                self._last_used_sub_id = sub_id
                return view_id
        # Pool full: recycle by wrapping around and replacing the oldest sub_id
        sub_id = (self._last_used_sub_id + 1) % MAX_VIEW_IDS
        if sub_id == 0:
            sub_id = 1
        self._last_used_sub_id = sub_id
        view_id = actor_number * MAX_VIEW_IDS + sub_id
        self.views.pop(view_id, None)
        return view_id

    def owned_by(self, actor_number: int) -> list:
        return [v for v in self.views.values() if v.owner_actor_nr == actor_number]

    def clear(self) -> None:
        self.views.clear()
        self._last_used_sub_id = 0


class RpcRegistry:
    """Method name -> callable, plus the optional shortcut list.

    `rpc_list` only exists so the byte-index form (key 5) can be decoded; we
    always *send* the full name (key 3), which every server accepts.
    """

    def __init__(self):
        self.methods: dict[str, Callable] = {}
        self.rpc_list: list[str] = []

    def register(self, name: str, method: Callable) -> None:
        self.methods[name] = method

    def resolve(self, name: str | None, shortcut: int | None) -> str | None:
        if name is not None:
            return name
        if shortcut is not None and 0 <= shortcut < len(self.rpc_list):
            return self.rpc_list[shortcut]
        return None

    def __contains__(self, name: str) -> bool:
        return name in self.methods


def photon_rpc(name_or_method=None):
    """Marks a method as remotely callable, optionally under a different name.

    Usable bare (`@photon_rpc`) or with an explicit wire name
    (`@photon_rpc("TakeDamage")`) when the C# side uses a different spelling.
    """
    if callable(name_or_method):
        name_or_method._photon_rpc_name = name_or_method.__name__
        return name_or_method

    def decorate(method):
        method._photon_rpc_name = name_or_method or method.__name__
        return method

    return decorate


def collect_rpcs(obj) -> dict[str, Callable]:
    """Find every @photon_rpc method bound on an object."""
    found = {}
    for attribute in dir(type(obj)):
        method = getattr(obj, attribute, None)
        wire_name = getattr(method, "_photon_rpc_name", None)
        if wire_name is not None:
            found[wire_name] = method
    return found
