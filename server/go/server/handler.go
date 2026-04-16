package server

import (
	"encoding/json"
	"log"
	"time"

	"github.com/gorilla/websocket"
	"openchat-server/common"
	"openchat-server/protocol"
)

// HandleClient обрабатывает подключение одного клиента
func (s *ChatServer) HandleClient(conn *websocket.Conn) {
	var client *ClientInfo
	
	// Настройка Ping/Pong обработчиков для предотвращения обрывов соединения
	conn.SetReadDeadline(time.Now().Add(60 * time.Second))
	conn.SetPongHandler(func(string) error {
		conn.SetReadDeadline(time.Now().Add(60 * time.Second))
		return nil
	})
	conn.SetPingHandler(func(string) error {
		// Когда сервер получает ping от клиента, он отвечает pong
		return conn.WriteMessage(websocket.PongMessage, []byte{})
	})

	defer func() {
		if client != nil {
			s.HandleDisconnect(client.ID)
		}
		conn.Close()
	}()

	// Таймер для периодической отправки ping клиентам
	heartbeat := time.NewTicker(30 * time.Second)
	defer heartbeat.Stop()

	for {
		select {
		case <-heartbeat.C:
			// Периодически отправляем ping клиентам, чтобы проверить соединение
			if err := conn.WriteMessage(websocket.PingMessage, []byte{}); err != nil {
				log.Printf("Heartbeat error: %v", err)
				return
			}
		default:
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
			case protocol.MsgModelMessage:
				if client != nil {
					s.HandleModelMessage(client, msg)
				}
			case protocol.MsgLLMRequest:
				if client != nil {
					s.HandleLLMRequest(client, msg)
				}
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

// HandleModelMessage обрабатывает сообщение в чат модели
func (s *ChatServer) HandleModelMessage(client *ClientInfo, msg map[string]interface{}) {
	modelID, _ := msg["model_id"].(string)
	content, _ := msg["content"].(string)
	messageID, _ := msg["message_id"].(string)

	if modelID == "" {
		log.Printf("Model message from %d: missing model_id", client.ID)
		return
	}

	// Находим модель
	var modelConfig *common.ModelConfig
	var modelName string
	for i := range s.Models {
		if s.Models[i].ID == modelID {
			modelConfig = &s.Models[i]
			modelName = s.Models[i].Name
			break
		}
	}

	if modelConfig == nil {
		errMsg := protocol.MakeModelMessage(modelID, modelID, "Model not found", true, false)
		client.Conn.WriteMessage(websocket.TextMessage, []byte(errMsg))
		return
	}

	// ACK отправителю
	senderUsername := s.GetClientUsername(client.ID)
	ackMsg := protocol.MakeAck(messageID, senderUsername)
	client.Conn.WriteMessage(websocket.TextMessage, []byte(ackMsg))

	// Показываем "думающий" индикатор
	thinkingMsg := protocol.MakeModelMessage(modelID, modelName, "", false, true)
	client.Conn.WriteMessage(websocket.TextMessage, []byte(thinkingMsg))

	log.Printf("Client %d sent message to model %s (%s)", client.ID, modelID, truncateString(content, 50))

	// Создаём LLM-клиент и стримим ответ
	llmClient := NewLLMClient(*modelConfig)

	// Формируем сообщение для LLM
	messages := []Message{{Role: "user", Content: content}}

	go func() {
		err := llmClient.StreamMessage(messages, func(chunk string, done bool) {
			if done {
				payload := protocol.MakeModelMessage(modelID, modelName, "", true, false)
				client.Conn.WriteMessage(websocket.TextMessage, []byte(payload))
				log.Printf("Model streaming to client %d completed (model: %s)", client.ID, modelID)
				return
			}

			payload := protocol.MakeModelMessage(modelID, modelName, chunk, false, true)
			if err := client.Conn.WriteMessage(websocket.TextMessage, []byte(payload)); err != nil {
				log.Printf("Failed to send model chunk to client %d: %v", client.ID, err)
			}
		})

		if err != nil {
			log.Printf("Model streaming error for client %d (model %s): %v", client.ID, modelID, err)
			errData := protocol.MakeModelMessage(modelID, modelName, "Error: "+err.Error(), true, false)
			client.Conn.WriteMessage(websocket.TextMessage, []byte(errData))
		}
	}()
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
