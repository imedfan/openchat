"""
ChatApp — основной Textular App, оркестрация экранов, UI-обновления.
"""

import logging
import asyncio
from typing import Optional, List
def sanitize_id(text: str) -> str:
    """
    Санитизирует строку для использования в качестве Textual ID.
    Заменяет все недопустимые символы на подчеркивание и предотвращает
    начало ID с цифры.
    """
    # Заменяем все недопустимые символы на '_'
    sanitized = "".join(c if c.isalnum() or c == '_' else '_' for c in text)
    
    # Проверяем, не начинается ли с цифры
    if sanitized and sanitized[0].isdigit():
        sanitized = "id_" + sanitized
    
    # Гарантируем, что строка не пустая
    if not sanitized:
        sanitized = "id_empty"
    
    return sanitized


from textual.app import App
from textual.widgets import Label, Input, ListView, ListItem, TextArea, Tabs, Tab, Button, RichLog

from screens import LoginScreen, ChatScreen, CommandInput, CommandOverlay
from ws_client import WSClient
from commands import registry
from model_loader import user_models_ready

logger = logging.getLogger(__name__)


# ── Message dataclass ──────────────────────────────────────

class Message:
    __slots__ = (
        "content", "is_mine", "client_id", "timestamp",
        "username", "is_direct", "target_id", "acknowledged", "message_id",
    )

    def __init__(self, content: str, is_mine: bool = False, client_id: int = 0,
                 timestamp: str = "", username: str = "", is_direct: bool = False,
                 target_id: Optional[int] = None, acknowledged: bool = False,
                 message_id: str = ""):
        self.content = content
        self.is_mine = is_mine
        self.client_id = client_id
        self.timestamp = timestamp
        self.username = username
        self.is_direct = is_direct
        self.target_id = target_id
        self.acknowledged = acknowledged
        self.message_id = message_id


# ── ChatApp ────────────────────────────────────────────────

class ChatApp(App):
    """Главное приложение OpenChat."""

    CSS_PATH = None  # CSS определён в Screen'ах

    def __init__(self):
        super().__init__()
        self.ws = WSClient(self)

    # ── Подключение ─────────────────────────────────────────

    def on_mount(self) -> None:
        login_screen = LoginScreen(self.do_connect)
        self.push_screen(login_screen)

    def do_connect(self, username: str, ip: str, port: int) -> None:
        uri = f"ws://{ip}:{port}"
        self.run_worker(self.ws.connect(uri, username), exclusive=True)

    def do_disconnect(self) -> None:
        """Отключиться от сервера и вернуться на LoginScreen."""
        # Отменяем receive-цикл
        if self.ws._receive_task and not self.ws._receive_task.done():
            self.ws._receive_task.cancel()
        # Закрываем WebSocket
        if self.ws.websocket:
            self.run_worker(self._close_websocket(), exclusive=True)
        self.ws.running = False
        self.ws.connected = False
        self.ws.participants = {}
        self.ws.messages = []
        self.ws.pending_messages = {}
        self.ws.unread_counts.clear()
        self.ws.current_contact = None
        # Показываем LoginScreen
        self.call_later(self._show_login)

    def push_chat_screen(self) -> None:
        """Переключиться на ChatScreen и обновить overlay."""
        chat_screen = ChatScreen()
        self.push_screen(chat_screen)
        # После переключения обновим overlay
        self.call_later(self.refresh_command_overlay)

    async def _close_websocket(self) -> None:
        """Закрыть WebSocket соединение."""
        try:
            await self.ws.websocket.close()
        except Exception:
            pass

    def _show_login(self) -> None:
        """Показать LoginScreen поверх ChatScreen."""
        login_screen = LoginScreen(self.do_connect)
        self.push_screen(login_screen)

    # ── UI обновления ──────────────────────────────────────

    # ── Управление вкладками чата ──────────────────────────

    def _find_original_model_id(self, sanitized_id: str, is_user: bool = False) -> str:
        """Найти оригинальный model_id по санитизированному ID."""
        models = self.ws.user_models if is_user else self.ws.server_models
        for m in models:
            mid = m.get("id", m.get("model_id", ""))
            if sanitize_id(mid) == sanitized_id:
                return mid
        # Если не нашли — возвращаем sanitized_id (может быть уже оригинал)
        return sanitized_id

    def get_chat_tab_id(self, contact_id: Optional[int]) -> str:
        """Вернуть ID вкладки для контакта."""
        if contact_id is None:
            return "tab-general"
        return f"tab-dm-{contact_id}"

    def add_chat_tab(self, contact_id: Optional[int]) -> None:
        """Создать вкладку для контакта или активировать существующую."""
        try:
            chat_screen = self.screen
            if not isinstance(chat_screen, ChatScreen):
                return
            chat_tabs = chat_screen.query_one("#chat-tabs", Tabs)
            tab_id = self.get_chat_tab_id(contact_id)

            # Если вкладка уже есть — активируем
            if tab_id in [t.id for t in chat_tabs.query("Tab")]:
                chat_tabs.active = tab_id
                return

            # Создаём новую вкладку
            if contact_id is None:
                # General — не должно происходить, но на всякий случай
                chat_tabs.active = "tab-general"
                return

            uname = self.ws.participants.get(contact_id, {}).get("username", f"User {contact_id}")
            chat_tabs.add_tab(Tab(uname, id=tab_id))
            chat_tabs.active = tab_id
        except Exception as e:
            logger.error(f"add_chat_tab error: {e}")

    def add_chat_tab_model(self, model_id: str, is_user: bool = False) -> None:
        """Создать вкладку для модель-чата."""
        try:
            chat_screen = self.screen
            if not isinstance(chat_screen, ChatScreen):
                return
            chat_tabs = chat_screen.query_one("#chat-tabs", Tabs)

            prefix = "umodel" if is_user else "smodel"
            tab_id = f"tab-{prefix}-{sanitize_id(model_id)}"

            if tab_id in [t.id for t in chat_tabs.query("Tab")]:
                chat_tabs.active = tab_id
                return

            # Находим имя модели
            models = self.ws.user_models if is_user else self.ws.server_models
            model_name = model_id
            for m in models:
                mid = m.get("id", m.get("model_id", ""))
                if mid == model_id:
                    model_name = m.get("name", m.get("username", model_id))
                    break

            icon = "🔒" if is_user else "🤖"
            chat_tabs.add_tab(Tab(f"{icon} {model_name}", id=tab_id))
            chat_tabs.active = tab_id
        except Exception as e:
            logger.error(f"add_chat_tab_model error: {e}")

    def on_tabs_tab_activated(self, event: Tabs.TabActivated) -> None:
        """При активации вкладки переключаем контекст чата."""
        if not event.tab:
            return

        tab_id = event.tab.id
        if tab_id == "tab-general":
            self.ws.current_contact = None
        elif tab_id and tab_id.startswith("tab-dm-"):
            contact_id = int(tab_id.replace("tab-dm-", ""))
            self.ws.current_contact = contact_id
            self.ws.unread_counts[contact_id] = 0
        elif tab_id and tab_id.startswith("tab-smodel-"):
            sanitized_id = tab_id.replace("tab-smodel-", "")
            # Находим оригинальный model_id по санитизированному
            model_id = self._find_original_model_id(sanitized_id, is_user=False)
            self.ws.current_contact = f"model:{model_id}"
        elif tab_id and tab_id.startswith("tab-umodel-"):
            sanitized_id = tab_id.replace("tab-umodel-", "")
            model_id = self._find_original_model_id(sanitized_id, is_user=True)
            self.ws.current_contact = f"usermodel:{model_id}"

        self.ws.unread_counts[0] = 0
        self.update_messages_display()
        self.update_contacts_list()
        self.refresh_command_overlay()

    def update_chat_header(self) -> None:
        """Обновить название активной DM-вкладки (при смене имени)."""
        try:
            chat_screen = self.screen
            if isinstance(chat_screen, ChatScreen):
                chat_tabs = chat_screen.query_one("#chat-tabs", Tabs)
                if self.ws.current_contact:
                    tab_id = self.get_chat_tab_id(self.ws.current_contact)
                    uname = self.ws.participants.get(self.ws.current_contact, {}).get("username", "Unknown")
                    try:
                        tab = chat_tabs.get_tab(tab_id)
                        if tab:
                            tab.label = uname
                    except Exception:
                        pass
                # Обновить overlay с новым контекстом
                self.refresh_command_overlay()
        except Exception as e:
            logger.error(f"Header update error: {e}")

    def update_messages_display(self) -> None:
        try:
            chat_screen = self.screen
            if isinstance(chat_screen, ChatScreen):
                messages_display = chat_screen.query_one("#chat-messages", TextArea)

                contact = self.ws.current_contact

                # Модель-чат: показываем историю из model_conversations
                if contact and isinstance(contact, str) and contact.startswith("model:"):
                    model_id = contact.replace("model:", "")
                    msgs = self.ws.model_conversations.get(model_id, [])
                    filtered = msgs
                elif contact and isinstance(contact, str) and contact.startswith("usermodel:"):
                    model_id = contact.replace("usermodel:", "")
                    msgs = self.ws.model_conversations.get(model_id, [])
                    filtered = msgs
                elif self.ws.current_contact:
                    filtered = [msg for msg in self.ws.messages
                                if (msg.client_id == self.ws.current_contact and msg.is_direct) or
                                   (msg.is_mine and msg.target_id == self.ws.current_contact)]
                else:
                    # General: broadcast + system сообщения
                    filtered = [msg for msg in self.ws.messages
                                if msg.client_id == 0 or
                                   not msg.is_direct]

                lines = []
                for msg in filtered:
                    if msg.is_mine:
                        sender = self.ws.username if self.ws.username else "You"
                        ack_status = "✓" if msg.acknowledged else "..."
                        lines.append(f"[{msg.timestamp}] {ack_status} {sender}: {msg.content}")
                    elif msg.client_id == 0:
                        lines.append(f"[{msg.timestamp}] {msg.content}")
                    elif msg.client_id == -1:
                        # Модель-ответ
                        sender = msg.username if msg.username else "🤖 Model"
                        lines.append(f"[{msg.timestamp}] {sender}: {msg.content}")
                    else:
                        sender = msg.username if msg.username else f"User {msg.client_id}"
                        lines.append(f"[{msg.timestamp}] {sender}: {msg.content}")

                messages_display.text = "\n".join(lines)
                messages_display.scroll_end()
                chat_screen.refresh()
        except Exception as e:
            logger.error(f"Display update error: {e}")

    def update_contacts_list(self) -> None:
        try:
            chat_screen = self.screen
            if not isinstance(chat_screen, ChatScreen):
                return

            contacts_list = chat_screen.query_one("#contacts-list", ListView)

            # Собираем все ID которые должны быть
            # Формат: general, user_N, srv_model_ID, usr_model_ID
            others = {cid: data for cid, data in self.ws.participants.items()
                      if cid != self.ws.client_id}

            # Отделяем модели от обычных пользователей
            real_users = {}
            server_models = []
            for cid, data in others.items():
                if data.get("is_model"):
                    server_models.append(data)
                else:
                    real_users[cid] = data

            current_ids = {item.id for item in contacts_list.children} if contacts_list.children else set()

            # Формируем полный список ID (санитизируем ID моделей)
            new_ids = {"general"}
            new_ids |= {f"user_{cid}" for cid in real_users.keys()}
            new_ids |= {f"srv_model_{sanitize_id(m.get('model_id', m.get('username', '')))}" for m in server_models}
            if user_models_ready(self.ws.user_models):
                new_ids |= {f"usr_model_{sanitize_id(m['id'])}" for m in self.ws.user_models}

            # Удаляем элементы которых больше нет
            for item in list(contacts_list.children):
                if item.id not in new_ids:
                    item.remove()

            # Helper для создания ListItem
            def make_item(label_text: str, item_id: str, is_highlight: bool, unread: int = 0) -> ListItem:
                label = f"● {label_text}" if unread > 0 else label_text
                item = ListItem(Label(label), id=item_id)
                if unread > 0:
                    item.add_class("unread")
                if is_highlight:
                    item.add_class("--highlight")
                return item

            # 1) General — всегда первый
            general_unread = self.ws.unread_counts.get(0, 0)
            general_is_highlight = self.ws.current_contact is None
            if "general" in current_ids:
                for child in contacts_list.children:
                    if child.id == "general":
                        child.query_one(Label).update("● General" if general_unread > 0 else "General")
                        child.set_class(general_unread > 0, "unread")
                        child.set_class(general_is_highlight, "--highlight")
                        break
            else:
                item = make_item("General", "general", general_is_highlight, general_unread)
                if contacts_list.children:
                    contacts_list.children[0].remove()
                    contacts_list.append(item)
                else:
                    contacts_list.append(item)

            # 2) Серверные модели (🤖)
            for m in server_models:
                model_id = m.get('model_id', '')
                item_id = f"srv_model_{sanitize_id(model_id)}"
                model_name = m.get("username", "Unknown Model")
                is_highlight = self.ws.current_contact == f"model:{model_id}"
                if item_id not in current_ids:
                    contacts_list.append(make_item(f"🤖 {model_name}", item_id, is_highlight))
                    logger.info(f"Added server model contact: {item_id}")

            # 3) Личные модели (🔒)
            if user_models_ready(self.ws.user_models):
                for m in self.ws.user_models:
                    model_id = m['id']
                    item_id = f"usr_model_{sanitize_id(model_id)}"
                    is_highlight = self.ws.current_contact == f"usermodel:{model_id}"
                    if item_id not in current_ids:
                        contacts_list.append(make_item(f"🔒 {m['name']}", item_id, is_highlight))
                        logger.info(f"Added user model contact: {item_id}")

            # 4) Обычные пользователи
            for client_id, data in real_users.items():
                item_id = f"user_{client_id}"
                is_highlight = self.ws.current_contact == client_id
                if item_id not in current_ids:
                    unread = self.ws.unread_counts.get(client_id, 0)
                    username = data.get("username", f"User {client_id}")
                    contacts_list.append(make_item(username, item_id, is_highlight, unread))
                    logger.info(f"Added contact: {item_id}")
                else:
                    for child in contacts_list.children:
                        if child.id == item_id:
                            unread = self.ws.unread_counts.get(client_id, 0)
                            username = data.get("username", f"User {client_id}")
                            child.query_one(Label).update(f"● {username}" if unread > 0 else username)
                            child.set_class(unread > 0, "unread")
                            child.set_class(is_highlight, "--highlight")
                            break

            chat_screen.refresh()
        except Exception as e:
            logger.error(f"Contacts update error: {e}", exc_info=True)

    # ── Ввод сообщений ─────────────────────────────────────

    def refresh_command_overlay(self) -> None:
        """Обновить overlay команд с учётом текущего контекста."""
        try:
            chat_screen = self.screen
            if isinstance(chat_screen, ChatScreen):
                msg_input = chat_screen.query_one("#message-input", CommandInput)
                context = "dm" if self.ws.current_contact else "general"
                msg_input._update_overlay(context)
        except Exception as e:
            logger.error(f"refresh_command_overlay error: {e}")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "message-input":
            content = event.value.strip()
            if not content:
                return

            # Проверяем флаг подавления submit (после автокомплита из on_key)
            try:
                chat_screen = self.screen
                if isinstance(chat_screen, ChatScreen):
                    msg_input = chat_screen.query_one("#message-input", CommandInput)
                    if msg_input._suppress_submit:
                        msg_input._suppress_submit = False
                        return  # Не отправлять — пользователь будет вводить аргументы
            except Exception:
                pass

            event.input.value = ""

            # Скрываем overlay после отправки
            try:
                chat_screen = self.screen
                if isinstance(chat_screen, ChatScreen):
                    msg_input = chat_screen.query_one("#message-input", CommandInput)
                    msg_input.hide_overlay()
            except Exception:
                pass

            # /me — специальное сообщение (action)
            if content.startswith("/me "):
                action = content[4:].strip()
                formatted = f"*{action}*"
                if self.ws.current_contact:
                    self.run_worker(self.ws.send_direct(self.ws.current_contact, formatted), exclusive=True)
                else:
                    self.run_worker(self.ws.send_broadcast(formatted), exclusive=True)
                return
            elif content == "/me":
                self.call_later(self._add_system_message, "Usage: /me <action>")
                self.call_later(self.update_messages_display)
                return

            # Проверяем команду
            parsed = registry.parse(content)
            if parsed:
                cmd_name, cmd_args = parsed
                self.run_worker(self._execute_command(cmd_name, cmd_args), exclusive=True)
                return

            # Обычное сообщение
            contact = self.ws.current_contact

            # Модель-чат (серверная модель)
            if contact and isinstance(contact, str) and contact.startswith("model:"):
                model_id = contact.replace("model:", "")
                self.run_worker(self.ws.send_model_message(model_id, content), exclusive=True)
            # Модель-чат (личная модель — прямой HTTP вызов)
            elif contact and isinstance(contact, str) and contact.startswith("usermodel:"):
                model_id = contact.replace("usermodel:", "")
                # Находим модель в user_models
                model = None
                for m in self.ws.user_models:
                    if m["id"] == model_id:
                        model = m
                        break
                if model:
                    self.run_worker(self._send_user_model_message(model_id, content), exclusive=True)
            elif contact:
                self.run_worker(self.ws.send_direct(contact, content), exclusive=True)
            else:
                self.run_worker(self.ws.send_broadcast(content), exclusive=True)
                self.ws.unread_counts[0] = 0  # сброс unread при отправке в general

    async def _execute_command(self, cmd_name: str, args: List[str]) -> None:
        """Выполнить команду и показать результат."""
        cmd = registry.get(cmd_name)
        if not cmd:
            self.call_later(self._add_system_message, f"Unknown command: /{cmd_name}. Type /command for list.")
            return

        try:
            result = await cmd.execute(self.ws, args)
        except Exception as e:
            result = f"Command error: {e}"

        if result:
            if cmd_name == "command":
                # /command — добавить как сообщение в текущий чат
                self.call_later(self._add_command_result_message, result)
            else:
                self.call_later(self._add_system_message, result)

        # Обновить UI
        self.call_later(self.update_messages_display)
        self.call_later(self.update_contacts_list)
        self.call_later(self.update_chat_header)

    def _add_system_message(self, content: str) -> None:
        """Добавить системное сообщение (результат команды)."""
        from datetime import datetime
        msg = Message(content, is_mine=False, client_id=0,
                      timestamp=datetime.now().strftime("%H:%M"))
        self.ws.messages.append(msg)

    def _add_command_result_message(self, content: str) -> None:
        """Добавить результат команды /command как сообщение в текущий чат."""
        from datetime import datetime
        sender = self.ws.username if self.ws.username else "You"
        msg = Message(content, is_mine=True, client_id=self.ws.client_id,
                      username=sender, timestamp=datetime.now().strftime("%H:%M"),
                      is_direct=bool(self.ws.current_contact),
                      target_id=self.ws.current_contact)
        self.ws.messages.append(msg)

    def on_worker_state_changed(self, event):
        """Обрабатываем ошибки worker'ов — при ConnectionClosed возвращаем в General."""
        if event.worker.state.name == "ERROR":
            # Если отправка DM провалилась — сбрасываем контакт
            self.ws.current_contact = None
            self.update_messages_display()
            self.update_contacts_list()
            self.update_chat_header()

    # ── Выбор контакта ─────────────────────────────────────

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.item and event.item.id:
            item_id = event.item.id

            if item_id == "general":
                self.ws.current_contact = None
                self.add_chat_tab(None)
            elif item_id.startswith("srv_model_"):
                sanitized_id = item_id.replace("srv_model_", "")
                model_id = self._find_original_model_id(sanitized_id, is_user=False)
                self.ws.current_contact = f"model:{model_id}"
                self.add_chat_tab_model(model_id)
            elif item_id.startswith("usr_model_"):
                sanitized_id = item_id.replace("usr_model_", "")
                model_id = self._find_original_model_id(sanitized_id, is_user=True)
                self.ws.current_contact = f"usermodel:{model_id}"
                self.add_chat_tab_model(model_id, is_user=True)
            else:
                contact_id = int(item_id.replace("user_", ""))
                self.ws.current_contact = contact_id
                self.ws.unread_counts[contact_id] = 0
                self.add_chat_tab(contact_id)
            self.ws.unread_counts[0] = 0  # сброс unread для general

            # Highlight выбранного элемента
            try:
                chat_screen = self.screen
                if isinstance(chat_screen, ChatScreen):
                    contacts_list = chat_screen.query_one("#contacts-list", ListView)
                    for child in contacts_list.children:
                        child.remove_class("--highlight")
                    if event.item:
                        event.item.add_class("--highlight")
            except Exception:
                pass

            self.update_messages_display()
            self.update_contacts_list()
            self.update_chat_header()
            self.refresh_command_overlay()

    def on_key(self, event) -> None:
        """Esc — вернуться к general chat."""
        if event.key == "escape" and self.ws.current_contact:
            self.ws.current_contact = None
            self.add_chat_tab(None)
            self.ws.unread_counts[0] = 0
            self.update_messages_display()
            self.update_contacts_list()
            self.update_chat_header()
            self.refresh_command_overlay()

    # ── Кнопка Send ───────────────────────────────────────

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "send-btn":
            chat_screen = self.screen
            if isinstance(chat_screen, ChatScreen):
                msg_input = chat_screen.query_one("#message-input", Input)
                content = msg_input.value.strip()
                if not content:
                    return
                msg_input.value = ""
                chat_screen._update_send_button_state()

                # Скрываем overlay после отправки
                try:
                    cmd_input = chat_screen.query_one("#message-input", CommandInput)
                    cmd_input.hide_overlay()
                except Exception:
                    pass

                # Отправляем сообщение
                contact = self.ws.current_contact

                # Модель-чат (серверная модель)
                if contact and isinstance(contact, str) and contact.startswith("model:"):
                    model_id = contact.replace("model:", "")
                    self.run_worker(self.ws.send_model_message(model_id, content), exclusive=True)
                # Модель-чат (личная модель)
                elif contact and isinstance(contact, str) and contact.startswith("usermodel:"):
                    model_id = contact.replace("usermodel:", "")
                    self.run_worker(self._send_user_model_message(model_id, content), exclusive=True)
                elif contact:
                    self.run_worker(self.ws.send_direct(contact, content), exclusive=True)
                else:
                    self.run_worker(self.ws.send_broadcast(content), exclusive=True)
                    self.ws.unread_counts[0] = 0

    # ── LLM методы ─────────────────────────────────────────

    async def _send_user_model_message(self, model_id: str, content: str):
        """Отправить сообщение в чат личной модели с сохранением истории."""
        from datetime import datetime
        import uuid

        logger.info(f"Sending user model message to {model_id}, content: {content[:50]}")
        logger.info(f"User models available: {[m['id'] for m in self.ws.user_models]}")

        msg_id = f"umodel_{model_id}_{uuid.uuid4().hex[:8]}"
        timestamp = datetime.now().strftime("%H:%M")

        # Находим модель для получения имени
        model_name = model_id
        for m in self.ws.user_models:
            if m["id"] == model_id:
                model_name = m.get("name", model_id)
                break

        # 1. Сохраняем сообщение пользователя
        user_msg = Message(content, is_mine=True, client_id=self.ws.client_id,
                           username=self.ws.username, message_id=msg_id, timestamp=timestamp)
        if model_id not in self.ws.model_conversations:
            self.ws.model_conversations[model_id] = []
        self.ws.model_conversations[model_id].append(user_msg)
        self.ws.messages.append(user_msg)

        # 2. Создаём индикатор "thinking"
        thinking_id = f"{msg_id}_thinking"
        thinking = Message("[thinking...]", is_mine=False, client_id=-1,
                           username=f"🔒 {model_name}", message_id=thinking_id,
                           timestamp=timestamp)
        self.ws.model_conversations[model_id].append(thinking)
        self.ws.messages.append(thinking)

        self.update_messages_display()

        # 3. Создаём переменную для накопления контента и флага
        accumulated = {"content": "", "thinking_removed": False}

        # 4. Отправляем запрос и обрабатываем поток ответов
        messages = [{"role": "user", "content": content}]

        # Синхронный callback (вызывается из worker-потока aiohttp)
        def internal_callback(chunk: str, done: bool):
            # Accumulate контент
            if chunk:
                accumulated["content"] += chunk

            # При первом чанке: удаляем thinking и создаём ответ
            if chunk and not accumulated["thinking_removed"]:
                # Удаляем "[thinking...]"
                self.ws.model_conversations[model_id] = [
                    msg for msg in self.ws.model_conversations[model_id]
                    if msg.message_id != thinking_id
                ]
                self.ws.messages = [
                    msg for msg in self.ws.messages
                    if msg.message_id != thinking_id
                ]
                accumulated["thinking_removed"] = True

                # Создаём сообщение ответа
                response_msg = Message(accumulated["content"], is_mine=False, client_id=-1,
                                     username=f"🔒 {model_name}",
                                     message_id=f"{msg_id}_response",
                                     timestamp=timestamp)
                self.ws.model_conversations[model_id].append(response_msg)
                self.ws.messages.append(response_msg)
            elif chunk:
                # Обновляем существующее сообщение при каждом chunk
                for msg_list in [self.ws.model_conversations[model_id], self.ws.messages]:
                    for msg in msg_list:
                        if msg.message_id == f"{msg_id}_response":
                            msg.content = accumulated["content"]
                            break

            # При завершении финализируем сообщение
            if done:
                if not accumulated["thinking_removed"]:
                    # Удаляем thinking, если ещё не удалили (пустой ответ)
                    self.ws.model_conversations[model_id] = [
                        msg for msg in self.ws.model_conversations[model_id]
                        if msg.message_id != thinking_id
                    ]
                    self.ws.messages = [
                        msg for msg in self.ws.messages
                        if msg.message_id != thinking_id
                    ]
                    # Создаём финальное сообщение с пустым контентом
                    response_msg = Message("[no response]", is_mine=False, client_id=-1,
                                         username=f"🔒 {model_name}",
                                         message_id=f"{msg_id}_response",
                                         timestamp=timestamp)
                    self.ws.model_conversations[model_id].append(response_msg)
                    self.ws.messages.append(response_msg)
                else:
                    # Финализируем уже существующее сообщение
                    final_content = accumulated["content"] if accumulated["content"] else "[no response]"
                    for msg_list in [self.ws.model_conversations[model_id], self.ws.messages]:
                        msg_list[:] = [msg for msg in msg_list if msg.message_id != f"{msg_id}_response"]
                        response_msg = Message(final_content, is_mine=False, client_id=-1,
                                             username=f"🔒 {model_name}",
                                             message_id=f"{msg_id}_response",
                                             timestamp=datetime.now().strftime("%H:%M"))
                        msg_list.append(response_msg)

            # Обновляем отображение через call_later (безопасно для worker-потока)
            self.call_later(self.update_messages_display)

        await self.ws.send_user_llm_request(model_id, messages, callback=internal_callback)

    def update_llm_models(self) -> None:
        """Вызывается при получении списка LLM-моделей от сервера."""
        self.log(f"LLM models received: {[m['name'] for m in self.ws.available_models]}")
        # Если сейчас открыт LLMChatScreen — обновляем селектор
        try:
            if isinstance(self.screen, LLMChatScreen):
                self.screen._update_model_selector()
        except Exception:
            pass

    def update_llm_stream(self, model_id: str, chunk: str, done: bool) -> None:
        """Вызывается при получении чанка от LLM."""
        try:
            if isinstance(self.screen, LLMChatScreen):
                self.screen._on_llm_chunk(chunk, done)

                # Обновляем RichLog на экране
                messages_widget = self.screen.query_one("#llm-messages", RichLog)
                if done:
                    # Завершаем строку
                    messages_widget.write("\n")
                    self.screen._set_streaming_status(False)
                else:
                    # Дописываем chunk в ту же строку (без newline)
                    messages_widget.write(chunk)

            # Плавное обновление UI — обновляем общий список сообщений
            self.call_later(self.update_messages_display)
        except Exception as e:
            self.log(f"LLM stream update error: {e}")

    def update_llm_error(self, model_id: str, error: str) -> None:
        """Вызывается при ошибке LLM-запроса."""
        self.notify(f"LLM error: {error}", severity="error")
        try:
            if isinstance(self.screen, LLMChatScreen):
                messages_widget = self.screen.query_one("#llm-messages", RichLog)
                messages_widget.write(f"[bold red][Error: {error}][/bold red]\n")
                self.screen._set_streaming_status(False)
        except Exception:
            pass

    def open_llm_chat(self) -> None:
        """Открыть экран LLM-чата."""
        if not self.ws.available_models:
            self.notify("No LLM models available on the server", severity="warning")
            return
        self.push_screen(LLMChatScreen(self))
