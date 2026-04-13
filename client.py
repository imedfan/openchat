import asyncio
import json
import logging
import random
import string
import websockets
from datetime import datetime
from collections import deque
from typing import Optional, Dict

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import Button, Input, Label, ListView, ListItem, Static, TextArea
from textual.screen import Screen
from textual import events

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('client.log')
    ]
)
logger = logging.getLogger(__name__)


class Message:
    def __init__(self, content: str, is_mine: bool = False, client_id: Optional[int] = None,
                 timestamp: str = "", acknowledged: bool = False, message_id: str = "",
                 username: str = "", is_direct: bool = False, target_id: Optional[int] = None):
        self.content = content
        self.is_mine = is_mine
        self.client_id = client_id
        self.timestamp = timestamp
        self.acknowledged = acknowledged
        self.message_id = message_id
        self.username = username
        self.is_direct = is_direct
        self.target_id = target_id


class LoginScreen(Screen):
    def __init__(self, on_connect: callable):
        super().__init__()
        self.on_connect = on_connect

    def compose(self) -> ComposeResult:
        with Container(id="login-container"):
            with Vertical(id="login-form"):
                yield Static("OpenChat", id="login-title")
                yield Label("Username:")
                yield Input(placeholder="Enter username", id="input-name")
                yield Label("Server IP:")
                yield Input(placeholder="127.0.0.1", id="input-ip")
                yield Label("Port:")
                yield Input(placeholder="5000", id="input-port")
                yield Button("Connect", id="btn-connect", variant="primary")

    def on_mount(self) -> None:
        self.query_one("#input-name", Input).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-connect":
            self.connect_to_server()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "input-name":
            self.query_one("#input-ip", Input).focus()
        elif event.input.id == "input-ip":
            self.query_one("#input-port", Input).focus()
        elif event.input.id == "input-port":
            self.connect_to_server()

    def connect_to_server(self) -> None:
        name = self.query_one("#input-name", Input).value.strip()
        ip = self.query_one("#input-ip", Input).value.strip() or "127.0.0.1"
        port = self.query_one("#input-port", Input).value.strip() or "5000"

        if not name:
            username = ''.join(random.choices(string.ascii_uppercase, k=6))
        else:
            username = name

        try:
            port = int(port)
        except ValueError:
            self.notify("Invalid port number", severity="error")
            return

        self.on_connect(username, ip, port)


class ChatScreen(Screen):
    def __init__(self, app: App):
        super().__init__()
        self.chat_app = app

    def compose(self) -> ComposeResult:
        with Horizontal(id="chat-layout"):
            with Vertical(id="chat-main"):
                yield Static("OpenChat — General", id="chat-header")
                yield TextArea(id="chat-messages", read_only=True, show_line_numbers=False)
            with Vertical(id="contacts-panel"):
                yield Static("Participants", id="contacts-header")
                yield ListView(id="contacts-list")
        with Horizontal(id="input-dock"):
            yield Input(placeholder="Type a message...", id="chat-input")
            yield Button("Send", id="btn-send", variant="primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-send":
            self.send_message()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "chat-input":
            self.send_message()

    def send_message(self) -> None:
        input_field = self.query_one("#chat-input", Input)
        message = input_field.value.strip()
        if message:
            self.chat_app.send_message(message)
            input_field.value = ""


class ChatClient(App):
    CSS = """
    Screen {
        background: $surface;
    }

    #login-container {
        width: 100%;
        height: 100%;
        align: center middle;
    }

    #login-form {
        width: 50;
        height: auto;
        background: $panel;
        border: solid $primary;
        padding: 2;
    }

    #login-title {
        text-align: center;
        text-style: bold;
        color: $accent;
        margin-bottom: 2;
    }

    #login-form Label {
        margin-top: 1;
    }

    #login-form Input {
        margin-bottom: 1;
    }

    #login-form #btn-connect {
        margin-top: 2;
        width: 100%;
    }

    #chat-layout {
        width: 100%;
        height: 100%;
    }

    #chat-main {
        width: 80%;
        border-right: solid $primary;
    }

    #contacts-panel {
        width: 20%;
    }

    #input-dock {
        dock: bottom;
        height: auto;
        background: $panel;
    }

    #chat-input {
        width: 80%;
    }

    #input-dock #btn-send {
        width: 20%;
    }

    #chat-header {
        text-style: bold;
        color: $accent;
        padding: 1;
        background: $panel;
    }

    #chat-messages {
        height: 100%;
        margin: 1;
        background: $surface;
    }

    #chat-input-area {
        height: auto;
        padding: 1;
    }

    #chat-input {
        width: 80%;
    }

    #chat-input-area #btn-send {
        width: 20%;
    }

    #contacts-panel {
        background: $panel;
    }

    #contacts-header {
        text-style: bold;
        padding: 1;
        background: $accent;
        color: $text;
    }

    #contacts-list {
        height: 100%;
    }
    """

    def __init__(self):
        super().__init__()
        self.websocket: Optional[websockets.ClientConnection] = None
        self.client_id: Optional[int] = None
        self.username: str = ""
        self.running = False
        self.messages: deque = deque(maxlen=100)
        self.pending_messages: Dict[str, Message] = {}
        self.message_id_counter = 0
        self.connected = False
        self.participants: Dict[int, str] = {}
        self.unread_counts: Dict[int, int] = {}
        self.current_contact: Optional[int] = None
        self._receive_task = None
        self._connect_uri = None

    def on_mount(self) -> None:
        login_screen = LoginScreen(self.do_connect)
        self.push_screen(login_screen)

    def do_connect(self, username: str, ip: str, port: int) -> None:
        uri = f"ws://{ip}:{port}"
        self._connect_uri = uri
        self._username_to_connect = username
        self.run_worker(self._do_connect_async(), exclusive=True)

    async def _do_connect_async(self):
        uri = self._connect_uri
        username = self._username_to_connect

        try:
            self.websocket = await websockets.connect(uri)

            connect_msg = json.dumps({'type': 'connect', 'username': username})
            await self.websocket.send(connect_msg)

            response = json.loads(await self.websocket.recv())

            if response['type'] == 'connected':
                self.client_id = response['client_id']
                self.username = username
                self.running = True
                self.connected = True

                self.participants[self.client_id] = username

                self._receive_task = asyncio.create_task(self.receive_messages())

                chat_screen = ChatScreen(self)
                self.push_screen(chat_screen)

                logger.info(f"Connected with ID: {self.client_id}")
                self.notify(f"Connected as {username}")
                self.update_chat_header()
            else:
                self.notify("Connection failed", severity="error")

        except Exception as e:
            logger.error(f"Connection error: {e}")
            self.notify(f"Error: {e}", severity="error")

    async def receive_messages(self):
        try:
            async for raw_message in self.websocket:
                message = json.loads(raw_message)
                msg_type = message.get('type')

                if msg_type == 'ack':
                    msg_id = message.get('message_id')
                    if msg_id in self.pending_messages:
                        self.pending_messages[msg_id].acknowledged = True
                        for msg in self.messages:
                            if msg.message_id == msg_id:
                                msg.acknowledged = True
                                break
                        del self.pending_messages[msg_id]
                        self.call_later(self.update_messages_display)
                        logger.info(f"Message {msg_id} acknowledged")

                elif msg_type == 'message':
                    client_id = message.get('client_id')
                    username = message.get('username', '')
                    content = message.get('content', '')
                    timestamp = message.get('timestamp', '')

                    self.participants[client_id] = username

                    msg = Message(content, is_mine=False, client_id=client_id, timestamp=timestamp, username=username)
                    self.messages.append(msg)
                    self.call_later(self.update_messages_display)

                    if client_id != self.client_id:
                        self.unread_counts[client_id] = self.unread_counts.get(client_id, 0) + 1
                        self.call_later(self.update_contacts_list)

                    logger.info(f"Received message from user {client_id}: {content[:50]}")

                elif msg_type == 'direct':
                    client_id = message.get('client_id')
                    username = message.get('username', '')
                    content = message.get('content', '')
                    timestamp = message.get('timestamp', '')
                    target_id = message.get('target_id')

                    self.participants[client_id] = username

                    msg = Message(content, is_mine=False, client_id=client_id,
                                 timestamp=timestamp, username=username, is_direct=True, target_id=target_id)
                    self.messages.append(msg)
                    self.call_later(self.update_messages_display)

                    if client_id != self.client_id:
                        self.unread_counts[client_id] = self.unread_counts.get(client_id, 0) + 1
                        self.call_later(self.update_contacts_list)

                    logger.info(f"Received direct message from user {client_id}: {content[:50]}")

                elif msg_type == 'system':
                    content = message.get('message', '')
                    timestamp = message.get('timestamp', '')
                    msg = Message(content, is_mine=False, client_id=0, timestamp=timestamp)
                    self.messages.append(msg)
                    self.call_later(self.update_messages_display)
                    logger.info(f"System message: {content}")

                elif msg_type == 'participants':
                    count = message.get('count', 1)
                    participants_list = message.get('participants', [])
                    logger.info(f"Participants update received: count={count}, participants={participants_list}")
                    self.participants = {}
                    for p in participants_list:
                        cid = p.get('client_id')
                        username = p.get('username')
                        if cid and username:
                            self.participants[cid] = username
                    logger.info(f"Participants updated: {self.participants}")
                    self.call_later(self.update_contacts_list)

        except websockets.ConnectionClosed:
            logger.info("WebSocket connection closed")
        except Exception as e:
            logger.error(f"Receive error: {e}")

        self.connected = False

    def send_message(self, content: str) -> bool:
        if not self.running or not self.websocket:
            return False

        try:
            self.message_id_counter += 1
            message_id = f"{self.client_id}_{self.message_id_counter}"

            payload = {
                'type': 'message',
                'content': content,
                'message_id': message_id
            }
            if self.current_contact:
                payload['target_id'] = self.current_contact

            message = json.dumps(payload)

            msg = Message(content, is_mine=True, client_id=self.client_id,
                         timestamp=datetime.now().strftime('%H:%M'),
                         acknowledged=False, message_id=message_id,
                         is_direct=bool(self.current_contact),
                         target_id=self.current_contact)
            self.messages.append(msg)
            self.pending_messages[message_id] = msg

            self.run_worker(self._send_async(message), exclusive=True)

            logger.info(f"Sent message: {content[:50]} (direct={bool(self.current_contact)})")
            self.update_messages_display()
            return True
        except Exception as e:
            logger.error(f"Send error: {e}")
            return False

    async def _send_async(self, message: str):
        try:
            await self.websocket.send(message)
        except Exception as e:
            logger.error(f"Send error: {e}")

    def update_messages_display(self) -> None:
        try:
            chat_screen = self.screen
            if isinstance(chat_screen, ChatScreen):
                messages_display = chat_screen.query_one("#chat-messages", TextArea)

                if self.current_contact:
                    # Show only messages for this conversation
                    filtered = [msg for msg in self.messages
                               if (msg.client_id == self.current_contact and not msg.is_direct) or
                                  (msg.is_mine and (msg.target_id == self.current_contact or not msg.is_direct)) or
                                  (msg.is_direct and msg.client_id == self.current_contact) or
                                  (msg.is_direct and msg.is_mine and msg.target_id == self.current_contact)]
                else:
                    # Show general chat (non-direct) messages
                    filtered = [msg for msg in self.messages
                               if not msg.is_direct or
                                  (msg.is_mine and not msg.is_direct) or
                                  msg.client_id == 0]  # system messages

                lines = []
                for msg in filtered:
                    if msg.is_mine:
                        sender = self.username if self.username else "You"
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
            logger.info(f"update_contacts_list called. participants={self.participants}, self.client_id={self.client_id}")
            chat_screen = self.screen
            logger.info(f"Current screen: {type(chat_screen).__name__}")
            if not isinstance(chat_screen, ChatScreen):
                logger.warning(f"Not a ChatScreen, skipping update")
                return

            contacts_list = chat_screen.query_one("#contacts-list", ListView)

            # Exclude self from participants list
            others = {cid: uname for cid, uname in self.participants.items()
                      if cid != self.client_id}
            logger.info(f"Others (excluding self): {others}")

            current_ids = {item.id for item in contacts_list.children} if contacts_list.children else set()
            new_ids = {f"user_{cid}" for cid in others.keys()}
            logger.info(f"current_ids={current_ids}, new_ids={new_ids}")

            for item in list(contacts_list.children):
                if item.id not in new_ids:
                    logger.info(f"Removing contact: {item.id}")
                    item.remove()

            for client_id, username in others.items():
                item_id = f"user_{client_id}"
                if item_id not in current_ids:
                    unread = self.unread_counts.get(client_id, 0)
                    label = f"{username}" if username else f"User {client_id}"
                    if unread > 0:
                        label = f"● {label}"
                    item = ListItem(Label(label))
                    item.id = item_id
                    if unread > 0:
                        item.styles.background = "dark blue"
                    contacts_list.append(item)
                    logger.info(f"Added contact: {item_id} = {username}")
                else:
                    for child in contacts_list.children:
                        if child.id == item_id:
                            unread = self.unread_counts.get(client_id, 0)
                            label = f"{username}" if username else f"User {client_id}"
                            if unread > 0:
                                label = f"● {label}"
                            child.query_one(Label).update(label)
                            if unread > 0:
                                child.styles.background = "dark blue"
                            else:
                                child.styles.background = ""
                            break
            logger.info(f"Contacts list updated. Children: {[item.id for item in contacts_list.children]}")
        except Exception as e:
            logger.error(f"Contacts update error: {e}", exc_info=True)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.item and event.item.id:
            contact_id = int(event.item.id.replace("user_", ""))
            self.current_contact = contact_id
            self.unread_counts[contact_id] = 0
            self.update_messages_display()
            self.update_contacts_list()
            self.update_chat_header()

    def update_chat_header(self) -> None:
        try:
            chat_screen = self.screen
            if isinstance(chat_screen, ChatScreen):
                header = chat_screen.query_one("#chat-header", Static)
                if self.current_contact and self.current_contact in self.participants:
                    name = self.participants[self.current_contact]
                    header.update(f"OpenChat — {name}")
                else:
                    header.update("OpenChat — General")
        except Exception as e:
            logger.error(f"Header update error: {e}")

    def on_key(self, event: events.Key) -> None:
        if event.key == "escape":
            self.exit()


import asyncio

if __name__ == '__main__':
    app = ChatClient()
    app.run()
