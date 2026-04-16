"""
WebSocket-клиент: подключение, отправка, приём сообщений + E2EE для DM.
"""

from datetime import datetime
import asyncio
import json
import logging
from collections import defaultdict
from typing import Dict, Optional, FrozenSet

import websockets

from protocol import (
    MSG_CONNECT, MSG_CONNECTED, MSG_MESSAGE, MSG_DIRECT,
    MSG_ACK, MSG_SYSTEM, MSG_PARTICIPANTS,
    make_connect, make_message,
)
from crypto import (
    generate_keypair, load_public_key, derive_shared_key,
    encrypt_message, decrypt_message,
)

logger = logging.getLogger(__name__)


class WSClient:
    """
    asyncio WebSocket-клиент.
    Хранит:
      - participants: dict[client_id] → {username, public_key_pem}
      - shared_keys: dict[frozenset({my_id, their_id})] → aes_key
      - messages: список всех сообщений
    """

    def __init__(self, app):
        self.app = app                   # ссылка на ChatApp для call_later
        self.websocket = None
        self.client_id = None
        self.username = None
        self.running = False
        self.connected = False

        self.private_key = None
        self.public_key_pem = None
        self._receive_task: Optional[asyncio.Task] = None

        self.participants: Dict[int, dict] = {}   # client_id → {username, public_key_pem}
        self.shared_keys: Dict[FrozenSet, bytes] = {}  # {my_id, their_id} → aes_key

        self.messages = []                 # список Message-объектов
        self.pending_messages = {}         # message_id → Message (ждём ack)
        self.unread_counts: Dict[int, int] = defaultdict(int)
        self.current_contact: Optional[int] = None

    # ── Подключение ─────────────────────────────────────────

    async def connect(self, uri: str, username: str):
        self.websocket = await websockets.connect(uri)

        # Генерация keypair
        self.private_key, self.public_key_pem = generate_keypair()

        connect_payload = make_connect(username, self.public_key_pem)
        await self.websocket.send(connect_payload)

        response = json.loads(await self.websocket.recv())

        if response["type"] == MSG_CONNECTED:
            self.client_id = response["client_id"]
            self.username = username
            self.running = True
            self.connected = True

            # Добавляем себя в participants (для полноты)
            self.participants[self.client_id] = {
                "username": username,
                "public_key_pem": self.public_key_pem,
            }

            logger.info(f"Connected with ID: {self.client_id}")
            self.app.notify(f"Connected as {username}")

            # Переключаемся на ChatScreen (через call_later — из worker'а нельзя напрямую)
            self.app.call_later(self.app.push_chat_screen)

            # Запуск receive-цикла как asyncio task (не worker — мы уже внутри worker'а!)
            self._receive_task = asyncio.create_task(self._receive_loop())
            logger.info("Receive loop started as asyncio task")
        else:
            self.app.notify("Connection failed", severity="error")

    # ── E2EE: derive shared key ────────────────────────────

    def _get_shared_key(self, their_id: int) -> bytes:
        """
        Возвращает AES key для переписки с their_id.
        Если ключ ещё не выведен — выводит и кэширует.
        """
        pair = frozenset({self.client_id, their_id})
        if pair not in self.shared_keys:
            their_pem = self.participants[their_id]["public_key_pem"]
            their_public = load_public_key(their_pem)
            aes_key = derive_shared_key(self.private_key, their_public)
            self.shared_keys[pair] = aes_key
            logger.info(f"Derived shared key with {their_id}")
        return self.shared_keys[pair]

    # ── Отправка сообщений ──────────────────────────────────

    async def send_broadcast(self, content: str):
        payload, msg_id = make_message(content)

        try:
            await self.websocket.send(payload)
        except websockets.ConnectionClosed:
            self.app.notify("Connection lost!", severity="error")
            return

        from app import Message
        msg = Message(content, is_mine=True, client_id=self.client_id,
                      username=self.username, message_id=msg_id,
                      timestamp=datetime.now().strftime("%H:%M"))
        self.messages.append(msg)
        self.pending_messages[msg_id] = msg
        self.app.call_later(self.app.update_messages_display)
        logger.info(f"Sent broadcast: {content[:50]}")

    async def send_direct(self, target_id: int, content: str):
        """DM: encrypt → send."""

        # Проверяем что собеседник подключён
        if target_id not in self.participants:
            self.app.notify("User disconnected", severity="warning")
            self.current_contact = None
            return

        aes_key = self._get_shared_key(target_id)
        ciphertext_b64, nonce_b64 = encrypt_message(content, aes_key)

        msg_id = f"dm_{target_id}_{len(self.messages)}"
        direct_payload = json.dumps({
            "type": MSG_DIRECT,
            "client_id": self.client_id,
            "username": self.username,
            "target_id": target_id,
            "content": ciphertext_b64,
            "nonce": nonce_b64,
            "message_id": msg_id,
        })

        try:
            await self.websocket.send(direct_payload)
        except websockets.ConnectionClosed:
            self.app.notify("Connection lost!", severity="error")
            return

        from app import Message
        msg = Message(content, is_mine=True, client_id=self.client_id,
                      username=self.username, is_direct=True, target_id=target_id,
                      message_id=msg_id, timestamp=datetime.now().strftime("%H:%M"))
        self.messages.append(msg)
        self.pending_messages[msg_id] = msg
        self.app.call_later(self.app.update_messages_display)
        logger.info(f"Sent DM to {target_id}: [encrypted]")

    # ── Цикл приёма ─────────────────────────────────────────

    async def _receive_loop(self):
        try:
            async for raw_message in self.websocket:
                message = json.loads(raw_message)
                msg_type = message.get("type")
                logger.info(f"Received msg type={msg_type}")

                if msg_type == MSG_ACK:
                    self._handle_ack(message)

                elif msg_type == MSG_MESSAGE:
                    self._handle_broadcast(message)

                elif msg_type == MSG_DIRECT:
                    self._handle_direct(message)

                elif msg_type == MSG_SYSTEM:
                    self._handle_system(message)

                elif msg_type == MSG_PARTICIPANTS:
                    self._handle_participants(message)

        except websockets.ConnectionClosed:
            logger.info("WebSocket connection closed")
        except Exception as e:
            logger.error(f"Receive error: {e}")

        self.connected = False
        # Очищаем participants при отключении (только себя оставляем)
        self.participants = {}
        if self.client_id:
            self.participants[self.client_id] = {
                "username": self.username,
                "public_key_pem": self.public_key_pem,
            }
        self.app.call_later(self.app.update_contacts_list)

    def _handle_ack(self, message: dict):
        msg_id = message.get("message_id")
        if msg_id in self.pending_messages:
            self.pending_messages[msg_id].acknowledged = True
            for msg in self.messages:
                if msg.message_id == msg_id:
                    msg.acknowledged = True
                    break
            del self.pending_messages[msg_id]
            self.app.call_later(self.app.update_messages_display)
            logger.info(f"Message {msg_id} acknowledged")

    def _handle_broadcast(self, message: dict):
        from app import Message
        client_id = message.get("client_id")
        username = message.get("username", "")
        content = message.get("content", "")
        timestamp = message.get("timestamp", "")

        msg = Message(content, is_mine=False, client_id=client_id,
                      timestamp=timestamp, username=username)
        self.messages.append(msg)
        self.app.call_later(self.app.update_messages_display)

        # Unread для General (ключ 0)
        if client_id != self.client_id:
            self.unread_counts[0] = self.unread_counts.get(0, 0) + 1
            self.app.call_later(self.app.update_contacts_list)

        logger.info(f"Received broadcast from {client_id}: {content[:50]}")

    def _handle_direct(self, message: dict):
        from app import Message
        client_id = message.get("client_id")
        username = message.get("username", "")
        ciphertext_b64 = message.get("content", "")
        nonce_b64 = message.get("nonce", "")
        timestamp = message.get("timestamp", "")
        target_id = message.get("target_id")

        # Decrypt
        try:
            aes_key = self._get_shared_key(client_id)
            plaintext = decrypt_message(ciphertext_b64, nonce_b64, aes_key)
        except Exception as e:
            logger.error(f"DM decrypt failed from {client_id}: {e}")
            plaintext = "[decrypt error]"

        msg = Message(plaintext, is_mine=False, client_id=client_id,
                      timestamp=timestamp, username=username, is_direct=True,
                      target_id=target_id)
        self.messages.append(msg)
        self.app.call_later(self.app.update_messages_display)

        if client_id != self.client_id:
            self.unread_counts[client_id] = self.unread_counts.get(client_id, 0) + 1
            self.app.call_later(self.app.update_contacts_list)

        logger.info(f"Received DM from {client_id}: [decrypted]")

    def _handle_system(self, message: dict):
        from app import Message
        content = message.get("message", "")
        timestamp = message.get("timestamp", "")
        msg = Message(content, is_mine=False, client_id=0, timestamp=timestamp)
        self.messages.append(msg)
        self.unread_counts[0] = self.unread_counts.get(0, 0) + 1
        self.app.call_later(self.app.update_messages_display)
        logger.info(f"System message: {content}")

    def _handle_participants(self, message: dict):
        count = message.get("count", 1)
        participants_list = message.get("participants", [])
        logger.info(f"Participants update: count={count}")

        self.participants = {}
        for p in participants_list:
            cid = p.get("client_id")
            uname = p.get("username")
            pubkey = p.get("public_key", "").encode("utf-8")
            if cid and uname:
                self.participants[cid] = {
                    "username": uname,
                    "public_key_pem": pubkey,
                }

        # Добавляем себя обратно, если потеряли
        if self.client_id and self.client_id not in self.participants:
            self.participants[self.client_id] = {
                "username": self.username,
                "public_key_pem": self.public_key_pem,
            }

        logger.info(f"Participants updated: {[(cid, d['username']) for cid, d in self.participants.items()]}")
        self.app.call_later(self.app.update_contacts_list)
