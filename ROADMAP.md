# OpenChat — Roadmap

Эволюционная архитектура: начинаем с минимума, растём — и выносим части в микросервисы по мере необходимости.

---

## Фаза 1 — MVP (текущее состояние)

**Архитектура**: один Go-сервер, WebSocket relay, без БД, без авторизации.

### Что есть
- [x] Go WebSocket-сервер (`goServer/`) — relay поверх WebSocket
- [x] Protocol: 7 типов сообщений (connect, connected, message, ack, system, participants, direct)
- [x] E2EE relay — сервер НЕ расшифровывает DM (ECDH SECP256R1 + AES-256-GCM на клиенте)
- [x] Participant tracking — полный список при join/leave
- [x] Python Textual TUI клиент
- [x] Graceful shutdown (SIGINT/SIGTERM)

### Чего нет
- Нет БД — сообщения не сохраняются
- Нет авторизации — любой подключается с любым username
- Нет истории — при реконнекте всё теряется
- Нет REST API — только WebSocket
- Нет LLM — никакой AI

### Характеристики
- RAM: ~10 МБ
- Conn: ~10K–50K (goroutines)
- Артефакт: один `.exe` бинарник
- Зависимости: `gorilla/websocket` (stdlib + 1 external)

### Когда переходить к Фазе 2
Триггеры:
- «Нужно хранить историю сообщений»
- «Нужна регистрация/авторизация»
- «Нужен REST API для внешних клиентов»
- «Нужен чат-бот / суммаризация / модерация»

---

## Фаза 2 — Single Server + DB

**Архитектура**: Go-сервер с встроенным REST API, PostgreSQL, JWT auth, опционально Python LLM sidecar.

### Что добавляется

#### БД: PostgreSQL
- [ ] Таблица `users` — id, username, password_hash, public_key, created_at
- [ ] Таблица `messages` — id, sender_id, room/channel, content (encrypted), timestamp
- [ ] Таблица `direct_messages` — id, sender_id, recipient_id, ciphertext, nonce, timestamp
- [ ] Таблица `sessions` — id, user_id, token, expires_at
- [ ] Миграции через `goose` или `migrate`

#### REST API (gin или chi)
- [ ] `POST /api/v1/auth/register` — регистрация
- [ ] `POST /api/v1/auth/login` — логин, выдача JWT
- [ ] `GET /api/v1/users/me` — профиль (auth required)
- [ ] `GET /api/v1/messages` — история сообщений (auth required, pagination)
- [ ] `GET /api/v1/participants` — список онлайн-пользователей
- [ ] OpenAPI/Swagger генерация

#### Auth
- [ ] JWT middleware для WebSocket upgrade (проверка токена)
- [ ] Password hashing — bcrypt
- [ ] WebSocket auth: токен в query params или первом сообщении

#### LLM (опционально)
- [ ] Python-микросервис (`llm-server/`) — отдельный процесс
- [ ] Go вызывает Python по HTTP/gRPC
- [ ] Эндпоинты:
  - `POST /summarize` — суммаризация последних N сообщений
  - `POST /moderate` — проверка текста на токсичность
  - `POST /chat` — AI-бот в чате (RAG по истории)
- [ ] LangChain для pipeline

#### Инфраструктура
- [ ] Docker Compose: `go-server` + `postgres` + `llm-server` (opt)
- [ ] Health checks (`/health`)
- [ ] Rate limiting middleware (sliding window в Redis или in-memory)

### Характеристики
- RAM: ~50 МБ (Go) + ~150 МБ (PostgreSQL) + ~200 МБ (Python LLM)
- Conn: ~10K–50K
- Артефакты: Go binary + Docker-образы
- Зависимости: `gorilla/websocket`, `gin`/`chi`, `GORM`, `pgx`, `go-jwt`, `bcrypt`, `goose`

### Когда переходить к Фазе 3
Триггеры:
- «2000+ одновременных клиентов + нужна БД + auth»
- «Нужен SSO, LDAP, аудит, compliance»
- «Нужен кластер WebSocket-серверов»
- «Бизнес-логика стала слишком сложной для Go-монолита»

---

## Фаза 3 — Polyglot Microservices (Production)

**Архитектура**: Go WebSocket Gateway + Java Spring Boot Backend API + Python LLM Service + Redis + PostgreSQL. Каждый сервис делает то, что умеет лучше всего.

### Сервисы

#### 1. Go — WebSocket Gateway
**Задача**: держать соединения, relay, минимальная логика
- [ ] WebSocket relay (из Фазы 2, без изменений)
- [ ] Auth middleware — валидация JWT при upgrade
- [ ] Rate limiting — запрос к Redis или локальный счётчик
- [ ] Presence — heartbeat + Redis pub/sub для кластера
- [ ] REST API убран — только WebSocket + `/health`
- [ ] Связь с Backend API — gRPC (сохранение сообщений, проверка прав)
- [ ] Связь с LLM Service — gRPC (модерация, суммаризация)

**Характеристики**:
- RAM: ~10 МБ на инстанс
- Conn: ~50K на инстанс (горизонтально масштабируется)
- Деплой: Kubernetes Deployment, HPA по CPU/conn

#### 2. Java (Spring Boot) — Backend API
**Задача**: бизнес-логика, БД, авторизация, REST API
- [ ] Spring Security — OAuth2, JWT, SAML, LDAP
- [ ] Spring Data JPA — Users, Messages, Sessions, Roles
- [ ] REST API: auth, users, messages, rooms, admin
- [ ] Springdoc OpenAPI — автоматическая документация
- [ ] Flyway — миграции БД
- [ ] HikariCP — connection pooling
- [ ] Spring Boot Actuator — `/health`, `/metrics`, `/info`
- [ ] `@PreAuthorize` — RBAC, метод-level security
- [ ] gRPC сервер для Go Gateway (сохранение сообщений, проверка прав)
- [ ] Redis Session (Spring Session)

**Характеристики**:
- RAM: ~200–300 МБ
- Зависимости: Spring Boot 3.2+, Spring Security, Spring Data JPA, Flyway, HikariCP

#### 3. Python — LLM Service
**Задача**: AI/ML — всё, что требует Python-экосистему
- [ ] FastAPI — HTTP/gRPC endpoints
- [ ] LangChain — Function Calling, Tools, Agents
- [ ] RAG pipeline — embeddings + vector store (FAISS / Pinecone / Weaviate)
- [ ] Summarization — LLM-суммаризация чата
- [ ] Moderation — проверка на токсичность, spam
- [ ] Chat bot — AI-участник чата
- [ ] Sentence-transformers — локальные embeddings (опционально)
- [ ] gRPC клиент для Go и Java

**Характеристики**:
- RAM: ~500 МБ – 2 ГБ (зависит от модели)
- Зависимости: FastAPI, LangChain, OpenAI/Anthropic SDK, sentence-transformers, FAISS

#### 4. Redis
**Задача**: кэш, pub/sub, сессии, rate limiting, presence
- [ ] Pub/Sub — синхронизация WebSocket-гейтвеев в кластере
- [ ] Session store — Spring Session
- [ ] Rate limiting — счётчики per-user per-window
- [ ] Presence — online/offline статусы
- [ ] Cache — кэш часто читаемых данных (профили, конфиги)

#### 5. PostgreSQL
**Задача**: персистентность — пользователи, сообщения, конфиги
- [ ] Таблицы из Фазы 2 (users, messages, sessions)
- [ ] Индексы по `sender_id`, `timestamp`, `recipient_id`
- [ ] Partitioning по времени для `messages` (при больших объёмах)
- [ ] Read replicas (при необходимости)

### Коммуникация между сервисами

```
┌────────────────────────────────────────────────────────────────┐
│                         Clients                                 │
└───────────────┬────────────────────────────┬───────────────────┘
                │ WebSocket (wss://)          │ REST/gRPC
                ▼                             ▼
    ┌──────────────────────┐      ┌──────────────────────────┐
    │  Go — WS Gateway     │      │  Java — Backend API       │
    │                      │      │                           │
    │ • WebSocket relay    │◄────►│ • Users, Messages, Rooms  │
    │ • JWT validation     │ gRPC │ • Auth (Spring Security)  │
    │ • Rate limiting      │      │ • REST API + OpenAPI      │
    │ • Presence           │      │ • Spring Data JPA         │
    │                      │      │ • Actuator / metrics      │
    └───────┬──────────────┘      └───────────┬──────────────┘
            │ gRPC                            │ Hibernate
            ▼                                 ▼
    ┌──────────────────────┐      ┌──────────────────────────┐
    │  Python — LLM         │      │  PostgreSQL               │
    │                      │      │                           │
    │ • Summarization       │      │ • users                   │
    │ • Moderation          │      │ • messages                │
    │ • RAG / Chat bot      │      │ • sessions                │
    │ • LangChain Tools     │      │ • direct_messages         │
    └──────────────────────┘      └──────────────────────────┘
            │                              │
            └──────────┬───────────────────┘
                       ▼
              ┌──────────────────┐
              │  Redis            │
              │                   │
              │ • Pub/Sub          │
              │ • Session cache    │
              │ • Rate limit       │
              │ • Presence         │
              └──────────────────┘
```

### Инфраструктура
- [ ] Kubernetes — Deployment, Service, Ingress, HPA для каждого сервиса
- [ ] Docker Compose — для локальной разработки
- [ ] CI/CD — GitHub Actions: build → test → push → deploy
- [ ] Observability:
  - Prometheus + Grafana — метрики
  - Jaeger/Zipkin — distributed tracing
  - ELK/ Loki — логи
- [ ] Secrets management — Kubernetes Secrets / Vault
- [ ] TLS — Ingress с cert-manager

### Характеристики
- Масштаб: 100K+ conn (несколько Go-гейтвеев)
- RAM: ~10 МБ × N гейтвеев + ~300 МБ Java + ~1 ГБ Python + ~500 МБ Redis/PostgreSQL
- Высокая доступность: каждый сервис горизонтально реплицируется

---

## Сравнение фаз

| Параметр | Фаза 1 | Фаза 2 | Фаза 3 |
|----------|--------|--------|--------|
| **Сервисы** | 1 (Go) | 1 (Go) + БД | 3 + Redis + PostgreSQL |
| **RAM** | ~10 МБ | ~400 МБ | ~2–3 ГБ |
| **Conn** | 10K–50K | 10K–50K | 100K+ (кластер) |
| **БД** | Нет | PostgreSQL | PostgreSQL |
| **Auth** | Нет | JWT | OAuth2, SSO, LDAP |
| **API** | WebSocket | WS + REST | WS + REST + gRPC |
| **LLM** | Нет | HTTP к Python | gRPC, RAG, Tools |
| **Деплой** | `.exe` | Docker Compose | Kubernetes |
| **Команда** | 1 человек | 1–2 человека | 3+ человек |
| **Время** | Сейчас | 2–4 недели | 2–3 месяца |

---

## Принципы

1. **Не делать фазу 3 пока нет триггеров** — каждый переход стоит месяцы разработки «на всякий случай»
2. **Go-код не переписывается** — при переходе на Фазу 3 вы *выносите* бизнес-логику из Go в Java, а Go остаётся гейтвеем (тем, что он уже умеет)
3. **PostgreSQL с Фазы 2** — единственная БД, которая работает и в монолите, и в кластере без миграции
4. **LLM всегда на Python** — вся ML-экосистема создана на Python, Go/Java вызывают его как сервис
