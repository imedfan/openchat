package server

import (
	"encoding/json"
	"log"

	"github.com/gorilla/websocket"
	"openchat-server/common"
	"openchat-server/protocol"
)

// HandleLLMModels отправляет клиенту список доступных LLM-моделей
func (s *ChatServer) HandleLLMModels(client *ClientInfo) {
	models := make([]protocol.LLMModelInfo, 0, len(s.Models))
	for _, m := range s.Models {
		models = append(models, protocol.LLMModelInfo{
			ID:   m.ID,
			Name: m.Name,
		})
	}

	payload := protocol.MakeLLMModels(models)
	client.Conn.WriteMessage(websocket.TextMessage, []byte(payload))
	log.Printf("Sent %d LLM model(s) list to client %d", len(models), client.ID)
}

// HandleLLMRequest обрабатывает запрос к LLM от клиента и стримит ответ
func (s *ChatServer) HandleLLMRequest(client *ClientInfo, msg map[string]interface{}) {
	// Парсим запрос
	modelID, _ := msg["model_id"].(string)
	if modelID == "" {
		errMsg := protocol.MakeLLMError("", "missing model_id in request")
		client.Conn.WriteMessage(websocket.TextMessage, []byte(errMsg))
		return
	}

	// Находим модель в конфигурации
	var modelConfig *common.ModelConfig
	for i := range s.Models {
		if s.Models[i].ID == modelID {
			modelConfig = &s.Models[i]
			break
		}
	}

	if modelConfig == nil {
		errMsg := protocol.MakeLLMError(modelID, "model not found in config")
		client.Conn.WriteMessage(websocket.TextMessage, []byte(errMsg))
		return
	}

	// Парсим messages из запроса
	rawMessages, ok := msg["messages"].([]interface{})
	if !ok {
		errMsg := protocol.MakeLLMError(modelID, "missing or invalid messages in request")
		client.Conn.WriteMessage(websocket.TextMessage, []byte(errMsg))
		return
	}

	var messages []Message
	for _, raw := range rawMessages {
		m, ok := raw.(map[string]interface{})
		if !ok {
			continue
		}
		role, _ := m["role"].(string)
		content, _ := m["content"].(string)
		if role != "" && content != "" {
			messages = append(messages, Message{Role: role, Content: content})
		}
	}

	if len(messages) == 0 {
		errMsg := protocol.MakeLLMError(modelID, "no valid messages to send")
		client.Conn.WriteMessage(websocket.TextMessage, []byte(errMsg))
		return
	}

	log.Printf("Client %d requested LLM %s (%d messages)", client.ID, modelID, len(messages))

	// Создаём LLM-клиент и запускаем стриминг в отдельной горутине
	llmClient := NewLLMClient(*modelConfig)

	go func() {
		firstChunkLogged := false
		err := llmClient.StreamMessage(messages, func(chunk string, done bool) {
			if done {
				payload := protocol.MakeLLMChunk(modelID, "", true)
				client.Conn.WriteMessage(websocket.TextMessage, []byte(payload))
				log.Printf("LLM streaming to client %d completed (model: %s)", client.ID, modelID)
				return
			}

			if !firstChunkLogged && chunk != "" {
				log.Printf("LLM first chunk for client %d (model %s): %s", client.ID, modelID, truncateString(chunk, 50))
				firstChunkLogged = true
			}

			payload := protocol.MakeLLMChunk(modelID, chunk, false)
			if err := client.Conn.WriteMessage(websocket.TextMessage, []byte(payload)); err != nil {
				log.Printf("Failed to send LLM chunk to client %d: %v", client.ID, err)
			}
		})

		if err != nil {
			log.Printf("LLM streaming error for client %d (model %s): %v", client.ID, modelID, err)
			// Отправляем сообщение об ошибке, только если ещё не начали стримин
			errData, _ := json.Marshal(map[string]interface{}{
				"type":     protocol.MsgLLMError,
				"model_id": modelID,
				"error":    err.Error(),
			})
			client.Conn.WriteMessage(websocket.TextMessage, errData)
		}
	}()
}
