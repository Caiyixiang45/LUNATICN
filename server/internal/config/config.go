// Package config 负责加载服务端配置（JSON 格式，UTF-8 编码）。
package config

import (
	"bytes"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sync"
	"time"
)

// FixedServer 描述一台常驻固定服务器（由本服务端守护进程拉起）。
type FixedServer struct {
	Name   string `json:"name"`   // 房间显示名
	Bin    string `json:"bin"`    // luantiserver 可执行文件路径
	World  string `json:"world"`  // 世界路径
	GameID string `json:"gameid"` // 游戏 ID
	Config string `json:"config"` // 可选 minetest.conf 路径
	Port   int    `json:"port"`   // 监听端口
}

// Announcement 是一条客户端公告。
type Announcement struct {
	ID        string    `json:"id"`
	Title     string    `json:"title"`
	Body      string    `json:"body"`
	Level     string    `json:"level"`  // info | warning | update
	Pinned    bool      `json:"pinned"` // 是否置顶
	CreatedAt time.Time `json:"created_at"`
}

// ClientUpdate 是客户端更新推送信息。
type ClientUpdate struct {
	Version     string    `json:"version"` // 最新客户端版本，如 "1.1.0"
	Notes       string    `json:"notes"`   // 更新说明
	Mirrors     []string  `json:"mirrors"` // 更新包下载地址（按优先级排列，逐个兜底）
	PublishedAt time.Time `json:"published_at"`
}

// Config 是服务端总配置。
type Config struct {
	Listen          string         `json:"listen"`            // 监听地址，如 ":8080"
	DataDir         string         `json:"data_dir"`          // 数据目录
	JWTSecret       string         `json:"jwt_secret"`        // JWT 签名密钥
	TokenTTLMinutes int            `json:"token_ttl_minutes"` // 令牌有效期（分钟）
	PublicBase      string         `json:"public_base"`       // 下载链接前缀，如 https://api.example.com
	FixedServers    []FixedServer  `json:"fixed_servers"`     // 固定服务器列表
	AdminToken      string         `json:"admin_token"`       // 管理令牌：管理公告/更新推送时携带
	Announcements   []Announcement `json:"announcements"`     // 初始公告（首次启动写入 data/announcements.json）
	ClientUpdate    *ClientUpdate  `json:"client_update"`     // 初始更新推送（首次启动写入 data/client_update.json）
	ModsRepo        string         `json:"mods_repo"`         // 自托管模组仓库目录（相对路径按配置文件所在目录解析，Load 后为绝对路径）

	mu   sync.Mutex `json:"-"` // 保护 Save/AddFixedServer/RemoveFixedServer
	path string      `json:"-"` // 配置文件路径（Load 时记录）
}

// Load 读取配置文件，缺失字段填默认值。
func Load(path string) (*Config, error) {
	cfg := &Config{
		Listen:          ":8080",
		DataDir:         "data",
		TokenTTLMinutes: 60 * 24 * 7,
		ModsRepo:        "mods_repo",
	}
	b, err := os.ReadFile(path)
	if err != nil {
		if os.IsNotExist(err) {
			cfg.ModsRepo = resolveModsRepo(cfg.ModsRepo, path)
			cfg.path = path
			return cfg, nil
		}
		return nil, fmt.Errorf("读取配置失败: %w", err)
	}
	b = bytes.TrimPrefix(b, []byte{0xEF, 0xBB, 0xBF}) // 容忍 UTF-8 BOM
	if err := json.Unmarshal(b, cfg); err != nil {
		return nil, fmt.Errorf("解析配置失败: %w", err)
	}
	if cfg.Listen == "" {
		cfg.Listen = ":8080"
	}
	if cfg.DataDir == "" {
		cfg.DataDir = "data"
	}
	if cfg.TokenTTLMinutes <= 0 {
		cfg.TokenTTLMinutes = 60 * 24 * 7
	}
	if cfg.JWTSecret == "" {
		return nil, fmt.Errorf("配置缺少 jwt_secret，请在 config.json 中设置")
	}
	cfg.ModsRepo = resolveModsRepo(cfg.ModsRepo, path)
	cfg.path = path
	return cfg, nil
}

// Save 把当前配置写回加载时的配置文件（原子写：先 tmp 再改名）。
func (c *Config) Save() error {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.saveLocked()
}

// AddFixedServer 追加一台固定服务器并持久化。
func (c *Config) AddFixedServer(cf FixedServer) error {
	c.mu.Lock()
	defer c.mu.Unlock()
	for _, x := range c.FixedServers {
		if x.Name == cf.Name {
			return fmt.Errorf("固定服务器 %q 已存在", cf.Name)
		}
	}
	c.FixedServers = append(c.FixedServers, cf)
	if err := c.saveLocked(); err != nil {
		c.FixedServers = c.FixedServers[:len(c.FixedServers)-1]
		return err
	}
	return nil
}

// RemoveFixedServer 删除一台固定服务器并持久化。
func (c *Config) RemoveFixedServer(name string) error {
	c.mu.Lock()
	defer c.mu.Unlock()
	for i, x := range c.FixedServers {
		if x.Name == name {
			rest := make([]FixedServer, 0, len(c.FixedServers)-1)
			rest = append(rest, c.FixedServers[:i]...)
			rest = append(rest, c.FixedServers[i+1:]...)
			old := c.FixedServers
			c.FixedServers = rest
			if err := c.saveLocked(); err != nil {
				c.FixedServers = old
				return err
			}
			return nil
		}
	}
	return fmt.Errorf("固定服务器 %q 不存在", name)
}

// saveLocked 持久化（调用方须持有 c.mu）。
func (c *Config) saveLocked() error {
	if c.path == "" {
		return fmt.Errorf("配置未从文件加载，无法保存")
	}
	b, err := json.MarshalIndent(c, "", "  ")
	if err != nil {
		return fmt.Errorf("序列化配置失败: %w", err)
	}
	tmp := c.path + ".tmp"
	if err := os.WriteFile(tmp, append(b, '\n'), 0o644); err != nil {
		return fmt.Errorf("写入配置失败: %w", err)
	}
	if err := os.Rename(tmp, c.path); err != nil {
		os.Remove(tmp)
		return fmt.Errorf("保存配置失败: %w", err)
	}
	return nil
}

// resolveModsRepo 把模组仓库目录解析为绝对路径：
// 空值取默认名 mods_repo，相对路径按配置文件所在目录展开。
func resolveModsRepo(dir string, cfgPath string) string {
	if dir == "" {
		dir = "mods_repo"
	}
	if filepath.IsAbs(dir) {
		return filepath.Clean(dir)
	}
	base := filepath.Dir(cfgPath)
	if abs, err := filepath.Abs(base); err == nil {
		base = abs
	}
	return filepath.Join(base, dir)
}

// AbsDataDir 返回数据目录绝对路径，并确保其存在。
func (c *Config) AbsDataDir() (string, error) {
	abs, err := filepath.Abs(c.DataDir)
	if err != nil {
		return "", err
	}
	if err := os.MkdirAll(abs, 0o755); err != nil {
		return "", err
	}
	return abs, nil
}
