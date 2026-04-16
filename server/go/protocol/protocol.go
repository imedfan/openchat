package protocol

import (
	"encoding/json"
	"fmt"
	"time"
)

// ── Типы сообщений ─────────────────────────────────────────
const (
	MsgConnect     = "connect"
	MsgConnected   = "connected"
	MsgMessage     = "message"
	MsgDirect      = "direct"
	MsgAck         = "ack"
	MsgSystem      = "system"
	MsgParticipants = "participants"
)

// ── JSON структуры сообщений ──────────────────────────────

// ConnectMessage — C→S: подключение клиента
type ConnectMessage struct {
	Type      string `json:"type"`
	Username  string `json:"username"`
	PublicKey string `json:"public_key"`
}

// ConnectedMessage — S→C: подтверждение подключения
type ConnectedMessage struct {
	Type             string `json:"type"`
	ClientID         int    `json:"client_id"`
	ParticipantCount int    `json:"participant_count"`
}

// Message — C→S: обычное сообщение
type Message struct {
	Type      string `json:"type"`
	Content   string `json:"content"`
	MessageID string `json:"message_id"`
}

// DirectMessage — C→S: личное сообщение (encrypted)
type DirectMessage struct {
	Type      string `json:"type"`
	TargetID  int    `json:"target_id"`
	Content   string `json:"content"`
	Nonce     string `json:"nonce"`
	MessageID string `json:"message_id"`
}

// AckMessage — S→C: подтверждение получения
type AckMessage struct {
	Type      string `json:"type"`
	MessageID string `json:"message_id"`
	Username  string `json:"username"`
}

// SystemMessage — S→C: системное сообщение
type SystemMessage struct {
	Type      string `json:"type"`
	Message   string `json:"message"`
	Timestamp string `json:"timestamp"`
}

// ParticipantsMessage — S→C: список участников
type ParticipantsMessage struct {
	Type         string         `json:"type"`
	Count        int            `json:"count"`
	Participants []Participant  `json:"participants"`
}

// Participant — информация об одном участнике
type Participant struct {
	ClientID  int    `json:"client_id"`
	Username  string `json:"username"`
	PublicKey string `json:"public_key"`
}

// BroadcastMessage — S→C: сообщение для рассылки
type BroadcastMessage struct {
	Type      string `json:"type"`
	ClientID  int    `json:"client_id"`
	Username  string `json:"username"`
	Content   string `json:"content"`
	Timestamp string `json:"timestamp"`
}

// DirectRelayMessage — S→C: личное сообщение для relay
type DirectRelayMessage struct {
	Type      string `json:"type"`
	ClientID  int    `json:"client_id"`
	Username  string `json:"username"`
	TargetID  int    `json:"target_id"`
	Content   string `json:"content"`
	Nonce     string `json:"nonce"`
	MessageID string `json:"message_id"`
	Timestamp string `json:"timestamp"`
}

// ── Фабрики сообщений ─────────────────────────────────────

func MakeConnected(clientID int, participantCount int) string {
	msg := ConnectedMessage{
		Type:             MsgConnected,
		ClientID:         clientID,
		ParticipantCount: participantCount,
	}
	data, _ := json.Marshal(msg)
	return string(data)
}

func MakeSystemMessage(message string) string {
	msg := SystemMessage{
		Type:      MsgSystem,
		Message:   message,
		Timestamp: time.Now().Format("15:04"),
	}
	data, _ := json.Marshal(msg)
	return string(data)
}

func MakeParticipants(count int, participants []Participant) string {
	msg := ParticipantsMessage{
		Type:         MsgParticipants,
		Count:        count,
		Participants: participants,
	}
	data, _ := json.Marshal(msg)
	return string(data)
}

func MakeAck(messageID string, username string) string {
	msg := AckMessage{
		Type:      MsgAck,
		MessageID: messageID,
		Username:  username,
	}
	data, _ := json.Marshal(msg)
	return string(data)
}

func MakeBroadcast(clientID int, username string, content string) string {
	msg := BroadcastMessage{
		Type:      MsgMessage,
		ClientID:  clientID,
		Username:  username,
		Content:   content,
		Timestamp: time.Now().Format("15:04"),
	}
	data, _ := json.Marshal(msg)
	return string(data)
}

func MakeDirectRelay(clientID int, username string, targetID int, content string, nonce string, messageID string) string {
	msg := DirectRelayMessage{
		Type:      MsgDirect,
		ClientID:  clientID,
		Username:  username,
		TargetID:  targetID,
		Content:   content,
		Nonce:     nonce,
		MessageID: messageID,
		Timestamp: time.Now().Format("15:04"),
	}
	data, _ := json.Marshal(msg)
	return string(data)
}

// ParseMessage — парсит JSON в map для определения типа
func ParseMessage(data string) (map[string]interface{}, error) {
	var msg map[string]interface{}
	err := json.Unmarshal([]byte(data), &msg)
	if err != nil {
		return nil, fmt.Errorf("failed to parse message: %w", err)
	}
	return msg, nil
}

// GetMsgType — безопасно получает тип сообщения
func GetMsgType(msg map[string]interface{}) string {
	if t, ok := msg["type"].(string); ok {
		return t
	}
	return ""
}
