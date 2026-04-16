package server

import (
	"sync"

	"github.com/gorilla/websocket"
)

// MockConn — мок WebSocket подключения для тестирования
type MockConn struct {
	mu       sync.Mutex
	messages []string
}

// NewMockConn создаёт новый мок подключения
func NewMockConn() *MockConn {
	return &MockConn{
		messages: make([]string, 0),
	}
}

// WriteMessage имплементирует websocket.Conn.WriteMessage
func (m *MockConn) WriteMessage(messageType int, data []byte) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.messages = append(m.messages, string(data))
	return nil
}

// ReadMessage — заглушка (для тестов не используется)
func (m *MockConn) ReadMessage() (messageType int, p []byte, err error) {
	return 0, nil, nil
}

// Close — заглушка
func (m *MockConn) Close() error {
	return nil
}

// SentMessages возвращает все отправленные сообщения
func (m *MockConn) SentMessages() []string {
	m.mu.Lock()
	defer m.mu.Unlock()
	result := make([]string, len(m.messages))
	copy(result, m.messages)
	return result
}

// LastMessage возвращает последнее отправленное сообщение
func (m *MockConn) LastMessage() string {
	m.mu.Lock()
	defer m.mu.Unlock()
	if len(m.messages) == 0 {
		return ""
	}
	return m.messages[len(m.messages)-1]
}

// Убедимся что MockConn имплементирует нужный интерфейс
// (websocket.Conn — это конкретный тип, а не интерфейс, поэтому просто используем методы)

// We need a way to use MockConn where *websocket.Conn is expected.
// Since *websocket.Conn is a concrete type, we'll use a wrapper approach.
// For tests, we directly call WriteMessage on MockConn.

// NOTE: Handler tests use MockConn directly (not as *websocket.Conn)
// and call WriteMessage method which has the same signature.
