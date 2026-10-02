package api

import (
	"encoding/json"
	"log"
	"net/http"
	"strings"
	"sync"
	"time"

	"github.com/gorilla/websocket"

	"lunaticn/server/internal/lobby"
)

// WsHub 管理全部 WebSocket 连接，向客户端推送事件。
// 已鉴权的连接会按 userID 建立索引，供定向推送（聊天、邀请）使用；
// 未鉴权连接仍会收到房间与公告广播，兼容既有客户端。
type WsHub struct {
	mu    sync.RWMutex
	conns map[*websocket.Conn]struct{}
	// 每条连接一把写锁，避免多个协程并发写同一连接导致帧交错。
	wlocks map[*websocket.Conn]*sync.Mutex
	// userID -> 该用户的全部连接（多端同步）
	byUser map[string]map[*websocket.Conn]struct{}
	// 连接 -> 绑定的用户 ID（未鉴权则不记录）
	userOf map[*websocket.Conn]string
	// 用户上/下线回调（首连上线、末连断开且过宽限期后离线），由 Server 设置。
	OnUserPresence func(userID string, online bool)
	// 离线宽限定时器：短暂断线重连不触发离线通知
	offlineTimers map[string]*time.Timer
}

// offlineGrace 离线宽限：断开后超过该时长未重连才推送离线。
const offlineGrace = 6 * time.Second

// NewWsHub 创建连接中心。
func NewWsHub() *WsHub {
	return &WsHub{
		conns:        make(map[*websocket.Conn]struct{}),
		wlocks:       make(map[*websocket.Conn]*sync.Mutex),
		byUser:       make(map[string]map[*websocket.Conn]struct{}),
		userOf:       make(map[*websocket.Conn]string),
		offlineTimers: make(map[string]*time.Timer),
	}
}

var upgrader = websocket.Upgrader{
	ReadBufferSize:  1024,
	WriteBufferSize: 1024,
	// 启动器与本地开发页访问，放行同源与本地地址
	CheckOrigin: func(r *http.Request) bool { return true },
}

// HandleWS GET /api/ws 升级为 WebSocket。
// 客户端连上后：先收到 {type:"rooms"} 全量事件，之后房间列表有变化会收到同样事件。
// 令牌可放在查询参数 ?token= 或 Authorization: Bearer 头，校验通过后该连接绑定用户，
// 之后可接收 {type:"chat"} / {type:"invite"} 定向事件。
func (s *Server) HandleWS(w http.ResponseWriter, r *http.Request) {
	conn, err := upgrader.Upgrade(w, r, nil)
	if err != nil {
		return
	}
	s.WsHub.add(conn, s.wsUserID(r))

	// 首帧：立即推送当前房间
	s.sendRooms(conn)

	// 读循环：仅用于维持连接与检测关闭
	go func() {
		defer func() {
			s.WsHub.remove(conn)
			conn.Close()
		}()
		conn.SetReadLimit(4096)
		for {
			if _, _, err := conn.ReadMessage(); err != nil {
				return
			}
			// 客户端发 ping，回 pong
			_ = conn.SetReadDeadline(time.Now().Add(90 * time.Second))
		}
	}()
}

// wsUserID 从查询参数或 Authorization 头解析用户令牌，返回绑定的用户 ID（失败返回空串）。
func (s *Server) wsUserID(r *http.Request) string {
	tok := strings.TrimSpace(r.URL.Query().Get("token"))
	if tok == "" {
		h := r.Header.Get("Authorization")
		if strings.HasPrefix(h, "Bearer ") {
			tok = strings.TrimSpace(strings.TrimPrefix(h, "Bearer "))
		}
	}
	if tok == "" {
		return ""
	}
	claims, err := s.Tokens.Verify(tok)
	if err != nil {
		return ""
	}
	if _, ok := s.Store.GetUser(claims.Sub); !ok {
		return ""
	}
	return claims.Sub
}

// BroadcastRoomsChanged 房间变化时广播（由 lobby.Hub 回调触发）。
func (h *WsHub) BroadcastRoomsChanged() {
	h.Broadcast(map[string]string{"type": "rooms"})
}

// BroadcastNotice 公告或客户端更新推送变化时广播，客户端收到后重新拉取。
func (h *WsHub) BroadcastNotice() {
	h.Broadcast(map[string]string{"type": "notice"})
}

// Broadcast 向全部连接推送一帧 JSON（未鉴权连接同样收到）。
func (h *WsHub) Broadcast(payload any) {
	h.mu.RLock()
	conns := make([]*websocket.Conn, 0, len(h.conns))
	for c := range h.conns {
		conns = append(conns, c)
	}
	h.mu.RUnlock()

	for _, c := range conns {
		h.writeTo(c, payload)
	}
}

// SendToUser 向某个用户的全部在线连接推送一帧 JSON（多端同步）；无在线连接时静默跳过。
func (h *WsHub) SendToUser(userID string, payload any) {
	if userID == "" {
		return
	}
	h.mu.RLock()
	conns := make([]*websocket.Conn, 0, len(h.byUser[userID]))
	for c := range h.byUser[userID] {
		conns = append(conns, c)
	}
	h.mu.RUnlock()

	for _, c := range conns {
		h.writeTo(c, payload)
	}
}

// writeTo 串行化单连接写入，写失败即摘除并关闭。
func (h *WsHub) writeTo(c *websocket.Conn, payload any) {
	h.mu.RLock()
	lk := h.wlocks[c]
	h.mu.RUnlock()
	if lk == nil {
		lk = &sync.Mutex{}
	}
	lk.Lock()
	defer lk.Unlock()
	_ = c.SetWriteDeadline(time.Now().Add(5 * time.Second))
	if err := c.WriteJSON(payload); err != nil {
		h.remove(c)
		c.Close()
	}
}

// sendRooms 向单连接推送当前房间全量列表。
func (s *Server) sendRooms(conn *websocket.Conn) {
	// WS 推送为“有更新”通知，客户端收到后自行拉取 REST 列表
	// （私密房间过滤依赖登录态，统一在 GET /api/rooms 完成）。
	rooms := s.Hub.List("", map[string]bool{})
	if rooms == nil {
		rooms = []lobby.Room{}
	}
	payload := map[string]any{"type": "rooms", "rooms": rooms}
	b, _ := json.Marshal(payload)
	s.WsHub.mu.RLock()
	lk := s.WsHub.wlocks[conn]
	s.WsHub.mu.RUnlock()
	if lk == nil {
		lk = &sync.Mutex{}
	}
	lk.Lock()
	_ = conn.SetWriteDeadline(time.Now().Add(5 * time.Second))
	if err := conn.WriteMessage(websocket.TextMessage, b); err != nil {
		log.Printf("ws push: %v", err)
	}
	lk.Unlock()
}

// add 登记连接；userID 非空时建立用户索引，首连触发上线回调。
func (h *WsHub) add(c *websocket.Conn, userID string) {
	h.mu.Lock()
	h.conns[c] = struct{}{}
	h.wlocks[c] = &sync.Mutex{}
	offline := false
	if userID != "" {
		if h.byUser[userID] == nil {
			h.byUser[userID] = make(map[*websocket.Conn]struct{})
		}
		first := len(h.byUser[userID]) == 0
		h.byUser[userID][c] = struct{}{}
		h.userOf[c] = userID
		if first {
			// 取消尚未触发的离线定时（断线重连场景）
			if t, ok := h.offlineTimers[userID]; ok {
				t.Stop()
				delete(h.offlineTimers, userID)
			}
			offline = true // 复用变量表示“刚上线”
		}
	}
	online := offline
	cb := h.OnUserPresence
	h.mu.Unlock()
	if online && cb != nil {
		go cb(userID, true)
	}
}

func (h *WsHub) remove(c *websocket.Conn) {
	h.mu.Lock()
	delete(h.conns, c)
	delete(h.wlocks, c)
	var offUID string
	schedule := false
	if uid, ok := h.userOf[c]; ok {
		delete(h.userOf, c)
		if set, ok := h.byUser[uid]; ok {
			delete(set, c)
			if len(set) == 0 {
				delete(h.byUser, uid)
				offUID = uid
				schedule = true
			}
		}
	}
	cb := h.OnUserPresence
	if schedule && cb != nil {
		// 宽限期内重连则取消离线通知
		if t, ok := h.offlineTimers[offUID]; ok {
			t.Stop()
		}
		uid := offUID
		h.offlineTimers[uid] = time.AfterFunc(offlineGrace, func() {
			h.mu.Lock()
			if len(h.byUser[uid]) > 0 {
				h.mu.Unlock() // 已重连
				return
			}
			delete(h.offlineTimers, uid)
			h.mu.Unlock()
			if h.OnUserPresence != nil {
				h.OnUserPresence(uid, false)
			}
		})
	}
	h.mu.Unlock()
}

// Count 在线连接数。
func (h *WsHub) Count() int {
	h.mu.RLock()
	defer h.mu.RUnlock()
	return len(h.conns)
}
