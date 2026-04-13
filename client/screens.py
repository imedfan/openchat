"""
Textual экраны: LoginScreen и ChatScreen.
"""

from textual.screen import Screen
from textual.containers import Container, Horizontal
from textual.widgets import Label, Input, Button, ListView, ListItem, TextArea
from textual.app import ComposeResult

from common.protocol import DEFAULT_IP, DEFAULT_PORT


# ── LoginScreen ────────────────────────────────────────────

class LoginScreen(Screen):
    """Экран входа: username, IP, port."""

    CSS = """
    LoginScreen {
        align: center middle;
    }

    #login-container {
        width: 50;
        height: auto;
        padding: 2 4;
        background: $surface;
        border: double $primary;
        layout: vertical;
    }

    #login-title {
        text-style: bold;
        content-align: center middle;
        padding: 1 0;
        margin-bottom: 1;
    }

    #login-container Input {
        margin-bottom: 1;
        width: 100%;
    }

    #connect-btn {
        width: 100%;
        margin-top: 1;
    }
    """

    def __init__(self, on_connect_callback):
        super().__init__()
        self._on_connect = on_connect_callback

    def compose(self) -> ComposeResult:
        with Container(id="login-container"):
            yield Label("OpenChat", id="login-title")
            yield Input(placeholder="Username", id="username-input")
            yield Input(placeholder="IP Address", id="ip-input", value=DEFAULT_IP)
            yield Input(placeholder="Port", id="port-input", value=str(DEFAULT_PORT))
            yield Button("Connect", id="connect-btn", variant="primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "connect-btn":
            username = self.query_one("#username-input", Input).value.strip()
            ip = self.query_one("#ip-input", Input).value.strip()
            port_str = self.query_one("#port-input", Input).value.strip()

            if not username:
                self.notify("Enter username", severity="warning")
                return

            try:
                port = int(port_str)
            except ValueError:
                self.notify("Invalid port", severity="warning")
                return

            self._on_connect(username, ip, port)


# ── ChatScreen ─────────────────────────────────────────────

class ChatScreen(Screen):
    """Экран чата: список контактов + сообщения + ввод."""

    CSS = """
    .unread {
        background: $accent-darken-2;
    }

    #chat-layout {
        width: 100%;
        height: 100%;
        layout: horizontal;
    }

    #contacts-panel {
        width: 25;
        height: 100%;
        background: $surface-darken-1;
        border-right: solid $primary;
        layout: vertical;
    }

    #contacts-header {
        padding: 1 2;
        text-style: bold;
        background: $primary;
        color: $text;
    }

    #contacts-list {
        width: 100%;
        height: 1fr;
    }

    #chat-panel {
        width: 1fr;
        height: 100%;
        layout: vertical;
    }

    #chat-header-label {
        padding: 1 2;
        text-style: bold;
        background: $primary;
        color: $text;
    }

    #chat-messages {
        width: 1fr;
        height: 1fr;
    }

    #message-input {
        width: 100%;
        dock: bottom;
    }
    """

    def compose(self) -> ComposeResult:
        with Horizontal(id="chat-layout"):
            # Левая панель — контакты
            with Container(id="contacts-panel"):
                yield Label("Participants", id="contacts-header")
                yield ListView(id="contacts-list")

            # Правая панель — чат
            with Container(id="chat-panel"):
                yield Label("General", id="chat-header-label")
                yield TextArea(id="chat-messages", read_only=True)
                yield Input(placeholder="Type a message...", id="message-input")

    def on_mount(self) -> None:
        self.query_one("#message-input", Input).focus()
