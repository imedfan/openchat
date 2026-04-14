"""
Textual экраны: LoginScreen и ChatScreen.
"""

from textual.screen import Screen
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import Label, Input, Button, ListView, ListItem, TextArea, DataTable, Tabs, Tab, Static
from textual.widget import Widget
from textual.app import ComposeResult
from rich.text import Text
from rich.style import Style
import random
import asyncio

from common.protocol import DEFAULT_IP, DEFAULT_PORT
from client.commands import registry


# ── Banner: "OpenChat" block-art с градиентом и тенью ──────

# Буквы как матрица 7×7 с использованием полных и полублоков
# Для создания объёмного эффекта используем █ для основы и ░ для тени
_BLOCK_FONTS = {
    "O": [
        "  ████  ",
        " ██  ██ ",
        "██    ██",
        "██    ██",
        "██    ██",
        " ██  ██ ",
        "  ████  ",
    ],
    "p": [
        "██████  ",
        "██   ██ ",
        "██████  ",
        "██      ",
        "██      ",
        "██      ",
        "██      ",
    ],
    "e": [
        " ██████ ",
        "██      ",
        "██      ",
        "██████  ",
        "██      ",
        "██      ",
        " ██████ ",
    ],
    "n": [
        "███  ██ ",
        "███  ██ ",
        "████ ██ ",
        "██ ███  ",
        "██  ██  ",
        "██   ██ ",
        "██   ██ ",
    ],
    "C": [
        " ██████ ",
        "██    ██",
        "██      ",
        "██      ",
        "██      ",
        "██    ██",
        " ██████ ",
    ],
    "h": [
        "██      ",
        "██      ",
        "██████  ",
        "██   ██ ",
        "██    ██",
        "██    ██",
        "██    ██",
    ],
    "a": [
        " ██████ ",
        "██    ██",
        "██    ██",
        "████████",
        "██    ██",
        "██    ██",
        "██    ██",
    ],
    "t": [
        "   ██   ",
        "  ████  ",
        " █████  ",
        "   ██   ",
        "   ██   ",
        "   ██   ",
        "  ████  ",
    ],
}

# Разделитель между буквами
_BLOCK_SEP = "   "

# Градиент: глубокий фиолетовый → розовый → оранжевый → золотой
_GRADIENT_COLORS = [
    (128, 0, 128),      # глубокий фиолетовый
    (200, 50, 150),     # розовый
    (255, 120, 50),     # оранжевый
    (255, 200, 50),     # золотой
]

# Цвет тени
_SHADOW_COLOR = (40, 40, 60)  # тёмно-синий/серый


def _interpolate_color(colors, pos):
    """Интерполяция цвета по позиции."""
    if len(colors) <= 1:
        return colors[0]
    seg = pos * (len(colors) - 1)
    idx = int(seg)
    t = seg - idx
    if idx >= len(colors) - 1:
        return colors[-1]
    c1 = colors[idx]
    c2 = colors[idx + 1]
    return (
        int(c1[0] + (c2[0] - c1[0]) * t),
        int(c1[1] + (c2[1] - c1[1]) * t),
        int(c1[2] + (c2[2] - c1[2]) * t),
    )


def make_openchat_banner() -> Text:
    """Создать простую текстовую надпись 'OpenChat'."""
    return Text("OpenChat", Style(color="cyan", bold=True))


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


# ── NodeNetworkBackground ─────────────────────────────────

class NodeNetworkBackground(Widget):
    """Анимированный фон с узлами-точками, которые появляются, соединяются и исчезают."""

    DEFAULT_CSS = """
    NodeNetworkBackground {
        width: 100%;
        height: 100%;
        opacity: 0.3;
    }
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.nodes = []
        self.connections = []
        self.max_nodes = 20
        self.max_connections = 30
        self.update_interval = 0.35
        # Цвета для узлов (от тёмного к светлому)
        self.node_colors = [
            (100, 100, 180),   # тёмно-синий
            (140, 140, 220),   # синий
            (180, 160, 255),   # светло-фиолетовый
            (200, 180, 255),   # светлый фиолетовый
            (220, 200, 255),   # очень светлый
        ]

    class Node:
        def __init__(self, x, y):
            self.x = x
            self.y = y
            self.life = 0.0  # 0→1→0 (появление→пик→исчезновение)
            self.max_life = 1.0
            self.speed = random.uniform(0.003, 0.008)
            self.vx = random.uniform(-0.05, 0.05)
            self.vy = random.uniform(-0.05, 0.05)

        def update(self):
            self.life += self.speed
            self.x += self.vx
            self.y += self.vy
            # Отскок от краёв
            if self.x < 0 or self.x > 1:
                self.vx *= -1
                self.x = max(0, min(1, self.x))
            if self.y < 0 or self.y > 1:
                self.vy *= -1
                self.y = max(0, min(1, self.y))

        @property
        def is_alive(self):
            return 0 < self.life < self.max_life

        @property
        def brightness(self):
            # Плавное появление и затухание (колокол)
            if self.life <= 0:
                return 0
            if self.life < 0.3:
                return self.life / 0.3
            if self.life > 0.7:
                return (1.0 - self.life) / 0.3
            return 1.0

    def on_mount(self) -> None:
        self.set_interval(self.update_interval, self.update_network)

    def update_network(self) -> None:
        """Обновить состояние сети узлов."""
        # Обновляем существующие узлы
        for node in self.nodes:
            node.update()

        # Удаляем мёртвые
        self.nodes = [n for n in self.nodes if n.is_alive]

        # Добавляем новые, если есть место
        if len(self.nodes) < self.max_nodes and random.random() < 0.15:
            self.nodes.append(self.Node(
                x=random.uniform(0.1, 0.9),
                y=random.uniform(0.1, 0.9)
            ))

        # Создаём соединения между близкими узлами
        self.connections = []
        connection_distance = 0.3
        for i, n1 in enumerate(self.nodes):
            for j, n2 in enumerate(self.nodes[i+1:], i+1):
                dx = n1.x - n2.x
                dy = n1.y - n2.y
                dist = (dx*dx + dy*dy) ** 0.5
                if dist < connection_distance:
                    # Прозрачность линии зависит от яркости обоих узлов
                    alpha = min(n1.brightness, n2.brightness) * (1 - dist / connection_distance)
                    if alpha > 0.1:
                        self.connections.append((n1, n2, alpha))

        self.refresh()

    def render(self):
        """Отрисовать сеть узлов через ASCII-арт."""
        width = self.size.width
        height = self.size.height

        if width <= 0 or height <= 0:
            return Text("")

        # Буфер: каждый элемент — (символ, Style или None)
        buffer = [[(" ", None) for _ in range(width)] for _ in range(height)]

        # Рисуем соединения (линии)
        for n1, n2, alpha in self.connections:
            x1, y1 = int(n1.x * (width - 1)), int(n1.y * (height - 1))
            x2, y2 = int(n2.x * (width - 1)), int(n2.y * (height - 1))
            self._draw_line(buffer, x1, y1, x2, y2, alpha)

        # Рисуем узлы
        for node in self.nodes:
            x = int(node.x * (width - 1))
            y = int(node.y * (height - 1))
            if 0 <= x < width and 0 <= y < height:
                brightness = node.brightness
                color_idx = int(brightness * (len(self.node_colors) - 1))
                r, g, b = self.node_colors[color_idx]
                factor = 0.6 + brightness * 0.6
                r = min(255, int(r * factor))
                g = min(255, int(g * factor))
                b = min(255, int(b * factor))
                style = Style(color=f"rgb({r},{g},{b})")
                # Не перезаписываем если уже есть что-то (линия)
                if buffer[y][x][0] == " ":
                    buffer[y][x] = ("●", style)

        # Собираем в Text
        result = Text()
        for row in buffer:
            for ch, style in row:
                if style:
                    result.append(ch, style)
                else:
                    result.append(ch)
            result.append("\n")

        return result

    def _draw_line(self, buffer, x1, y1, x2, y2, alpha):
        """Рисует линию между двумя точками с заданной прозрачностью."""
        dx = abs(x2 - x1)
        dy = abs(y2 - y1)
        sx = 1 if x1 < x2 else -1
        sy = 1 if y1 < y2 else -1
        err = dx - dy

        x, y = x1, y1
        r = min(255, int(120 + alpha * 120))
        g = min(255, int(120 + alpha * 120))
        b = min(255, int(200 + alpha * 55))
        style = Style(color=f"rgb({r},{g},{b})")

        while True:
            if 0 <= x < len(buffer[0]) and 0 <= y < len(buffer):
                if buffer[y][x][0] == " ":
                    buffer[y][x] = ("·", style)

            if x == x2 and y == y2:
                break
            e2 = 2 * err
            if e2 > -dy:
                err -= dy
                x += sx
            if e2 < dx:
                err += dx
                y += sy


# ── LoginScreen ────────────────────────────────────────────

class LoginScreen(Screen):
    """Экран входа: username, IP, port."""

    CSS = """
    LoginScreen {
        layers: background content;
        align: center middle;
    }

    NodeNetworkBackground {
        layer: background;
        width: 100%;
        height: 100%;
    }

    #login-container {
        layer: content;
        width: 60;
        height: auto;
        padding: 2 4;
        background: $surface 80%;
        border: double $primary;
        layout: vertical;
    }

    #login-title {
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
        yield NodeNetworkBackground()
        with Container(id="login-container"):
            yield Static(make_openchat_banner(), id="login-title")
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
