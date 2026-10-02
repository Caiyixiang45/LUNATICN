package api

import (
	_ "embed"
	"encoding/json"
	"net/http"
	"strings"

	"lunaticn/server/internal/config"
)

// ---------- 管理端 ----------
//
// 全部接口要求请求头 X-Admin-Token: <config.admin_token>。
// /admin 页面为单文件后台（内联 CSS/JS，无外网依赖）。

//go:embed adminhtml/admin.html
var adminHTML []byte

// requireAdmin 校验管理令牌，失败时写 403 并返回 false。
func (s *Server) requireAdmin(w http.ResponseWriter, r *http.Request) bool {
	if !s.adminOK(r) {
		writeErr(w, 403, "管理令牌无效")
		return false
	}
	return true
}

// handleAdminStats 概览统计：GET /api/admin/stats
func (s *Server) handleAdminStats(w http.ResponseWriter, r *http.Request) {
	if !s.requireAdmin(w, r) {
		return
	}
	users, friends, requests, packages := s.Store.Counts()
	writeJSON(w, 200, map[string]any{
		"users":         users,
		"friends":       friends,
		"requests":      requests,
		"packages":      packages,
		"announcements": len(s.Notices.sorted()),
		"rooms":         s.Hub.Count(),
	})
}

// handleAdminUsers 用户列表：GET /api/admin/users（绝不返回密码哈希）
func (s *Server) handleAdminUsers(w http.ResponseWriter, r *http.Request) {
	if !s.requireAdmin(w, r) {
		return
	}
	list := s.Store.ListUsers()
	out := make([]map[string]any, 0, len(list))
	for _, u := range list {
		out = append(out, map[string]any{
			"id": u.ID, "username": u.Username, "nickname": u.Nickname,
			"created_at": u.CreatedAt,
		})
	}
	writeJSON(w, 200, map[string]any{"users": out})
}

// handleAdminUserCreate 建号：POST /api/admin/users
func (s *Server) handleAdminUserCreate(w http.ResponseWriter, r *http.Request) {
	if !s.requireAdmin(w, r) {
		return
	}
	var req struct {
		Username string `json:"username"`
		Password string `json:"password"`
		Nickname string `json:"nickname"`
	}
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
	writeJSON(w, 201, map[string]any{
		"id": u.ID, "username": u.Username, "nickname": u.Nickname,
		"created_at": u.CreatedAt,
	})
}

// handleAdminUserDelete 删号：DELETE /api/admin/users/{id}
func (s *Server) handleAdminUserDelete(w http.ResponseWriter, r *http.Request) {
	if !s.requireAdmin(w, r) {
		return
	}
	id := strings.TrimSpace(r.PathValue("id"))
	if id == "" {
		writeErr(w, 400, "参数错误")
		return
	}
	if _, ok := s.Store.GetUser(id); !ok {
		writeErr(w, 404, "用户不存在")
		return
	}
	if err := s.Store.DeleteUser(id); err != nil {
		writeErr(w, 404, "用户不存在")
		return
	}
	writeJSON(w, 200, map[string]any{"ok": true})
}

// handleAdminPage 管理后台页面：GET /admin/
func (s *Server) handleAdminPage(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "text/html; charset=utf-8")
	w.Header().Set("Cache-Control", "no-store")
	_, _ = w.Write(adminHTML)
}

// ---------- 房间管理 ----------

// handleAdminRooms 房间列表（含私密房间）：GET /api/admin/rooms
func (s *Server) handleAdminRooms(w http.ResponseWriter, r *http.Request) {
	if !s.requireAdmin(w, r) {
		return
	}
	writeJSON(w, 200, map[string]any{"rooms": s.Hub.AdminList()})
}

// handleAdminRoomKick 踢出房间：DELETE /api/admin/rooms/{id}
func (s *Server) handleAdminRoomKick(w http.ResponseWriter, r *http.Request) {
	if !s.requireAdmin(w, r) {
		return
	}
	id := strings.TrimSpace(r.PathValue("id"))
	if id == "" {
		writeErr(w, 400, "参数错误")
		return
	}
	if err := s.Hub.Kick(id); err != nil {
		writeErr(w, 404, err.Error())
		return
	}
	writeJSON(w, 200, map[string]any{"ok": true})
}

// ---------- 固定服务器管理 ----------

// handleAdminServers 状态列表：GET /api/admin/servers
func (s *Server) handleAdminServers(w http.ResponseWriter, r *http.Request) {
	if !s.requireAdmin(w, r) {
		return
	}
	writeJSON(w, 200, map[string]any{"servers": s.Fixed.StatusList()})
}

// handleAdminServerCreate 创建固定服务器：POST /api/admin/servers
func (s *Server) handleAdminServerCreate(w http.ResponseWriter, r *http.Request) {
	if !s.requireAdmin(w, r) {
		return
	}
	var req struct {
		Name   string `json:"name"`
		Bin    string `json:"bin"`
		World  string `json:"world"`
		GameID string `json:"gameid"`
		Config string `json:"config"`
		Port   int    `json:"port"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeErr(w, 400, "请求格式错误")
		return
	}
	req.Name = strings.TrimSpace(req.Name)
	req.Bin = strings.TrimSpace(req.Bin)
	cf := config.FixedServer{
		Name: req.Name, Bin: req.Bin, World: strings.TrimSpace(req.World),
		GameID: strings.TrimSpace(req.GameID), Config: strings.TrimSpace(req.Config),
		Port: req.Port,
	}
	// 先入配置（持久化），成功后再守护进程；进程侧失败则回滚配置。
	if err := s.Cfg.AddFixedServer(cf); err != nil {
		writeErr(w, 400, err.Error())
		return
	}
	if err := s.Fixed.Add(cf); err != nil {
		_ = s.Cfg.RemoveFixedServer(cf.Name)
		writeErr(w, 400, err.Error())
		return
	}
	writeJSON(w, 201, map[string]any{"ok": true, "name": cf.Name})
}

// handleAdminServerDelete 删除固定服务器：DELETE /api/admin/servers/{name}
func (s *Server) handleAdminServerDelete(w http.ResponseWriter, r *http.Request) {
	if !s.requireAdmin(w, r) {
		return
	}
	name := strings.TrimSpace(r.PathValue("name"))
	if name == "" {
		writeErr(w, 400, "参数错误")
		return
	}
	if err := s.Cfg.RemoveFixedServer(name); err != nil {
		writeErr(w, 404, err.Error())
		return
	}
	_ = s.Fixed.Remove(name) // 配置中已删除；进程侧尽力停止
	writeJSON(w, 200, map[string]any{"ok": true})
}

// handleAdminServerAction 启停控制：POST /api/admin/servers/{name}/{action}
func (s *Server) handleAdminServerAction(w http.ResponseWriter, r *http.Request) {
	if !s.requireAdmin(w, r) {
		return
	}
	name := strings.TrimSpace(r.PathValue("name"))
	action := strings.TrimSpace(r.PathValue("action"))
	var err error
	switch action {
	case "start":
		err = s.Fixed.Start(name)
	case "stop":
		err = s.Fixed.Stop(name)
	case "restart":
		err = s.Fixed.Restart(name)
	default:
		writeErr(w, 400, "动作必须是 start / stop / restart")
		return
	}
	if err != nil {
		writeErr(w, 404, err.Error())
		return
	}
	writeJSON(w, 200, map[string]any{"ok": true, "action": action})
}

// handleAdminModList 仓库模组列表：GET /api/admin/mods（同公开接口，但要求管理令牌）
func (s *Server) handleAdminModList(w http.ResponseWriter, r *http.Request) {
	if !s.requireAdmin(w, r) {
		return
	}
	writeJSON(w, 200, map[string]any{"mods": s.listMods()})
}

// ---------- 分享包管理 ----------

// handleAdminPackages 分享包列表：GET /api/admin/packages?type=&q=&limit=&offset=
func (s *Server) handleAdminPackages(w http.ResponseWriter, r *http.Request) {
	if !s.requireAdmin(w, r) {
		return
	}
	total, list := s.Store.ListPackages(
		strings.TrimSpace(r.URL.Query().Get("type")),
		strings.TrimSpace(r.URL.Query().Get("q")),
		queryInt(r, "limit", 50), queryInt(r, "offset", 0))
	out := make([]map[string]any, 0, len(list))
	for _, p := range list {
		authorName := p.AuthorName
		if u, ok := s.Store.GetUser(p.Author); ok {
			if u.Nickname != "" {
				authorName = u.Nickname
			} else {
				authorName = u.Username
			}
		}
		out = append(out, map[string]any{
			"id": p.ID, "type": p.Type, "name": p.Name,
			"author": p.Author, "author_name": authorName,
			"version": p.Version, "description": p.Description,
			"gameid": p.GameID, "size": p.Size,
			"downloads": p.Downloads, "created_at": p.CreatedAt,
		})
	}
	writeJSON(w, 200, map[string]any{"total": total, "packages": out})
}

// handleAdminPackageDelete 强制删除分享包：DELETE /api/admin/packages/{id}
func (s *Server) handleAdminPackageDelete(w http.ResponseWriter, r *http.Request) {
	if !s.requireAdmin(w, r) {
		return
	}
	id := strings.TrimSpace(r.PathValue("id"))
	if id == "" {
		writeErr(w, 400, "参数错误")
		return
	}
	if err := s.Pkgs.DeleteAny(id); err != nil {
		writeErr(w, 404, err.Error())
		return
	}
	writeJSON(w, 200, map[string]any{"ok": true})
}
