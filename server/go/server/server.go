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

// WSConn — интерфейс для WebSocket соединения (для тестирования)
type WSConn interface {
	WriteMessage(messageType int, data []byte) error
	ReadMessage() (messageType int, p []byte, err error)
	Close() error
}

// ConnMutex — обёртка с мьютексом для безопасных записей в WebSocket
type ConnMutex struct {
	conn WSConn
	mu   sync.Mutex
}

func NewConnMutex(conn WSConn) *ConnMutex {
	return &ConnMutex{conn: conn}
}

func (c *ConnMutex) WriteMessage(messageType int, data []byte) error {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.conn.WriteMessage(messageType, data)
}

func (c *ConnMutex) ReadMessage() (int, []byte, error) {
	return c.conn.ReadMessage()
}

func (c *ConnMutex) Close() error {
	return c.conn.Close()
}

// ClientInfo — информация о подключённом клиенте
type ClientInfo struct {
	ID        int
	Username  string
	PublicKey []byte
	Conn      *ConnMutex
}

// ChatServer — WebSocket сервер чата
type ChatServer struct {
	Host            string
	Port            int
	Clients         map[int]*ClientInfo // client_id → ClientInfo
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

	// Добавляем модели как виртуальных участников (если все поля заполнены)
	participants = append(participants, s.getModelParticipants()...)

	return participants
}

// getModelParticipants возвращает модели как виртуальных участников
func (s *ChatServer) getModelParticipants() []protocol.Participant {
	// Используем уже удерживаемую блокировку из вызывающего кода, не делаем новый RLock

	if !common.ModelsReady(s.Models) {
		return nil
	}

	result := make([]protocol.Participant, 0, len(s.Models))
	for _, m := range s.Models {
		result = append(result, protocol.Participant{
			ClientID:  -1,     // отрицательный ID = виртуальный участник
			Username:  m.Name, // отображаемое имя из name
			PublicKey: "",
			IsModel:   true,
			ModelID:   m.ID,
		})
	}
	return result
}

// UpdateModels обновляет список моделей и рассылает обновлённый список участников
func (s *ChatServer) UpdateModels(models []common.ModelConfig) {
	s.Mu.Lock()
	s.Models = models
	s.Mu.Unlock()

	log.Printf("Models updated: %d model(s)", len(models))

	// Рассылаем обновлённый список участников всем
	s.SendParticipantsToAll(nil)

	// Если модели готовы, отправляем список LLM-моделей всем клиентам
	if common.ModelsReady(models) {
		s.Mu.RLock()
		for _, client := range s.Clients {
			go func(c *ClientInfo) {
				s.HandleLLMModels(c)
			}(client)
		}
		s.Mu.RUnlock()
	}
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
func (s *ChatServer) AddClient(username string, publicKey []byte, connMu *ConnMutex) *ClientInfo {
	s.Mu.Lock()
	defer s.Mu.Unlock()

	client := &ClientInfo{
		ID:        s.ClientIDCounter,
		Username:  username,
		PublicKey: publicKey,
		Conn:      connMu,
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

// HandleDisconnect обрабатывает отключение клиента
func (s *ChatServer) HandleDisconnect(clientID int) {
	// Удаляем клиента
	client := s.RemoveClient(clientID)
	if client == nil {
		return
	}

	// Уведомляем остальных о выходе
	msg := protocol.MakeSystemMessage(s.GetClientUsername(clientID) + " left the chat")
	s.Broadcast(msg, []int{})

	// Рассылаем обновлённый список участников
	s.SendParticipantsToAll(nil)

	log.Printf("Client %d (%s) disconnected", client.ID, client.Username)
}

// HandleBroadcast обрабатывает широковещательное сообщение
func (s *ChatServer) HandleBroadcast(client *ClientInfo, msg map[string]interface{}) {
	content, _ := msg["content"].(string)
	messageID, _ := msg["message_id"].(string)

	// Отправляем ack отправителю
	ackMsg := protocol.MakeAck(messageID, client.Username)
	client.Conn.WriteMessage(websocket.TextMessage, []byte(ackMsg))

	// Рассылаем сообщение всем
	payload := protocol.MakeBroadcast(client.ID, client.Username, content)
	s.Broadcast(payload, []int{})
}

// HandleDirect обрабатывает личное сообщение
func (s *ChatServer) HandleDirect(client *ClientInfo, msg map[string]interface{}) {
	to, _ := msg["to"].(float64)
	targetID := int(to)
	content, _ := msg["content"].(string)
	messageID, _ := msg["message_id"].(string)
	encrypted, _ := msg["encrypted"].(bool)

	// Отправляем ack отправителю
	ackMsg := protocol.MakeAck(messageID, client.Username)
	client.Conn.WriteMessage(websocket.TextMessage, []byte(ackMsg))

	// Создаём сообщение для relay
	payload := protocol.MakeDirectRelay(client.ID, client.Username, targetID, content, "", messageID)

	// Отправляем получателю
	if _, ok := s.Clients[targetID]; ok {
		client.Conn.WriteMessage(websocket.TextMessage, []byte(payload))

		// Отправляем отправителю копию, если не зашифровано
		if !encrypted {
			s.Broadcast(payload, []int{})
		}
	}
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
func (s *ChatServer) GetClientConn(clientID int) WSConn {
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
