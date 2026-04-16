"""
Загрузка и валидация личных моделей пользователя из models_user.json.
"""

import json
import os
import logging
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

REQUIRED_FIELDS = ["id", "name", "envKey", "baseUrl"]
DEFAULT_USER_MODELS_PATH = os.path.join(os.path.dirname(__file__), "models_user.json")
USER_MODELS_EXAMPLE_PATH = os.path.join(os.path.dirname(__file__), "models_user.json.example")


class UserModelError(Exception):
    """Ошибка загрузки пользовательских моделей."""
    pass


def load_user_models(path: Optional[str] = None) -> List[Dict]:
    """
    Загружает и валидирует личные модели пользователя.
    
    Возвращает пустой список если файл отсутствует или невалиден.
    """
    path = path or DEFAULT_USER_MODELS_PATH
    
    if not os.path.exists(path):
        logger.debug(f"User models file not found: {path}")
        return []
    
    try:
        with open(path, "r", encoding="utf-8") as f:
            models = json.load(f)
    except json.JSONDecodeError as e:
        logger.warning(f"Invalid JSON in user models file: {e}")
        return []
    except OSError as e:
        logger.warning(f"Cannot read user models file: {e}")
        return []
    
    if not isinstance(models, list):
        logger.warning("User models file must contain a JSON array")
        return []
    
    return validate_user_models(models)


def validate_user_models(models: List[Dict]) -> List[Dict]:
    """
    Валидирует модели и возвращает только корректные.
    В отличие от сервера, не бросает ошибку — просто пропускает невалидные.
    """
    valid = []
    for i, m in enumerate(models):
        if not isinstance(m, dict):
            logger.warning(f"User model[{i}] is not a dict, skipping")
            continue
        
        missing = [f for f in REQUIRED_FIELDS if not m.get(f)]
        if missing:
            model_id = m.get("id", f"index_{i}")
            logger.warning(f"User model '{model_id}': missing fields {missing}, skipping")
            continue
        
        valid.append(m)
    
    return valid


def user_models_ready(models: List[Dict]) -> bool:
    """Возвращает True если есть хотя бы одна валидная модель."""
    if models is None:
        return False
    return len(models) > 0


def create_default_user_models(path: Optional[str] = None) -> str:
    """
    Создаёт файл с примером конфигурации если его нет.
    Возвращает путь к файлу.
    """
    path = path or DEFAULT_USER_MODELS_PATH
    
    if os.path.exists(path):
        return path
    
    example = [
        {
            "id": "my-custom-model",
            "name": "My Model",
            "envKey": "MY_API_KEY",
            "baseUrl": "http://localhost:1234/v1"
        }
    ]
    
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(example, f, indent=2, ensure_ascii=False)
        logger.info(f"Created default user models file: {path}")
    except OSError as e:
        logger.warning(f"Cannot create user models file: {e}")
    
    return path
