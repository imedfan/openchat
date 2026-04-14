"""
Система команд: registry + базовый класс.
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Tuple


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

    @property
    def contexts(self) -> List[str]:
        """Контексты, в которых доступна команда: 'general' и/или 'dm'."""
        return ["general", "dm"]

    @abstractmethod
    async def execute(self, ws, args: List[str]) -> Optional[str]:
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
        self._commands: Dict[str, ChatCommand] = {}

    def register(self, cmd: ChatCommand) -> None:
        self._commands[cmd.name.lower()] = cmd

    def get(self, name: str) -> Optional[ChatCommand]:
        return self._commands.get(name.lower())

    def list_all(self, context: Optional[str] = None) -> List[ChatCommand]:
        cmds = sorted(self._commands.values(), key=lambda c: c.name)
        if context:
            cmds = [c for c in cmds if context in c.contexts]
        return cmds

    def parse(self, text: str) -> Optional[Tuple[str, List[str]]]:
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

    def match_prefix(self, prefix: str, context: Optional[str] = None) -> List[ChatCommand]:
        """Найти команды начинающиеся с prefix, с фильтрацией по контексту."""
        prefix = prefix.lower().lstrip("/")
        return [
            cmd for cmd in self.list_all(context)
            if cmd.name.startswith(prefix)
        ]


# Глобальный реестр
registry = CommandRegistry()
