# OpenChat Server — Go Edition

Высокопроизводительный WebSocket сервер для OpenChat, написанный на Go.

## 🚀 Быстрый старт

### Требования
- Go 1.21+

### Установка зависимостей
```bash
cd goServer
go mod download
```

### Запуск
```bash
# По умолчанию порт 5000
go run main.go

# Или указать свой порт
go run main.go -port 8080
```

### Сборка бинарника
```bash
# Для текущей платформы
go build -o openchat-server

# Для Windows
GOOS=windows GOARCH=amd64 go build -o openchat-server.exe

# Для Linux
GOOS=linux GOARCH=amd64 go build -o openchat-server

# Для macOS
GOOS=darwin GOARCH=amd64 go build -o openchat-server
```

## 📁 Структура проекта

```
goServer/
├── main.go              # Точка входа, CLI, graceful shutdown
├── server/
│   ├── server.go        # ChatServer, хранение клиентов, broadcast
│   └── handler.go       # Обработка подключений (connect/disconnect/message/direct)
├── protocol/
│   └── protocol.go      # Типы сообщений, JSON-модели, фабрики
├── common/
│   └── config.go        # Константы (порт, buffer size)
├── go.mod               # Go модуль
└── README.md
```

## 🔄 Протокол (JSON поверх WebSocket)

| Тип | Направление | Описание |
|-----|--------------|----------|
| `connect` | C→S | Подключение клиента |
| `connected` | S→C | Подтверждение подключения |
| `message` | C→S | Обычное сообщение |
| `ack` | S→C | Подтверждение получения |
| `system` | S→C | Системное сообщение (join/leave) |
| `participants` | S→C | Список участников |
| `direct` | C→S / S→C | Личное сообщение (E2EE relay) |

## ⚡ Преимущества Go версии

- **Производительность**: goroutines легче потоков, нативная многопоточность
- **Один бинарник**: не нужен Python, pip, зависимости
- **Меньше памяти**: ~10-20 МБ vs ~50-100 МБ у Python
- **Быстрый запуск**: ~0.01 сек vs ~0.5-1 сек у Python
- **Кроссплатформенность**: компиляция под любую ОС одной командой

## 🛠 Стек

- **WebSocket**: `github.com/gorilla/websocket`
- **Concurrency**: goroutines + channels + `sync.RWMutex`
- **Логирование**: стандартный `log` (файл + консоль)

## 📝 Совместимость

Полностью совместим с Python-клиентом из основного проекта. Сервер — только ретранслятор, для DM НЕ расшифровывает сообщения.

## 🔒 Безопасность

- Direct Messages используют E2EE (ECDH + AES-256-GCM)
- Сервер НЕ имеет доступа к приватным ключам клиентов
- Relay происходит без расшифровки
