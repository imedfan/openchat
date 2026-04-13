"""
Протокол: типы сообщений, константы, фабрики JSON-сообщений.
"""

import json
import uuid
from datetime import datetime

# ── Константы ──────────────────────────────────────────────
BUFFER_SIZE = 4096
MAX_MESSAGES = 100
DEFAULT_PORT = 5000
DEFAULT_IP = "127.0.0.1"

# ── Типы сообщений ─────────────────────────────────────────
MSG_CONNECT = "connect"
MSG_CONNECTED = "connected"
MSG_MESSAGE = "message"
MSG_DIRECT = "direct"
MSG_ACK = "ack"
MSG_SYSTEM = "system"
MSG_PARTICIPANTS = "participants"


# ── Фабрики сообщений ──────────────────────────────────────

def make_connect(username: str, public_key_pem: bytes) -> str:
    return json.dumps({
        "type": MSG_CONNECT,
        "username": username,
        "public_key": public_key_pem.decode("utf-8"),
    })


def make_connected(client_id: int, participant_count: int) -> str:
    return json.dumps({
        "type": MSG_CONNECTED,
        "client_id": client_id,
        "participant_count": participant_count,
    })


def make_message(content: str, message_id: str | None = None) -> tuple[str, str]:
    msg_id = message_id or str(uuid.uuid4())
    return json.dumps({
        "type": MSG_MESSAGE,
        "content": content,
        "message_id": msg_id,
    }), msg_id


def make_direct_message(client_id: int, username: str, target_id: int,
                        content: str, nonce: str, message_id: str | None = None) -> tuple[str, str]:
    msg_id = message_id or str(uuid.uuid4())
    return json.dumps({
        "type": MSG_DIRECT,
        "client_id": client_id,
        "username": username,
        "target_id": target_id,
        "content": content,       # base64 ciphertext
        "nonce": nonce,           # base64 nonce
        "message_id": msg_id,
    }), msg_id


def make_ack(message_id: str, username: str = "") -> str:
    return json.dumps({
        "type": MSG_ACK,
        "message_id": message_id,
        "username": username,
    })


def make_system_message(message: str, timestamp: str | None = None) -> str:
    return json.dumps({
        "type": MSG_SYSTEM,
        "message": message,
        "timestamp": timestamp or datetime.now().strftime("%H:%M"),
    })


def make_participants(count: int, participants: list) -> str:
    return json.dumps({
        "type": MSG_PARTICIPANTS,
        "count": count,
        "participants": participants,
    })


def now_timestamp() -> str:
    return datetime.now().strftime("%H:%M")
