package api

import (
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"net/http"
	"os"
	"strings"
	"time"

	"lunaticn/server/internal/auth"
	"lunaticn/server/internal/store"
)

// ---------- 账号 ----------

type registerReq struct {
	Username string `json:"username"`
	Password string `json:"password"`
	Nickname string `json:"nickname"`
}

// handleRegister 注册：POST /api/auth/register
func (s *Server) handleRegister(w http.ResponseWriter, r *http.Request) {
	var req registerReq
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeErr(w, 400, "请求格式错误")
		return
	}
	u, code, msg := s.newUser(req.Username, req.Password, req.Nickname)
	if code != 0 {
		writeErr(w, code, msg)
		return
	}
	if err := s.Store.CreateUser(u); err != nil {
		writeErr(w, 409, err.Error())
		return
	}
	token := s.Tokens.Issue(u.ID, u.Username)
	writeJSON(w, 201, map[string]any{"token": token, "user": s.userJSON(u)})
}

// newUser 校验用户名/密码并构造待创建用户（不落盘）。
// 校验通过返回 code=0，否则返回对应 HTTP 状态码与中文提示。
// 注册接口与管理端建号共用此逻辑。
func (s *Server) newUser(username, password, nickname string) (store.User, int, string) {
	username = strings.TrimSpace(strings.ToLower(username))
	if len(username) < 3 || len(username) > 24 {
		return store.User{}, 400, "用户名需 3-24 个字符"
	}
	for _, c := range username {
		if !(c >= 'a' && c <= 'z' || c >= '0' && c <= '9' || c == '_' || c == '-') {
			return store.User{}, 400, "用户名仅限小写字母、数字、下划线与连字符"
		}
	}
	if len(password) < 6 {
		return store.User{}, 400, "密码至少 6 位"
	}
	hash, err := auth.HashPassword(password)
	if err != nil {
		return store.User{}, 500, "服务内部错误"
	}
	nick := strings.TrimSpace(nickname)
	if nick == "" {
		nick = username
	}
	idB := make([]byte, 8)
	_, _ = rand.Read(idB)
	return store.User{
		ID:           hex.EncodeToString(idB),
		Username:     username,
		Nickname:     nick,
		PasswordHash: hash,
		CreatedAt:    time.Now(),
	}, 0, ""
}

type loginReq struct {
	Username string `json:"username"`
	Password string `json:"password"`
}

// handleLogin 登录：POST /api/auth/login
func (s *Server) handleLogin(w http.ResponseWriter, r *http.Request) {
	var req loginReq
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeErr(w, 400, "请求格式错误")
		return
	}
	u, ok := s.Store.FindUser(strings.TrimSpace(strings.ToLower(req.Username)))
	if !ok || !auth.VerifyPassword(u.PasswordHash, req.Password) {
		writeErr(w, 401, "用户名或密码错误")
		return
	}
	token := s.Tokens.Issue(u.ID, u.Username)
	writeJSON(w, 200, map[string]any{"token": token, "user": s.userJSON(u)})
}

// handleRefresh 刷新令牌：POST /api/auth/refresh
func (s *Server) handleRefresh(w http.ResponseWriter, r *http.Request) {
	h := r.Header.Get("Authorization")
	if !strings.HasPrefix(h, "Bearer ") {
		writeErr(w, 401, "未登录")
		return
	}
	newTok, claims, err := s.Tokens.Refresh(strings.TrimPrefix(h, "Bearer "))
	if err != nil {
		writeErr(w, 401, err.Error())
		return
	}
	writeJSON(w, 200, map[string]any{"token": newTok, "user_id": claims.Sub})
}

// handleMe 当前用户：GET /api/me
func (s *Server) handleMe(w http.ResponseWriter, r *http.Request) {
	u, _, err := s.authUser(r)
	if err != nil {
		writeErr(w, 401, err.Error())
		return
	}
	writeJSON(w, 200, s.userJSON(u))
}

// handleUpdateMe 修改昵称/密码：PATCH /api/me
func (s *Server) handleUpdateMe(w http.ResponseWriter, r *http.Request) {
	u, _, err := s.authUser(r)
	if err != nil {
		writeErr(w, 401, err.Error())
		return
	}
	var req struct {
		Nickname string `json:"nickname"`
		Password string `json:"password"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeErr(w, 400, "请求格式错误")
		return
	}
	if nick := strings.TrimSpace(req.Nickname); nick != "" {
		u.Nickname = nick
	}
	if req.Password != "" {
		if len(req.Password) < 6 {
			writeErr(w, 400, "密码至少 6 位")
			return
		}
		hash, err := auth.HashPassword(req.Password)
		if err != nil {
			writeErr(w, 500, "服务内部错误")
			return
		}
		u.PasswordHash = hash
	}
	if err := s.Store.UpdateUser(u); err != nil {
		writeErr(w, 500, err.Error())
		return
	}
	writeJSON(w, 200, s.userJSON(u))
}

func (s *Server) userJSON(u store.User) map[string]any {
	return map[string]any{
		"id": u.ID, "username": u.Username, "nickname": u.Nickname,
		"created_at": u.CreatedAt,
	}
}

// ---------- 好友 ----------

// handleFriends 好友列表：GET /api/friends
func (s *Server) handleFriends(w http.ResponseWriter, r *http.Request) {
	u, _, err := s.authUser(r)
	if err != nil {
		writeErr(w, 401, err.Error())
		return
	}
	ids := s.Store.FriendIDs(u.ID)
	list := make([]map[string]any, 0, len(ids))
	for _, id := range ids {
		if f, ok := s.Store.GetUser(id); ok {
			list = append(list, s.userJSON(f))
		}
	}
	writeJSON(w, 200, map[string]any{"friends": list})
}

// handleFriendRequest 发送好友请求：POST /api/friends/request
func (s *Server) handleFriendRequest(w http.ResponseWriter, r *http.Request) {
	u, _, err := s.authUser(r)
	if err != nil {
		writeErr(w, 401, err.Error())
		return
	}
	var req struct {
		Username string `json:"username"` // 按用户名查找
		UserID   string `json:"user_id"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeErr(w, 400, "请求格式错误")
		return
	}
	target := req.UserID
	if target == "" {
		t, ok := s.Store.FindUser(strings.TrimSpace(strings.ToLower(req.Username)))
		if !ok {
			writeErr(w, 404, "用户不存在")
			return
		}
		target = t.ID
	}
	if target == u.ID {
		writeErr(w, 400, "不能添加自己")
		return
	}
	if _, ok := s.Store.GetUser(target); !ok {
		writeErr(w, 404, "用户不存在")
		return
	}
	if err := s.Store.SendRequest(u.ID, target); err != nil {
		apiError(w, err)
		return
	}
	writeJSON(w, 200, map[string]string{"status": "ok"})
}

// handleFriendRequests 请求列表：GET /api/friends/requests
func (s *Server) handleFriendRequests(w http.ResponseWriter, r *http.Request) {
	u, _, err := s.authUser(r)
	if err != nil {
		writeErr(w, 401, err.Error())
		return
	}
	in, out := s.Store.ListRequests(u.ID)
	render := func(rs []store.FriendRequest) []map[string]any {
		res := make([]map[string]any, 0, len(rs))
		for _, rq := range rs {
			other := rq.From
			if other == u.ID {
				other = rq.To
			}
			item := map[string]any{"created_at": rq.CreatedAt, "direction": "in"}
			if ou, ok := s.Store.GetUser(other); ok {
				item["user"] = s.userJSON(ou)
			}
			if rq.From == u.ID {
				item["direction"] = "out"
			}
			res = append(res, item)
		}
		return res
	}
	writeJSON(w, 200, map[string]any{"incoming": render(in), "outgoing": render(out)})
}

// handleFriendRespond 处理请求：POST /api/friends/respond
// body: {from: 用户ID, accept: bool}
func (s *Server) handleFriendRespond(w http.ResponseWriter, r *http.Request) {
	u, _, err := s.authUser(r)
	if err != nil {
		writeErr(w, 401, err.Error())
		return
	}
	var req struct {
		From   string `json:"from"`
		Accept bool   `json:"accept"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeErr(w, 400, "请求格式错误")
		return
	}
	if req.Accept {
		err = s.Store.AcceptRequest(req.From, u.ID)
	} else {
		err = s.Store.RejectRequest(req.From, u.ID)
	}
	if err != nil {
		apiError(w, err)
		return
	}
	writeJSON(w, 200, map[string]string{"status": "ok"})
}

// handleFriendRemove 删除好友：DELETE /api/friends/{id}
func (s *Server) handleFriendRemove(w http.ResponseWriter, r *http.Request) {
	u, _, err := s.authUser(r)
	if err != nil {
		writeErr(w, 401, err.Error())
		return
	}
	other := strings.TrimPrefix(r.URL.Path, "/api/friends/")
	if other == "" || other == u.ID {
		writeErr(w, 400, "参数错误")
		return
	}
	if err := s.Store.RemoveFriend(u.ID, other); err != nil {
		apiError(w, err)
		return
	}
	writeJSON(w, 200, map[string]string{"status": "ok"})
}

// friendSet 构造"我是谁的好友"查询集合。
func (s *Server) friendSet(uid string) map[string]bool {
	set := map[string]bool{}
	for _, id := range s.Store.FriendIDs(uid) {
		set[id] = true
	}
	return set
}

// ---------- 运行环境 ----------

// fileExists 供其他 handler 复用的简单判断。
func fileExists(p string) bool {
	_, err := os.Stat(p)
	return err == nil
}
