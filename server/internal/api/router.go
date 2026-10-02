package api

import (
	"net/http"
	"strings"
)

// Handler 返回完整路由表。
func (s *Server) Handler() http.Handler {
	mux := http.NewServeMux()

	// 健康检查
	mux.HandleFunc("GET /api/health", func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, 200, map[string]any{
			"status": "ok", "version": s.Version,
			"rooms": s.Hub.Count(), "ws": s.WsHub.Count(),
		})
	})

	// 账号
	mux.HandleFunc("POST /api/auth/register", s.handleRegister)
	mux.HandleFunc("POST /api/auth/login", s.handleLogin)
	mux.HandleFunc("POST /api/auth/refresh", s.handleRefresh)
	mux.HandleFunc("GET /api/me", s.handleMe)
	mux.HandleFunc("PATCH /api/me", s.handleUpdateMe)

	// 好友
	mux.HandleFunc("GET /api/friends", s.handleFriends)
	mux.HandleFunc("POST /api/friends/request", s.handleFriendRequest)
	mux.HandleFunc("GET /api/friends/requests", s.handleFriendRequests)
	mux.HandleFunc("POST /api/friends/respond", s.handleFriendRespond)
	mux.HandleFunc("DELETE /api/friends/{id}", s.handleFriendRemove)

	// 房间 / 社区服务器列表
	mux.HandleFunc("GET /api/rooms", s.handleRooms)
	mux.HandleFunc("POST /api/room/register", s.handleRoomRegister)
	mux.HandleFunc("POST /api/room/heartbeat", s.handleRoomHeartbeat)
	mux.HandleFunc("POST /api/room/unregister", s.handleRoomUnregister)
	mux.HandleFunc("GET /api/servers", s.handleServers)

	// 实时推送
	mux.HandleFunc("GET /api/ws", s.HandleWS)

	// 好友即时聊天 / 邀请进房
	mux.HandleFunc("GET /api/chat/{peerID}", s.handleChatGet)
	mux.HandleFunc("POST /api/chat/{peerID}", s.handleChatSend)
	mux.HandleFunc("POST /api/invite", s.handleInvite)

	// 自托管模组仓库
	mux.HandleFunc("GET /api/mods", s.handleModList)
	mux.HandleFunc("GET /api/mods/", s.handleModDownload)

	// ContentDB 代理（分页 + 游戏适配过滤）
	mux.HandleFunc("GET /api/cdb/mods", s.handleCdbMods)

	// 管理端 API 与后台页面
	mux.HandleFunc("GET /api/admin/stats", s.handleAdminStats)
	mux.HandleFunc("GET /api/admin/users", s.handleAdminUsers)
	mux.HandleFunc("POST /api/admin/users", s.handleAdminUserCreate)
	mux.HandleFunc("DELETE /api/admin/users/{id}", s.handleAdminUserDelete)
	// 房间管理
	mux.HandleFunc("GET /api/admin/rooms", s.handleAdminRooms)
	mux.HandleFunc("DELETE /api/admin/rooms/{id}", s.handleAdminRoomKick)
	// 固定服务器管理（创建/删除/启停）
	mux.HandleFunc("GET /api/admin/servers", s.handleAdminServers)
	mux.HandleFunc("POST /api/admin/servers", s.handleAdminServerCreate)
	mux.HandleFunc("DELETE /api/admin/servers/{name}", s.handleAdminServerDelete)
	mux.HandleFunc("POST /api/admin/servers/{name}/{action}", s.handleAdminServerAction)
	// 模组仓库管理
	mux.HandleFunc("GET /api/admin/mods", s.handleAdminModList)
	mux.HandleFunc("POST /api/admin/mods", s.handleAdminModUpload)
	mux.HandleFunc("DELETE /api/admin/mods/{file}", s.handleAdminModDelete)
	// 分享包管理
	mux.HandleFunc("GET /api/admin/packages", s.handleAdminPackages)
	mux.HandleFunc("DELETE /api/admin/packages/{id}", s.handleAdminPackageDelete)
	mux.Handle("GET /admin", http.RedirectHandler("/admin/", http.StatusFound))
	mux.Handle("GET /admin/", http.HandlerFunc(s.handleAdminPage))

	// 公告与客户端更新推送
	mux.HandleFunc("GET /api/announcements", s.handleAnnouncements)
	mux.HandleFunc("POST /api/announcements", s.handleAnnCreate)
	mux.HandleFunc("DELETE /api/announcements/{id}", s.handleAnnDelete)
	mux.HandleFunc("GET /api/client-update", s.handleClientUpdate)
	mux.HandleFunc("PUT /api/client-update", s.handleUpdateSet)

	// 工坊（分享包）
	mux.HandleFunc("GET /api/packages", s.handlePackageList)
	mux.HandleFunc("POST /api/packages", s.handlePackageUpload)
	mux.HandleFunc("GET /api/packages/mine", s.handlePackageMine)
	mux.HandleFunc("GET /api/packages/{id}", s.dispatchPackageDetail)
	mux.HandleFunc("DELETE /api/packages/{id}", s.handlePackageDelete)

	return withCORS(mux)
}

// dispatchPackageDetail 分发 /api/packages/{id} 的子路径。
func (s *Server) dispatchPackageDetail(w http.ResponseWriter, r *http.Request) {
	rest := strings.TrimPrefix(r.URL.Path, "/api/packages/")
	switch {
	case strings.HasSuffix(rest, "/download") && r.Method == http.MethodGet:
		s.handlePackageDownload(w, r)
	case strings.HasSuffix(rest, "/thumbnail") && r.Method == http.MethodGet:
		s.handlePackageThumb(w, r)
	case r.Method == http.MethodGet:
		s.handlePackageDetail(w, r)
	default:
		writeErr(w, 405, "方法不允许")
	}
}

// withCORS 允许启动器与本地开发页跨域访问。
func withCORS(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Access-Control-Allow-Origin", "*")
		w.Header().Set("Access-Control-Allow-Methods", "GET, POST, PATCH, PUT, DELETE, OPTIONS")
		w.Header().Set("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Admin-Token")
		if r.Method == http.MethodOptions {
			w.WriteHeader(http.StatusNoContent)
			return
		}
		next.ServeHTTP(w, r)
	})
}
