package server

import (
	"encoding/json"
	"log"

	"github.com/gorilla/websocket"
	"openchat-server/common"
	"openchat-server/protocol"
)

// HandleClient обрабатывает подключение одного клиента
func (s *ChatServer) HandleClient(conn *websocket.Conn) {
	var client *ClientInfo

	// Обёртка с мьютексом — ОДИН экземпляр на всё подключение
	connMu := NewConnMutex(conn)

	defer func() {
		if client != nil {
			s.HandleDisconnect(client.ID)
		}
		connMu.Close()
	}()

	for {
		_, message, err := connMu.ReadMessage()
		if err != nil {
			if websocket.IsUnexpectedCloseError(err, websocket.CloseGoingAway, websocket.CloseNormalClosure) {
				log.Printf("WebSocket error: %v", err)
			}
			return
		}

		// Парсим JSON
		var msg map[string]interface{}
		if err := json.Unmarshal(message, &msg); err != nil {
			log.Printf("Failed to parse message: %v", err)
			continue
		}

		// Получаем тип сообщения
		msgType := protocol.GetMsgType(msg)

		switch msgType {
		case protocol.MsgConnect:
			var connectMsg protocol.ConnectMessage
			if err := json.Unmarshal(message, &connectMsg); err != nil {
				log.Printf("Failed to parse connect message: %v", err)
				continue
			}
			// Конвертируем publicKey из string в []byte
			publicKey := []byte(connectMsg.PublicKey)
			client = s.AddClient(connectMsg.Username, publicKey, connMu)

			// Получаем количество участников
			participantCount := s.ClientCount()

			// Отправляем подтверждение подключения
			payload := protocol.MakeConnected(client.ID, participantCount)
			connMu.WriteMessage(websocket.TextMessage, []byte(payload))

			log.Printf("Client %d (%s) connected", client.ID, connectMsg.Username)

			// Отправляем список участников новому клиенту
			if err := s.SendParticipantsTo(client); err != nil {
				log.Printf("Failed to send participants to new client %d: %v", client.ID, err)
			}

			// Уведомляем остальных о новом участнике
			joinMsg := protocol.MakeSystemMessage(connectMsg.Username + " joined the chat")
			s.Broadcast(joinMsg, []int{client.ID})

			// Рассылаем обновлённый список участников остальным
			s.SendParticipantsToAll([]int{client.ID})

			// Отправляем список доступных LLM-моделей
			if len(s.Models) > 0 {
				s.HandleLLMModels(client)
			}

		case protocol.MsgMessage:
			if client != nil {
				msgStruct := struct {
					Content   string `json:"content"`
					MessageID string `json:"message_id"`
				}{
					Content:   msg["content"].(string),
					MessageID: msg["message_id"].(string),
				}
				s.HandleBroadcast(client, map[string]interface{}{
					"content":     msgStruct.Content,
					"message_id":  msgStruct.MessageID,
				})
			}

		case protocol.MsgDirect:
			if client != nil {
				msgStruct := struct {
					TargetID  int    `json:"target_id"`
					Content   string `json:"content"`
					MessageID string `json:"message_id"`
					Encrypted bool   `json:"encrypted"`
				}{
					TargetID:  int(msg["target_id"].(float64)),
					Content:   msg["content"].(string),
					MessageID: msg["message_id"].(string),
					Encrypted: msg["encrypted"].(bool),
				}
				s.HandleDirect(client, map[string]interface{}{
					"to":         msgStruct.TargetID,
					"content":    msgStruct.Content,
					"message_id": msgStruct.MessageID,
					"encrypted":  msgStruct.Encrypted,
				})
			}

		case protocol.MsgModelMessage:
			if client != nil {
				s.HandleModelMessage(client, msg)
			}

		case protocol.MsgLLMRequest:
			if client != nil {
				s.HandleLLMRequest(client, msg)
			}
		default:
			log.Printf("Unknown message type: %s", msgType)
		}
	}
}

// HandleConnect обрабатывает подключение нового клиента
func (s *ChatServer) HandleConnect(conn *websocket.Conn, msg *protocol.ConnectMessage) *ClientInfo {
	connMu := NewConnMutex(conn)
	client := s.AddClient(msg.Username, []byte(msg.PublicKey), connMu)
	participantCount := s.ClientCount()

	// Отправляем подтверждение подключения
	connMu.WriteMessage(websocket.TextMessage, []byte(protocol.MakeConnected(client.ID, participantCount)))
	log.Printf("Client %d (%s) connected", client.ID, msg.Username)

	// Отправляем список участников новому клиенту
	if err := s.SendParticipantsTo(client); err != nil {
		log.Printf("Failed to send participants to new client %d: %v", client.ID, err)
	}

	// Уведомляем остальных о новом участнике
	joinMsg := protocol.MakeSystemMessage(msg.Username + " joined the chat")
	s.Broadcast(joinMsg, []int{client.ID})

	// Рассылаем обновлённый список участников остальным
	s.SendParticipantsToAll([]int{client.ID})

	// Отправляем список доступных LLM-моделей
	if len(s.Models) > 0 {
		s.HandleLLMModels(client)
	}

	return client
}

// ParseConnectMessage парсит сообщение подключения
func ParseConnectMessage(data string) (*protocol.ConnectMessage, error) {
	var msg protocol.ConnectMessage
	err := json.Unmarshal([]byte(data), &msg)
	return &msg, err
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
		firstChunkLogged := false
		err := llmClient.StreamMessage(messages, func(chunk string, done bool) {
			if done {
				payload := protocol.MakeModelMessage(modelID, modelName, "", true, false)
				client.Conn.WriteMessage(websocket.TextMessage, []byte(payload))
				log.Printf("Model streaming to client %d completed (model: %s)", client.ID, modelID)
				return
			}

			if !firstChunkLogged && chunk != "" {
				log.Printf("Model first chunk for client %d (model %s): %s", client.ID, modelID, truncateString(chunk, 50))
				firstChunkLogged = true
			}

			payload := protocol.MakeModelMessage(modelID, modelName, chunk, false, true)
			if err := client.Conn.WriteMessage(websocket.TextMessage, []byte(payload)); err != nil {
				log.Printf("Failed to send model chunk to client %d: %v", client.ID, err)
			}
		})

		if err != nil {
			log.Printf("Model streaming error for client %d (model %s): %v", client.ID, modelID, err)
			errData := protocol.MakeModelMessage(modelID, modelName, "Error: "+err.Error()+"", true, false)
			client.Conn.WriteMessage(websocket.TextMessage, []byte(errData))
		}
	}()
}

// truncateString обрезает строку до указанной длины
func truncateString(s string, maxLen int) string {
	if len(s) > maxLen {
		return s[:maxLen]
	}
	return s
}