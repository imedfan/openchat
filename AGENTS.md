# AGENTS.md — OpenChat

## Команды

```bash
python server.py [порт]   # по умолчанию 5000
python client.py
```

## Зависимости

`pip install textual`

## Архитектура

- **server.py**: TCP-сервер, один поток на клиента, broadcast через `threading.Lock`
- **client.py**: Textual TUI, два экрана (логин → чат), демон-поток для приёма

## Протокол (JSON поверх TCP)

| Тип | Направление | Поля |
|-----|--------------|------|
| `connect` | C→S | `type`, `username` |
| `connected` | S→C | `type`, `client_id`, `participant_count` |
| `message` | C→S | `type`, `content`, `message_id` |
| `ack` | S→C | `type`, `message_id` |
| `system` | S→C | `type`, `message`, `timestamp` (join/leave) |
| `participants` | S→C | `type`, `count`, `participants[]` |

## Константы

- `BUFFER_SIZE = 4096`
- `MAX_MESSAGES = 100` (история в deque)
- `DEFAULT_PORT = 5000`
- `DEFAULT_IP = "127.0.0.1"`

## Логи

`client.log`, `server.log` — в рабочей директории

## Ключевые места в коде

| Задача | Файл | Функция |
|--------|------|---------|
| Обработка сообщений | server.py | `handle_client()` |
| Broadcast | server.py | `broadcast()` |
| Приём сообщений | client.py | `receive_messages()` UI через `call_from_thread()` |
| UI обновление | client.py | `update_messages_display()` |

## Тесты

Нет. При добавлении: `pytest tests/`