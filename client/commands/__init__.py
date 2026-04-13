"""
Система команд: registry + базовый класс.
"""

from abc import ABC, abstractmethod


class ChatCommand(ABC):
    """Базовый класс для команд."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Имя команды (без /)."""
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """Краткое описание."""
        ...

    @property
    def usage(self) -> str:
        """Пример использования. По умолчанию /name."""
        return f"/{self.name}"

    @abstractmethod
    async def execute(self, ws, args: list[str]) -> str | None:
        """
        Выполнить команду.
        ws — экземпляр WSClient.
        args — список аргументов после имени команды.
        Возвращает строку (сообщение для пользователя) или None (тихое выполнение).
        """
        ...


class CommandRegistry:
    """Реестр команд."""

    def __init__(self):
        self._commands: dict[str, ChatCommand] = {}

    def register(self, cmd: ChatCommand) -> None:
        self._commands[cmd.name.lower()] = cmd

    def get(self, name: str) -> ChatCommand | None:
        return self._commands.get(name.lower())

    def list_all(self) -> list[ChatCommand]:
        return sorted(self._commands.values(), key=lambda c: c.name)

    def parse(self, text: str) -> tuple[str, list[str]] | None:
        """
        Парсит текст команды.
        "/dm Alice hello" → ("dm", ["Alice", "hello"])
        "просто текст" → None
        """
        text = text.strip()
        if not text.startswith("/"):
            return None

        parts = text[1:].split()
        if not parts:
            return None

        cmd_name = parts[0]
        cmd_args = parts[1:]
        return cmd_name, cmd_args

    def match_prefix(self, prefix: str) -> list[ChatCommand]:
        """Найти команды начинающиеся с prefix."""
        prefix = prefix.lower().lstrip("/")
        return [
            cmd for cmd in self.list_all()
            if cmd.name.startswith(prefix)
        ]


# Глобальный реестр
registry = CommandRegistry()
