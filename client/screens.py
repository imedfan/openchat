"""
Textual экраны: LoginScreen и ChatScreen.
"""

from textual.screen import Screen
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import Label, Input, Button, ListView, ListItem, TextArea, DataTable, Tabs, Tab
from textual.app import ComposeResult

from common.protocol import DEFAULT_IP, DEFAULT_PORT
from client.commands import registry


# ── CommandOverlay ─────────────────────────────────────────

class CommandOverlay(Vertical):
    """Overlay-окно со списком команд в стиле /cmd : description."""

    DEFAULT_CSS = """
    CommandOverlay {
        width: 100%;
        height: auto;
        max-height: 12;
        background: $surface;
        border: solid $primary;
        display: none;
        dock: bottom;
    }
    CommandOverlay #cmd-listview {
        width: 100%;
        height: 1fr;
    }
    CommandOverlay #cmd-listview > ListItem.--highlight {
        background: $accent;
        color: $text;
    }
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._selected_index: int = 0
        self._commands: list = []

    def compose(self) -> ComposeResult:
        yield ListView(id="cmd-listview")

    def update_commands(self, commands: list) -> None:
        """Обновить список команд в overlay."""
        lv = self.query_one("#cmd-listview", ListView)
        # Очищаем текущие элементы
        for child in list(lv.children):
            child.remove()

        self._commands = commands

        if not commands:
            self.styles.display = "none"
            return

        for cmd in commands:
            text = f"/{cmd.name}  \u2014  {cmd.description}"
            item = ListItem(Label(text))
            lv.append(item)

        self.styles.display = "block"
        self._selected_index = 0
        # Выделяем первый элемент
        try:
            lv.index = 0
        except Exception:
            pass
        self.refresh()

    def get_selected_command_name(self) -> str | None:
        """Вернуть имя выбранной команды."""
        lv = self.query_one("#cmd-listview", ListView)
        # Синхронизируем индекс с реальным состоянием ListView
        try:
            current_idx = lv.index
        except Exception:
            current_idx = 0
        self._selected_index = current_idx

        if self._commands and 0 <= current_idx < len(self._commands):
            return self._commands[current_idx].name
        return None

    def hide_overlay(self) -> None:
        self.styles.display = "none"
        self._selected_index = 0


# ── CommandInput ───────────────────────────────────────────

class CommandInput(Input):
    """Input с overlay-окном команд при /."""

    BINDINGS = [
        ("tab", "autocomplete", "Autocomplete"),
    ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._overlay: CommandOverlay | None = None
        self._matches: list = []
        self._suppress_submit: bool = False

    def set_overlay(self, widget: CommandOverlay) -> None:
        self._overlay = widget

    def _update_overlay(self, context: str | None = None) -> None:
        if not self._overlay:
            return

        text = self.value
        if not text.startswith("/"):
            self._overlay.hide_overlay()
            return

        parts = text[1:].split()
        if len(parts) == 0:
            # Только / — показать все команды контекста
            matches = registry.list_all(context)
        else:
            prefix = parts[0]
            matches = registry.match_prefix(prefix, context)

        self._matches = matches
        self._overlay.update_commands(matches)

    def action_autocomplete(self) -> None:
        """Tab: выбрать команду из overlay или дописать префикс."""
        if self._overlay and self._overlay.styles.display != "none":
            cmd_name = self._overlay.get_selected_command_name()
            if cmd_name:
                self.value = f"/{cmd_name} "
                self._overlay.hide_overlay()
                return

        # Fallback: как раньше — общий префикс
        if not self._matches:
            return
        if len(self._matches) == 1:
            self.value = f"/{self._matches[0].name} "
        else:
            names = [cmd.name for cmd in self._matches]
            prefix = ""
            for chars in zip(*names):
                if len(set(chars)) == 1:
                    prefix += chars[0]
                else:
                    break
            if prefix:
                self.value = f"/{prefix}"

    def hide_overlay(self) -> None:
        if self._overlay:
            self._overlay.hide_overlay()

    def _update_overlay_from_parent(self) -> None:
        """Определить контекст из родительского экрана и обновить overlay."""
        try:
            parent = self.screen
            ws = parent.app.ws
            context = "dm" if ws.current_contact else "general"
            self._update_overlay(context)
        except Exception:
            pass

    def on_input_changed(self, event: Input.Changed) -> None:
        self._update_overlay_from_parent()

    def on_key(self, event) -> None:
        """Обработка клавиш: стрелки для overlay, Esc для закрытия, Enter для автокомплита."""
        if self._overlay and self._overlay.styles.display != "none":
            if event.key == "up":
                lv = self._overlay.query_one("#cmd-listview", ListView)
                if lv.children and lv.index > 0:
                    lv.index = lv.index - 1
                event.prevent_default()
                return
            elif event.key == "down":
                lv = self._overlay.query_one("#cmd-listview", ListView)
                if lv.children and lv.index < len(lv.children) - 1:
                    lv.index = lv.index + 1
                event.prevent_default()
                return
            elif event.key == "enter":
                # Проверяем: если текст — только команда (без аргументов) → автокомплит
                text = self.value
                parts = text[1:].split()
                if len(parts) <= 1:
                    # Нет аргументов → вставляем команду, блокируем submit
                    cmd_name = self._overlay.get_selected_command_name()
                    if cmd_name:
                        self.value = f"/{cmd_name} "
                        self.cursor_position = len(self.value)
                        self._suppress_submit = True
                        event.prevent_default()
                    return
                # Есть аргументы → пропускаем Enter (отправка)
            elif event.key == "escape":
                self._overlay.hide_overlay()
                event.prevent_default()
                return


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
        background: $primary;
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
        border: round $primary;
        layout: vertical;
    }

    #contacts-header {
        width: 100%;
        height: 1;
        dock: top;
        content-align: center middle;
        text-align: center;
        text-style: bold;
        background: $primary;
        color: $text;
        padding: 0;
        margin: 0;
    }

    #contacts-list {
        width: 100%;
        height: 1fr;
    }

    #chat-panel {
        width: 1fr;
        height: 100%;
        layout: vertical;
        border: round $primary;
    }

    #chat-tabs {
        dock: top;
        height: 1;
    }

    #chat-messages {
        width: 1fr;
        height: 1fr;
    }

    #command-overlay {
        width: 100%;
        height: auto;
        max-height: 40%;
        background: $surface;
        border: solid $primary;
        display: none;
        dock: bottom;
    }

    #message-bar {
        width: 100%;
        height: auto;
        dock: bottom;
        layout: horizontal;
    }

    #message-input {
        width: 1fr;
    }

    #send-btn {
        width: auto;
        margin: 0 1 0 0;
    }
    """

    def compose(self) -> ComposeResult:
        with Horizontal(id="chat-layout"):
            with Container(id="contacts-panel"):
                yield Label("Participants", id="contacts-header")
                yield ListView(id="contacts-list")

            with Container(id="chat-panel"):
                yield Tabs(
                    Tab("General", id="tab-general"),
                    id="chat-tabs",
                )
                yield TextArea(id="chat-messages", read_only=True)
                yield CommandOverlay(id="command-overlay")
                with Horizontal(id="message-bar"):
                    yield CommandInput(placeholder="Type a message...  /help for commands", id="message-input")
                    yield Button("Send", id="send-btn", variant="success")

    def on_mount(self) -> None:
        msg_input = self.query_one("#message-input", CommandInput)
        overlay = self.query_one("#command-overlay", CommandOverlay)
        msg_input.set_overlay(overlay)
        msg_input.focus()
        # Установить начальное состояние кнопки (disabled когда поле пустое)
        self._update_send_button_state()

    def _update_send_button_state(self) -> None:
        """Обновить состояние кнопки Send (disabled если поле пустое)."""
        try:
            msg_input = self.query_one("#message-input", Input)
            send_btn = self.query_one("#send-btn", Button)
            send_btn.disabled = not msg_input.value.strip()
        except Exception:
            pass

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "message-input":
            self._update_send_button_state()
