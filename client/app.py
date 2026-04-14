"""
ChatApp — основной Textular App, оркестрация экранов, UI-обновления.
"""

import logging
import asyncio

from textual.app import App
from textual.widgets import Label, Input, ListView, ListItem, TextArea, Tabs, Tab, Button

from client.screens import LoginScreen, ChatScreen, CommandInput, CommandOverlay
from client.ws_client import WSClient
from client.commands import registry

logger = logging.getLogger(__name__)


# ── Message dataclass ──────────────────────────────────────

class Message:
    __slots__ = (
        "content", "is_mine", "client_id", "timestamp",
        "username", "is_direct", "target_id", "acknowledged", "message_id",
    )

    def __init__(self, content: str, is_mine: bool = False, client_id: int = 0,
                 timestamp: str = "", username: str = "", is_direct: bool = False,
                 target_id: int | None = None, acknowledged: bool = False,
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

    def get_chat_tab_id(self, contact_id: int | None) -> str:
        """Вернуть ID вкладки для контакта."""
        if contact_id is None:
            return "tab-general"
        return f"tab-dm-{contact_id}"

    def add_chat_tab(self, contact_id: int | None) -> None:
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

                if self.ws.current_contact:
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
            logger.info(f"update_contacts_list called. participants={self.ws.participants}, self.client_id={self.ws.client_id}")
            chat_screen = self.screen
            logger.info(f"Current screen: {type(chat_screen).__name__}")
            if not isinstance(chat_screen, ChatScreen):
                logger.warning(f"Not a ChatScreen, skipping update")
                return

            contacts_list = chat_screen.query_one("#contacts-list", ListView)

            others = {cid: data for cid, data in self.ws.participants.items()
                      if cid != self.ws.client_id}
            logger.info(f"Others (excluding self): {others}")

            current_ids = {item.id for item in contacts_list.children} if contacts_list.children else set()
            new_ids = {"general"} | {f"user_{cid}" for cid in others.keys()}
            logger.info(f"current_ids={current_ids}, new_ids={new_ids}")

            # Удаляем элементы которых больше нет (кроме general)
            for item in list(contacts_list.children):
                if item.id not in new_ids:
                    logger.info(f"Removing contact: {item.id}")
                    item.remove()

            # General — всегда первый элемент (перемещаем в начало если уже есть)
            general_unread = self.ws.unread_counts.get(0, 0)
            general_label = "● General" if general_unread > 0 else "General"
            general_is_highlight = self.ws.current_contact is None

            if "general" in current_ids:
                # Перемещаем general в начало
                for child in contacts_list.children:
                    if child.id == "general":
                        child.query_one(Label).update(general_label)
                        if general_unread > 0:
                            child.add_class("unread")
                        else:
                            child.remove_class("unread")
                        if general_is_highlight:
                            child.add_class("--highlight")
                        else:
                            child.remove_class("--highlight")
                        break
            else:
                general_item = ListItem(Label(general_label), id="general")
                if general_unread > 0:
                    general_item.add_class("unread")
                if general_is_highlight:
                    general_item.add_class("--highlight")
                # Вставляем general первым
                if contacts_list.children:
                    contacts_list.children[0].remove()
                    contacts_list.append(general_item)
                else:
                    contacts_list.append(general_item)
                logger.info("Added: general")

            # Контакты
            for client_id, data in others.items():
                item_id = f"user_{client_id}"
                is_highlight = self.ws.current_contact == client_id
                if item_id not in current_ids:
                    unread = self.ws.unread_counts.get(client_id, 0)
                    username = data.get("username", f"User {client_id}")
                    label = f"● {username}" if unread > 0 else username
                    item = ListItem(Label(label), id=item_id)
                    if unread > 0:
                        item.add_class("unread")
                    if is_highlight:
                        item.add_class("--highlight")
                    contacts_list.append(item)
                    logger.info(f"Added contact: {item_id} = {username}")
                else:
                    for child in contacts_list.children:
                        if child.id == item_id:
                            unread = self.ws.unread_counts.get(client_id, 0)
                            username = data.get("username", f"User {client_id}")
                            label = f"● {username}" if unread > 0 else username
                            child.query_one(Label).update(label)
                            if unread > 0:
                                child.add_class("unread")
                            else:
                                child.remove_class("unread")
                            if is_highlight:
                                child.add_class("--highlight")
                            else:
                                child.remove_class("--highlight")
                            break
            logger.info(f"Contacts list updated. Children: {[item.id for item in contacts_list.children]}")
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
            if self.ws.current_contact:
                self.run_worker(self.ws.send_direct(self.ws.current_contact, content), exclusive=True)
            else:
                self.run_worker(self.ws.send_broadcast(content), exclusive=True)
                self.ws.unread_counts[0] = 0  # сброс unread при отправке в general

    async def _execute_command(self, cmd_name: str, args: list[str]) -> None:
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
            if event.item.id == "general":
                self.ws.current_contact = None
                self.add_chat_tab(None)
            else:
                contact_id = int(event.item.id.replace("user_", ""))
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
                if self.ws.current_contact:
                    self.run_worker(self.ws.send_direct(self.ws.current_contact, content), exclusive=True)
                else:
                    self.run_worker(self.ws.send_broadcast(content), exclusive=True)
                    self.ws.unread_counts[0] = 0
