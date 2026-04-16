package common

import (
	"encoding/json"
	"fmt"
	"os"
)

// ModelConfig — конфигурация одной LLM-модели
type ModelConfig struct {
	ID      string `json:"id"`      // Уникальный идентификатор модели, напр. "qwen3.5-9b-sushi-coder-rl"
	Name    string `json:"name"`    // Отображаемое имя, напр. "local"
	EnvKey  string `json:"envKey"`  // Имя переменной окружения с API ключом, напр. "OPENCODE_API_KEY"
	BaseURL string `json:"baseUrl"` // Base URL API, напр. "http://192.168.0.2:1234/v1"
}

// LoadModels загружает и валидирует конфигурацию моделей из JSON файла
func LoadModels(path string) ([]ModelConfig, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("read models config: %w", err)
	}

	var models []ModelConfig
	if err := json.Unmarshal(data, &models); err != nil {
		return nil, fmt.Errorf("parse models config: %w", err)
	}

	if err := validateModels(models); err != nil {
		return nil, err
	}

	return models, nil
}

// validateModels проверяет обязательные поля у каждой модели
func validateModels(models []ModelConfig) error {
	for i, m := range models {
		if m.ID == "" {
			return fmt.Errorf("model[%d]: missing required field 'id'", i)
		}
		if m.Name == "" {
			return fmt.Errorf("model[%d] '%s': missing required field 'name'", i, m.ID)
		}
		if m.EnvKey == "" {
			return fmt.Errorf("model[%d] '%s': missing required field 'envKey'", i, m.ID)
		}
		if m.BaseURL == "" {
			return fmt.Errorf("model[%d] '%s': missing required field 'baseUrl'", i, m.ID)
		}
	}
	return nil
}
