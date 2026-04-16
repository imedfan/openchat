# AGENTS.md — OpenChat

## Структура проекта

```
auc/
├── AGENTS.md, ROADMAP.md, TODO.md, .gitignore, requirements.txt
├── server/
│   └── go/                          # Go WebSocket сервер (Phase 1)
├── client/
│   └── python/
│       └── openchatpy/              # Python Textual TUI клиент
└── old/                             # Архив (не используется)
    ├── python-server/               # Старый Python сервер
    ├── java-server/                 # Java сервер (прототип)
    ├── build-artifacts/             # PyInstaller сборки
    ├── logs/                        # Логи
    └── cache/                       # __pycache__, .pytest_cache
```

## Команды

### Go сервер (Phase 1 — текущий)

```bash
cd server/go
go run . [порт]            # по умолчанию 5000
go build -o openchat-server.exe
```

### Python клиент

```bash
cd client/python/openchatpy
python client.py             # запуск клиента
```

### Зависимости клиента

`pip install textual`

### Старый Python сервер (архив, old/python-server/)

```bash
cd old/python-server
python server.py [порт]
```

## Архитектура

- **Go сервер** (`server/go/`): WebSocket, один горутин на клиента, broadcast через `sync.Mutex`
- **Python клиент** (`client/python/openchatpy/`): Textual TUI, два экрана (логин → чат), демон-поток для приёма

## Протокол (JSON поверх WebSocket)

| Тип | Направление | Поля |
|-----|--------------|------|
| `connect` | C→S | `type`, `username` |
| `connected` | S→C | `type`, `client_id`, `participant_count` |
| `message` | C→S | `type`, `content`, `message_id` |
| `ack` | S→C | `type`, `message_id` |
| `system` | S→C | `type`, `message`, `timestamp` (join/leave) |
| `participants` | S→C | `type`, `count`, `participants[]` |
| `direct` | C→S/C | `type`, `from`, `to`, `content` (E2EE, сервер не расшифровывает) |

## Константы

- `BUFFER_SIZE = 4096`
- `MAX_MESSAGES = 100` (история в deque)
- `DEFAULT_PORT = 5000`
- `DEFAULT_IP = "127.0.0.1"`

## Криптография (E2EE)

- ECDH SECP256R1 для обмена ключами
- AES-256-GCM для шифрования сообщений
- Ключевые файлы: `client/python/openchatpy/crypto.py`

## Логи

`server.log` — в корне рабочей директории (Go сервер пишет и в stdout)

## Ключевые места в коде

### Go сервер

| Задача | Файл | Функция |
|--------|------|---------|
| Обработка сообщений | `server/handler.go` | `HandleClient()` |
| Broadcast | `server/server.go` | `Broadcast()` |
| Протокол | `protocol/protocol.go` | типы сообщений |
| Конфиг | `common/config.go` | `LoadConfig()` |

### Python клиент

| Задача | Файл | Функция |
|--------|------|---------|
| Подключение | `ws_client.py` | `connect()` |
| Приём сообщений | `ws_client.py` | `receive_messages()` |
| UI экраны | `screens.py` | `LoginScreen`, `ChatScreen` |
| Приложение | `app.py` | `OpenChatApp` |
| Команды | `commands/builtin.py` | встроенные команды |

## Тесты

Старые тесты Python сервера: `old/python-server/test_*.py`

При добавлении новых: `pytest tests/`
