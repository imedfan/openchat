package server

import (
	"fmt"
	"log"
	"net"
	"sync"

	"github.com/gorilla/websocket"
	"openchat-server/common"
	"openchat-server/protocol"
)

// ClientInfo — информация о подключённом клиенте
type ClientInfo struct {
	ID        int
	Username  string
	PublicKey []byte
	Conn      *websocket.Conn
}

// ChatServer — WebSocket сервер чата
type ChatServer struct {
	Host            string
	Port            int
	Clients         map[int]*ClientInfo    // client_id → ClientInfo
	ClientIDCounter int
	Mu              sync.RWMutex
	Models          []common.ModelConfig // Доступные LLM-модели
}

// NewChatServer создаёт новый сервер
func NewChatServer(host string, port int, models []common.ModelConfig) *ChatServer {
	return &ChatServer{
		Host:            host,
		Port:            port,
		Clients:         make(map[int]*ClientInfo),
		ClientIDCounter: 1,
		Models:          models,
	}
}

// GetPublicIP определяет внешний IP адрес сервера
func GetPublicIP() string {
	conn, err := net.Dial("udp", "8.8.8.8:80")
	if err != nil {
		return "0.0.0.0"
	}
	defer conn.Close()

	localAddr := conn.LocalAddr().(*net.UDPAddr)
	return localAddr.IP.String()
}

// GetParticipantsList возвращает текущий список участников
func (s *ChatServer) GetParticipantsList() []protocol.Participant {
	s.Mu.RLock()
	defer s.Mu.RUnlock()

	participants := make([]protocol.Participant, 0, len(s.Clients))
	for _, client := range s.Clients {
		participants = append(participants, protocol.Participant{
			ClientID:  client.ID,
			Username:  client.Username,
			PublicKey: string(client.PublicKey),
		})
	}
	return participants
}

// SendParticipantsToAll рассылает обновлённый список участников всем (кроме exclude)
func (s *ChatServer) SendParticipantsToAll(exclude []int) {
	excludeMap := make(map[int]bool)
	for _, id := range exclude {
		excludeMap[id] = true
	}

	s.Mu.RLock()
	participantCount := len(s.Clients)
	participantsList := s.GetParticipantsList()
	s.Mu.RUnlock()

	payload := protocol.MakeParticipants(participantCount, participantsList)

	s.Mu.RLock()
	for _, client := range s.Clients {
		if !excludeMap[client.ID] {
			go func(c *ClientInfo) {
				if err := c.Conn.WriteMessage(websocket.TextMessage, []byte(payload)); err != nil {
					log.Printf("Send participants error to %d: %v", c.ID, err)
				}
			}(client)
		}
	}
	s.Mu.RUnlock()
}

// SendParticipantsTo отправляет список участников одному клиенту
func (s *ChatServer) SendParticipantsTo(client *ClientInfo) error {
	s.Mu.RLock()
	participantCount := len(s.Clients)
	participantsList := s.GetParticipantsList()
	s.Mu.RUnlock()

	payload := protocol.MakeParticipants(participantCount, participantsList)
	return client.Conn.WriteMessage(websocket.TextMessage, []byte(payload))
}

// Broadcast рассылает сообщение всем клиентам (кроме exclude)
func (s *ChatServer) Broadcast(message string, exclude []int) {
	excludeMap := make(map[int]bool)
	for _, id := range exclude {
		excludeMap[id] = true
	}

	s.Mu.RLock()
	for _, client := range s.Clients {
		if !excludeMap[client.ID] {
			go func(c *ClientInfo) {
				if err := c.Conn.WriteMessage(websocket.TextMessage, []byte(message)); err != nil {
					log.Printf("Broadcast error to %d: %v", c.ID, err)
				}
			}(client)
		}
	}
	s.Mu.RUnlock()
}

// AddClient добавляет нового клиента
func (s *ChatServer) AddClient(username string, publicKey []byte, conn *websocket.Conn) *ClientInfo {
	s.Mu.Lock()
	defer s.Mu.Unlock()

	client := &ClientInfo{
		ID:        s.ClientIDCounter,
		Username:  username,
		PublicKey: publicKey,
		Conn:      conn,
	}
	s.Clients[client.ID] = client
	s.ClientIDCounter++

	return client
}

// RemoveClient удаляет клиента по ID
func (s *ChatServer) RemoveClient(clientID int) *ClientInfo {
	s.Mu.Lock()
	defer s.Mu.Unlock()

	client, exists := s.Clients[clientID]
	if !exists {
		return nil
	}

	delete(s.Clients, clientID)
	return client
}

// GetClientUsername безопасно получает username клиента
func (s *ChatServer) GetClientUsername(clientID int) string {
	s.Mu.RLock()
	defer s.Mu.RUnlock()

	if client, exists := s.Clients[clientID]; exists {
		return client.Username
	}
	return fmt.Sprintf("User %d", clientID)
}

// GetClientConn безопасно получает WebSocket подключение клиента
func (s *ChatServer) GetClientConn(clientID int) *websocket.Conn {
	s.Mu.RLock()
	defer s.Mu.RUnlock()

	if client, exists := s.Clients[clientID]; exists {
		return client.Conn
	}
	return nil
}

// ClientCount возвращает количество подключённых клиентов
func (s *ChatServer) ClientCount() int {
	s.Mu.RLock()
	defer s.Mu.RUnlock()
	return len(s.Clients)
}
