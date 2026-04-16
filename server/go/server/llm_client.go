package server

import (
	"bufio"
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"strings"
	"sync"
	"time"

	"openchat-server/common"
)

// LLMClient — клиент для обращения к OpenAI-совместимому LLM API с поддержкой streaming
type LLMClient struct {
	model   common.ModelConfig
	httpCli *http.Client
	mu      sync.Mutex // защищает cancel
	cancel  chan struct{}
}

// NewLLMClient создаёт новый LLM-клиент для указанной модели
func NewLLMClient(model common.ModelConfig) *LLMClient {
	return &LLMClient{
		model: model,
		httpCli: &http.Client{
			Timeout: 5 * time.Minute, // долгое таймаут для долгих генераций
		},
		cancel: make(chan struct{}),
	}
}

// StreamMessage отправляет streaming-запрос к LLM API и вызывает callback для каждого чанка
// callback(chunk, done) — done=true означает завершение стриминга
func (c *LLMClient) StreamMessage(messages []Message, callback func(chunk string, done bool)) error {
	// Пробуем получить API-ключ из переменной окружения
	apiKey := os.Getenv(c.model.EnvKey)
	
	// Если переменная окружения не найдена, используем envKey как сам ключ
	if apiKey == "" {
		apiKey = c.model.EnvKey
	}
	
	if apiKey == "" {
		return fmt.Errorf("API key not set (envKey: %s)", c.model.EnvKey)
	}

	url := c.model.BaseURL + "/chat/completions"

	reqBody := map[string]interface{}{
		"model":    c.model.ID,
		"messages": messages,
		"stream":   true,
	}

	bodyBytes, err := json.Marshal(reqBody)
	if err != nil {
		return fmt.Errorf("marshal request: %w", err)
	}

	req, err := http.NewRequest("POST", url, bytes.NewReader(bodyBytes))
	if err != nil {
		return fmt.Errorf("create request: %w", err)
	}

	req.Header.Set("Content-Type", "application/json")
	if apiKey != "" {
		req.Header.Set("Authorization", "Bearer "+apiKey)
	}

	resp, err := c.httpCli.Do(req)
	if err != nil {
		return fmt.Errorf("request failed: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(resp.Body)
		return fmt.Errorf("API error (HTTP %d): %s", resp.StatusCode, string(body))
	}

	return c.readSSE(resp.Body, callback)
}

// Abort прерывает активный streaming-запрос
func (c *LLMClient) Abort() {
	c.mu.Lock()
	defer c.mu.Unlock()
	close(c.cancel)
	c.cancel = make(chan struct{})
}

// readSSE читает Server-Sent Events поток и вызывает callback для каждого data-чанка
func (c *LLMClient) readSSE(body io.ReadCloser, callback func(chunk string, done bool)) error {
	defer body.Close()

	scanner := bufio.NewScanner(body)
	scanner.Split(splitSSE)

	for {
		// Проверяем, не был ли запрос прерван
		select {
		case <-c.cancel:
			callback("", true)
			return nil
		default:
		}

		if !scanner.Scan() {
			if err := scanner.Err(); err != nil {
				return fmt.Errorf("SSE scan error: %w", err)
			}
			// Конец потока — нормальное завершение
			callback("", true)
			return nil
		}

		line := scanner.Text()
		if !strings.HasPrefix(line, "data: ") {
			continue
		}

		data := strings.TrimPrefix(line, "data: ")
		data = strings.TrimSpace(data)

		if data == "[DONE]" {
			callback("", true)
			return nil
		}

		var parsed struct {
			Choices []struct {
				Delta struct {
					Content string `json:"content"`
				} `json:"delta"`
				FinishReason string `json:"finish_reason"`
			} `json:"choices"`
		}

		if err := json.Unmarshal([]byte(data), &parsed); err != nil {
			// Пропускаем невалидные SSE data-строки
			continue
		}

		if len(parsed.Choices) == 0 {
			continue
		}

		choice := parsed.Choices[0]

		// Сначала отправляем чанк если есть контент (даже если finish_reason установлен)
		content := choice.Delta.Content
		if content != "" {
			callback(content, false)
		}

		// Потом проверяем finish_reason — если установлен, завершаем
		if choice.FinishReason != "" {
			callback("", true)
			return nil
		}
	}
}

// splitSSE — кастомная split-функция для SSE: разбивает по двойным новым строкам (\n\n)
func splitSSE(data []byte, atEOF bool) (advance int, token []byte, err error) {
	if atEOF && len(data) == 0 {
		return 0, nil, nil
	}

	// Ищем разделитель SSE — двойной newline
	if i := bytes.Index(data, []byte("\n\n")); i >= 0 {
		return i + 2, bytes.TrimSpace(data[:i]), nil
	}

	if atEOF {
		return len(data), bytes.TrimSpace(data), nil
	}

	// Запрашиваем больше данных
	return 0, nil, nil
}

// Message — структура сообщения для LLM API (совместима с OpenAI format)
type Message struct {
	Role    string `json:"role"`
	Content string `json:"content"`
}
