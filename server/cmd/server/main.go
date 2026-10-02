// LUNATICN 社区服务端入口。
//
// 职责：账号认证、好友、房间注册中心（roomd/启动器都注册到此）、
// 地图与模组分享、固定服务器守护、WebSocket 实时推送。
//
// 用法：
//
//	go run ./cmd/server -config config.json
package main

import (
	"context"
	"errors"
	"flag"
	"log"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"lunaticn/server/internal/api"
	"lunaticn/server/internal/config"
	"lunaticn/server/internal/fixedserver"
	"lunaticn/server/internal/lobby"
	"lunaticn/server/internal/packages"
	"lunaticn/server/internal/store"
)

func main() {
	cfgPath := flag.String("config", "config.json", "配置文件路径")
	flag.Parse()

	cfg, err := config.Load(*cfgPath)
	if err != nil {
		log.Fatalf("加载配置失败: %v", err)
	}
	dataDir, err := cfg.AbsDataDir()
	if err != nil {
		log.Fatalf("准备数据目录失败: %v", err)
	}

	st, err := store.Open(dataDir)
	if err != nil {
		log.Fatalf("打开存储失败: %v", err)
	}

	hub := lobby.NewHub()
	stopSweep := make(chan struct{})
	go hub.RunSweeper(stopSweep)

	pkgs := packages.NewService(st, dataDir, 512)
	fixed := fixedserver.NewManager()
	if len(cfg.FixedServers) > 0 {
		fixed.StartAll(cfg.FixedServers)
	}

	srv := api.New(cfg, st, hub, pkgs, fixed)

	httpSrv := &http.Server{
		Addr:              cfg.Listen,
		Handler:           srv.Handler(),
		ReadHeaderTimeout: 10 * time.Second,
	}

	go func() {
		log.Printf("LUNATICN 社区服务端启动: %s (数据目录 %s)", cfg.Listen, dataDir)
		if err := httpSrv.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
			log.Fatalf("服务监听失败: %v", err)
		}
	}()

	// 优雅退出
	quit := make(chan os.Signal, 1)
	signal.Notify(quit, syscall.SIGINT, syscall.SIGTERM)
	<-quit
	log.Println("正在关闭…")
	close(stopSweep)
	fixed.StopAll()
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	_ = httpSrv.Shutdown(ctx)
}
