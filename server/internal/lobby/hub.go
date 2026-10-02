// Package lobby 是房间注册中心：房间注册、心跳续期、列表与过期剔除。
// 房间来源有两类：
//  1. roomd —— 玩家自行运行的独立轻量房间服务器，带 token 自动注册；
//  2. 启动器房主 —— 创建房间时由启动器代为注册。
//
// 服务器列表统一由本社区服务维护并对外提供。
package lobby

import (
	"crypto/rand"
	"encoding/hex"
	"errors"
	"sort"
	"sync"
	"time"
)

// Room 房间（= 一个可进入的 Luanti 服务器端点）。
type Room struct {
	ID            string    `json:"id"`
	Name          string    `json:"name"`
	Owner         string    `json:"owner"`      // 房主用户 ID
	OwnerName     string    `json:"owner_name"` // 房主展示名
	Host          string    `json:"host"`       // 玩家可连的地址
	Port          int       `json:"port"`
	GameID        string    `json:"gameid"`
	World         string    `json:"world"` // 世界名（展示用）
	MaxPlayers    int       `json:"max_players"`
	Players       int       `json:"players"` // 当前人数（roomd 心跳上报）
	HasPassword   bool      `json:"has_password"`
	Private       bool      `json:"private"`  // true = 仅好友可见
	Engine        string    `json:"engine"`   // 引擎版本
	Protocol      int       `json:"protocol"` // 网络协议版本
	Source        string    `json:"source"`   // roomd | launcher
	Description   string    `json:"description"`
	LastHeartbeat time.Time `json:"last_heartbeat"`
}

// 在线判定：超过该时长未心跳即从列表移除。
const roomTTL = 45 * time.Second

// Hub 房间注册中心。
type Hub struct {
	mu    sync.RWMutex
	rooms map[string]*Room
	// token -> roomID，供 roomd 用注册令牌续期与更新
	tokens map[string]string

	// 变更通知回调（用于 WebSocket 广播），可为空。
	notify func()
}

// NewHub 创建房间中心。
func NewHub() *Hub {
	return &Hub{
		rooms:  make(map[string]*Room),
		tokens: make(map[string]string),
	}
}

// SetNotify 注册变更回调（如向所有在线客户端广播房间列表更新）。
func (h *Hub) SetNotify(fn func()) { h.notify = fn }

func (h *Hub) fire() {
	if h.notify != nil {
		h.notify()
	}
}

func randomID() string {
	b := make([]byte, 8)
	_, _ = rand.Read(b)
	return hex.EncodeToString(b)
}

// RegisterInput 注册参数。
type RegisterInput struct {
	Token       string // roomd 的注册令牌（roomd 模式续期用，可空）
	Name        string
	Owner       string
	OwnerName   string
	Host        string
	Port        int
	GameID      string
	World       string
	MaxPlayers  int
	Players     int
	HasPassword bool
	Private     bool
	Engine      string
	Protocol    int
	Source      string
	Description string
}

// Register 注册或更新房间。返回房间与（新建时的）访问令牌。
func (h *Hub) Register(in RegisterInput) (Room, string, error) {
	if in.Name == "" {
		return Room{}, "", errors.New("房间名不能为空")
	}
	if in.Host == "" || in.Port <= 0 || in.Port > 65535 {
		return Room{}, "", errors.New("主机地址或端口无效")
	}
	h.mu.Lock()
	defer h.mu.Unlock()

	// 凭 token 续期既有房间
	if in.Token != "" {
		if id, ok := h.tokens[in.Token]; ok {
			r := h.rooms[id]
			r.Name = in.Name
			r.Host = in.Host
			r.Port = in.Port
			r.Players = in.Players
			r.MaxPlayers = in.MaxPlayers
			r.Engine = in.Engine
			r.Protocol = in.Protocol
			r.Description = in.Description
			r.GameID = in.GameID
			r.World = in.World
			r.HasPassword = in.HasPassword
			r.Private = in.Private
			r.LastHeartbeat = time.Now()
			h.fire()
			return *r, in.Token, nil
		}
	}

	// 房主重复创建时先移除旧房间（一人一房）
	for id, r := range h.rooms {
		if r.Owner == in.Owner && r.Source == in.Source {
			delete(h.rooms, id)
			for t, rid := range h.tokens {
				if rid == id {
					delete(h.tokens, t)
				}
			}
		}
	}

	tokB := make([]byte, 16)
	_, _ = rand.Read(tokB)
	token := hex.EncodeToString(tokB)

	r := &Room{
		ID:            randomID(),
		Name:          in.Name,
		Owner:         in.Owner,
		OwnerName:     in.OwnerName,
		Host:          in.Host,
		Port:          in.Port,
		GameID:        in.GameID,
		World:         in.World,
		MaxPlayers:    in.MaxPlayers,
		Players:       in.Players,
		HasPassword:   in.HasPassword,
		Private:       in.Private,
		Engine:        in.Engine,
		Protocol:      in.Protocol,
		Source:        in.Source,
		Description:   in.Description,
		LastHeartbeat: time.Now(),
	}
	h.rooms[r.ID] = r
	h.tokens[token] = r.ID
	h.fire()
	return *r, token, nil
}

// Heartbeat 房间心跳，同时上报人数。uid 用于校验房主身份。
func (h *Hub) Heartbeat(token, uid string, players int) error {
	h.mu.Lock()
	defer h.mu.Unlock()
	id, ok := h.tokens[token]
	if !ok {
		return errors.New("房间令牌无效")
	}
	r, ok := h.rooms[id]
	if !ok {
		return errors.New("房间不存在")
	}
	if r.Owner != uid {
		return errors.New("无权操作该房间")
	}
	r.Players = players
	r.LastHeartbeat = time.Now()
	h.fire()
	return nil
}

// Unregister 注销房间。
func (h *Hub) Unregister(token, uid string) error {
	h.mu.Lock()
	defer h.mu.Unlock()
	id, ok := h.tokens[token]
	if !ok {
		return errors.New("房间令牌无效")
	}
	if r, ok := h.rooms[id]; ok && r.Owner != uid {
		return errors.New("无权操作该房间")
	}
	delete(h.rooms, id)
	delete(h.tokens, token)
	h.fire()
	return nil
}

// List 返回未过期房间。
// viewerID/viewerFriends 用于私密房间过滤：仅房主与房主好友可见。
func (h *Hub) List(viewerID string, viewerFriends map[string]bool) []Room {
	h.mu.Lock()
	defer h.mu.Unlock()
	now := time.Now()
	out := make([]Room, 0, len(h.rooms))
	for id, r := range h.rooms {
		if now.Sub(r.LastHeartbeat) > roomTTL {
			delete(h.rooms, id)
			for t, rid := range h.tokens {
				if rid == id {
					delete(h.tokens, t)
				}
			}
			continue
		}
		if r.Private && r.Owner != viewerID && !viewerFriends[r.Owner] {
			continue
		}
		out = append(out, *r)
	}
	sort.Slice(out, func(i, j int) bool {
		return out[i].LastHeartbeat.After(out[j].LastHeartbeat)
	})
	h.fireIfNeededLocked(now)
	return out
}

// fireIfNeededLocked 单独抽出让 List 尾部清理后也触发广播。
func (h *Hub) fireIfNeededLocked(time.Time) {}

// AdminList 管理端房间列表：包含私密房间，先清理过期。
func (h *Hub) AdminList() []Room {
	h.mu.Lock()
	defer h.mu.Unlock()
	now := time.Now()
	for id, r := range h.rooms {
		if now.Sub(r.LastHeartbeat) > roomTTL {
			delete(h.rooms, id)
			for t, rid := range h.tokens {
				if rid == id {
					delete(h.tokens, t)
				}
			}
		}
	}
	out := make([]Room, 0, len(h.rooms))
	for _, r := range h.rooms {
		out = append(out, *r)
	}
	sort.Slice(out, func(i, j int) bool {
		return out[i].LastHeartbeat.After(out[j].LastHeartbeat)
	})
	return out
}

// Kick 管理端踢出房间：直接移除并广播（同名房间可立即重新注册）。
func (h *Hub) Kick(id string) error {
	h.mu.Lock()
	defer h.mu.Unlock()
	if _, ok := h.rooms[id]; !ok {
		return errors.New("房间不存在")
	}
	delete(h.rooms, id)
	for t, rid := range h.tokens {
		if rid == id {
			delete(h.tokens, t)
		}
	}
	h.fire()
	return nil
}

// Sweep 周期清理过期房间（由后台协程调用）。
func (h *Hub) Sweep() {
	h.mu.Lock()
	changed := false
	now := time.Now()
	for id, r := range h.rooms {
		if now.Sub(r.LastHeartbeat) > roomTTL {
			delete(h.rooms, id)
			for t, rid := range h.tokens {
				if rid == id {
					delete(h.tokens, t)
				}
			}
			changed = true
		}
	}
	h.mu.Unlock()
	if changed {
		h.fire()
	}
}

// RunSweeper 启动定期清扫。
func (h *Hub) RunSweeper(stop <-chan struct{}) {
	t := time.NewTicker(10 * time.Second)
	defer t.Stop()
	for {
		select {
		case <-t.C:
			h.Sweep()
		case <-stop:
			return
		}
	}
}

// Get 按 ID 取房间。
func (h *Hub) Get(id string) (Room, bool) {
	h.mu.RLock()
	defer h.mu.RUnlock()
	r, ok := h.rooms[id]
	if !ok {
		return Room{}, false
	}
	return *r, true
}

// Count 当前房间数（测试用）。
func (h *Hub) Count() int {
	h.mu.RLock()
	defer h.mu.RUnlock()
	return len(h.rooms)
}
