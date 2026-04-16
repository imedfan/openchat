# TODO — Архитектура и развитие

## Архитектура: текущая vs production

### Что есть сейчас

Текущий подход — **минималистичный P2P-подобный чат**:

```
┌─────────────────────────────────────────────┐
│  Клиент (Textual TUI / будущий iOS / др.)  │
│  WSClient.connect() / send_broadcast()      │
│  / send_direct() / _receive_loop()          │
└────────────────────┬────────────────────────┘
                     │
                     │ WebSocket (JSON)
                     │
                     ▼
┌─────────────────────────────────────────────┐
│  Сервер (websockets, asyncio)               │
│  handle_client() — только relay             │
│  broadcast / direct пересылка               │
└─────────────────────────────────────────────┘
```

**Плюсы текущей архитектуры:**
- Простота — один WebSocket-порт, минимум кода
- E2EE — сервер НЕ видит содержимое DM
- Любой клиент (iOS, Android, Web) может подключиться, зная протокол
- Сервер — тупой ретранслятор, не хранит данные, не исполняет команды

**Минусы для production:**
- Нет авторизации — просто имя при коннекте
- Нет хранения — сообщения в памяти клиента, теряются при перезапуске
- Нет offline-доставки — если клиент отключён, сообщение пропало
- Сервер не может индексировать/искать по DM (зашифрованы)
- Нет REST API — нельзя построить Web-фронт или мобильное приложение с кэшем
- Нет LLM-интеграции — сервер не читает сообщения, не может вызывать тулзы

---

## Production-архитектура

### 1. REST API + WebSocket (гибридный подход)

WebSocket оставить **только для real-time** уведомлений и доставки сообщений.
REST API (или GraphQL) — для CRUD, авторизации, истории, настроек.

```
POST /auth/register          → создание пользователя
POST /auth/login             → JWT token (access + refresh)
POST /auth/refresh           → обновление access token
POST /auth/logout            → инвалидация сессии

GET  /api/users              → список онлайн/офлайн
GET  /api/users/me           → профиль текущего
PUT  /api/users/me           → обновление профиля

GET  /api/channels           → список каналов/чатов
POST /api/channels           → создать канал
GET  /api/channels/{id}/messages?after=...&limit=50
POST /api/messages           → отправка (через WS relay)

GET  /api/contacts
POST /api/contacts/{id}/block

GET  /api/settings
PUT  /api/settings

POST /api/llm/chat           → чат с LLM
POST /api/llm/summarize      → суммаризация треда
POST /api/llm/ask            → вопрос по контексту чата
```

### 2. База данных

```sql
Users:
  id (UUID), username, email, password_hash,
  public_key_pem, avatar_url, status, created_at, last_seen

Channels:
  id (UUID), type (general/dm/group), name, creator_id, created_at

Channel_Members:
  channel_id, user_id, role, joined_at

Messages:
  id (UUID), sender_id, channel_id, content,
  encrypted (bool), nonce, parent_id (thread),
  created_at, updated_at, delivery_status

LLM_Sessions:
  id (UUID), user_id, channel_id,
  context_window, tool_calls, created_at

LLM_Tool_Calls:
  id, session_id, tool_name, input, output, status

API_Tokens:
  id, user_id, access_token, refresh_token,
  expires_at, revoked_at
```

### 3. Полная архитектура

```
┌──────────────────────────────────────────────────────┐
│  Clients (Web / iOS / Android / Textual)             │
│  REST API  │  WebSocket  │  GraphQL                   │
└──────────┬───────────────┬──────────────┬─────────────┘
           │               │              │
           ▼               ▼              ▼
     ┌──────────┐   ┌───────────┐   ┌──────────┐
     │ API GW   │   │ WS Server │   │ LLM GW   │
     │ (nginx)  │   │ (relay)   │   │ (proxy)  │
     └────┬─────┘   └─────┬─────┘   └────┬─────┘
          │               │              │
          ▼               ▼              ▼
     ┌──────────────────────────────────────────┐
     │         Backend (FastAPI / Django)       │
     │  Auth │ Messages │ Users │ LLM Tools     │
     └────────────────────┬─────────────────────┘
                          │
              ┌───────────┼───────────┐
              ▼           ▼           ▼
          PostgreSQL   Redis      S3/MinIO
          (messages)  (sessions,  (files,
                       cache)      media)
```

### 4. Компоненты

**API Gateway (nginx / Traefik):**
- TLS termination
- Rate limiting
- CORS
- Load balancing

**WS Server (текущий, доработать):**
- Авторизация при подключении (JWT в handshake)
- Регистрация клиентов в Redis (online/offline)
- Relay сообщений между клиентами
- Уведомления о новых сообщениях, typing, presence

**Backend (FastAPI):**
```
src/
  auth/          — регистрация, login, JWT, refresh tokens
  users/         — профиль, настройки, аватар
  channels/      — CRUD каналов, members
  messages/      — CRUD сообщений, пагинация, поиск
  llm/           — интеграция с LLM, тулзы, контекст
  notifications/ — push, email, in-app
```

**LLM-сервис (отдельный микросервис):**
```python
# LLM может:
# - читать историю чата (из БД, не зашифрованную)
# - суммаризировать тред
# - отвечать на вопросы по контексту
# - выполнять действия (через function calling):
#   - создать канал
#   - отправить сообщение
#   - найти пользователя
#   - сделать backup
```

### 5. Message Queue

```
Kafka / RabbitMQ:
  - delivery queue (offline users)
  - retry logic (failed sends)
  - event sourcing (audit log)
  - LLM request queue (async)
  - notification fan-out
```

### 6. E2EE: два режима

| Режим | Когда | Сервер видит? |
|---|---|---|
| **E2EE DM** | Пользователи включили | Нет, только relay |
| **Server-side encrypted** | Default | Да (для поиска/LLM), но encrypted at rest |

Для LLM-интеграции сообщения должны быть доступны серверу — значит E2EE опционален (как в Signal — только по желанию).

---

## План миграции (поэтапно)

### Фаза 1: REST API + Auth
- [ ] FastAPI проект с роутингом
- [ ] PostgreSQL (Alembic миграции)
- [ ] Регистрация / Login / JWT
- [ ] REST эндпоинты: users, channels, messages

### Фаза 2: WebSocket доработка
- [ ] Auth при WS handshake (JWT в query params)
- [ ] Online/offline статусы через Redis
- [ ] Offline message queue
- [ ] Typing indicators, presence

### Фаза 3: Persistent storage
- [ ] Сохранение всех сообщений в БД
- [ ] Пагинация истории
- [ ] Поиск по сообщениям
- [ ] Threads / replies

### Фаза 4: LLM интеграция
- [ ] LLM-сервис (FastAPI + OpenAI/Anthropic)
- [ ] Tool definitions (create channel, send msg, search)
- [ ] Context window management
- [ ] Summarization endpoint

### Фаза 5: Client apps
- [ ] Web-клиент (React/Next.js)
- [ ] iOS-клиент (Swift + WebSocket)
- [ ] Сохранить Textual-клиент (legacy)

---

## Что можно надстроить без ломки текущих клиентов

Текущий WebSocket-протокол **совместим** с production-архитектурой:
- JSON-формат сообщений останется
- Сервер продолжит relay'ить сообщения
- E2EE для DM сохранится (опционально)

Новое — это **надстройка**: REST API, БД, auth, LLM.
Существующие клиенты продолжат работать без изменений.
