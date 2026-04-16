package server

import (
	"encoding/json"
	"strings"
	"testing"

	"openchat-server/common"
	"openchat-server/protocol"
)

func TestHandleLLMModels_EmptyList(t *testing.T) {
	server := NewChatServer("127.0.0.1", 5000, []common.ModelConfig{})
	if len(server.Models) != 0 {
		t.Fatalf("expected 0 models, got %d", len(server.Models))
	}
}

func TestHandleLLMModels_NonEmptyList(t *testing.T) {
	models := []common.ModelConfig{
		{ID: "model-1", Name: "local", EnvKey: "K1", BaseURL: "http://a/v1"},
		{ID: "model-2", Name: "cloud", EnvKey: "K2", BaseURL: "http://b/v1"},
	}
	server := NewChatServer("127.0.0.1", 5000, models)

	if len(server.Models) != 2 {
		t.Fatalf("expected 2 models, got %d", len(server.Models))
	}
	if server.Models[0].ID != "model-1" {
		t.Errorf("expected first model ID 'model-1', got '%s'", server.Models[0].ID)
	}
}

func TestHandleLLMRequest_MissingModelID(t *testing.T) {
	// Тестируем что при отсутствии model_id возвращается ошибка
	models := []common.ModelConfig{
		{ID: "test", Name: "test", EnvKey: "K", BaseURL: "http://x/v1"},
	}
	server := NewChatServer("127.0.0.1", 5000, models)

	// Создаём mock-клиент с buffered connection для захвата ответов
	conn := NewMockConn()
	client := &ClientInfo{ID: 1, Username: "tester", Conn: conn}

	msg := map[string]interface{}{
		"type":     protocol.MsgLLMRequest,
		"messages": []interface{}{map[string]interface{}{"role": "user", "content": "hi"}},
	}

	server.HandleLLMRequest(client, msg)

	// Проверяем что была отправлена ошибка
	sent := conn.SentMessages()
	if len(sent) == 0 {
		t.Fatal("expected at least one message (error)")
	}

	var resp protocol.LLMError
	if err := json.Unmarshal([]byte(sent[0]), &resp); err != nil {
		t.Fatalf("failed to parse response: %v", err)
	}
	if resp.Type != protocol.MsgLLMError {
		t.Errorf("expected type llm_error, got '%s'", resp.Type)
	}
	if !strings.Contains(resp.Error, "missing") {
		t.Errorf("expected 'missing' in error, got: %s", resp.Error)
	}
}

func TestHandleLLMRequest_ModelNotFound(t *testing.T) {
	models := []common.ModelConfig{
		{ID: "existing", Name: "test", EnvKey: "K", BaseURL: "http://x/v1"},
	}
	server := NewChatServer("127.0.0.1", 5000, models)

	conn := NewMockConn()
	client := &ClientInfo{ID: 1, Username: "tester", Conn: conn}

	msg := map[string]interface{}{
		"type":     protocol.MsgLLMRequest,
		"model_id": "nonexistent",
		"messages": []interface{}{map[string]interface{}{"role": "user", "content": "hi"}},
	}

	server.HandleLLMRequest(client, msg)

	sent := conn.SentMessages()
	if len(sent) == 0 {
		t.Fatal("expected at least one message (error)")
	}

	var resp protocol.LLMError
	if err := json.Unmarshal([]byte(sent[0]), &resp); err != nil {
		t.Fatalf("failed to parse response: %v", err)
	}
	if resp.Type != protocol.MsgLLMError {
		t.Errorf("expected type llm_error, got '%s'", resp.Type)
	}
	if !strings.Contains(resp.Error, "not found") {
		t.Errorf("expected 'not found' in error, got: %s", resp.Error)
	}
}

func TestHandleLLMRequest_NoMessages(t *testing.T) {
	models := []common.ModelConfig{
		{ID: "test", Name: "test", EnvKey: "K", BaseURL: "http://x/v1"},
	}
	server := NewChatServer("127.0.0.1", 5000, models)

	conn := NewMockConn()
	client := &ClientInfo{ID: 1, Username: "tester", Conn: conn}

	msg := map[string]interface{}{
		"type":     protocol.MsgLLMRequest,
		"model_id": "test",
	}

	server.HandleLLMRequest(client, msg)

	sent := conn.SentMessages()
	if len(sent) == 0 {
		t.Fatal("expected at least one message (error)")
	}

	var resp protocol.LLMError
	if err := json.Unmarshal([]byte(sent[0]), &resp); err != nil {
		t.Fatalf("failed to parse response: %v", err)
	}
	if resp.Type != protocol.MsgLLMError {
		t.Errorf("expected type llm_error, got '%s'", resp.Type)
	}
}
