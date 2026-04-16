"""
LLM Chat Screen — экран для общения с LLM-моделями.
"""

from textual.screen import Screen
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import Label, Input, Button, Select, Static, RichLog
from textual.app import ComposeResult
from rich.text import Text
from typing import Optional, List


class LLMChatScreen(Screen):
    """Экран чата с LLM-моделью: выбор модели + история диалога + ввод."""

    CSS = """
    LLMChatScreen {
        layout: vertical;
    }

    #llm-header {
        width: 100%;
        height: 3;
        dock: top;
        background: $surface-darken-1;
        border: round $primary;
        layout: horizontal;
        padding: 0 2;
    }

    #model-selector {
        width: 1fr;
        height: 1fr;
        content-align: left middle;
    }

    #back-btn {
        width: auto;
        height: 1fr;
        margin: 0 1 0 0;
    }

    #llm-messages {
        width: 100%;
        height: 1fr;
        background: $surface;
        border: round $primary;
    }

    #llm-input-bar {
        width: 100%;
        height: auto;
        dock: bottom;
        layout: horizontal;
    }

    #llm-input {
        width: 1fr;
    }

    #llm-send-btn {
        width: auto;
        margin: 0 1 0 0;
    }

    #llm-status {
        width: 100%;
        height: 1;
        dock: bottom;
        content-align: center middle;
        color: $success;
    }

    #llm-status.streaming {
        color: $warning;
    }
    """

    def __init__(self, app):
        super().__init__()
        self.app_ref = app
        self.conversation_history: List[dict] = []  # [{"role": "user", "content": "..."}, ...]
        self.current_model_id: Optional[str] = None
        self.is_streaming = False
        self._current_response_text = ""

    def compose(self) -> ComposeResult:
        # Header с выбором модели
        with Horizontal(id="llm-header"):
            model_options = self._get_model_options()
            yield Select(model_options, id="model-selector", prompt="Select model...")
            yield Button("← Back", id="back-btn", variant="default")

        # Область сообщений
        yield RichLog(id="llm-messages", markup=True, wrap=True)

        # Статус стриминга
        yield Static("", id="llm-status")

        # Панель ввода
        with Horizontal(id="llm-input-bar"):
            yield Input(placeholder="Ask LLM...", id="llm-input")
            yield Button("Send", id="llm-send-btn", variant="success")

    def _get_model_options(self) -> list:
        """Возвращает список опций для Select из доступных моделей."""
        models = self.app_ref.ws.available_models if hasattr(self.app_ref, 'ws') else []
        options = []
        for m in models:
            options.append((m["name"], m["id"]))
        return options

    def on_mount(self) -> None:
        # Обновляем список моделей в Select
        self._update_model_selector()
        # Фокус на поле ввода
        self.query_one("#llm-input", Input).focus()

    def _update_model_selector(self) -> None:
        """Обновляет опции в Select при получении списка моделей."""
        try:
            selector = self.query_one("#model-selector", Select)
            options = self._get_model_options()
            selector.set_options(options)

            # Если только одна модель — выбираем её
            if len(options) == 1:
                selector.value = options[0][1]
                self.current_model_id = options[0][1]
        except Exception as e:
            self.log(f"Error updating model selector: {e}")

    def on_select_changed(self, event: Select.Changed) -> None:
        """При смене модели сохраняем ID."""
        if event.value is not None and event.value != Select.BLANK:
            self.current_model_id = event.value

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "back-btn":
            self.dismiss()
        elif event.button.id == "llm-send-btn":
            self._send_message()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "llm-input":
            self._send_message()

    def _send_message(self) -> None:
        """Отправить сообщение LLM-модели."""
        if self.is_streaming:
            self.notify("Wait for the current response to complete", severity="warning")
            return

        input_widget = self.query_one("#llm-input", Input)
        content = input_widget.value.strip()
        if not content:
            return

        input_widget.value = ""

        # Проверяем что модель выбрана
        if not self.current_model_id:
            self.notify("Please select a model first", severity="warning")
            return

        # Добавляем сообщение пользователя в историю
        self.conversation_history.append({"role": "user", "content": content})

        # Отображаем сообщение пользователя
        messages_widget = self.query_one("#llm-messages", RichLog)
        messages_widget.write(f"[bold blue]You:[/bold blue] {content}\n")

        # Готовим место для ответа LLM
        self._current_response_text = ""
        messages_widget.write("[bold green]LLM:[/bold green] ")

        # Включаем индикатор стриминга
        self._set_streaming_status(True)

        # Отправляем запрос на сервер
        ws = self.app_ref.ws
        self.app_ref.run_worker(
            ws.send_llm_request(
                self.current_model_id,
                list(self.conversation_history),  # полная история
                callback=self._on_llm_chunk
            ),
            exclusive=True
        )

    def _on_llm_chunk(self, chunk: str, done: bool):
        """Callback для обработкики chunks от LLM (вызывается из ws_client)."""
        if done:
            # Завершение стриминга — добавляем полный ответ в историю
            if self._current_response_text.strip():
                self.conversation_history.append({
                    "role": "assistant",
                    "content": self._current_response_text.strip()
                })
            self._current_response_text = ""
            return

        # Накапливаем текст
        self._current_response_text += chunk

    def _set_streaming_status(self, streaming: bool) -> None:
        """Обновить индикатор статуса стриминга."""
        self.is_streaming = streaming
        try:
            status_widget = self.query_one("#llm-status", Static)
            send_btn = self.query_one("#llm-send-btn", Button)
            if streaming:
                status_widget.update("[yellow]● LLM is typing...[/yellow]")
                status_widget.add_class("streaming")
                send_btn.disabled = True
                send_btn.variant = "default"
            else:
                status_widget.update("")
                status_widget.remove_class("streaming")
                send_btn.disabled = False
                send_btn.variant = "success"
        except Exception:
            pass
