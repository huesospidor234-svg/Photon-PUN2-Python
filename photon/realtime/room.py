"""Room and Player state, mirrored from the server's property broadcasts."""

from ..protocol.constants import ActorProperty, GamePropertyKey


class Player:
    def __init__(self, actor_number: int, is_local: bool = False):
        self.actor_number = actor_number
        self.is_local = is_local
        self.nick_name = ""
        self.user_id: str | None = None
        self.is_inactive = False
        self.custom_properties: dict = {}
        self.room = None

    @property
    def actor_nr(self) -> int:
        return self.actor_number

    @property
    def is_master_client(self) -> bool:

        return self.room is not None and self.room.master_client_id == self.actor_number

    def cache_properties(self, properties: dict | None) -> None:
        if not properties:
            return
        for key, value in properties.items():
            if key == ActorProperty.PLAYER_NAME:
                self.nick_name = value
            elif key == ActorProperty.USER_ID:
                self.user_id = value
            elif key == ActorProperty.IS_INACTIVE:
                self.is_inactive = bool(value)
            else:
                self.custom_properties[key] = value

    def __repr__(self):
        return f"Player({self.actor_number}, {self.nick_name!r})"


class Room:
    def __init__(self, name: str = ""):
        self.name = name
        self.players: dict[int, Player] = {}
        self.master_client_id = 0
        self.max_players = 0
        self.is_open = True
        self.is_visible = True
        self.player_count = 0
        self.player_ttl = 0
        self.empty_room_ttl = 0
        self.props_listed_in_lobby: list = []
        self.custom_properties: dict = {}

    def add_player(self, actor_number: int, is_local: bool = False) -> Player:
        player = self.players.get(actor_number)
        if player is None:
            player = Player(actor_number, is_local)
            player.room = self
            self.players[actor_number] = player
        return player

    def remove_player(self, actor_number: int) -> Player | None:
        return self.players.pop(actor_number, None)

    def cache_properties(self, properties: dict | None) -> None:
        if not properties:
            return
        for key, value in properties.items():
            if key == GamePropertyKey.MAX_PLAYERS:
                # MaxPlayersInt wins when both are present, so don't clobber it.
                if not self.max_players:
                    self.max_players = int(value)
            elif key == GamePropertyKey.MAX_PLAYERS_INT:
                self.max_players = int(value)
            elif key == GamePropertyKey.IS_OPEN:
                self.is_open = bool(value)
            elif key == GamePropertyKey.IS_VISIBLE:
                self.is_visible = bool(value)
            elif key == GamePropertyKey.PLAYER_COUNT:
                self.player_count = int(value)
            elif key == GamePropertyKey.MASTER_CLIENT_ID:
                self.master_client_id = int(value)
            elif key == GamePropertyKey.PLAYER_TTL:
                self.player_ttl = int(value)
            elif key == GamePropertyKey.EMPTY_ROOM_TTL:
                self.empty_room_ttl = int(value)
            elif key == GamePropertyKey.PROPS_LISTED_IN_LOBBY:
                self.props_listed_in_lobby = list(value)
            elif key in (GamePropertyKey.REMOVED, GamePropertyKey.CLEANUP_CACHE_ON_LEAVE,
                         GamePropertyKey.EXPECTED_USERS):
                pass
            else:
                self.custom_properties[key] = value

    def __repr__(self):
        return f"Room({self.name!r}, players={sorted(self.players)})"
