import socket
import threading
import logging
import json
import random
import string
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
                 username: str = ""):
        self.content = content
        self.is_mine = is_mine
        self.client_id = client_id
        self.timestamp = timestamp
        self.acknowledged = acknowledged
        self.message_id = message_id
        self.username = username


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
                yield Static("OpenChat", id="chat-header")
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
        self.socket: Optional[socket.socket] = None
        self.client_id: Optional[int] = None
        self.username: str = ""
        self.running = False
        self.messages: deque = deque(maxlen=100)
        self.pending_messages: Dict[str, Message] = {}
        self.message_id_counter = 0
        self.connected = False
        self.new_message_event = threading.Event()
        self.participants: Dict[int, str] = {}
        self.unread_counts: Dict[int, int] = {}
        self.current_contact: Optional[int] = None

    def on_mount(self) -> None:
        login_screen = LoginScreen(self.do_connect)
        self.push_screen(login_screen)

    def do_connect(self, username: str, ip: str, port: int) -> None:
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.connect((ip, port))

            connect_msg = json.dumps({'type': 'connect', 'username': username})
            self.socket.send(connect_msg.encode('utf-8'))

            response = json.loads(self.socket.recv(4096).decode('utf-8'))

            if response['type'] == 'connected':
                self.client_id = response['client_id']
                self.username = username
                self.running = True
                self.connected = True

                self.participants[self.client_id] = username

                receive_thread = threading.Thread(target=self.receive_messages)
                receive_thread.daemon = True
                receive_thread.start()

                chat_screen = ChatScreen(self)
                self.push_screen(chat_screen)

                logger.info(f"Connected with ID: {self.client_id}")
                self.notify(f"Connected as {username}")
            else:
                self.notify("Connection failed", severity="error")

        except Exception as e:
            logger.error(f"Connection error: {e}")
            self.notify(f"Error: {e}", severity="error")

    def receive_messages(self):
        while self.running:
            try:
                data = self.socket.recv(4096)
                if not data:
                    break

                message = json.loads(data.decode('utf-8'))
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
                        self.new_message_event.set()
                        self.call_from_thread(self.update_messages_display)
                        logger.info(f"Message {msg_id} acknowledged")

                elif msg_type == 'message':
                    client_id = message.get('client_id')
                    username = message.get('username', '')
                    content = message.get('content', '')
                    timestamp = message.get('timestamp', '')

                    self.participants[client_id] = username

                    msg = Message(content, is_mine=False, client_id=client_id, timestamp=timestamp, username=username)
                    self.messages.append(msg)
                    self.new_message_event.set()
                    self.call_from_thread(self.update_messages_display)
                    
                    if client_id != self.client_id:
                        self.unread_counts[client_id] = self.unread_counts.get(client_id, 0) + 1
                        self.call_from_thread(self.update_contacts_list)
                    
                    logger.info(f"Received message from user {client_id}: {content[:50]}")

                elif msg_type == 'system':
                    content = message.get('message', '')
                    timestamp = message.get('timestamp', '')
                    msg = Message(content, is_mine=False, client_id=0, timestamp=timestamp)
                    self.messages.append(msg)
                    self.new_message_event.set()
                    self.call_from_thread(self.update_messages_display)
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
                    self.call_from_thread(self.update_contacts_list)

            except Exception as e:
                logger.error(f"Receive error: {e}")
                break

        self.connected = False

    def send_message(self, content: str) -> bool:
        if not self.running or not self.socket:
            return False

        try:
            self.message_id_counter += 1
            message_id = f"{self.client_id}_{self.message_id_counter}"

            message = json.dumps({
                'type': 'message',
                'content': content,
                'message_id': message_id
            })

            msg = Message(content, is_mine=True, client_id=self.client_id,
                         timestamp=datetime.now().strftime('%H:%M'),
                         acknowledged=False, message_id=message_id)
            self.messages.append(msg)
            self.pending_messages[message_id] = msg

            self.socket.send(message.encode('utf-8'))
            logger.info(f"Sent message: {content[:50]}")
            self.update_messages_display()
            return True
        except Exception as e:
            logger.error(f"Send error: {e}")
            return False

    def update_messages_display(self) -> None:
        try:
            chat_screen = self.screen
            if isinstance(chat_screen, ChatScreen):
                messages_display = chat_screen.query_one("#chat-messages", TextArea)

                if self.current_contact:
                    filtered = [msg for msg in self.messages
                               if msg.client_id == self.current_contact or msg.is_mine]
                else:
                    filtered = list(self.messages)

                lines = []
                for msg in filtered:
                    if msg.is_mine or msg.client_id == self.client_id:
                        sender = self.username if self.username else "You"
                        ack_status = "✓" if msg.acknowledged else "..."
                        lines.append(f"[{msg.timestamp}] {sender}: {msg.content} {ack_status}")
                    else:
                        sender = msg.username if msg.username else f"User {msg.client_id}"
                        lines.append(f"[{msg.timestamp}] {sender}: {msg.content}")

                messages_display.text = "\n".join(lines)
                messages_display.scroll_end()
        except Exception as e:
            logger.error(f"Display update error: {e}")

    def update_contacts_list(self) -> None:
        try:
            chat_screen = self.screen
            if isinstance(chat_screen, ChatScreen):
                contacts_list = chat_screen.query_one("#contacts-list", ListView)
                
                current_ids = {item.id for item in contacts_list.children} if contacts_list.children else set()
                new_ids = {f"user_{cid}" for cid in self.participants.keys()}
                
                for item in list(contacts_list.children):
                    if item.id not in new_ids:
                        item.remove()
                
                for client_id, username in self.participants.items():
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
        except Exception as e:
            logger.error(f"Contacts update error: {e}")

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.item and event.item.id:
            contact_id = int(event.item.id.replace("user_", ""))
            self.current_contact = contact_id
            self.unread_counts[contact_id] = 0
            self.update_messages_display()
            self.update_contacts_list()

    def on_key(self, event: events.Key) -> None:
        if event.key == "escape":
            self.exit()


if __name__ == '__main__':
    app = ChatClient()
    app.run()