// roomd 是 LUNATICN 的独立轻量房间服务器。
//
// 玩家在自己电脑上运行它即可开设一个 Luanti 房间：
//  1. 拉起本机 luanti --server 进程；
//  2. 登录社区服务器并把房间注册到社区服务器列表；
//  3. 周期心跳上报人数，房间下线后自动从列表移除。
//
// 用法：
//
//	roomd -config config.json
package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"log"
	"net"
	"os"
	"os/signal"
	"syscall"
	"time"

	"lunaticn/roomd/internal/proc"
	"lunaticn/roomd/internal/regclient"
)

// Config roomd 配置文件（config.json，UTF-8 编码）。
type Config struct {
	Registry    string `json:"registry"`     // 社区服务器地址，如 https://lunaticn.example.com
	Username    string `json:"username"`     // 社区账号
	Password    string `json:"password"`     // 社区密码
	RoomName    string `json:"room_name"`    // 房间显示名
	LuantiPath  string `json:"luanti_path"`  // luanti.exe 路径
	World       string `json:"world"`        // 世界路径（--world）
	WorldName   string `json:"worldname"`    // 世界名（--worldname），二选一
	GameID      string `json:"gameid"`       // 游戏 ID
	Port        int    `json:"port"`         // 游戏端口
	MaxPlayers  int    `json:"max_players"`  // 人数上限
	Host        string `json:"host"`         // 对外地址；留空自动探测本机局域网 IP
	HasPassword bool   `json:"has_password"` // 房间是否需要密码
	Private     bool   `json:"private"`      // 仅好友可见
	Description string `json:"description"`  // 房间简介
	ConfigFile  string `json:"config_file"`  // 可选 minetest.conf 路径
}

func loadConfig(path string) (*Config, error) {
	b, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("读取配置失败: %w", err)
	}
	var c Config
	if err := json.Unmarshal(b, &c); err != nil {
		return nil, fmt.Errorf("配置解析失败（请确认是 UTF-8 的 JSON）: %w", err)
	}
	if c.Registry == "" || c.Username == "" {
		return nil, fmt.Errorf("配置缺少 registry 或 username")
	}
	if c.LuantiPath == "" {
		return nil, fmt.Errorf("配置缺少 luanti_path")
	}
	if c.RoomName == "" {
		return nil, fmt.Errorf("配置缺少 room_name")
	}
	if c.Port <= 0 {
		c.Port = 30000
	}
	if c.MaxPlayers <= 0 {
		c.MaxPlayers = 8
	}
	return &c, nil
}

// detectHost 自动探测本机局域网 IP（UDP 拨号不实际发包）。
func detectHost() string {
	conn, err := net.Dial("udp", "8.8.8.8:53")
	if err != nil {
		return "127.0.0.1"
	}
	defer conn.Close()
	if addr, ok := conn.LocalAddr().(*net.UDPAddr); ok {
		return addr.IP.String()
	}
	return "127.0.0.1"
}

func main() {
	cfgPath := flag.String("config", "config.json", "配置文件路径")
	flag.Parse()
	log.SetFlags(log.Ltime)

	cfg, err := loadConfig(*cfgPath)
	if err != nil {
		log.Fatalf("[roomd] %v", err)
	}
	host := cfg.Host
	if host == "" {
		host = detectHost()
	}

	// 1. 登录社区服务器
	rc := regclient.New(cfg.Registry)
	ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
	token, err := rc.Login(ctx, cfg.Username, cfg.Password)
	cancel()
	if err != nil {
		log.Fatalf("[roomd] 登录社区服务器失败: %v", err)
	}
	log.Printf("[roomd] 已登录社区服务器 %s", cfg.Registry)

	// 2. 启动 luanti 服务器进程
	args := []string{"--server", "--port", fmt.Sprint(cfg.Port)}
	if cfg.World != "" {
		args = append(args, "--world", cfg.World)
	}
	if cfg.WorldName != "" {
		args = append(args, "--worldname", cfg.WorldName)
	}
	if cfg.GameID != "" {
		args = append(args, "--gameid", cfg.GameID)
	}
	if cfg.ConfigFile != "" {
		args = append(args, "--config", cfg.ConfigFile)
	}
	engine := proc.New(cfg.LuantiPath, args)
	if err := engine.Start(); err != nil {
		log.Fatalf("[roomd] 启动 Luanti 失败: %v", err)
	}
	log.Printf("[roomd] Luanti 服务器已启动 (端口 %d, PID %d)", cfg.Port, engine.PID())

	// 3. 注册房间
	roomToken, roomID, err := rc.Register(ctx, token, regclient.RoomInfo{
		Name:        cfg.RoomName,
		Host:        host,
		Port:        cfg.Port,
		GameID:      cfg.GameID,
		World:       cfg.WorldName,
		MaxPlayers:  cfg.MaxPlayers,
		HasPassword: cfg.HasPassword,
		Private:     cfg.Private,
		Source:      "roomd",
		Description: cfg.Description,
	})
	if err != nil {
		log.Printf("[roomd] 房间注册失败: %v（仍会继续开服，可稍后重试）", err)
	}
	if roomID != "" {
		log.Printf("[roomd] 房间已上架社区服务器列表: %s", cfg.RoomName)
	}

	// 4. 心跳 + 人数上报（人数由进程输出解析）
	stopHB := make(chan struct{})
	go func() {
		t := time.NewTicker(15 * time.Second)
		defer t.Stop()
		for {
			select {
			case <-t.C:
				cctx, ccancel := context.WithTimeout(context.Background(), 10*time.Second)
				if err := rc.Heartbeat(cctx, token, roomToken, engine.Players()); err != nil {
					log.Printf("[roomd] 心跳失败: %v", err)
				}
				ccancel()
			case <-stopHB:
				return
			}
		}
	}()

	// 5. 等待退出信号或进程结束
	sigCh := make(chan os.Signal, 1)
	signal.Notify(sigCh, syscall.SIGINT, syscall.SIGTERM)
	select {
	case sig := <-sigCh:
		log.Printf("[roomd] 收到信号 %v，正在关闭…", sig)
	case <-engine.Done():
		log.Printf("[roomd] Luanti 进程已退出")
	}

	// 6. 清理：注销房间、停止进程
	close(stopHB)
	if roomToken != "" {
		cctx, ccancel := context.WithTimeout(context.Background(), 5*time.Second)
		if err := rc.Unregister(cctx, token, roomToken); err != nil {
			log.Printf("[roomd] 注销房间失败: %v", err)
		}
		ccancel()
	}
	engine.Stop()
	log.Println("[roomd] 已退出")
}
