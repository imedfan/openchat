"""
Встроенные команды.
"""

from typing import List, Optional

from commands import ChatCommand, registry


# ── /command ───────────────────────────────────────────────

class CommandCommand(ChatCommand):
    @property
    def name(self) -> str:
        return "command"

    @property
    def description(self) -> str:
        return "Show available commands"

    async def execute(self, ws, args: List[str]) -> Optional[str]:
        # Показываем команды текущего контекста
        context = "dm" if ws.current_contact else "general"
        cmds = registry.list_all(context)
        lines = ["Available commands:"]
        for cmd in cmds:
            lines.append(f"  {cmd.usage} — {cmd.description}")
        return "\n".join(lines)


# ── /clear ─────────────────────────────────────────────────

class ClearCommand(ChatCommand):
    @property
    def name(self) -> str:
        return "clear"

    @property
    def description(self) -> str:
        return "Clear current chat history"

    @property
    def contexts(self) -> List[str]:
        return ["general", "dm"]

    async def execute(self, ws, args: List[str]) -> Optional[str]:
        if ws.current_contact:
            # DM: удалить сообщения текущего DM-чата
            ws.messages = [
                msg for msg in ws.messages
                if not (
                    (msg.is_direct and msg.client_id == ws.current_contact) or
                    (msg.is_mine and msg.target_id == ws.current_contact)
                )
            ]
        else:
            # General: удалить broadcast и system сообщения
            ws.messages = [
                msg for msg in ws.messages
                if msg.is_direct
            ]
        return None  # тихо, UI обновится отдельно


# ── /users ─────────────────────────────────────────────────

class UsersCommand(ChatCommand):
    @property
    def name(self) -> str:
        return "users"

    @property
    def description(self) -> str:
        return "Show online users"

    @property
    def contexts(self) -> List[str]:
        return ["general"]

    async def execute(self, ws, args: List[str]) -> Optional[str]:
        others = {cid: data for cid, data in ws.participants.items()
                  if cid != ws.client_id}
        if not others:
            return "No other users online"
        lines = ["Online users:"]
        for cid, data in others.items():
            uname = data.get("username", f"User {cid}")
            lines.append(f"  {uname} (ID: {cid})")
        return "\n".join(lines)


# ── /dm <user> ─────────────────────────────────────────────

class DMCommand(ChatCommand):
    @property
    def name(self) -> str:
        return "dm"

    @property
    def description(self) -> str:
        return "Switch to private chat with user"

    @property
    def usage(self) -> str:
        return "/dm <username>"

    @property
    def contexts(self) -> List[str]:
        return ["general"]

    async def execute(self, ws, args: List[str]) -> Optional[str]:
        if ws.current_contact:
            return "Already in a DM chat. Use Esc to return to General."

        if not args:
            return "Usage: /dm <username>"

        target_name = args[0].lower()
        for cid, data in ws.participants.items():
            if data.get("username", "").lower() == target_name and cid != ws.client_id:
                ws.current_contact = cid
                ws.unread_counts[cid] = 0
                return f"Switched to DM with {data['username']}"

        return f"User '{args[0]}' not found online"


# ── /me <action> ───────────────────────────────────────────

class MeCommand(ChatCommand):
    @property
    def name(self) -> str:
        return "me"

    @property
    def description(self) -> str:
        return "Send an action message in italic"

    @property
    def usage(self) -> str:
        return "/me <action>"

    @property
    def contexts(self) -> List[str]:
        return ["general", "dm"]

    async def execute(self, ws, args: List[str]) -> Optional[str]:
        if not args:
            return "Usage: /me <action>"
        # Отправляем как обычное сообщение с пометкой
        content = " ".join(args)
        if ws.current_contact:
            await ws.send_direct(ws.current_contact, f"/me {content}")
        else:
            await ws.send_broadcast(f"/me {content}")
        return None  # сообщение отправлено, UI обновится


# ── /exit ──────────────────────────────────────────────────

class ExitCommand(ChatCommand):
    @property
    def name(self) -> str:
        return "exit"

    @property
    def description(self) -> str:
        return "Disconnect from server and return to login"

    @property
    def contexts(self) -> List[str]:
        return ["general", "dm"]

    async def execute(self, ws, args: List[str]) -> Optional[str]:
        ws.app.do_disconnect()
        return None  # UI обновится отдельно


# ── /ai ────────────────────────────────────────────────────

class AICommand(ChatCommand):
    @property
    def name(self) -> str:
        return "ai"

    @property
    def description(self) -> str:
        return "Open LLM chat"

    @property
    def contexts(self) -> list:
        return ["general", "dm"]

    async def execute(self, ws, args: list):
        # Открываем LLM-чат через приложение
        ws.app.open_llm_chat()
        return None


# ── Регистрация ────────────────────────────────────────────

def register_builtin_commands():
    registry.register(CommandCommand())
    registry.register(ClearCommand())
    registry.register(UsersCommand())
    registry.register(DMCommand())
    registry.register(MeCommand())
    registry.register(ExitCommand())
    registry.register(AICommand())
