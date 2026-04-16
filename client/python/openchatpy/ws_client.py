"""
WebSocket-клиент: подключение, отправка, приём сообщений + E2EE для DM.
"""

from datetime import datetime
import asyncio
import json
import logging
import os
from collections import defaultdict
from typing import Dict, Optional, FrozenSet

import aiohttp
import websockets

from protocol import (
    MSG_CONNECT, MSG_CONNECTED, MSG_MESSAGE, MSG_DIRECT,
    MSG_ACK, MSG_SYSTEM, MSG_PARTICIPANTS,
    MSG_LLM_MODELS, MSG_LLM_CHUNK, MSG_LLM_ERROR,
    MSG_MODEL_MESSAGE, MSG_MODEL_RESPONSE,
    make_connect, make_message, make_llm_request, make_model_message,
)
from crypto import (
    generate_keypair, load_public_key, derive_shared_key,
    encrypt_message, decrypt_message,
)
from model_loader import load_user_models, user_models_ready

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

        # LLM-состояние
        self.available_models: list = []   # [{"id": ..., "name": ...}, ...]
        self.llm_streaming = False         # идёт ли сейчас streaming
        self.llm_callbacks: Dict[str, list] = {}  # model_id → [callback(chunk, done), ...]

        # Модель-чаты (серверные + личные)
        self.server_models: list = []      # [{"id": ..., "name": ...}, ...]
        self.user_models: list = []         # [{"id": ..., "name": ...}, ...]
        self.model_conversations: Dict[str, list] = {}  # model_id → [Message, ...]
        self._srv_resp_counter: int = 0    # счётчик для уникальных ID ответов серверной модели

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

            # Загружаем пользовательские модели
            self.user_models = load_user_models()
            if user_models_ready(self.user_models):
                logger.info(f"Loaded {len(self.user_models)} user model(s)")

            # Обновляем UI контактов
            self.app.call_later(self.app.update_contacts_list)
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

                # Логируем типы LLM-сообщений
                if msg_type in [MSG_LLM_MODELS, MSG_LLM_CHUNK, MSG_LLM_ERROR, MSG_MODEL_RESPONSE]:
                    logger.info(f"Received LLM message type: {msg_type}")

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

                elif msg_type == MSG_LLM_MODELS:
                    self._handle_llm_models(message)

                elif msg_type == MSG_LLM_CHUNK:
                    self._handle_llm_chunk(message)

                elif msg_type == MSG_LLM_ERROR:
                    self._handle_llm_error(message)

                elif msg_type == MSG_MODEL_RESPONSE:
                    self._handle_model_response(message)

        except websockets.ConnectionClosed as e:
            logger.error(f"WebSocket connection closed with code {e.code}, reason: {e.reason}")
            self.app.notify(f"Connection lost: {e.reason}", severity="error")
        except Exception as e:
            logger.error(f"Receive error: {e}", exc_info=True)
            self.app.notify("Connection error occurred", severity="error")

        finally:
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

        # Сохраняем текущие модели (если есть), чтобы не потерять их при обновлении
        old_server_models = self.server_models.copy() if hasattr(self, 'server_models') else []
        
        # Создаём новый dict для участников — НЕ перезаписываем полностью, а добавляем/обновляем
        new_participants = {}
        for p in participants_list:
            cid = p.get("client_id")
            uname = p.get("username")
            is_model = p.get("is_model", False)
            pubkey = p.get("public_key", "").encode("utf-8")
            if cid and uname:
                # Если это модель (is_model=true или client_id=-1), сохраняем её отдельно
                if is_model or cid == -1:
                    # Сохраняем как модель с полными данными из participants
                    model_data = {
                        "id": p.get("model_id", ""),
                        "name": uname,
                        "baseUrl": p.get("base_url", ""),
                        "envKey": p.get("env_key", ""),
                        # Сохраняем как модель (не просто dict участника)
                    }
                    if cid == -1:
                        # Серверная модель — сохраняем в self.server_models
                        existing = next((m for m in self.server_models if m["id"] == p.get("model_id")), None)
                        if not existing or existing.get("name") != uname:
                            self.server_models.append(model_data)
                    else:
                        # Личная модель — обновляем в self.user_models
                        for i, um in enumerate(self.user_models):
                            if um["id"] == p.get("model_id"):
                                self.user_models[i] = model_data
                                break
                elif cid and uname:
                    new_participants[cid] = {
                        "username": uname,
                        "public_key_pem": pubkey,
                    }

        # Добавляем себя обратно, если потеряли
        if self.client_id and self.client_id not in new_participants:
            new_participants[self.client_id] = {
                "username": self.username,
                "public_key_pem": self.public_key_pem,
            }

        self.participants = new_participants

        # Обновляем UI (через call_later — из worker'а нельзя напрямую)
        logger.info(f"Participants updated: {[(cid, d['username']) for cid, d in self.participants.items()]}")
        self.app.call_later(self.app.update_contacts_list)

    # ── LLM обработка ──────────────────────────────────────

    def _handle_llm_models(self, message: dict):
        """S→C: список доступных LLM-моделей."""
        self.available_models = message.get("models", [])
        self.server_models = list(self.available_models)  # копируем
        logger.info(f"Received {len(self.available_models)} LLM model(s): {[m['name'] for m in self.available_models]}")
        self.app.call_later(self.app.update_llm_models)
        self.app.call_later(self.app.update_contacts_list)

    def _handle_llm_chunk(self, message: dict):
        """S→C: часть streaming-ответа от LLM."""
        model_id = message.get("model_id", "")
        chunk = message.get("chunk", "")
        done = message.get("done", False)

        self.llm_streaming = not done

        # Логируем первый чанк и завершение потока
        if chunk and not done:
            logger.info(f"LLM chunk received for {model_id}: {chunk[:50]}")
        elif done:
            logger.info(f"LLM streaming completed for {model_id}")

        # Вызываем зарегистрированные callback'и
        callbacks = self.llm_callbacks.get(model_id, [])
        for callback in callbacks:
            try:
                callback(chunk, done)
            except Exception as e:
                logger.error(f"LLM callback error: {e}")

        # Уведомляем приложение для обновления UI
        self.app.call_later(self.app.update_llm_stream, model_id, chunk, done)

        if done:
            self.llm_callbacks.pop(model_id, None)
            logger.info(f"LLM streaming for {model_id} completed")

    def _handle_llm_error(self, message: dict):
        """S→C: ошибка LLM-запроса."""
        model_id = message.get("model_id", "")
        error = message.get("error", "Unknown error")
        logger.error(f"LLM error for {model_id}: {error}")
        self.app.call_later(self.app.update_llm_error, model_id, error)

        # Уведомляем callback'и об ошибке
        callbacks = self.llm_callbacks.get(model_id, [])
        for callback in callbacks:
            try:
                callback("", True)  # done = True
            except Exception:
                pass
        self.llm_callbacks.pop(model_id, None)

    # ── LLM отправка запроса ───────────────────────────────

    async def send_llm_request(self, model_id: str, messages: list, callback=None):
        """C→S: отправить запрос к LLM-модели."""
        # Заменяем callback (не накаплируем старые)
        if callback:
            self.llm_callbacks[model_id] = [callback]

        payload = make_llm_request(model_id, messages)
        try:
            await self.websocket.send(payload)
            logger.info(f"Sent LLM request for model {model_id}")
        except websockets.ConnectionClosed:
            self.app.notify("Connection lost!", severity="error")

    # ── Модель-чаты ────────────────────────────────────────

    async def send_model_message(self, model_id: str, content: str):
        """Отправить сообщение в чат модели."""
        import uuid
        from datetime import datetime
        from app import Message

        conv_key = f"srv:{model_id}"
        msg_id = f"model_{model_id}_{uuid.uuid4().hex[:8]}"

        payload = make_model_message(model_id, content, msg_id)
        try:
            await self.websocket.send(payload)
        except websockets.ConnectionClosed:
            self.app.notify("Connection lost!", severity="error")
            return

        # Добавляем сообщение пользователя в историю
        msg = Message(content, is_mine=True, client_id=self.client_id,
                      username=self.username, message_id=msg_id,
                      timestamp=datetime.now().strftime("%H:%M"))

        if conv_key not in self.model_conversations:
            self.model_conversations[conv_key] = []
        self.model_conversations[conv_key].append(msg)
        self.messages.append(msg)

        # Показываем индикатор "думаю"
        thinking = Message("[thinking...]", is_mine=False, client_id=-1,
                           username=f"🤖 {model_id}", message_id=f"{msg_id}_thinking",
                           timestamp=datetime.now().strftime("%H:%M"))
        self.model_conversations[conv_key].append(thinking)
        self.messages.append(thinking)

        self.app.call_later(self.app.update_messages_display)
        logger.info(f"Sent model message to {model_id}: {content[:50]}")

    def _handle_model_response(self, message: dict):
        """S→C: ответ от модели в чате (streaming chunks)."""
        model_id = message.get("model_id", "")
        model_name = message.get("model_name", model_id)
        content = message.get("content", "")
        done = message.get("done", False)
        stream = message.get("stream", False)
        timestamp = message.get("timestamp", "")

        conv_key = f"srv:{model_id}"
        if conv_key not in self.model_conversations:
            self.model_conversations[conv_key] = []

        # При первом chunk (stream=True): создаём уникальный ID для этого ответа
        if content and stream:
            # Удаляем "[thinking...]" из истории
            self.model_conversations[conv_key] = [
                msg for msg in self.model_conversations[conv_key]
                if not (msg.content == "[thinking...]" and msg.client_id == -1)
            ]
            self.messages = [
                msg for msg in self.messages
                if not (msg.content == "[thinking...]" and msg.client_id == -1)
            ]

            # Создаём уникальный ID для этого конкретного ответа (не для модели!)
            resp_id = f"srv_resp_{model_id}_{self._srv_resp_counter}"

            # Находим или создаём сообщение для накопления контента
            existing = None
            for msg in self.model_conversations[conv_key]:
                if msg.message_id == resp_id:
                    existing = msg
                    break

            if existing is None:
                # Новый ответ — инкрементируем счётчик
                self._srv_resp_counter += 1
                from app import Message
                response_msg = Message(content, is_mine=False, client_id=-1,
                                     username=f"🤖 {model_name}",
                                     message_id=resp_id,
                                     timestamp=timestamp)
                self.model_conversations[conv_key].append(response_msg)
                self.messages.append(response_msg)
            else:
                existing.content += content

        # При done=True: финализируем (если не было streaming)
        elif done:
            # Проверяем есть ли уже streaming-ответ для этого запроса
            # (по последнему созданному resp_id)
            has_streaming = any(
                msg.message_id.startswith(f"srv_resp_{model_id}_")
                for msg in self.model_conversations[conv_key]
            )
            if not has_streaming:
                resp_id = f"srv_resp_{model_id}_{self._srv_resp_counter}"
                self._srv_resp_counter += 1
                from app import Message
                response_msg = Message(content if content else "[no response]",
                                     is_mine=False, client_id=-1,
                                     username=f"🤖 {model_name}",
                                     message_id=resp_id,
                                     timestamp=timestamp)
                self.model_conversations[conv_key].append(response_msg)
                self.messages.append(response_msg)

        self.app.call_later(self.app.update_messages_display)

    async def send_user_llm_request(self, model_id: str, messages: list, callback=None):
        """Прямой HTTP SSE запрос к LLM API для личных моделей."""
        logger.info(f"send_user_llm_request called for {model_id}")

        # Находим модель в user_models по id
        model = None
        for m in self.user_models:
            if m["id"] == model_id:
                model = m
                break

        if not model:
            logger.error(f"User model {model_id} not found in user_models")
            if callback:
                try:
                    callback("", True)  # done = True
                except Exception:
                    pass
            return

        base_url = model.get("baseUrl", "").rstrip("/")
        if not base_url:
            logger.error(f"No baseUrl for user model {model_id}")
            if callback:
                try:
                    callback("", True)  # done = True
                except Exception:
                    pass
            return

        # Формируем URL — нормализуем baseUrl (убираем trailing /v1 если есть)
        base_url = base_url.rstrip("/").removesuffix("/v1")
        url = f"{base_url}/v1/chat/completions"

        # Подготавливаем headers
        headers = {
            "Content-Type": "application/json"
        }

        # Получаем API-ключ: сначала из переменной окружения, потом используем envKey как fallback
        env_key_name = model.get("envKey", "OPENAI_API_KEY")
        api_key = os.getenv(env_key_name)  # сначала пытаемся получить из переменной окружения

        # Если переменная окружения не найдена, используем значение envKey как сам ключ
        if not api_key:
            api_key = env_key_name

        logger.info(f"API key found: {'yes' if api_key else 'no'} (envKey={env_key_name})")
        logger.info(f"Full URL: {url}")
        logger.info(f"Model ID in payload: {model.get('id', model_id)}")

        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        
        # Подготавливаем payload
        payload = {
            "model": model.get("id", model_id),  # используем ID модели, а не отображаемое имя
            "messages": messages,
            "stream": True
        }
        
        # Заменяем callback для данной модели (не накаплируем!)
        # Каждый запрос к модели — это отдельная сессия, старые callbacks больше не нужны
        if callback:
            self.llm_callbacks[model_id] = [callback]
        
        # Создаем HTTP сессию и отправляем streaming запрос
        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(url, json=payload, headers=headers) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        logger.error(f"LLM API error {response.status}: {error_text}")
                        if callback:
                            for cb in self.llm_callbacks.get(model_id, []):
                                try:
                                    cb(f"Error {response.status}: {error_text}", True)
                                except Exception:
                                    pass
                        self.llm_callbacks.pop(model_id, None)
                        return
                    
                    # Обработка SSE ответа
                    async for line in response.content:
                        line = line.strip()
                        if not line:
                            continue

                        # SSE формат: data: {...}
                        if line.startswith(b"data: "):
                            data = line[6:]  # убираем "data: "
                            if data == b"[DONE]":
                                # Завершение потока
                                logger.info(f"User model response completed for {model_id}")
                                if model_id in self.llm_callbacks:
                                    callbacks = self.llm_callbacks.pop(model_id, [])
                                    for cb in callbacks:
                                        try:
                                            # Отправляем пустой chunk с done=True
                                            cb("", True)
                                        except Exception as e:
                                            logger.error(f"Callback error on done: {e}")
                                break

                            try:
                                # Разбираем JSON
                                chunk_data = json.loads(data)
                                if "choices" in chunk_data and len(chunk_data["choices"]) > 0:
                                    delta = chunk_data["choices"][0].get("delta", {})
                                    content = delta.get("content", "")
                                    if content:
                                        # Логируем первый чанк
                                        if model_id in self.llm_callbacks:
                                            logger.info(f"User model response chunk for {model_id}: {content[:50]}")
                                        # Вызываем callback для каждого chunk
                                        if model_id in self.llm_callbacks:
                                            for cb in self.llm_callbacks[model_id]:
                                                try:
                                                    cb(content, False)  # done=False
                                                except Exception as e:
                                                    logger.error(f"Callback error: {e}")
                                        # Отдаём управление event loop'у чтобы UI обновился плавно
                                        await asyncio.sleep(0.01)
                            except json.JSONDecodeError:
                                logger.warning(f"Invalid JSON in LLM stream: {data}")
            except Exception as e:
                logger.error(f"LLM HTTP request failed: {e}")
                if callback:
                    for cb in self.llm_callbacks.get(model_id, []):
                        try:
                            cb(f"Request failed: {e}", True)
                        except Exception:
                            pass
                self.llm_callbacks.pop(model_id, None)
