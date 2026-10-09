"""Photon protocol constants, verified against the decompiled C# sources."""

from enum import IntEnum


# --- GpBinaryV16 type codes (Protocol16.cs GpType) ---------------------------

class GpType(IntEnum):
    UNKNOWN = 0
    NULL = 42               # '*'
    STRING_ARRAY = 97       # 'a'
    BYTE = 98               # 'b'
    CUSTOM = 99             # 'c'
    DOUBLE = 100            # 'd'
    EVENT_DATA = 101        # 'e'
    FLOAT = 102             # 'f'
    HASHTABLE = 104         # 'h'
    INTEGER = 105           # 'i'
    SHORT = 107             # 'k'
    LONG = 108              # 'l'
    INTEGER_ARRAY = 110     # 'n'
    BOOLEAN = 111           # 'o'
    OPERATION_RESPONSE = 112  # 'p'
    OPERATION_REQUEST = 113   # 'q'
    STRING = 115            # 's'
    BYTE_ARRAY = 120        # 'x'
    ARRAY = 121             # 'y'
    OBJECT_ARRAY = 122      # 'z'
    DICTIONARY = 68         # 'D'


# --- Message envelope (EgMessageType) ----------------------------------------

MESSAGE_MAGIC = 0xF3
MESSAGE_MAGIC_ALT = 0xFD  # 253, also accepted by the receiver
ENCRYPTION_FLAG = 0x80


class MessageType(IntEnum):
    INIT = 0
    INIT_RESPONSE = 1
    OPERATION = 2
    OPERATION_RESPONSE = 3
    EVENT = 4
    DISCONNECT_REASON = 5
    INTERNAL_OPERATION_REQUEST = 6
    INTERNAL_OPERATION_RESPONSE = 7
    MESSAGE = 8
    RAW_MESSAGE = 9


# --- ENet commands (NCommand.cs) ---------------------------------------------

class CommandType(IntEnum):
    NONE = 0
    ACK = 1
    CONNECT = 2
    VERIFY_CONNECT = 3
    DISCONNECT = 4
    PING = 5
    SEND_RELIABLE = 6
    SEND_UNRELIABLE = 7
    SEND_FRAGMENT = 8
    SEND_UNSEQUENCED = 11
    SERVER_TIME = 12
    SEND_UNRELIABLE_PROCESSED = 13
    SEND_RELIABLE_UNSEQUENCED = 14
    SEND_FRAGMENT_UNSEQUENCED = 15
    ACK_UNSEQUENCED = 16


class CommandFlags(IntEnum):
    UNRELIABLE = 0
    RELIABLE = 1
    UNRELIABLE_UNSEQUENCED = 2
    RELIABLE_UNSEQUENCED = 3


COMMAND_HEADER_LENGTH = 12
COMMAND_RESERVED_BYTE = 4

# Total command sizes for the fixed-layout variants.
ACK_COMMAND_LENGTH = 20
CONNECT_COMMAND_LENGTH = 44
FRAGMENT_HEADER_LENGTH = 32


# --- Datagram framing (EnetPeer.SendData) ------------------------------------

DATAGRAM_HEADER_LENGTH = 12
CRC_LENGTH = 4
FLAG_PLAIN = 0x00
FLAG_CRC_ENABLED = 0xCC
FLAG_DATAGRAM_ENCRYPTED = 0x01
PEER_ID_UNASSIGNED = 0xFFFF


# --- Peer configuration (PeerBase / EnetPeer defaults) -----------------------

MTU = 1200
CHANNEL_COUNT = 2
INTERNAL_CHANNEL = 255
# EnetPeer.cs:468 — fragment payload size is mtu - 12 - 36.
FRAGMENT_PAYLOAD_LENGTH = MTU - 12 - 36

SEND_WINDOW_SIZE = 50
QUICK_RESEND_ATTEMPTS = 2
SENT_COUNT_ALLOWANCE = 15
INITIAL_RESEND_TIME_MAX = 400
DISCONNECT_TIMEOUT = 10000
PING_INTERVAL = 1000

INITIAL_ROUND_TRIP_TIME = 200
INITIAL_ROUND_TRIP_TIME_VARIANCE = 5

# Init request (PeerBase.cs) — client identity, part of the wire fingerprint.
CLIENT_VERSION = (4, 1, 8, 21, 0)
CLIENT_SDK_ID = 15
PROTOCOL_VERSION = (1, 6)  # GpBinaryV16
APP_ID_LENGTH = 32
INIT_REQUEST_LENGTH = 41


# --- Internal operations (PhotonCodes.cs) ------------------------------------

class PhotonCode(IntEnum):
    INIT_ENCRYPTION = 0
    CLIENT_KEY = 1
    SERVER_KEY = 1
    MODE_KEY = 2
    OK = 0


# --- Client Authentication Types (CustomAuthenticationType.cs) ---------------

class CustomAuthenticationType(IntEnum):
    CUSTOM = 0
    STEAM = 1
    FACEBOOK = 2
    OCULUS = 3
    PLAYSTATION4 = 4
    PLAYSTATION = 4
    XBOX = 5
    VIVEPORT = 10
    NINTENDO_SWITCH = 11
    PLAYSTATION5 = 12
    EPIC = 13
    FACEBOOK_GAMING = 14
    NONE = 255


# --- Realtime operations (LoadBalancingPeer.cs OperationCode) ----------------

class OperationCode(IntEnum):
    AUTHENTICATE_ONCE = 231
    AUTHENTICATE = 230
    JOIN_LOBBY = 229
    LEAVE_LOBBY = 228
    CREATE_GAME = 227
    JOIN_GAME = 226
    JOIN_RANDOM_GAME = 225
    FIND_FRIENDS = 222
    GET_LOBBY_STATS = 221
    GET_REGIONS = 220
    WEB_RPC = 219
    SERVER_SETTINGS = 218
    GET_GAME_LIST = 217
    CHANGE_GROUPS = 248
    GET_PROPERTIES = 251
    SET_PROPERTIES = 252
    RAISE_EVENT = 253
    LEAVE = 254


class ParameterCode(IntEnum):
    ROOM_NAME = 255
    ACTOR_NR = 254
    TARGET_ACTOR_NR = 253
    ACTOR_LIST = 252
    PROPERTIES = 251
    BROADCAST = 250
    PLAYER_PROPERTIES = 249
    GAME_PROPERTIES = 248
    CACHE = 247
    RECEIVER_GROUP = 246
    DATA = 245
    CODE = 244
    CLEANUP_CACHE_ON_LEAVE = 241
    GROUP = 240
    PUBLISH_USER_ID = 239
    ADD = 238
    SUPPRESS_ROOM_EVENTS = 237
    EMPTY_ROOM_TTL = 236
    PLAYER_TTL = 235
    EVENT_FORWARD = 234
    IS_INACTIVE = 233
    CHECK_USER_ON_JOIN = 232
    EXPECTED_VALUES = 231
    ADDRESS = 230
    PEER_COUNT = 229
    GAME_COUNT = 228
    MASTER_PEER_COUNT = 227
    USER_ID = 225
    APPLICATION_ID = 224
    POSITION = 223
    MATCH_MAKING_TYPE = 223  # alias: OpJoinRandomRoom reuses the Position code
    GAME_LIST = 222
    TOKEN = 221
    APP_VERSION = 220
    INFO = 218
    CLIENT_AUTHENTICATION_TYPE = 217
    CLIENT_AUTHENTICATION_PARAMS = 216
    JOIN_MODE = 215
    CLIENT_AUTHENTICATION_DATA = 214
    LOBBY_NAME = 213
    LOBBY_TYPE = 212
    LOBBY_STATS = 211
    REGION = 210
    URI_PATH = 209
    WEB_RPC_PARAMETERS = 208
    CACHE_SLICE_INDEX = 205
    PLUGINS = 204
    MASTER_CLIENT_ID = 203
    NICK_NAME = 202
    CLUSTER = 196
    EXPECTED_PROTOCOL = 195
    CUSTOM_INIT_DATA = 194
    ENCRYPTION_MODE = 193
    ENCRYPTION_DATA = 192
    ROOM_OPTION_FLAGS = 191
    TICKET = 190
    ALLOW_REPEATS = 188
    REPORT_QOS = 187


class EventCode(IntEnum):
    JOIN = 255
    LEAVE = 254
    PROPERTIES_CHANGED = 253
    ERROR_INFO = 251
    CACHE_SLICE_CHANGED = 250
    GAME_LIST = 230
    GAME_LIST_UPDATE = 229
    QUEUE_STATE = 228
    MATCH = 227
    APP_STATS = 226
    LOBBY_STATS = 224
    AUTH_EVENT = 223


class ReceiverGroup(IntEnum):
    OTHERS = 0
    ALL = 1
    MASTER_CLIENT = 2


class EventCaching(IntEnum):
    DO_NOT_CACHE = 0
    ADD_TO_ROOM_CACHE = 4
    ADD_TO_ROOM_CACHE_GLOBAL = 5
    REMOVE_FROM_ROOM_CACHE = 6
    REMOVE_FROM_ROOM_CACHE_FOR_ACTORS_LEFT = 7
    SLICE_INCREASE_INDEX = 10
    SLICE_SET_INDEX = 11
    SLICE_PURGE_INDEX = 12
    SLICE_PURGE_UP_TO_INDEX = 13


class JoinMode(IntEnum):
    DEFAULT = 0
    CREATE_IF_NOT_EXISTS = 1
    JOIN_OR_REJOIN = 2
    REJOIN_ONLY = 3


class GamePropertyKey(IntEnum):
    MAX_PLAYERS = 255
    IS_VISIBLE = 254
    IS_OPEN = 253
    PLAYER_COUNT = 252
    REMOVED = 251
    PROPS_LISTED_IN_LOBBY = 250
    CLEANUP_CACHE_ON_LEAVE = 249
    MASTER_CLIENT_ID = 248
    EXPECTED_USERS = 247
    PLAYER_TTL = 246
    EMPTY_ROOM_TTL = 245
    MAX_PLAYERS_INT = 243


class ActorProperty(IntEnum):
    PLAYER_NAME = 255
    IS_INACTIVE = 254
    USER_ID = 253


# --- PUN event codes (PunClasses.cs PunEvent) --------------------------------

class PunEvent(IntEnum):
    RPC = 200
    SEND_SERIALIZE = 201
    INSTANTIATION = 202
    CLOSE_CONNECTION = 203
    DESTROY = 204
    REMOVE_CACHED_RPCS = 205
    SEND_SERIALIZE_RELIABLE = 206
    DESTROY_PLAYER = 207
    OWNERSHIP_REQUEST = 209
    OWNERSHIP_TRANSFER = 210
    VACANT_VIEW_IDS = 211
    OWNERSHIP_UPDATE = 212


# RPC hashtable byte keys (PhotonNetworkPart.cs).
RPC_KEY_VIEW_ID = 0
RPC_KEY_PREFIX = 1
RPC_KEY_TIMESTAMP = 2
RPC_KEY_METHOD_NAME = 3
RPC_KEY_PARAMETERS = 4
RPC_KEY_SHORTCUT = 5

# Instantiation hashtable byte keys (PhotonNetwork.cs).
INST_KEY_PREFAB_NAME = 0
INST_KEY_POSITION = 1
INST_KEY_ROTATION = 2
INST_KEY_GROUP = 3
INST_KEY_VIEW_IDS = 4
INST_KEY_DATA = 5
INST_KEY_TIMESTAMP = 6
INST_KEY_INSTANTIATION_ID = 7
INST_KEY_LEVEL_PREFIX = 8

# View data batch layout for events 201/206.
SYNC_VIEW_ID = 0
SYNC_COMPRESSED = 1
SYNC_NULL_VALUES = 2
SYNC_FIRST_VALUE = 3

MAX_VIEW_IDS = 1000

PUN_VERSION = "2.55"
SEND_RATE_MS = 33          # 30/s
SERIALIZATION_RATE_MS = 100  # 10/s


# --- Servers -----------------------------------------------------------------

NAME_SERVER_HOST = "ns.photonengine.io"
NAME_SERVER_PORT_UDP = 5058
MASTER_PORT_UDP = 5055
GAME_PORT_UDP = 5056
