package server

import (
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"sync"
	"testing"

	"openchat-server/common"
)

// mockSSEServer создаёт тестовый HTTP-сервер, эмулирующий SSE streaming
func mockSSEServer(handler func(w http.ResponseWriter)) *httptest.Server {
	return httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/event-stream")
		handler(w)
	}))
}

func TestLLMClient_StreamMessage_Success(t *testing.T) {
	server := mockSSEServer(func(w http.ResponseWriter) {
		flusher := w.(http.Flusher)
		chunks := []string{
			`data: {"choices":[{"delta":{"content":"Hello"},"finish_reason":""}]}`,
			`data: {"choices":[{"delta":{"content":" world"},"finish_reason":""}]}`,
			`data: {"choices":[{"delta":{"content":"!"},"finish_reason":"stop"}]}`,
			`data: [DONE]`,
		}
		for _, c := range chunks {
			w.Write([]byte(c + "\n\n"))
			flusher.Flush()
		}
	})
	defer server.Close()

	model := common.ModelConfig{
		ID:      "test-model",
		Name:    "test",
		EnvKey:  "TEST_API_KEY",
		BaseURL: server.URL,
	}

	os.Setenv("TEST_API_KEY", "test-key")
	defer os.Unsetenv("TEST_API_KEY")

	client := NewLLMClient(model)

	var mu sync.Mutex
	var received []string
	done := false

	err := client.StreamMessage([]Message{{Role: "user", Content: "Hi"}}, func(chunk string, d bool) {
		mu.Lock()
		defer mu.Unlock()
		if d {
			done = true
		} else if chunk != "" {
			received = append(received, chunk)
		}
	})

	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	mu.Lock()
	defer mu.Unlock()

	if !done {
		t.Fatal("expected done=true callback")
	}

	// Проверяем что получен полный текст (порядок может варьироваться из-за SSE buffering)
	fullText := ""
	for _, c := range received {
		fullText += c
	}
	expectedText := "Hello world!"
	if fullText != expectedText {
		t.Fatalf("expected full text %q, got %q", expectedText, fullText)
	}
}

func TestLLMClient_StreamMessage_APIError(t *testing.T) {
	server := mockSSEServer(func(w http.ResponseWriter) {
		w.WriteHeader(http.StatusUnauthorized)
		w.Write([]byte(`{"error":"Invalid API key"}`))
	})
	defer server.Close()

	model := common.ModelConfig{
		ID:      "test-model",
		Name:    "test",
		EnvKey:  "TEST_API_KEY_2",
		BaseURL: server.URL,
	}

	os.Setenv("TEST_API_KEY_2", "wrong-key")
	defer os.Unsetenv("TEST_API_KEY_2")

	client := NewLLMClient(model)

	err := client.StreamMessage([]Message{{Role: "user", Content: "Hi"}}, func(chunk string, d bool) {})

	if err == nil {
		t.Fatal("expected error for unauthorized request, got nil")
	}
	if !strings.Contains(err.Error(), "401") {
		t.Errorf("expected 401 in error, got: %v", err)
	}
}

func TestLLMClient_StreamMessage_MissingAPIKey(t *testing.T) {
	model := common.ModelConfig{
		ID:      "test-model",
		Name:    "test",
		EnvKey:  "NONEXISTENT_KEY_XXXXX",
		BaseURL: "http://localhost:9999",
	}

	client := NewLLMClient(model)

	err := client.StreamMessage([]Message{{Role: "user", Content: "Hi"}}, func(chunk string, d bool) {})

	// envKey используется как fallback ключ → запрос идёт на сервер
	// Сервер недоступен → "connection refused" ошибка
	if err == nil {
		t.Fatal("expected connection error, got nil")
	}
	if !strings.Contains(err.Error(), "request failed") && !strings.Contains(err.Error(), "connect") {
		t.Errorf("expected connection error, got: %v", err)
	}
}

func TestLLMClient_Abort(t *testing.T) {
	// Сервер который стримит бесконечно
	server := mockSSEServer(func(w http.ResponseWriter) {
		flusher := w.(http.Flusher)
		for i := 0; i < 100; i++ {
			w.Write([]byte(`data: {"choices":[{"delta":{"content":"chunk"},"finish_reason":""}]}` + "\n\n"))
			flusher.Flush()
		}
	})
	defer server.Close()

	model := common.ModelConfig{
		ID:      "test-model",
		Name:    "test",
		EnvKey:  "TEST_API_KEY_ABORT",
		BaseURL: server.URL,
	}

	os.Setenv("TEST_API_KEY_ABORT", "test-key")
	defer os.Unsetenv("TEST_API_KEY_ABORT")

	client := NewLLMClient(model)

	var mu sync.Mutex
	chunkCount := 0
	done := false

	// Абортируем после получения нескольких чанков
	err := client.StreamMessage([]Message{{Role: "user", Content: "Hi"}}, func(chunk string, d bool) {
		mu.Lock()
		defer mu.Unlock()
		if d {
			done = true
			return
		}
		chunkCount++
		if chunkCount >= 3 {
			client.Abort()
		}
	})

	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	mu.Lock()
	defer mu.Unlock()

	if !done {
		t.Fatal("expected done=true after abort")
	}
}

func TestLLMClient_StreamMessage_EmptyChoices(t *testing.T) {
	server := mockSSEServer(func(w http.ResponseWriter) {
		flusher := w.(http.Flusher)
		w.Write([]byte(`data: {"choices":[]}` + "\n\n"))
		w.Write([]byte(`data: {"choices":[{"delta":{"content":"Hi"},"finish_reason":""}]}` + "\n\n"))
		w.Write([]byte(`data: [DONE]` + "\n\n"))
		flusher.Flush()
	})
	defer server.Close()

	model := common.ModelConfig{
		ID:      "test-model",
		Name:    "test",
		EnvKey:  "TEST_API_KEY_EMPTY",
		BaseURL: server.URL,
	}

	os.Setenv("TEST_API_KEY_EMPTY", "test-key")
	defer os.Unsetenv("TEST_API_KEY_EMPTY")

	client := NewLLMClient(model)

	var mu sync.Mutex
	var received []string
	done := false

	err := client.StreamMessage([]Message{{Role: "user", Content: "Hi"}}, func(chunk string, d bool) {
		mu.Lock()
		defer mu.Unlock()
		if d {
			done = true
		} else if chunk != "" {
			received = append(received, chunk)
		}
	})

	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	mu.Lock()
	defer mu.Unlock()

	if !done {
		t.Fatal("expected done=true")
	}
	if len(received) != 1 || received[0] != "Hi" {
		t.Fatalf("expected [Hi], got %v", received)
	}
}
