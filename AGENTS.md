# AGENTS.md — OpenChat

## Структура проекта

```
auc/
├── AGENTS.md, ROADMAP.md, TODO.md, .gitignore, requirements.txt
├── server/
│   └── go/                          # Go WebSocket сервер (Phase 1) — исходники
│       ├── main.go                  # Точка входа, CLI аргументы, graceful shutdown
│       ├── go.mod, go.sum           # Go модуль и зависимости
│       ├── models.json              # Серверные LLM-модели (общие для всех)
│       ├── README.md, .gitignore
│       ├── common/
│       │   ├── config.go            # Константы (порт, хост, буфер)
│       │   └── models.go            # ModelConfig, LoadModels(), ModelsReady(), WatchModels()
│       ├── protocol/
│       │   └── protocol.go          # Типы сообщений, фабрики, парсинг
│       └── server/
│           ├── server.go            # ChatServer, клиенты, broadcast, участники
│           ├── handler.go           # WebSocket роутинг (connect/broadcast/direct/model/disconnect)
│           ├── llm_handler.go       # LLM список и запросы
│           ├── llm_client.go        # HTTP SSE клиент для OpenAI-совместимых API
│           └── *_test.go            # Тесты
├── client/
│   └── python/
│       └── openchatpy/              # Python Textual TUI клиент
│           ├── client.py            # Точка входа
│           ├── app.py               # ChatApp — оркестрация, UI
│           ├── screens.py           # LoginScreen, ChatScreen, CommandInput
│           ├── ws_client.py         # WebSocket клиент, E2EE, модель-чаты
│           ├── protocol.py          # Типы сообщений, фабрики
│           ├── crypto.py            # E2EE: ECDH + AES-256-GCM
│           ├── llm_screen.py        # Экран LLM-чата
│           ├── model_loader.py      # Загрузка личных моделей
│           ├── models_user.json.example  # Шаблон личных моделей
│           ├── commands/            # Система команд (/me, /users, /ai...)
│           └── tests/               # pytest тесты
├── builds/                          # Собранные бинарники (по датам)
│   └── YYYY-MM-DD/                  # Папка с датой сборки
│       └── openchat-server.exe      # Сервер
└── old/                             # Архив (не используется)
```

## Сборка и запуск

### Go сервер (Phase 1 — текущий)

**Сборка:**
```bash
cd server/go
go build -o openchat-server.exe
```

**Сборка в builds/ с датой:**
```bash
# Windows
cd server\go
go build -o openchat-server.exe
for /f "tokens=2 delims==" %a in ('wmic OS Get localdatetime /value') do set "dt=%a"
set "DATE_DIR=%dt:~0,4%-%dt:~4,2%-%dt:~6,2%"
mkdir ..\..\builds\%DATE_DIR% 2>nul
move openchat-server.exe ..\..\builds\%DATE_DIR%\

# Linux/macOS
cd server/go
go build -o openchat-server.exe
DATE_DIR=$(date +%Y-%m-%d)
mkdir -p ../../builds/$DATE_DIR
mv openchat-server.exe ../../builds/$DATE_DIR/
```

**Где лежит exe:** `builds/YYYY-MM-DD/openchat-server.exe`
- Каждая сборка кладётся в папку с текущей датой
- Старые сборки не удаляются (архив версий)
- Файл `openchat-server.exe` не добавляется в git (см. `.gitignore`)

**Запуск:**
```bash
# Из папки builds/YYYY-MM-DD
cd builds\2026-04-16
openchat-server.exe [-port 5000] [-models models.json]

# Или из исходников
cd server/go
go run . [порт]            # по умолчанию 5000
```

**Зависимости для сборки:** Go 1.21+, `gorilla/websocket`, `fsnotify`

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
| `participants` | S→C | `type`, `count`, `participants[]` (с `is_model` для моделей) |
| `direct` | C→S/C | `type`, `from`, `to`, `content` (E2EE, сервер не расшифровывает) |
| `model_message` | C→S | `type`, `model_id`, `content`, `message_id` (сообщение в чат модели) |
| `model_response` | S→C | `type`, `model_id`, `model_name`, `content`, `done`, `stream` (ответ модели) |

## Модель-чаты

### Серверные модели (`server/go/models.json`)
- Общий файл, виден **всем** подключённым клиентам
- Если все поля заполнены (`id`, `name`, `envKey`, `baseUrl`) → модель появляется в Participants как `🤖 name`
- Каждый пользователь может писать в этот чат — сообщения идут к LLM через SSE
- **Горячая перезагрузка**: изменение `models.json` автоматически подхватывается сервером (fsnotify, debounce 500ms)

### Личные модели (`client/python/openchatpy/models_user.json`)
- Локальный файл пользователя, виден **только** этому клиенту
- Та же структура что `models.json`, пример в `models_user.json.example`
- Если заполнен → появляется как `🔒 name` в Participants
- Отправка через `llm_request` (сервер не участвует — LLM API вызывается через сервер)

### Participants — порядок отображения
1. `General` — общий чат
2. `🤖 ModelName` — серверные модели
3. `🔒 ModelName` — личные модели
4. `Username` — обычные пользователи

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
