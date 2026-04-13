import asyncio
import json
import logging
import socket
import websockets
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('server.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class ChatServer:
    def __init__(self, host='0.0.0.0', port=5000):
        self.host = host
        self.port = port
        self.clients = {}
        self.client_usernames = {}
        self.client_id_counter = 1
        self.lock = asyncio.Lock()

    async def _get_participants_list(self):
        return [
            {'client_id': cid, 'username': self.client_usernames.get(cid, f'User {cid}')}
            for cid in self.clients.keys()
        ]

    async def _send_participants_to_all(self, exclude=None):
        exclude = exclude or []
        async with self.lock:
            participant_count = len(self.clients)
            participants_list = await self._get_participants_list()

        count_msg = json.dumps({
            'type': 'participants',
            'count': participant_count,
            'participants': participants_list
        })

        async with self.lock:
            targets = list(self.clients.items())

        for client_id, client_ws in targets:
            if client_id not in exclude:
                try:
                    await client_ws.send(count_msg)
                except Exception as e:
                    logger.error(f"Send participants error to {client_id}: {e}")

    async def _send_participants_to(self, websocket):
        async with self.lock:
            participant_count = len(self.clients)
            participants_list = await self._get_participants_list()

        count_msg = json.dumps({
            'type': 'participants',
            'count': participant_count,
            'participants': participants_list
        })
        await websocket.send(count_msg)

    async def handle_client(self, websocket):
        client_id = None
        try:
            async for raw_message in websocket:
                message = json.loads(raw_message)
                msg_type = message.get('type')

                if msg_type == 'connect':
                    username = message.get('username', '')
                    async with self.lock:
                        client_id = self.client_id_counter
                        self.clients[client_id] = websocket
                        self.client_usernames[client_id] = username
                        self.client_id_counter += 1
                        participant_count = len(self.clients)

                    response = json.dumps({
                        'type': 'connected',
                        'client_id': client_id,
                        'participant_count': participant_count
                    })
                    await websocket.send(response)
                    logger.info(f"Client {client_id} ({username}) connected")

                    # Send participants list directly to new client
                    await self._send_participants_to(websocket)

                    # Broadcast join notification to others
                    join_msg = json.dumps({
                        'type': 'system',
                        'message': f'{username} joined the chat',
                        'timestamp': datetime.now().strftime('%H:%M')
                    })
                    await self.broadcast(join_msg, exclude=[client_id])

                    # Broadcast updated participants to others
                    await self._send_participants_to_all(exclude=[client_id])

                elif msg_type == 'message':
                    content = message.get('content', '')
                    target_id = message.get('target_id')
                    async with self.lock:
                        sender_username = self.client_usernames.get(client_id, f"User {client_id}")

                    # ACK to sender
                    ack = json.dumps({
                        'type': 'ack',
                        'message_id': message.get('message_id'),
                        'username': sender_username
                    })
                    await websocket.send(ack)
                    logger.info(f"Message from {client_id} acknowledged")

                    if target_id:
                        # Direct message to specific client
                        async with self.lock:
                            target_ws = self.clients.get(target_id)
                            target_username = self.client_usernames.get(target_id, f"User {target_id}")

                        if target_ws:
                            direct_msg = json.dumps({
                                'type': 'direct',
                                'client_id': client_id,
                                'username': sender_username,
                                'target_id': target_id,
                                'content': content,
                                'timestamp': datetime.now().strftime('%H:%M')
                            })
                            await target_ws.send(direct_msg)
                            logger.info(f"Direct message from {client_id} to {target_id}: {content[:50]}")
                        else:
                            logger.warning(f"Target client {target_id} not found")
                    else:
                        # Broadcast to all except sender
                        broadcast_msg = json.dumps({
                            'type': 'message',
                            'client_id': client_id,
                            'username': sender_username,
                            'content': content,
                            'timestamp': datetime.now().strftime('%H:%M')
                        })
                        await self.broadcast(broadcast_msg, exclude=[client_id])
                        logger.info(f"Broadcast message from {client_id}: {content[:50]}")

        except websockets.ConnectionClosed:
            logger.info(f"Client {client_id} connection closed")
        except Exception as e:
            logger.error(f"Client {client_id} error: {e}")
        finally:
            if client_id:
                username = self.client_usernames.get(client_id, f"User {client_id}")
                async with self.lock:
                    self.clients.pop(client_id, None)
                    self.client_usernames.pop(client_id, None)

                leave_msg = json.dumps({
                    'type': 'system',
                    'message': f'{username} left the chat',
                    'timestamp': datetime.now().strftime('%H:%M')
                })
                await self.broadcast(leave_msg)

                # Send updated participants to remaining clients
                await self._send_participants_to_all()
                logger.info(f"Client {client_id} ({username}) disconnected")

    async def broadcast(self, message, exclude=None):
        exclude = exclude or []
        async with self.lock:
            targets = list(self.clients.items())

        for client_id, client_ws in targets:
            if client_id not in exclude:
                try:
                    await client_ws.send(message)
                except Exception as e:
                    logger.error(f"Broadcast error to {client_id}: {e}")

    def start(self):
        local_ip = socket.gethostbyname(socket.gethostname())
        logger.info(f"Server starting on {local_ip}:{self.port}")
        print(f"\n{'='*50}")
        print(f"  OpenChat Server (WebSocket)")
        print(f"{'='*50}")
        print(f"  IP: {local_ip}")
        print(f"  Port: {self.port}")
        print(f"  ws://{local_ip}:{self.port}")
        print(f"{'='*50}\n")

        return websockets.serve(
            self.handle_client,
            self.host,
            self.port,
        )

async def main():
    import sys
    port = 5000
    if len(sys.argv) > 1:
        port = int(sys.argv[1])

    server = ChatServer(port=port)
    async with server.start():
        await asyncio.Future()  # run forever

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Server stopped")
        print(f"\n{'='*50}")
        print(f"  OpenChat Server shutting down...")
        print(f"  Goodbye! See you next time!")
        print(f"{'='*50}")
