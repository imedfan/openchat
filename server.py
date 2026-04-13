"""
OpenChat Server — точка входа.
"""

import asyncio
import logging

from server.handler import ChatServer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("server.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)


async def main():
    import sys
    port = 5000
    if len(sys.argv) > 1:
        port = int(sys.argv[1])

    server = ChatServer(port=port)
    async with server.start():
        await asyncio.Future()  # run forever


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Server stopped")
        print(f"\n{'='*50}")
        print(f"  OpenChat Server shutting down...")
        print(f"  Goodbye! See you next time!")
        print(f"{'='*50}")
