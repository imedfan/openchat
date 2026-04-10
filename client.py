import socket
import threading
import logging
import json
import sys
import os
from datetime import datetime
from collections import deque
from typing import Optional, Dict, Any

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('client.log')
    ]
)
logger = logging.getLogger(__name__)

class Message:
    def __init__(self, content: str, is_mine: bool = False, client_id: Optional[int] = None, 
                 timestamp: str = "", acknowledged: bool = False, message_id: str = ""):
        self.content = content
        self.is_mine = is_mine
        self.client_id = client_id
        self.timestamp = timestamp
        self.acknowledged = acknowledged
        self.message_id = message_id

class TUI:
    BLACK = "\033[30m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"
    GRAY = "\033[90m"
    LIGHT_GRAY = "\033[37m"
    BOLD = "\033[1m"
    RESET = "\033[0m"
    
    BG_BLACK = "\033[40m"
    BG_WHITE = "\033[47m"
    BG_GRAY = "\033[100m"

    @staticmethod
    def clear_screen():
        os.system('cls' if os.name == 'nt' else 'clear')

    @staticmethod
    def print_welcome():
        TUI.clear_screen()
        print(f"""
{TUI.MAGENTA}╔══════════════════════════════════════════════════════╗
║                                                      ║
║   {TUI.CYAN}  ══╗ ╔═══╗ ╔═══╗ ╔╗ ╔╗ ╔═══╗ ╔═╗ ╔══╗ ╔═══╗  {TUI.MAGENTA}║
║   {TUI.CYAN}  ╔╝ ║╔═╗║ ║╔═╗║ ║║ ║║ ║╔═╗║ ║ ║╚╗╔╝ ║╔═╗║  {TUI.MAGENTA}║
║   {TUI.CYAN}  ═╗ ║╚═╝║ ║╚═╝║ ║╚═╝║ ║╚═╝║ ║ ║ ╚╝   ║╚═╝║  {TUI.MAGENTA}║
║   {TUI.CYAN}╔╗╚╝ ║╔═╝║ ║╔═╝║ ║╔╗║ ║╔═╝║ ║ ║     ║╔═╝║  {TUI.MAGENTA}║
║   {TUI.CYAN}╚═══ ║║  ║ ║║  ║ ║║╚╗║ ║║  ║ ╚═╗║     ║║  ║  {TUI.MAGENTA}║
║       ╚╝  ╚ ╚╝  ╚ ╚╝ ╚╝ ╚╩ ╩ ╚╝  ╚═══╝     ╚╝  ║  {TUI.MAGENTA}║
║                                                      ║
║        {TUI.WHITE}Network Messaging Made Simple{TUI.MAGENTA}            ║
║                                                      ║
╚══════════════════════════════════════════════════════╝{TUI.RESET}
""")
        print(f"{TUI.GRAY}Press Enter to continue...{TUI.RESET}")
        input()

    @staticmethod
    def print_connect_dialog():
        TUI.clear_screen()
        print(f"""
{TUI.CYAN}╔══════════════════════════════════════╗
║       Connect to Server        ║
╚══════════════════════════════════════╝{TUI.RESET}
""")
        host = input(f"{TUI.YELLOW}Enter server IP: {TUI.RESET}").strip()
        port = input(f"{TUI.YELLOW}Enter server port: {TUI.RESET}").strip()
        return host, int(port)

    @staticmethod
    def print_chat_header(client_id: int, connected: bool, participant_count: int = 1):
        status = f"{TUI.GREEN}Connected{TUI.RESET}" if connected else f"{TUI.RED}Disconnected{TUI.RESET}"
        print(f"""
{TUI.BLACK}{TUI.BG_WHITE}╔══════════════════════════════════════════════════════╗
║ OpenChat                              ID: {client_id}    Status: {status}  ║
║ Participants: {participant_count}{' ' * 42}║
╚══════════════════════════════════════════════════════╝{TUI.RESET}
""")

    @staticmethod
    def print_messages(messages: list, my_id: int):
        print(f"\n{TUI.GRAY}{'─'*62}{TUI.RESET}")
        for msg in messages:
            sender = "You" if msg.is_mine or msg.client_id == my_id else f"User {msg.client_id}"
            if msg.is_mine:
                color = TUI.GREEN if msg.acknowledged else TUI.GRAY
                ack_status = "✓" if msg.acknowledged else "..."
                print(f"{msg.timestamp} - {sender}: {msg.content} {color}{ack_status}{TUI.RESET}")
            else:
                print(f"{msg.timestamp} - {sender}: {msg.content}")
        print(f"{TUI.GRAY}{'─'*62}{TUI.RESET}\n")

    @staticmethod
    def print_system(message: str):
        print(f"{TUI.YELLOW}[System] {message}{TUI.RESET}")

class ChatClient:
    def __init__(self):
        self.socket = None
        self.client_id: Optional[int] = None
        self.running = False
        self.messages: deque = deque(maxlen=100)
        self.pending_messages: Dict[str, Message] = {}
        self.message_id_counter = 0
        self.connected = False
        self.new_message_event = threading.Event()
        self.participant_count = 1

    def connect(self, host: str, port: int) -> bool:
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.connect((host, port))
            
            connect_msg = json.dumps({'type': 'connect'})
            self.socket.send(connect_msg.encode('utf-8'))
            
            response = json.loads(self.socket.recv(4096).decode('utf-8'))
            
            if response['type'] == 'connected':
                self.client_id = response['client_id']
                self.participant_count = response.get('participant_count', 1)
                self.running = True
                self.connected = True
                logger.info(f"Connected with ID: {self.client_id}")
                TUI.print_system(f"Connected to server with ID: {self.client_id}")
                return True
            return False
        except Exception as e:
            logger.error(f"Connection error: {e}")
            print(f"{TUI.RED}Error connecting to server: {e}{TUI.RESET}")
            return False

    def receive_messages(self):
        while self.running:
            try:
                data = self.socket.recv(4096)
                if not data:
                    break
                
                message = json.loads(data.decode('utf-8'))
                msg_type = message.get('type')
                
                if msg_type == 'ack':
                    msg_id = message.get('message_id')
                    if msg_id in self.pending_messages:
                        self.pending_messages[msg_id].acknowledged = True
                        for msg in self.messages:
                            if msg.message_id == msg_id:
                                msg.acknowledged = True
                                break
                        del self.pending_messages[msg_id]
                        self.new_message_event.set()
                        logger.info(f"Message {msg_id} acknowledged")
                
                elif msg_type == 'message':
                    client_id = message.get('client_id')
                    content = message.get('content', '')
                    timestamp = message.get('timestamp', '')
                    
                    msg = Message(content, is_mine=False, client_id=client_id, timestamp=timestamp)
                    self.messages.append(msg)
                    self.new_message_event.set()
                    logger.info(f"Received message from user {client_id}: {content[:50]}")
                
                elif msg_type == 'system':
                    content = message.get('message', '')
                    timestamp = message.get('timestamp', '')
                    msg = Message(content, is_mine=False, client_id=0, timestamp=timestamp)
                    self.messages.append(msg)
                    self.new_message_event.set()
                    logger.info(f"System message: {content}")
                
                elif msg_type == 'participants':
                    count = message.get('count', 1)
                    self.participant_count = count
                    self.new_message_event.set()
                    
            except Exception as e:
                logger.error(f"Receive error: {e}")
                break
        
        self.connected = False

    def send_message(self, content: str) -> bool:
        if not self.running or not self.socket:
            return False
        
        try:
            self.message_id_counter += 1
            message_id = f"{self.client_id}_{self.message_id_counter}"
            
            message = json.dumps({
                'type': 'message',
                'content': content,
                'message_id': message_id
            })
            
            msg = Message(content, is_mine=True, client_id=self.client_id, 
                         timestamp=datetime.now().strftime('%H:%M'),
                         acknowledged=False, message_id=message_id)
            self.messages.append(msg)
            self.pending_messages[message_id] = msg
            self.new_message_event.set()
            
            self.socket.send(message.encode('utf-8'))
            logger.info(f"Sent message: {content[:50]}")
            return True
        except Exception as e:
            logger.error(f"Send error: {e}")
            return False

    def _display_loop(self):
        while self.running:
            self.new_message_event.wait(timeout=0.5)
            if self.new_message_event.is_set():
                self.new_message_event.clear()
                if self.connected:
                    TUI.clear_screen()
                    TUI.print_chat_header(self.client_id, self.connected, self.participant_count)
                    TUI.print_messages(list(self.messages), self.client_id)
                    print(f"\n{TUI.CYAN}>> {TUI.RESET}", end="")
        
    def run(self):
        TUI.print_welcome()
        
        host, port = TUI.print_connect_dialog()
        
        if not self.connect(host, port):
            print(f"\n{TUI.RED}Failed to connect. Press Enter to exit...{TUI.RESET}")
            input()
            return
        
        receive_thread = threading.Thread(target=self.receive_messages)
        receive_thread.daemon = True
        receive_thread.start()
        
        display_thread = threading.Thread(target=self._display_loop)
        display_thread.daemon = True
        display_thread.start()
        
        while self.connected:
            TUI.clear_screen()
            TUI.print_chat_header(self.client_id, self.connected)
            TUI.print_messages(list(self.messages), self.client_id)
            
            try:
                print(f"\n{TUI.CYAN}>> {TUI.RESET}", end="")
                message = input().strip()
                
                if message.lower() in ['/exit', '/quit']:
                    print(f"\n{TUI.YELLOW}Disconnecting from server...{TUI.RESET}")
                    break
                elif message:
                    self.send_message(message)
            except (KeyboardInterrupt, EOFError):
                print(f"\n\n{TUI.YELLOW}Disconnecting from server...{TUI.RESET}")
                break
        
        self.running = False
        if self.socket:
            self.socket.close()
        logger.info("Client disconnected")
        
        print(f"\n{'='*50}")
        print(f"  OpenChat Client closing...")
        print(f"  Goodbye! See you next time!")
        print(f"{'='*50}")

if __name__ == '__main__':
    try:
        client = ChatClient()
        client.run()
    except KeyboardInterrupt:
        print(f"\n\n{TUI.YELLOW}OpenChat closed by user{TUI.RESET}")
        print(f"\n{'='*50}")
        print(f"  OpenChat Client closing...")
        print(f"  Goodbye! See you next time!")
        print(f"{'='*50}")