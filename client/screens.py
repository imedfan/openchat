"""
Textual экраны: LoginScreen и ChatScreen.
"""

from textual.screen import Screen
from textual.containers import Container, Horizontal
from textual.widgets import Label, Input, Button, ListView, ListItem, TextArea, DataTable
from textual.app import ComposeResult
from textual.events import Key

from common.protocol import DEFAULT_IP, DEFAULT_PORT
from client.commands import registry


# ── CommandInput ───────────────────────────────────────────

class CommandInput(Input):
    """Input с автодополнением команд при /."""

    BINDINGS = [("tab", "autocomplete", "Autocomplete")]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._suggestions: Label | None = None
        self._matches: list = []

    def set_suggestions_label(self, widget: Label) -> None:
        self._suggestions = widget

    def _update_suggestions(self) -> None:
        if not self._suggestions:
            return

        text = self.value
        if not text.startswith("/"):
            self._hide_suggestions()
            return

        parts = text[1:].split()
        if len(parts) > 1:
            self._hide_suggestions()
            return

        prefix = parts[0] if parts else ""
        matches = registry.match_prefix(prefix)

        if not matches:
            self._hide_suggestions()
            return

        self._matches = matches
        names = ", ".join(f"/{cmd.name}" for cmd in matches)
        self._suggestions.update(names)
        self._suggestions.styles.display = "block"

    def _hide_suggestions(self) -> None:
        if self._suggestions:
            self._suggestions.styles.display = "none"
        self._matches = []

    def action_autocomplete(self) -> None:
        if not self._matches:
            return
        if len(self._matches) == 1:
            self.value = f"/{self._matches[0].name} "
        else:
            # Общий префикс
            names = [cmd.name for cmd in self._matches]
            prefix = ""
            for chars in zip(*names):
                if len(set(chars)) == 1:
                    prefix += chars[0]
                else:
                    break
            if prefix:
                self.value = f"/{prefix}"
        self._hide_suggestions()

    def on_input_changed(self, event: Input.Changed) -> None:
        self._update_suggestions()


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

    #contacts-list > ListItem.--highlight {
        background: $accent;
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

    #cmd-suggestions {
        width: 100%;
        height: auto;
        background: $surface;
        color: $text-muted;
        padding: 0 2;
        display: none;
        dock: bottom;
    }

    #message-input {
        width: 100%;
        dock: bottom;
    }
    """

    def compose(self) -> ComposeResult:
        with Horizontal(id="chat-layout"):
            with Container(id="contacts-panel"):
                yield Label("Participants", id="contacts-header")
                yield ListView(id="contacts-list")

            with Container(id="chat-panel"):
                yield Label("General", id="chat-header-label")
                yield TextArea(id="chat-messages", read_only=True)
                yield Label("", id="cmd-suggestions")
                yield CommandInput(placeholder="Type a message...  /help for commands", id="message-input")

    def on_mount(self) -> None:
        msg_input = self.query_one("#message-input", CommandInput)
        sugg = self.query_one("#cmd-suggestions", Label)
        msg_input.set_suggestions_label(sugg)
        msg_input.focus()
