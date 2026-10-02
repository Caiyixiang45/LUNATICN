// Package api 实现 LUNATICN 社区服务端的 HTTP/WebSocket 接口。
package api

import (
	"encoding/json"
	"net/http"
	"strconv"
	"strings"
	"time"

	"lunaticn/server/internal/auth"
	"lunaticn/server/internal/config"
	"lunaticn/server/internal/fixedserver"
	"lunaticn/server/internal/lobby"
	"lunaticn/server/internal/packages"
	"lunaticn/server/internal/store"
)

// Server 组装全部处理器依赖。
type Server struct {
	Cfg     *config.Config
	Store   *store.Store
	Tokens  *auth.TokenIssuer
	Hub     *lobby.Hub
	Pkgs    *packages.Service
	Fixed   *fixedserver.Manager
	WsHub   *WsHub
	Notices *noticeStore
	Version string
}

// New 创建 API 服务。
func New(cfg *config.Config, st *store.Store, hub *lobby.Hub, pk *packages.Service, fx *fixedserver.Manager) *Server {
	s := &Server{
		Cfg:     cfg,
		Store:   st,
		Tokens:  auth.NewTokenIssuer(cfg.JWTSecret, time.Duration(cfg.TokenTTLMinutes)*time.Minute),
		Hub:     hub,
		Pkgs:    pk,
		Fixed:   fx,
		WsHub:   NewWsHub(),
		Version: "1.0.0",
	}
	if dataDir, err := cfg.AbsDataDir(); err == nil {
		s.Notices = newNoticeStore(dataDir, cfg.AdminToken, cfg.Announcements, cfg.ClientUpdate)
	} else {
		s.Notices = newNoticeStore(".", cfg.AdminToken, cfg.Announcements, cfg.ClientUpdate)
	}
	hub.SetNotify(func() { s.WsHub.BroadcastRoomsChanged() })
	s.WsHub.OnUserPresence = s.pushPresence
	return s
}

// pushPresence 用户上/下线时向其全部好友推送 presence 事件。
// 好“特别关心”由客户端本地过滤，服务端只负责广播在线状态。
func (s *Server) pushPresence(uid string, online bool) {
	u, ok := s.Store.GetUser(uid)
	if !ok {
		return
	}
	for _, fid := range s.Store.FriendIDs(uid) {
		s.WsHub.SendToUser(fid, map[string]any{
			"type":    "presence",
			"user_id": uid,
			"name":    u.Nickname,
			"online":  online,
		})
	}
}

func minutes(m int) time.Duration { return time.Duration(m) * time.Minute }

// ---------- 通用工具 ----------

func writeJSON(w http.ResponseWriter, code int, v any) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(code)
	_ = json.NewEncoder(w).Encode(v)
}

func writeErr(w http.ResponseWriter, code int, msg string) {
	writeJSON(w, code, map[string]string{"error": msg})
}

func apiError(w http.ResponseWriter, err error) {
	writeErr(w, http.StatusBadRequest, err.Error())
}

// authUser 解析 Authorization: Bearer 令牌，返回用户。
func (s *Server) authUser(r *http.Request) (store.User, *auth.Claims, error) {
	h := r.Header.Get("Authorization")
	if !strings.HasPrefix(h, "Bearer ") {
		return store.User{}, nil, errUnauthorized
	}
	claims, err := s.Tokens.Verify(strings.TrimPrefix(h, "Bearer "))
	if err != nil {
		return store.User{}, nil, errUnauthorized
	}
	u, ok := s.Store.GetUser(claims.Sub)
	if !ok {
		return store.User{}, nil, errUnauthorized
	}
	return u, claims, nil
}

type unauthorized struct{}

func (unauthorized) Error() string { return "未登录或令牌无效" }

var errUnauthorized = unauthorized{}

// queryInt 读取整型查询参数。
func queryInt(r *http.Request, key string, def int) int {
	v := r.URL.Query().Get(key)
	if v == "" {
		return def
	}
	n, err := strconv.Atoi(v)
	if err != nil {
		return def
	}
	return n
}
