"""
OpenChat Client — точка входа.
"""

import logging

from client.app import ChatApp
from client.commands.builtin import register_builtin_commands

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("client.log", mode="w"),
    ],
    force=True,
)
logger = logging.getLogger(__name__)


def main():
    register_builtin_commands()
    app = ChatApp()
    app.run()


if __name__ == "__main__":
    main()
