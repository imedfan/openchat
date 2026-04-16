package main

import (
	"flag"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"os/signal"
	"syscall"

	"github.com/gorilla/websocket"
	"openchat-server/common"
	"openchat-server/server"
)

var upgrader = websocket.Upgrader{
	ReadBufferSize:  common.BufferSize,
	WriteBufferSize: common.BufferSize,
	CheckOrigin: func(r *http.Request) bool {
		return true // Разрешаем все origins (для локального чата ок)
	},
}

func main() {
	// Парсинг аргументов CLI
	port := flag.Int("port", common.DefaultPort, "Port to listen on")
	modelsFile := flag.String("models", "models.json", "Path to LLM models config file")
	flag.Parse()

	// Настройка логирования
	log.SetFlags(log.Ldate | log.Ltime | log.Lmicroseconds)
	logFile, err := os.OpenFile("server.log", os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0666)
	if err == nil {
		multiWriter := io.MultiWriter(os.Stdout, logFile)
		log.SetOutput(multiWriter)
		defer logFile.Close()
	}

	// Загрузка конфигурации LLM-моделей
	models, err := common.LoadModels(*modelsFile)
	if err != nil {
		log.Printf("Warning: failed to load LLM models config: %v (LLM features will be disabled)", err)
		models = []common.ModelConfig{}
	} else {
		log.Printf("Loaded %d LLM model(s):", len(models))
		for _, m := range models {
			log.Printf("  - %s (%s) @ %s", m.ID, m.Name, m.BaseURL)
		}
	}

	// Создание сервера
	chatServer := server.NewChatServer(common.DefaultHost, *port, models)

	// Горячая перезагрузка моделей
	modelsDone := make(chan struct{})
	modelsCh, modelsErrCh, watchErr := common.WatchModels(*modelsFile, modelsDone)
	if watchErr != nil {
		log.Printf("Warning: failed to watch models file: %v (hot reload disabled)", watchErr)
	} else {
		go func() {
			for {
				select {
				case newModels := <-modelsCh:
					log.Printf("Models file changed, reloading %d model(s)...", len(newModels))
					chatServer.UpdateModels(newModels)
				case err := <-modelsErrCh:
					log.Printf("Models watch error: %v", err)
				case <-modelsDone:
					return
				}
			}
		}()
	}

	// Получение IP для отображения
	publicIP := server.GetPublicIP()

	// Вывод информации о запуске
	fmt.Println("\n==================================================")
	fmt.Println("  OpenChat Server (WebSocket) — Go Edition")
	fmt.Println("==================================================")
	fmt.Printf("  Listening on: %s:%d\n", common.DefaultHost, *port)
	fmt.Printf("  Public IP:    %s\n", publicIP)
	fmt.Printf("  Connect to:   ws://%s:%d\n", publicIP, *port)
	fmt.Println("==================================================")

	// WebSocket handler
	http.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		conn, err := upgrader.Upgrade(w, r, nil)
		if err != nil {
			log.Printf("WebSocket upgrade error: %v", err)
			return
		}
		go chatServer.HandleClient(conn)
	})

	// Graceful shutdown
	go func() {
		sigChan := make(chan os.Signal, 1)
		signal.Notify(sigChan, syscall.SIGINT, syscall.SIGTERM)
		<-sigChan
		fmt.Println("\n\n==================================================")
		fmt.Println("  OpenChat Server shutting down...")
		fmt.Println("  Goodbye! See you next time!")
		fmt.Println("==================================================")
		os.Exit(0)
	}()

	// Запуск сервера
	addr := fmt.Sprintf("%s:%d", common.DefaultHost, *port)
	log.Printf("Server starting on %s", addr)
	if err := http.ListenAndServe(addr, nil); err != nil {
		log.Fatalf("Server failed to start: %v", err)
	}
}
