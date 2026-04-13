"""
ChatApp — основной Textular App, оркестрация экранов, UI-обновления.
"""

import logging

from textual.app import App
from textual.widgets import Label, Input, ListView, ListItem, TextArea

from client.screens import LoginScreen, ChatScreen
from client.ws_client import WSClient

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

    # ── UI обновления ──────────────────────────────────────

    def update_chat_header(self) -> None:
        try:
            chat_screen = self.screen
            if isinstance(chat_screen, ChatScreen):
                header = chat_screen.query_one("#chat-header-label", Label)
                if self.ws.current_contact:
                    uname = self.ws.participants.get(self.ws.current_contact, {}).get("username", "Unknown")
                    header.update(f"DM: {uname}")
                else:
                    header.update("General")
        except Exception as e:
            logger.error(f"Header update error: {e}")

    def update_messages_display(self) -> None:
        try:
            chat_screen = self.screen
            if isinstance(chat_screen, ChatScreen):
                messages_display = chat_screen.query_one("#chat-messages", TextArea)

                if self.ws.current_contact:
                    filtered = [msg for msg in self.ws.messages
                                if (msg.client_id == self.ws.current_contact and not msg.is_direct) or
                                   (msg.is_mine and (msg.target_id == self.ws.current_contact or not msg.is_direct)) or
                                   (msg.is_direct and msg.client_id == self.ws.current_contact) or
                                   (msg.is_direct and msg.is_mine and msg.target_id == self.ws.current_contact)]
                else:
                    filtered = [msg for msg in self.ws.messages
                                if not msg.is_direct or
                                   (msg.is_mine and not msg.is_direct) or
                                   msg.client_id == 0]

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
            new_ids = {f"user_{cid}" for cid in others.keys()}
            logger.info(f"current_ids={current_ids}, new_ids={new_ids}")

            for item in list(contacts_list.children):
                if item.id not in new_ids:
                    logger.info(f"Removing contact: {item.id}")
                    item.remove()

            for client_id, data in others.items():
                item_id = f"user_{client_id}"
                if item_id not in current_ids:
                    unread = self.ws.unread_counts.get(client_id, 0)
                    username = data.get("username", f"User {client_id}")
                    label = f"{username}" if username else f"User {client_id}"
                    if unread > 0:
                        label = f"● {label}"
                    item = ListItem(Label(label), id=item_id)
                    if unread > 0:
                        item.add_class("unread")
                    contacts_list.append(item)
                    logger.info(f"Added contact: {item_id} = {username}")
                else:
                    for child in contacts_list.children:
                        if child.id == item_id:
                            unread = self.ws.unread_counts.get(client_id, 0)
                            username = data.get("username", f"User {client_id}")
                            label = f"{username}" if username else f"User {client_id}"
                            if unread > 0:
                                label = f"● {label}"
                            child.query_one(Label).update(label)
                            if unread > 0:
                                child.add_class("unread")
                            else:
                                child.remove_class("unread")
                            break
            logger.info(f"Contacts list updated. Children: {[item.id for item in contacts_list.children]}")
        except Exception as e:
            logger.error(f"Contacts update error: {e}", exc_info=True)

    # ── Ввод сообщений ─────────────────────────────────────

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "message-input":
            content = event.value.strip()
            if not content:
                return

            if self.ws.current_contact:
                self.run_worker(self.ws.send_direct(self.ws.current_contact, content), exclusive=True)
            else:
                self.run_worker(self.ws.send_broadcast(content), exclusive=True)

            event.input.value = ""

    # ── Выбор контакта ─────────────────────────────────────

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.item and event.item.id:
            contact_id = int(event.item.id.replace("user_", ""))
            self.ws.current_contact = contact_id
            self.ws.unread_counts[contact_id] = 0
            self.update_messages_display()
            self.update_contacts_list()
            self.update_chat_header()

    def on_key(self, event) -> None:
        """Esc — вернуться к general chat."""
        if event.key == "escape" and self.ws.current_contact:
            self.ws.current_contact = None
            self.update_messages_display()
            self.update_contacts_list()
            self.update_chat_header()
