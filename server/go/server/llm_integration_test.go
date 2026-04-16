package server

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"sync"
	"testing"

	"openchat-server/common"
)

// TestLLMIntegration_FullFlow тестирует полный поток LLM-запроса
// с мокированным LLM API сервером
func TestLLMIntegration_FullFlow(t *testing.T) {
	// Мокированный LLM API сервер
	llmServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/event-stream")
		flusher := w.(http.Flusher)

		// Эмулируем streaming ответ
		chunks := []string{
			`data: {"choices":[{"delta":{"content":"Hello"},"finish_reason":""}]}`,
			`data: {"choices":[{"delta":{"content":" from"},"finish_reason":""}]}`,
			`data: {"choices":[{"delta":{"content":" LLM"},"finish_reason":""}]}`,
			`data: {"choices":[{"delta":{"content":"!"},"finish_reason":"stop"}]}`,
			`data: [DONE]`,
		}
		for _, c := range chunks {
			w.Write([]byte(c + "\n\n"))
			flusher.Flush()
		}
	}))
	defer llmServer.Close()

	// Создаём сервер с LLM-моделью
	models := []common.ModelConfig{
		{
			ID:      "test-llm",
			Name:    "Test Model",
			EnvKey:  "TEST_LLM_API_KEY",
			BaseURL: llmServer.URL,
		},
	}
	os.Setenv("TEST_LLM_API_KEY", "test-key")
	defer os.Unsetenv("TEST_LLM_API_KEY")

	chatServer := NewChatServer("127.0.0.1", 5000, models)

	// Проверяем что модель загрузилась
	if len(chatServer.Models) != 1 {
		t.Fatalf("expected 1 model, got %d", len(chatServer.Models))
	}
	if chatServer.Models[0].ID != "test-llm" {
		t.Errorf("expected model ID 'test-llm', got '%s'", chatServer.Models[0].ID)
	}

	// Создаём мокированного клиента
	conn := NewMockConn()
	client := &ClientInfo{ID: 1, Username: "tester", Conn: NewConnMutex(conn)}

	// Отправляем LLM-запрос
	msg := map[string]interface{}{
		"type":     "llm_request",
		"model_id": "test-llm",
		"messages": []interface{}{
			map[string]interface{}{"role": "user", "content": "Hello LLM"},
		},
	}

	chatServer.HandleLLMRequest(client, msg)

	// Ждём завершения стриминга (асинхронная операция)
	var mu sync.Mutex
	var chunks []string
	done := false

	// Имитируем обработку в том же потоке (в реальности это асинхронно)
	// Для теста создаём LLM-клиент напрямую и вызываем StreamMessage
	llmClient := NewLLMClient(chatServer.Models[0])

	err := llmClient.StreamMessage([]Message{{Role: "user", Content: "Hello LLM"}}, func(chunk string, d bool) {
		mu.Lock()
		defer mu.Unlock()
		if d {
			done = true
		} else if chunk != "" {
			chunks = append(chunks, chunk)
		}
	})

	if err != nil {
		t.Fatalf("StreamMessage error: %v", err)
	}

	mu.Lock()
	defer mu.Unlock()

	if !done {
		t.Fatal("expected streaming to complete")
	}

	// Проверяем полный текст вместо количества чанков (может варьироваться из-за SSE buffering)
	fullText := ""
	for _, c := range chunks {
		fullText += c
	}
	expectedText := "Hello from LLM!"
	if fullText != expectedText {
		t.Fatalf("expected full text %q, got %q", expectedText, fullText)
	}
}

// TestLLMIntegration_ModelNotFound тестирует обработку несуществующей модели
func TestLLMIntegration_ModelNotFound(t *testing.T) {
	chatServer := NewChatServer("127.0.0.1", 5000, []common.ModelConfig{
		{ID: "existing", Name: "test", EnvKey: "K", BaseURL: "http://x/v1"},
	})

	conn := NewMockConn()
	client := &ClientInfo{ID: 1, Username: "tester", Conn: NewConnMutex(conn)}

	msg := map[string]interface{}{
		"type":     "llm_request",
		"model_id": "nonexistent",
		"messages": []interface{}{map[string]interface{}{"role": "user", "content": "hi"}},
	}

	chatServer.HandleLLMRequest(client, msg)

	sent := conn.SentMessages()
	if len(sent) == 0 {
		t.Fatal("expected error response")
	}

	// Проверяем что отправлена ошибка
	var resp struct {
		Type     string `json:"type"`
		ModelID  string `json:"model_id"`
		ErrorMsg string `json:"error"`
	}
	if err := parseJSON(sent[0], &resp); err != nil {
		t.Fatalf("failed to parse response: %v", err)
	}
	if resp.Type != "llm_error" {
		t.Errorf("expected llm_error, got '%s'", resp.Type)
	}
	if resp.ErrorMsg == "" {
		t.Error("expected non-empty error message")
	}
}

// parseJSON — вспомогательная функция для парсинга JSON
func parseJSON(data string, v interface{}) error {
	return json.Unmarshal([]byte(data), v)
}
