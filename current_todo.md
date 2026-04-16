# Current TODO — 16.04.2026

## ✅ Выполненные задачи

### 1. Удалить дублирующий go.mod в корне проекта (C:\dev\auc\go.mod)
**Статус:** ✅ ВЫПОЛНЕНО
- `C:\dev\auc\go.mod` удалён
- `build_server.bat` исправлен — собирает из `server/go/`

### 2. Частые disconnect: websocket close 1006 (abnormal closure)
**Статус:** ✅ ВЫПОЛНЕНО (с исправлениями)
- Добавлен heartbeat/ping-pong в Go сервер (`server/go/server/handler.go`)
- Добавлен heartbeat в Python клиент (`client/python/openchatpy/ws_client.py`)
- **Исправлено:** Синтаксическая ошибка (лишняя `)`) в `SetPingHandler` — теперь компилируется

### 3. Исправить BadIdentifier ошибку для моделей в Participants
**Статус:** ✅ ВЫПОЛНЕНО (с исправлениями)
- Добавлена функция `sanitize_id()` в `app.py`
- **Исправлено:** `new_ids` в `update_contacts_list()` теперь использует `sanitize_id()`
- **Исправлено:** `add_chat_tab_model()` теперь санитизирует tab_id
- **Исправлено:** `on_list_view_selected()` и `on_tabs_tab_activated()` теперь корректно восстанавливают оригинальный model_id через `_find_original_model_id()`

---

## 🆕 Новые задачи для исполнителя

### 4. Улучшить логирование отключений на стороне Go сервера
**Проблема:** При отключении клиента не всегда понятно причина (timeout, closed by client, network error)
**Решение:**
- [ ] В `server/go/server/handler.go` добавить проверку `*websocket.CloseError` в блоке обработки ошибок чтения
- [ ] Логировать код и текст закрытия соединения
- [ ] Пример:
```go
if websocket.IsUnexpectedCloseError(err, websocket.CloseGoingAway, websocket.CloseNormalClosure) {
    var closeErr *websocket.CloseError
    if errors.As(err, &closeErr) {
        log.Printf("Client %d disconnected: code=%d reason=%s", clientID, closeErr.Code, closeErr.Text)
    }
}
```

### 5. Протестировать heartbeat механизм
**Проблема:** Heartbeat добавлен, но не протестирован в реальных условиях
**Решение:**
- [ ] Запустить сервер и клиент, подождать 1+ минуту без активности
- [ ] Проверить что соединение не рвётся
- [ ] Проверить в логах что ping/pong работают (можно добавить временное debug-логирование)
- [ ] Убедиться что `builds/YYYY-MM-DD/openchat-server.exe` запускается без ошибок

### 6. Добавить unit-тесты для `sanitize_id()`
**Проблема:** Функция `sanitize_id()` критична для стабильности UI, но не покрыта тестами
**Решение:**
- [ ] Создать `client/python/openchatpy/tests/test_sanitize_id.py`
- [ ] Протестировать кейсы:
  - `qwen3.5-9b` → `qwen3_5_9b`
  - `.hidden-model` → `_hidden_model`
  - `123model` → `id_123model`
  - `""` → `id_empty`
  - `normal_model` → `normal_model`

### 7. (Опционально) Улучшить обработку pong в Python клиенте
**Проблема:** `websockets` библиотека обрабатывает ping/pong автоматически, ручное назначение `pong_received` может быть неэффективно
**Решение:**
- [ ] Изучить документацию `websockets` для версии используемой в проекте
- [ ] Если `ping()` уже жёт pong автоматически — убрать ручной `_handle_pong`
- [ ] Оставить только периодический `ping()` для поддержания соединения

---

## 📝 Примечания
- Все изменения в `app.py` требуют проверки на обратной совместимости с существующими моделями
- При сборке сервера убедиться что `go.mod` в `server/go/` содержит все зависимости
- Heartbeat интервал: 30 секунд ping, 60 секунд read deadline
