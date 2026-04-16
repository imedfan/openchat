"""Тесты для model_loader.py."""

import json
import os
import tempfile
import unittest
import sys

# Добавляем корень openchatpy в sys.path
_current_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.dirname(_current_dir)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from model_loader import (
    load_user_models,
    validate_user_models,
    user_models_ready,
    create_default_user_models,
)


class TestLoadUserModels(unittest.TestCase):

    def test_load_valid_file(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump([
                {"id": "m1", "name": "local", "envKey": "K", "baseUrl": "http://x/v1"}
            ], f)
            path = f.name
        try:
            models = load_user_models(path)
            self.assertEqual(len(models), 1)
            self.assertEqual(models[0]["id"], "m1")
        finally:
            os.unlink(path)

    def test_load_nonexistent_file(self):
        models = load_user_models("/nonexistent/path/file.json")
        self.assertEqual(models, [])

    def test_load_invalid_json(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            f.write("{ invalid json }")
            path = f.name
        try:
            models = load_user_models(path)
            self.assertEqual(models, [])
        finally:
            os.unlink(path)

    def test_load_not_array(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump({"id": "m1"}, f)
            path = f.name
        try:
            models = load_user_models(path)
            self.assertEqual(models, [])
        finally:
            os.unlink(path)


class TestValidateUserModels(unittest.TestCase):

    def test_all_valid(self):
        models = [
            {"id": "m1", "name": "local", "envKey": "K", "baseUrl": "http://x/v1"},
        ]
        valid = validate_user_models(models)
        self.assertEqual(len(valid), 1)

    def test_skips_invalid(self):
        models = [
            {"id": "m1", "name": "local", "envKey": "K", "baseUrl": "http://x/v1"},
            {"id": "m2"},  # missing fields
            "not a dict",
        ]
        valid = validate_user_models(models)
        self.assertEqual(len(valid), 1)
        self.assertEqual(valid[0]["id"], "m1")

    def test_empty_list(self):
        valid = validate_user_models([])
        self.assertEqual(valid, [])


class TestUserModelsReady(unittest.TestCase):

    def test_ready(self):
        self.assertTrue(user_models_ready([{"id": "m1"}]))

    def test_not_ready_empty(self):
        self.assertFalse(user_models_ready([]))

    def test_not_ready_none(self):
        self.assertFalse(user_models_ready(None))


class TestCreateDefaultUserModels(unittest.TestCase):

    def test_creates_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "models_user.json")
            result = create_default_user_models(path)
            self.assertEqual(result, path)
            self.assertTrue(os.path.exists(path))

            models = load_user_models(path)
            self.assertEqual(len(models), 1)

    def test_does_not_overwrite(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "models_user.json")
            # Создаём валидную модель вручную
            with open(path, 'w') as f:
                json.dump([{"id": "custom", "name": "Custom", "envKey": "K", "baseUrl": "http://x/v1"}], f)

            result = create_default_user_models(path)
            self.assertEqual(result, path)

            models = load_user_models(path)
            self.assertEqual(len(models), 1)
            self.assertEqual(models[0]["id"], "custom")


if __name__ == "__main__":
    unittest.main()
