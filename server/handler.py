"""
Серверный обработчик WebSocket-соединений.
Сервер — ТОЛЬКО ретранслятор. Для DM он НЕ расшифровывает сообщения.
"""

import asyncio
import json
import logging
import socket
from datetime import datetime
from typing import Dict, List, Optional

import websockets

from common.protocol import (
    MSG_CONNECT, MSG_CONNECTED, MSG_MESSAGE, MSG_DIRECT,
    MSG_ACK, MSG_SYSTEM, MSG_PARTICIPANTS,
    make_connected, make_system_message, make_participants,
)

logger = logging.getLogger(__name__)


class ChatServer:
    def __init__(self, host="0.0.0.0", port=5000):
        self.host = host
        self.port = port
        self.clients: Dict[int, websockets.ServerProtocol] = {}   # client_id → websocket
        self.client_usernames: Dict[int, str] = {}
        self.client_public_keys: Dict[int, bytes] = {}             # client_id → public_key_pem
        self.client_id_counter = 1
        self.lock = asyncio.Lock()

    # ── Helpers ──────────────────────────────────────────────

    async def _get_participants_list(self) -> List[dict]:
        return [
            {
                "client_id": cid,
                "username": self.client_usernames.get(cid, f"User {cid}"),
                "public_key": self.client_public_keys.get(cid, b"").decode("utf-8", errors="replace"),
            }
            for cid in self.clients.keys()
        ]

    async def _send_participants_to_all(self, exclude: Optional[List[int]] = None):
        """Рассылает обновлённый список участников всем (кроме exclude)."""
        exclude = exclude or []
        async with self.lock:
            participant_count = len(self.clients)
            participants_list = await self._get_participants_list()

        payload = make_participants(participant_count, participants_list)

        async with self.lock:
            targets = list(self.clients.items())

        for cid, ws in targets:
            if cid not in exclude:
                try:
                    await ws.send(payload)
                except Exception as e:
                    logger.error(f"Send participants error to {cid}: {e}")

    async def _send_participants_to(self, websocket) -> str:
        """Отправляет список участников одному клиенту. Возвращает payload."""
        async with self.lock:
            participant_count = len(self.clients)
            participants_list = await self._get_participants_list()

        payload = make_participants(participant_count, participants_list)
        await websocket.send(payload)
        return payload

    # ── Обработка клиента ───────────────────────────────────

    async def handle_client(self, websocket):
        client_id = None
        try:
            async for raw_message in websocket:
                message = json.loads(raw_message)
                msg_type = message.get("type")

                if msg_type == MSG_CONNECT:
                    client_id = await self._handle_connect(websocket, message)

                elif msg_type == MSG_MESSAGE:
                    await self._handle_broadcast(client_id, websocket, message)

                elif msg_type == MSG_DIRECT:
                    await self._handle_direct(client_id, websocket, message)

        except websockets.ConnectionClosed:
            logger.info(f"Client {client_id} connection closed")
        except Exception as e:
            logger.error(f"Client {client_id} error: {e}")
        finally:
            if client_id:
                await self._handle_disconnect(client_id)

    async def _handle_connect(self, websocket, message: dict):
        client_id = None
        username = message.get("username", "")
        public_key_pem = message.get("public_key", "").encode("utf-8")

        async with self.lock:
            client_id = self.client_id_counter
            self.clients[client_id] = websocket
            self.client_usernames[client_id] = username
            self.client_public_keys[client_id] = public_key_pem
            self.client_id_counter += 1
            participant_count = len(self.clients)

        # Ответ клиенту
        await websocket.send(make_connected(client_id, participant_count))
        logger.info(f"Client {client_id} ({username}) connected")

        # Список участников новому клиенту
        await self._send_participants_to(websocket)

        # Уведомление остальным о join
        join_msg = make_system_message(f"{username} joined the chat")
        await self.broadcast(join_msg, exclude=[client_id])

        # Обновлённый participants остальным
        await self._send_participants_to_all(exclude=[client_id])

        return client_id

    async def _handle_broadcast(self, client_id: int, websocket, message: dict):
        content = message.get("content", "")
        async with self.lock:
            sender_username = self.client_usernames.get(client_id, f"User {client_id}")

        # ACK
        ack_msg = json.dumps({
            "type": MSG_ACK,
            "message_id": message.get("message_id"),
            "username": sender_username,
        })
        await websocket.send(ack_msg)
        logger.info(f"Message from {client_id} acknowledged")

        # Broadcast всем кроме отправителя
        broadcast_msg = json.dumps({
            "type": MSG_MESSAGE,
            "client_id": client_id,
            "username": sender_username,
            "content": content,
            "timestamp": datetime.now().strftime("%H:%M"),
        })
        await self.broadcast(broadcast_msg, exclude=[client_id])
        logger.info(f"Broadcast message from {client_id}: {content[:50]}")

    async def _handle_direct(self, client_id: int, websocket, message: dict):
        """DM — сервер НЕ расшифровывает, просто relay."""
        target_id = message.get("target_id")
        async with self.lock:
            sender_username = self.client_usernames.get(client_id, f"User {client_id}")

        # ACK
        ack_msg = json.dumps({
            "type": MSG_ACK,
            "message_id": message.get("message_id"),
            "username": sender_username,
        })
        await websocket.send(ack_msg)
        logger.info(f"Message from {client_id} acknowledged")

        async with self.lock:
            target_ws = self.clients.get(target_id)

        if target_ws:
            # Relay DM (opaque — сервер не decrypt'ит)
            direct_msg = json.dumps({
                "type": MSG_DIRECT,
                "client_id": client_id,
                "username": sender_username,
                "target_id": target_id,
                "content": message.get("content"),     # base64 ciphertext
                "nonce": message.get("nonce"),         # base64 nonce
                "message_id": message.get("message_id"),
                "timestamp": datetime.now().strftime("%H:%M"),
            })
            await target_ws.send(direct_msg)
            logger.info(f"Direct message from {client_id} to {target_id}: [encrypted]")
        else:
            logger.warning(f"Target client {target_id} not found for DM from {client_id}")

    async def _handle_disconnect(self, client_id: int):
        username = self.client_usernames.get(client_id, f"User {client_id}")

        async with self.lock:
            self.clients.pop(client_id, None)
            self.client_usernames.pop(client_id, None)
            self.client_public_keys.pop(client_id, None)

        leave_msg = make_system_message(f"{username} left the chat")
        await self.broadcast(leave_msg)

        await self._send_participants_to_all()
        logger.info(f"Client {client_id} ({username}) disconnected")

    # ── Broadcast ───────────────────────────────────────────

    async def broadcast(self, message: str, exclude: Optional[List[int]] = None):
        exclude = exclude or []
        async with self.lock:
            targets = list(self.clients.items())

        for cid, ws in targets:
            if cid not in exclude:
                try:
                    await ws.send(message)
                except Exception as e:
                    logger.error(f"Broadcast error to {cid}: {e}")

    # ── Запуск ──────────────────────────────────────────────

    def start(self):
        # Detect real non-loopback IP
        local_ip = self._get_public_ip()
        logger.info(f"Server starting on {self.host}:{self.port}")
        print(f"\n{'='*50}")
        print(f"  OpenChat Server (WebSocket)")
        print(f"{'='*50}")
        print(f"  Listening on: {self.host}:{self.port}")
        print(f"  Public IP:    {local_ip}")
        print(f"  Connect to:   ws://{local_ip}:{self.port}")
        print(f"{'='*50}\n")

        return websockets.serve(
            self.handle_client,
            self.host,
            self.port,
        )

    def _get_public_ip(self) -> str:
        """Detect the server's public IP from network interfaces."""
        try:
            import socket
            # Connect to an external address to detect our outgoing IP
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "0.0.0.0"
