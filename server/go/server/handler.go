package server

import (
	"encoding/json"
	"log"

	"github.com/gorilla/websocket"
	"openchat-server/protocol"
)

// HandleClient обрабатывает подключение одного клиента
func (s *ChatServer) HandleClient(conn *websocket.Conn) {
	var client *ClientInfo
	defer func() {
		if client != nil {
			s.HandleDisconnect(client.ID)
		}
		conn.Close()
	}()

	for {
		_, message, err := conn.ReadMessage()
		if err != nil {
			if websocket.IsUnexpectedCloseError(err, websocket.CloseGoingAway, websocket.CloseNormalClosure) {
				log.Printf("WebSocket error: %v", err)
			}
			break
		}

		msg, err := protocol.ParseMessage(string(message))
		if err != nil {
			log.Printf("Failed to parse message: %v", err)
			continue
		}

		msgType := protocol.GetMsgType(msg)

		switch msgType {
		case protocol.MsgConnect:
			client = s.HandleConnect(conn, msg)
		case protocol.MsgMessage:
			if client != nil {
				s.HandleBroadcast(client, msg)
			}
		case protocol.MsgDirect:
			if client != nil {
				s.HandleDirect(client, msg)
			}
		case protocol.MsgLLMRequest:
			if client != nil {
				s.HandleLLMRequest(client, msg)
			}
		}
	}
}

// HandleConnect обрабатывает подключение нового клиента
func (s *ChatServer) HandleConnect(conn *websocket.Conn, msg map[string]interface{}) *ClientInfo {
	username, _ := msg["username"].(string)
	publicKeyStr, _ := msg["public_key"].(string)
	publicKey := []byte(publicKeyStr)

	client := s.AddClient(username, publicKey, conn)
	participantCount := s.ClientCount()

	// Отправляем подтверждение подключения
	conn.WriteMessage(websocket.TextMessage, []byte(protocol.MakeConnected(client.ID, participantCount)))
	log.Printf("Client %d (%s) connected", client.ID, username)

	// Отправляем список участников новому клиенту
	if err := s.SendParticipantsTo(client); err != nil {
		log.Printf("Failed to send participants to new client %d: %v", client.ID, err)
	}

	// Уведомляем остальных о новом участнике
	joinMsg := protocol.MakeSystemMessage(username + " joined the chat")
	s.Broadcast(joinMsg, []int{client.ID})

	// Рассылаем обновлённый список участников остальным
	s.SendParticipantsToAll([]int{client.ID})

	// Отправляем список доступных LLM-моделей
	if len(s.Models) > 0 {
		s.HandleLLMModels(client)
	}

	return client
}

// HandleBroadcast обрабатывает обычное сообщение для рассылки
func (s *ChatServer) HandleBroadcast(client *ClientInfo, msg map[string]interface{}) {
	content, _ := msg["content"].(string)
	messageID, _ := msg["message_id"].(string)
	senderUsername := s.GetClientUsername(client.ID)

	// ACK отправителю
	ackMsg := protocol.MakeAck(messageID, senderUsername)
	client.Conn.WriteMessage(websocket.TextMessage, []byte(ackMsg))
	log.Printf("Message from %d acknowledged", client.ID)

	// Broadcast всем кроме отправителя
	broadcastMsg := protocol.MakeBroadcast(client.ID, senderUsername, content)
	s.Broadcast(broadcastMsg, []int{client.ID})
	log.Printf("Broadcast message from %d: %s", client.ID, truncateString(content, 50))
}

// HandleDirect обрабатывает личное сообщение (relay без расшифровки)
func (s *ChatServer) HandleDirect(client *ClientInfo, msg map[string]interface{}) {
	targetIDFloat, _ := msg["target_id"].(float64)
	targetID := int(targetIDFloat)
	content, _ := msg["content"].(string)
	nonce, _ := msg["nonce"].(string)
	messageID, _ := msg["message_id"].(string)
	senderUsername := s.GetClientUsername(client.ID)

	// ACK отправителю
	ackMsg := protocol.MakeAck(messageID, senderUsername)
	client.Conn.WriteMessage(websocket.TextMessage, []byte(ackMsg))
	log.Printf("Message from %d acknowledged", client.ID)

	// Relay DM целевому клиенту (сервер НЕ расшифровывает)
	targetConn := s.GetClientConn(targetID)
	if targetConn != nil {
		directMsg := protocol.MakeDirectRelay(client.ID, senderUsername, targetID, content, nonce, messageID)
		targetConn.WriteMessage(websocket.TextMessage, []byte(directMsg))
		log.Printf("Direct message from %d to %d: [encrypted]", client.ID, targetID)
	} else {
		log.Printf("Target client %d not found for DM from %d", targetID, client.ID)
	}
}

// HandleDisconnect обрабатывает отключение клиента
func (s *ChatServer) HandleDisconnect(clientID int) {
	username := s.GetClientUsername(clientID)
	s.RemoveClient(clientID)

	leaveMsg := protocol.MakeSystemMessage(username + " left the chat")
	s.Broadcast(leaveMsg, nil)

	s.SendParticipantsToAll(nil)
	log.Printf("Client %d (%s) disconnected", clientID, username)
}

// truncateString обрезает строку до указанной длины
func truncateString(s string, maxLen int) string {
	if len(s) > maxLen {
		return s[:maxLen]
	}
	return s
}

// ParseConnectMessage парсит сообщение подключения
func ParseConnectMessage(data string) (*protocol.ConnectMessage, error) {
	var msg protocol.ConnectMessage
	err := json.Unmarshal([]byte(data), &msg)
	if err != nil {
		return nil, err
	}
	return &msg, nil
}

// ParseDirectMessage парсит личное сообщение
func ParseDirectMessage(data string) (*protocol.DirectMessage, error) {
	var msg protocol.DirectMessage
	err := json.Unmarshal([]byte(data), &msg)
	if err != nil {
		return nil, err
	}
	return &msg, nil
}
