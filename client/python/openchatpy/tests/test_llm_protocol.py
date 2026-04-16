"""
Интеграционные тесты для LLM-функциональности Python клиента.
"""

import json
import pytest
import sys
import os

# Добавляем корень openchatpy в sys.path (для импорта protocol)
# __file__ = tests/test_llm_protocol.py → os.path.dirname → tests/ → ещё раз → openchatpy/
_current_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.dirname(_current_dir)  # папка openchatpy/
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

# Импортируем из модуля protocol (теперь он должен быть доступен)
from protocol import (
    MSG_LLM_MODELS, MSG_LLM_CHUNK, MSG_LLM_ERROR, MSG_LLM_REQUEST,
    make_llm_request,
)


class TestLLMProtocol:
    """Тесты LLM-протокола."""

    def test_make_llm_request(self):
        messages = [
            {"role": "user", "content": "Hello"},
        ]
        payload = make_llm_request("test-model", messages)
        data = json.loads(payload)

        assert data["type"] == MSG_LLM_REQUEST
        assert data["model_id"] == "test-model"
        assert data["messages"] == messages

    def test_make_llm_request_multiple_messages(self):
        messages = [
            {"role": "system", "content": "You are helpful"},
            {"role": "user", "content": "Hi"},
            {"role": "assistant", "content": "Hello!"},
            {"role": "user", "content": "How are you?"},
        ]
        payload = make_llm_request("my-model", messages)
        data = json.loads(payload)

        assert len(data["messages"]) == 4
        assert data["messages"][0]["role"] == "system"
        assert data["messages"][-1]["content"] == "How are you?"

    def test_parse_llm_models_response(self):
        raw = json.dumps({
            "type": MSG_LLM_MODELS,
            "models": [
                {"id": "model-1", "name": "local"},
                {"id": "model-2", "name": "cloud"},
            ]
        })
        data = json.loads(raw)

        assert data["type"] == MSG_LLM_MODELS
        assert len(data["models"]) == 2
        assert data["models"][0]["id"] == "model-1"
        assert data["models"][1]["name"] == "cloud"

    def test_parse_llm_chunk(self):
        raw = json.dumps({
            "type": MSG_LLM_CHUNK,
            "model_id": "test-model",
            "chunk": "Hello",
            "done": False,
        })
        data = json.loads(raw)

        assert data["type"] == MSG_LLM_CHUNK
        assert data["model_id"] == "test-model"
        assert data["chunk"] == "Hello"
        assert data["done"] is False

    def test_parse_llm_chunk_done(self):
        raw = json.dumps({
            "type": MSG_LLM_CHUNK,
            "model_id": "test-model",
            "chunk": "",
            "done": True,
        })
        data = json.loads(raw)

        assert data["done"] is True

    def test_parse_llm_error(self):
        raw = json.dumps({
            "type": MSG_LLM_ERROR,
            "model_id": "test-model",
            "error": "API key invalid",
        })
        data = json.loads(raw)

        assert data["type"] == MSG_LLM_ERROR
        assert data["model_id"] == "test-model"
        assert "API key" in data["error"]
