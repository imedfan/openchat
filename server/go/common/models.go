package common

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"time"

	"github.com/fsnotify/fsnotify"
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

// ModelsReady возвращает true только если все модели имеют все 4 заполненных поля
func ModelsReady(models []ModelConfig) bool {
	return validateModels(models) == nil && len(models) > 0
}

// WatchModels отслеживает изменения файла моделей и возвращает канал для уведомлений
func WatchModels(path string, done <-chan struct{}) (<-chan []ModelConfig, <-chan error, error) {
	absPath, err := filepath.Abs(path)
	if err != nil {
		return nil, nil, fmt.Errorf("resolve path: %w", err)
	}

	watcher, err := fsnotify.NewWatcher()
	if err != nil {
		return nil, nil, fmt.Errorf("create watcher: %w", err)
	}

	modelsCh := make(chan []ModelConfig, 1)
	errCh := make(chan error, 1)

	// Загружаем текущую версию
	models, err := LoadModels(absPath)
	if err != nil {
		// Не блокируем — отправляем ошибку, но продолжаем мониторинг
		select {
		case errCh <- err:
		default:
		}
	} else {
		select {
		case modelsCh <- models:
		default:
		}
	}

	// Начинаем наблюдение за директорией файла
	dir := filepath.Dir(absPath)
	if err := watcher.Add(dir); err != nil {
		watcher.Close()
		return nil, nil, fmt.Errorf("watch directory: %w", err)
	}

	go func() {
		defer watcher.Close()
		debounceTimer := time.NewTimer(0)
		<-debounceTimer.C // первый тик сразу

		for {
			select {
			case <-done:
				return
			case event, ok := <-watcher.Events:
				if !ok {
					return
				}
				// Реагируем только на изменения целевого файла
				if filepath.Clean(event.Name) != absPath {
					continue
				}
				if event.Op&(fsnotify.Write|fsnotify.Create|fsnotify.Remove) == 0 {
					continue
				}

				// Debounce: ждём 500ms после последнего изменения
				if !debounceTimer.Stop() {
					select {
					case <-debounceTimer.C:
					default:
					}
				}
				debounceTimer.Reset(500 * time.Millisecond)

				select {
				case <-debounceTimer.C:
					// Файл изменился, перечитываем
					newModels, err := LoadModels(absPath)
					if err != nil {
						select {
						case errCh <- err:
						default:
						}
					} else {
						select {
						case modelsCh <- newModels:
						default:
						}
					}
				case <-done:
					return
				}
			case err, ok := <-watcher.Errors:
				if !ok {
					return
				}
				select {
				case errCh <- err:
				default:
				}
			}
		}
	}()

	return modelsCh, errCh, nil
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
