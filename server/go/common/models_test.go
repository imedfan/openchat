package common

import (
	"os"
	"path/filepath"
	"testing"
)

func TestLoadModels_ValidFile(t *testing.T) {
	tmpDir := t.TempDir()
	path := filepath.Join(tmpDir, "models.json")
	content := `[
		{"id": "model-1", "name": "local", "envKey": "API_KEY", "baseUrl": "http://localhost:8080/v1"}
	]`
	if err := os.WriteFile(path, []byte(content), 0644); err != nil {
		t.Fatal(err)
	}

	models, err := LoadModels(path)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(models) != 1 {
		t.Fatalf("expected 1 model, got %d", len(models))
	}
	if models[0].ID != "model-1" {
		t.Errorf("expected id 'model-1', got '%s'", models[0].ID)
	}
	if models[0].Name != "local" {
		t.Errorf("expected name 'local', got '%s'", models[0].Name)
	}
	if models[0].EnvKey != "API_KEY" {
		t.Errorf("expected envKey 'API_KEY', got '%s'", models[0].EnvKey)
	}
	if models[0].BaseURL != "http://localhost:8080/v1" {
		t.Errorf("expected baseUrl 'http://localhost:8080/v1', got '%s'", models[0].BaseURL)
	}
}

func TestLoadModels_MultipleModels(t *testing.T) {
	tmpDir := t.TempDir()
	path := filepath.Join(tmpDir, "models.json")
	content := `[
		{"id": "m1", "name": "local", "envKey": "K1", "baseUrl": "http://a/v1"},
		{"id": "m2", "name": "cloud", "envKey": "K2", "baseUrl": "http://b/v1"}
	]`
	if err := os.WriteFile(path, []byte(content), 0644); err != nil {
		t.Fatal(err)
	}

	models, err := LoadModels(path)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(models) != 2 {
		t.Fatalf("expected 2 models, got %d", len(models))
	}
}

func TestLoadModels_EmptyArray(t *testing.T) {
	tmpDir := t.TempDir()
	path := filepath.Join(tmpDir, "models.json")
	if err := os.WriteFile(path, []byte(`[]`), 0644); err != nil {
		t.Fatal(err)
	}

	models, err := LoadModels(path)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(models) != 0 {
		t.Fatalf("expected 0 models, got %d", len(models))
	}
}

func TestLoadModels_FileNotFound(t *testing.T) {
	_, err := LoadModels("/nonexistent/path/models.json")
	if err == nil {
		t.Fatal("expected error for nonexistent file, got nil")
	}
}

func TestLoadModels_InvalidJSON(t *testing.T) {
	tmpDir := t.TempDir()
	path := filepath.Join(tmpDir, "models.json")
	if err := os.WriteFile(path, []byte(`not valid json`), 0644); err != nil {
		t.Fatal(err)
	}

	_, err := LoadModels(path)
	if err == nil {
		t.Fatal("expected error for invalid JSON, got nil")
	}
}

func TestLoadModels_MissingID(t *testing.T) {
	tmpDir := t.TempDir()
	path := filepath.Join(tmpDir, "models.json")
	content := `[{"name": "local", "envKey": "K", "baseUrl": "http://x/v1"}]`
	if err := os.WriteFile(path, []byte(content), 0644); err != nil {
		t.Fatal(err)
	}

	_, err := LoadModels(path)
	if err == nil {
		t.Fatal("expected error for missing id, got nil")
	}
}

func TestLoadModels_MissingName(t *testing.T) {
	tmpDir := t.TempDir()
	path := filepath.Join(tmpDir, "models.json")
	content := `[{"id": "m1", "envKey": "K", "baseUrl": "http://x/v1"}]`
	if err := os.WriteFile(path, []byte(content), 0644); err != nil {
		t.Fatal(err)
	}

	_, err := LoadModels(path)
	if err == nil {
		t.Fatal("expected error for missing name, got nil")
	}
}

func TestLoadModels_MissingEnvKey(t *testing.T) {
	tmpDir := t.TempDir()
	path := filepath.Join(tmpDir, "models.json")
	content := `[{"id": "m1", "name": "local", "baseUrl": "http://x/v1"}]`
	if err := os.WriteFile(path, []byte(content), 0644); err != nil {
		t.Fatal(err)
	}

	_, err := LoadModels(path)
	if err == nil {
		t.Fatal("expected error for missing envKey, got nil")
	}
}

func TestLoadModels_MissingBaseURL(t *testing.T) {
	tmpDir := t.TempDir()
	path := filepath.Join(tmpDir, "models.json")
	content := `[{"id": "m1", "name": "local", "envKey": "K"}]`
	if err := os.WriteFile(path, []byte(content), 0644); err != nil {
		t.Fatal(err)
	}

	_, err := LoadModels(path)
	if err == nil {
		t.Fatal("expected error for missing baseUrl, got nil")
	}
}

func TestModelsReady_ValidModels(t *testing.T) {
	models := []ModelConfig{
		{ID: "m1", Name: "local", EnvKey: "K", BaseURL: "http://x/v1"},
	}
	if !ModelsReady(models) {
		t.Fatal("expected ModelsReady to return true for valid models")
	}
}

func TestModelsReady_EmptyArray(t *testing.T) {
	models := []ModelConfig{}
	if ModelsReady(models) {
		t.Fatal("expected ModelsReady to return false for empty array")
	}
}

func TestModelsReady_MissingField(t *testing.T) {
	models := []ModelConfig{
		{ID: "m1", Name: "local", EnvKey: "K"}, // missing BaseURL
	}
	if ModelsReady(models) {
		t.Fatal("expected ModelsReady to return false for model with missing field")
	}
}
