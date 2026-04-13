"""
Встроенные команды.
"""

from client.commands import ChatCommand, registry


# ── /help ──────────────────────────────────────────────────

class HelpCommand(ChatCommand):
    @property
    def name(self) -> str:
        return "help"

    @property
    def description(self) -> str:
        return "Show available commands"

    async def execute(self, ws, args: list[str]) -> str | None:
        cmds = registry.list_all()
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
        return "Clear chat history"

    async def execute(self, ws, args: list[str]) -> str | None:
        ws.messages.clear()
        ws.unread_counts.clear()
        return None  # тихо, UI обновится отдельно


# ── /users ─────────────────────────────────────────────────

class UsersCommand(ChatCommand):
    @property
    def name(self) -> str:
        return "users"

    @property
    def description(self) -> str:
        return "Show online users"

    async def execute(self, ws, args: list[str]) -> str | None:
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

    async def execute(self, ws, args: list[str]) -> str | None:
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
        return "Send action message"

    @property
    def usage(self) -> str:
        return "/me <action>"

    async def execute(self, ws, args: list[str]) -> str | None:
        if not args:
            return "Usage: /me <action>"
        return None  # обрабатывается отдельно в UI


# ── Регистрация ────────────────────────────────────────────

def register_builtin_commands():
    registry.register(HelpCommand())
    registry.register(ClearCommand())
    registry.register(UsersCommand())
    registry.register(DMCommand())
    registry.register(MeCommand())
