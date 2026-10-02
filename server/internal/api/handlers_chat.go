package api

import (
	"encoding/json"
	"net/http"
	"strconv"
	"strings"
	"sync"
	"time"
	"unicode/utf8"

	"lunaticn/server/internal/store"
)

// ---------- 好友即时聊天 ----------

// maxChatText 聊天单条消息长度上限（按字符计）。
const maxChatText = 500

// chatIDMu 保证进程内消息 ID 严格递增（毫秒时间戳兜底同毫秒碰撞）。
var (
	chatIDMu   sync.Mutex
	lastChatID int64
)

// nextChatID 生成单调递增的消息 ID（Unix 毫秒）。
func nextChatID() int64 {
	chatIDMu.Lock()
	defer chatIDMu.Unlock()
	now := time.Now().UnixMilli()
	if now <= lastChatID {
		now = lastChatID + 1
	}
	lastChatID = now
	return now
}

// queryInt64 读取 int64 查询参数。
func queryInt64(r *http.Request, key string, def int64) int64 {
	v := r.URL.Query().Get(key)
	if v == "" {
		return def
	}
	n, err := strconv.ParseInt(v, 10, 64)
	if err != nil {
		return def
	}
	return n
}

// handleChatGet 会话记录：GET /api/chat/{peerID}?before=<id>&limit=50
func (s *Server) handleChatGet(w http.ResponseWriter, r *http.Request) {
	u, _, err := s.authUser(r)
	if err != nil {
		writeErr(w, 401, err.Error())
		return
	}
	peer := strings.TrimSpace(r.PathValue("peerID"))
	if peer == "" {
		writeErr(w, 400, "参数错误")
		return
	}
	before := queryInt64(r, "before", 0)
	limit := queryInt(r, "limit", 50)
	if limit <= 0 {
		limit = 50
	}
	if limit > 200 {
		limit = 200
	}
	list := s.Store.ListMessages(u.ID, peer, before, limit)
	if list == nil {
		list = []store.ChatMessage{}
	}
	writeJSON(w, 200, map[string]any{"messages": list})
}

// handleChatSend 发消息：POST /api/chat/{peerID} body {"text":"..."}
func (s *Server) handleChatSend(w http.ResponseWriter, r *http.Request) {
	u, _, err := s.authUser(r)
	if err != nil {
		writeErr(w, 401, err.Error())
		return
	}
	var req struct {
		Text string `json:"text"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeErr(w, 400, "请求格式错误")
		return
	}
	peer := strings.TrimSpace(r.PathValue("peerID"))
	if peer == "" {
		writeErr(w, 400, "参数错误")
		return
	}
	if _, ok := s.Store.GetUser(peer); !ok {
		writeErr(w, 404, "用户不存在")
		return
	}
	text := strings.TrimSpace(req.Text)
	if text == "" {
		writeErr(w, 400, "消息内容不能为空")
		return
	}
	if utf8.RuneCountInString(text) > maxChatText {
		writeErr(w, 400, "消息不能超过 500 个字符")
		return
	}
	m := store.ChatMessage{
		ID:        nextChatID(),
		From:      u.ID,
		To:        peer,
		Text:      text,
		CreatedAt: time.Now().UnixMilli(),
	}
	if err := s.Store.AppendMessage(m); err != nil {
		writeErr(w, 500, "消息保存失败")
		return
	}
	s.pushChat(m, u.Nickname)
	writeJSON(w, 201, map[string]any{"id": m.ID})
}

// pushChat 向接收方与发送者本人的所有在线连接推送同一事件（多端同步）。
func (s *Server) pushChat(m store.ChatMessage, fromName string) {
	if fromName == "" {
		fromName = m.From
	}
	payload := map[string]any{
		"type":       "chat",
		"from":       m.From,
		"from_name":  fromName,
		"id":         m.ID,
		"text":       m.Text,
		"created_at": m.CreatedAt,
	}
	s.WsHub.SendToUser(m.To, payload)
	s.WsHub.SendToUser(m.From, payload)
}

// ---------- 邀请好友进房间 ----------

// handleInvite 邀请好友：POST /api/invite body {"user_id":"...","room":"房间名"}
func (s *Server) handleInvite(w http.ResponseWriter, r *http.Request) {
	u, _, err := s.authUser(r)
	if err != nil {
		writeErr(w, 401, err.Error())
		return
	}
	var req struct {
		UserID string `json:"user_id"`
		Room   string `json:"room"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeErr(w, 400, "请求格式错误")
		return
	}
	peer := strings.TrimSpace(req.UserID)
	roomName := strings.TrimSpace(req.Room)
	if peer == "" || roomName == "" {
		writeErr(w, 400, "参数错误")
		return
	}
	if peer == u.ID {
		writeErr(w, 400, "不能邀请自己")
		return
	}
	if _, ok := s.Store.GetUser(peer); !ok {
		writeErr(w, 404, "用户不存在")
		return
	}

	// 与 GET /api/rooms 同源的活跃房间列表（含私密房间可见性过滤）。
	rooms := s.Hub.List(u.ID, s.friendSet(u.ID))
	idx := -1
	for i := range rooms {
		if rooms[i].Name == roomName {
			idx = i
			break
		}
	}
	if idx < 0 {
		writeErr(w, 404, "房间不存在或已关闭")
		return
	}
	rm := rooms[idx]

	fromName := u.Nickname
	if fromName == "" {
		fromName = u.Username
	}
	s.WsHub.SendToUser(peer, map[string]any{
		"type":      "invite",
		"from":      u.ID,
		"from_name": fromName,
		"room_name": rm.Name,
		"host":      rm.Host,
		"port":      rm.Port,
		"gameid":    rm.GameID,
	})
	writeJSON(w, 200, map[string]any{"ok": true})
}
