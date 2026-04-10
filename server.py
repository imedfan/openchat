import socket
import threading
import logging
import json
from datetime import datetime
from collections import defaultdict

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
        self.server_socket = None
        self.clients = {}
        self.client_addresses = {}
        self.client_usernames = {}
        self.client_id_counter = 1
        self.running = False
        self.lock = threading.Lock()

    def start(self):
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.bind((self.host, self.port))
        self.server_socket.listen(5)
        self.running = True

        local_ip = socket.gethostbyname(socket.gethostname())
        logger.info(f"Server started on {local_ip}:{self.port}")
        print(f"\n{'='*50}")
        print(f"  OpenChat Server")
        print(f"{'='*50}")
        print(f"  IP: {local_ip}")
        print(f"  Port: {self.port}")
        print(f"{'='*50}\n")

        while self.running:
            try:
                client_socket, address = self.server_socket.accept()
                thread = threading.Thread(target=self.handle_client, args=(client_socket, address))
                thread.daemon = True
                thread.start()
            except Exception as e:
                if self.running:
                    logger.error(f"Accept error: {e}")

    def handle_client(self, client_socket, address):
        client_id = None
        try:
            while self.running:
                data = client_socket.recv(4096)
                if not data:
                    break
                
                message = json.loads(data.decode('utf-8'))
                msg_type = message.get('type')

                if msg_type == 'connect':
                    username = message.get('username', '')
                    with self.lock:
                        client_id = self.client_id_counter
                        self.clients[client_id] = client_socket
                        self.client_addresses[client_id] = address
                        self.client_usernames[client_id] = username
                        self.client_id_counter += 1
                        participant_count = len(self.clients)
                    
                    response = json.dumps({
                        'type': 'connected',
                        'client_id': client_id,
                        'participant_count': participant_count
                    })
                    client_socket.send(response.encode('utf-8'))
                    logger.info(f"Client {client_id} ({username}) connected from {address}")

                    join_msg = json.dumps({
                        'type': 'system',
                        'message': f'{username} joined the chat',
                        'timestamp': datetime.now().strftime('%H:%M')
                    })
                    self.broadcast(join_msg, exclude=[client_id])
                    
                    count_msg = json.dumps({
                        'type': 'participants',
                        'count': participant_count
                    })
                    self.broadcast(count_msg)

                elif msg_type == 'message':
                    content = message.get('content', '')
                    with self.lock:
                        sender_socket = self.clients.get(client_id)
                        sender_username = self.client_usernames.get(client_id, f"User {client_id}")
                    
                    if sender_socket:
                        ack = json.dumps({
                            'type': 'ack',
                            'message_id': message.get('message_id'),
                            'username': sender_username
                        })
                        sender_socket.send(ack.encode('utf-8'))
                        logger.info(f"Message from {client_id} acknowledged")

                    broadcast_msg = json.dumps({
                        'type': 'message',
                        'client_id': client_id,
                        'username': sender_username,
                        'content': content,
                        'timestamp': datetime.now().strftime('%H:%M')
                    })
                    self.broadcast(broadcast_msg, exclude=[client_id])
                    logger.info(f"Broadcast message from {client_id}: {content[:50]}")

        except Exception as e:
            logger.error(f"Client {client_id} error: {e}")
        finally:
            if client_id:
                username = self.client_usernames.get(client_id, f"User {client_id}")
                with self.lock:
                    if client_id in self.clients:
                        del self.clients[client_id]
                    if client_id in self.client_addresses:
                        del self.client_addresses[client_id]
                    if client_id in self.client_usernames:
                        del self.client_usernames[client_id]
                
                leave_msg = json.dumps({
                    'type': 'system',
                    'message': f'{username} left the chat',
                    'timestamp': datetime.now().strftime('%H:%M')
                })
                self.broadcast(leave_msg)
                
                participant_count = len(self.clients)
                count_msg = json.dumps({
                    'type': 'participants',
                    'count': participant_count
                })
                self.broadcast(count_msg)
                logger.info(f"Client {client_id} ({username}) disconnected")

            client_socket.close()

    def broadcast(self, message, exclude=None):
        exclude = exclude or []
        with self.lock:
            for client_id, client_socket in list(self.clients.items()):
                if client_id not in exclude:
                    try:
                        client_socket.send(message.encode('utf-8'))
                    except Exception as e:
                        logger.error(f"Broadcast error to {client_id}: {e}")

    def stop(self):
        self.running = False
        if self.server_socket:
            self.server_socket.close()
        logger.info("Server stopped")

if __name__ == '__main__':
    import sys
    port = 5000
    if len(sys.argv) > 1:
        port = int(sys.argv[1])
    
    server = ChatServer(port=port)
    try:
        server.start()
    except KeyboardInterrupt:
        server.stop()
        print(f"\n{'='*50}")
        print(f"  OpenChat Server shutting down...")
        print(f"  Goodbye! See you next time!")
        print(f"{'='*50}")