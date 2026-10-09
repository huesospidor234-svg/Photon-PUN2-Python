"""Operation parameter builders, mirroring LoadBalancingPeer.cs.

Pure functions: each returns (parameters, encrypt). Which parameters are present
and which are omitted is part of the client fingerprint, so the omission rules
are copied exactly from the C# source.
"""

from dataclasses import dataclass, field

from ..protocol.constants import (
    EventCaching,
    GamePropertyKey,
    JoinMode,
    OperationCode,
    ParameterCode,
    ReceiverGroup,
)
from ..protocol.gpbinary16 import Hashtable, PhotonByte, StringArray


class RoomOptionBit:
    CHECK_USER_ON_JOIN = 0x01
    DELETE_CACHE_ON_LEAVE = 0x02
    SUPPRESS_ROOM_EVENTS = 0x04
    PUBLISH_USER_ID = 0x08
    DELETE_NULL_PROPS = 0x10
    BROADCAST_PROPS_CHANGE_TO_ALL = 0x20
    SUPPRESS_PLAYER_INFO = 0x40


@dataclass
class RoomOptions:
    is_open: bool = True
    is_visible: bool = True
    max_players: int = 0
    player_ttl: int = 0
    empty_room_ttl: int = 0
    cleanup_cache_on_leave: bool = True
    suppress_room_events: bool = False
    suppress_player_info: bool = False
    publish_user_id: bool = False
    delete_null_properties: bool = False
    broadcast_props_change_to_all: bool = False
    custom_room_properties: dict = field(default_factory=dict)
    custom_room_properties_for_lobby: list = field(default_factory=list)
    plugins: list | None = None


@dataclass
class EnterRoomParams:
    room_name: str | None = None
    room_options: RoomOptions | None = None
    lobby_name: str | None = None
    lobby_type: int = 0
    player_properties: dict | None = None
    on_game_server: bool = False
    join_mode: int = JoinMode.DEFAULT
    expected_users: list | None = None


def room_options_to_parameters(op: dict, options: RoomOptions | None,
                               use_properties_key: bool = False) -> None:
    if options is None:
        options = RoomOptions()

    game_properties = Hashtable({
        GamePropertyKey.IS_OPEN: options.is_open,
        GamePropertyKey.IS_VISIBLE: options.is_visible,
        GamePropertyKey.PROPS_LISTED_IN_LOBBY:
            StringArray(options.custom_room_properties_for_lobby),
    })
    game_properties.update(options.custom_room_properties)

    if options.max_players > 0:
        # Old servers read MaxPlayers as a byte; new ones prefer MaxPlayersInt.
        game_properties[GamePropertyKey.MAX_PLAYERS] = PhotonByte(
            options.max_players if options.max_players <= 255 else 0)
        game_properties[GamePropertyKey.MAX_PLAYERS_INT] = options.max_players

    key = ParameterCode.PROPERTIES if use_properties_key else ParameterCode.GAME_PROPERTIES
    op[key] = game_properties

    # PUN 2 always sets CheckUserOnJoin.
    flags = RoomOptionBit.CHECK_USER_ON_JOIN
    op[ParameterCode.CHECK_USER_ON_JOIN] = True

    op[ParameterCode.CLEANUP_CACHE_ON_LEAVE] = options.cleanup_cache_on_leave
    if options.cleanup_cache_on_leave:
        flags |= RoomOptionBit.DELETE_CACHE_ON_LEAVE
    else:
        game_properties[GamePropertyKey.CLEANUP_CACHE_ON_LEAVE] = False

    if options.player_ttl > 0 or options.player_ttl == -1:
        op[ParameterCode.PLAYER_TTL] = options.player_ttl
    if options.empty_room_ttl > 0:
        op[ParameterCode.EMPTY_ROOM_TTL] = options.empty_room_ttl
    if options.suppress_room_events:
        flags |= RoomOptionBit.SUPPRESS_ROOM_EVENTS
        op[ParameterCode.SUPPRESS_ROOM_EVENTS] = True
    if options.suppress_player_info:
        flags |= RoomOptionBit.SUPPRESS_PLAYER_INFO
    if options.plugins is not None:
        op[ParameterCode.PLUGINS] = StringArray(options.plugins)
    if options.publish_user_id:
        flags |= RoomOptionBit.PUBLISH_USER_ID
        op[ParameterCode.PUBLISH_USER_ID] = True
    if options.delete_null_properties:
        flags |= RoomOptionBit.DELETE_NULL_PROPS
    if options.broadcast_props_change_to_all:
        flags |= RoomOptionBit.BROADCAST_PROPS_CHANGE_TO_ALL

    op[ParameterCode.ROOM_OPTION_FLAGS] = flags


def op_get_regions(app_id: str) -> tuple[int, dict, bool]:
    return OperationCode.GET_REGIONS, {ParameterCode.APPLICATION_ID: app_id}, True


def op_authenticate(app_id: str, app_version: str, *, region: str | None = None,
                    user_id: str | None = None, token=None,
                    nick_name: str | None = None,
                    auth_type: int | None = None,
                    auth_get_parameters: str | None = None,
                    auth_post_data=None,
                    get_lobby_statistics: bool = False) -> tuple[int, dict, bool]:
    """A token short-circuits everything and goes out UNENCRYPTED."""
    parameters: dict = {}
    if get_lobby_statistics:
        parameters[ParameterCode.LOBBY_STATS] = True

    if token is not None:
        parameters[ParameterCode.TOKEN] = token
        # Передаём никнейм даже при реаутентификации по токену,
        # чтобы вебхук PathJoin на GameServer видел правильное имя.
        if nick_name:
            parameters[ParameterCode.NICK_NAME] = nick_name
        return OperationCode.AUTHENTICATE, parameters, False

    parameters[ParameterCode.APP_VERSION] = app_version
    parameters[ParameterCode.APPLICATION_ID] = app_id
    if region:
        parameters[ParameterCode.REGION] = region
    if user_id:
        parameters[ParameterCode.USER_ID] = user_id
    if nick_name:
        parameters[ParameterCode.NICK_NAME] = nick_name
    if auth_type is not None and int(auth_type) != 255:
        parameters[ParameterCode.CLIENT_AUTHENTICATION_TYPE] = PhotonByte(int(auth_type))
        if auth_get_parameters:
            parameters[ParameterCode.CLIENT_AUTHENTICATION_PARAMS] = auth_get_parameters
        if auth_post_data is not None:
            parameters[ParameterCode.CLIENT_AUTHENTICATION_DATA] = auth_post_data
    return OperationCode.AUTHENTICATE, parameters, True


def op_join_lobby(name: str | None = None, lobby_type: int = 0) -> tuple[int, dict | None, bool]:
    if not name:
        return OperationCode.JOIN_LOBBY, None, False
    return OperationCode.JOIN_LOBBY, {
        ParameterCode.LOBBY_NAME: name,
        ParameterCode.LOBBY_TYPE: PhotonByte(lobby_type),
    }, False


def op_leave_lobby() -> tuple[int, None, bool]:
    return OperationCode.LEAVE_LOBBY, None, False


def _enter_room_common(op: dict, params: EnterRoomParams) -> bool:
    encrypt = False
    if params.expected_users:
        op[ParameterCode.ADD] = StringArray(params.expected_users)
        encrypt = True
    if params.on_game_server:
        if params.player_properties:
            op[ParameterCode.PLAYER_PROPERTIES] = Hashtable(params.player_properties)
        op[ParameterCode.BROADCAST] = True
        room_options_to_parameters(op, params.room_options)
    return encrypt


def op_create_room(params: EnterRoomParams) -> tuple[int, dict, bool]:
    op: dict = {}
    if params.room_name:
        op[ParameterCode.ROOM_NAME] = params.room_name
    if params.lobby_name:
        op[ParameterCode.LOBBY_NAME] = params.lobby_name
        op[ParameterCode.LOBBY_TYPE] = PhotonByte(params.lobby_type)
    encrypt = _enter_room_common(op, params)
    return OperationCode.CREATE_GAME, op, encrypt


def op_join_room(params: EnterRoomParams) -> tuple[int, dict, bool]:
    op: dict = {}
    if params.room_name:
        op[ParameterCode.ROOM_NAME] = params.room_name
    if params.join_mode == JoinMode.CREATE_IF_NOT_EXISTS:
        op[ParameterCode.JOIN_MODE] = PhotonByte(JoinMode.CREATE_IF_NOT_EXISTS)
        if params.lobby_name:
            op[ParameterCode.LOBBY_NAME] = params.lobby_name
            op[ParameterCode.LOBBY_TYPE] = PhotonByte(params.lobby_type)
    elif params.join_mode == JoinMode.REJOIN_ONLY:
        op[ParameterCode.JOIN_MODE] = PhotonByte(JoinMode.REJOIN_ONLY)
    encrypt = _enter_room_common(op, params)
    return OperationCode.JOIN_GAME, op, encrypt


def op_join_random_room(*, expected_properties: dict | None = None,
                        expected_max_players: int = 0,
                        matchmaking_mode: int = 0,
                        lobby_name: str | None = None, lobby_type: int = 0,
                        sql_lobby_filter: str | None = None,
                        expected_users: list | None = None) -> tuple[int, dict, bool]:
    properties = Hashtable(expected_properties or {})
    if expected_max_players > 0:
        properties[GamePropertyKey.MAX_PLAYERS] = PhotonByte(
            expected_max_players if expected_max_players <= 255 else 0)
        if expected_max_players > 255:
            properties[GamePropertyKey.MAX_PLAYERS_INT] = expected_max_players

    op: dict = {}
    encrypt = False
    if properties:
        op[ParameterCode.GAME_PROPERTIES] = properties
    if matchmaking_mode != 0:  # 0 = FillRoom, the default
        op[ParameterCode.MATCH_MAKING_TYPE] = PhotonByte(matchmaking_mode)
    if lobby_name:
        op[ParameterCode.LOBBY_NAME] = lobby_name
        op[ParameterCode.LOBBY_TYPE] = PhotonByte(lobby_type)
    if sql_lobby_filter:
        op[ParameterCode.DATA] = sql_lobby_filter
    if expected_users:
        op[ParameterCode.ADD] = StringArray(expected_users)
        encrypt = True
    op[ParameterCode.ALLOW_REPEATS] = True
    return OperationCode.JOIN_RANDOM_GAME, op, encrypt


def op_leave_room(become_inactive: bool = False) -> tuple[int, dict, bool]:
    op: dict = {}
    if become_inactive:
        op[ParameterCode.IS_INACTIVE] = True
    return OperationCode.LEAVE, op, False


def op_set_properties_of_actor(actor_nr: int, properties: dict,
                               expected: dict | None = None) -> tuple[int, dict, bool]:
    op = {
        ParameterCode.PROPERTIES: Hashtable(properties),
        ParameterCode.ACTOR_NR: actor_nr,
        ParameterCode.BROADCAST: True,
    }
    if expected:
        op[ParameterCode.EXPECTED_VALUES] = Hashtable(expected)
    return OperationCode.SET_PROPERTIES, op, False


def op_set_properties_of_room(properties: dict,
                              expected: dict | None = None) -> tuple[int, dict, bool]:
    op = {
        ParameterCode.PROPERTIES: Hashtable(properties),
        ParameterCode.BROADCAST: True,
    }
    if expected:
        op[ParameterCode.EXPECTED_VALUES] = Hashtable(expected)
    return OperationCode.SET_PROPERTIES, op, False


def op_raise_event(event_code: int, content=None, *,
                   caching: int = EventCaching.DO_NOT_CACHE,
                   target_actors: list | None = None,
                   interest_group: int = 0,
                   receivers: int = ReceiverGroup.OTHERS) -> tuple[int, dict, bool]:
    op: dict = {}
    if caching != EventCaching.DO_NOT_CACHE:
        op[ParameterCode.CACHE] = PhotonByte(caching)

    # TargetActors, Group and ReceiverGroup are mutually exclusive, in that order.
    if target_actors is not None:
        op[ParameterCode.ACTOR_LIST] = target_actors
    elif interest_group != 0:
        op[ParameterCode.GROUP] = PhotonByte(interest_group)
    elif receivers != ReceiverGroup.OTHERS:
        op[ParameterCode.RECEIVER_GROUP] = PhotonByte(receivers)

    op[ParameterCode.CODE] = PhotonByte(event_code)
    if content is not None:
        op[ParameterCode.DATA] = content
    return OperationCode.RAISE_EVENT, op, False


def op_settings(receive_lobby_stats: bool) -> tuple[int, dict, bool]:
    return OperationCode.SERVER_SETTINGS, {ParameterCode.LOBBY_STATS: receive_lobby_stats}, False