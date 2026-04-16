"""
Протокол: типы сообщений, константы, фабрики JSON-сообщений.
"""

import json
import uuid
from datetime import datetime
from typing import Optional

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

# LLM-сообщения
MSG_LLM_MODELS = "llm_models"     # S→C: список доступных моделей
MSG_LLM_REQUEST = "llm_request"    # C→S: запрос к LLM
MSG_LLM_CHUNK = "llm_chunk"        # S→C: часть streaming-ответа
MSG_LLM_ERROR = "llm_error"        # S→C: ошибка LLM-запроса

# Модель-чаты
MSG_MODEL_MESSAGE = "model_message"   # C→S: сообщение в чат модели
MSG_MODEL_RESPONSE = "model_response" # S→C: ответ модели в чат


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


def make_message(content: str, message_id: Optional[str] = None) -> tuple:
    msg_id = message_id or str(uuid.uuid4())
    return json.dumps({
        "type": MSG_MESSAGE,
        "content": content,
        "message_id": msg_id,
    }), msg_id


def make_direct_message(client_id: int, username: str, target_id: int,
                        content: str, nonce: str, message_id: Optional[str] = None) -> tuple:
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


def make_system_message(message: str, timestamp: Optional[str] = None) -> str:
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


# ── Фабрики LLM-сообщений ─────────────────────────────────

def make_llm_request(model_id: str, messages: list) -> str:
    """C→S: запрос к LLM-модели с историей диалога."""
    return json.dumps({
        "type": MSG_LLM_REQUEST,
        "model_id": model_id,
        "messages": messages,  # [{"role": "user", "content": "..."}, ...]
    })


def make_model_message(model_id: str, content: str, message_id: str) -> str:
    """C→S: сообщение в чат модели."""
    return json.dumps({
        "type": MSG_MODEL_MESSAGE,
        "model_id": model_id,
        "content": content,
        "message_id": message_id,
    })
