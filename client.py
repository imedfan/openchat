"""
OpenChat Client — точка входа.
"""

import logging
import sys

from client.app import ChatApp

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("client.log", mode="w"),
        logging.StreamHandler(sys.stdout),
    ],
    force=True,
)
logger = logging.getLogger(__name__)


def main():
    app = ChatApp()
    app.run()


if __name__ == "__main__":
    main()
