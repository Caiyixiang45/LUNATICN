package api

import (
	"encoding/json"
	"io"
	"net/http"
	"strings"
	"time"

	"lunaticn/server/internal/lobby"
)

// ---------- 房间（联机大厅 / 社区服务器列表） ----------

// handleRooms 列表：GET /api/rooms
// 服务器列表由社区服务统一维护，roomd 与启动器都注册到这里。
func (s *Server) handleRooms(w http.ResponseWriter, r *http.Request) {
	viewerID := ""
	friends := map[string]bool{}
	if u, _, err := s.authUser(r); err == nil {
		viewerID = u.ID
		friends = s.friendSet(u.ID)
	}
	rooms := s.Hub.List(viewerID, friends)
	if rooms == nil {
		rooms = []lobby.Room{}
	}
	writeJSON(w, 200, map[string]any{"rooms": rooms, "servers": rooms})
}

// handleRoomRegister 注册/续期房间：POST /api/room/register
// 调用方：roomd（凭 token）与启动器（凭用户令牌）。
func (s *Server) handleRoomRegister(w http.ResponseWriter, r *http.Request) {
	u, _, err := s.authUser(r)
	if err != nil {
		writeErr(w, 401, err.Error())
		return
	}
	var in struct {
		Token       string `json:"token"`
		Name        string `json:"name"`
		Host        string `json:"host"`
		Port        int    `json:"port"`
		GameID      string `json:"gameid"`
		World       string `json:"world"`
		MaxPlayers  int    `json:"max_players"`
		Players     int    `json:"players"`
		HasPassword bool   `json:"has_password"`
		Private     bool   `json:"private"`
		Engine      string `json:"engine"`
		Protocol    int    `json:"protocol"`
		Source      string `json:"source"`
		Description string `json:"description"`
	}
	if err := json.NewDecoder(r.Body).Decode(&in); err != nil {
		writeErr(w, 400, "请求格式错误")
		return
	}
	if in.Source == "" {
		in.Source = "launcher"
	}
	if in.MaxPlayers <= 0 {
		in.MaxPlayers = 8
	}
	room, token, err := s.Hub.Register(lobby.RegisterInput{
		Token: in.Token, Name: in.Name, Owner: u.ID, OwnerName: u.Nickname,
		Host: in.Host, Port: in.Port, GameID: in.GameID, World: in.World,
		MaxPlayers: in.MaxPlayers, Players: in.Players, HasPassword: in.HasPassword,
		Private: in.Private, Engine: in.Engine, Protocol: in.Protocol,
		Source: in.Source, Description: in.Description,
	})
	if err != nil {
		apiError(w, err)
		return
	}
	writeJSON(w, 200, map[string]any{"room": room, "room_token": token})
}

// handleRoomHeartbeat 心跳：POST /api/room/heartbeat
// body: {token, players}
func (s *Server) handleRoomHeartbeat(w http.ResponseWriter, r *http.Request) {
	u, _, err := s.authUser(r)
	if err != nil {
		writeErr(w, 401, err.Error())
		return
	}
	var req struct {
		Token   string `json:"token"`
		Players int    `json:"players"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeErr(w, 400, "请求格式错误")
		return
	}
	if err := s.Hub.Heartbeat(req.Token, u.ID, req.Players); err != nil {
		apiError(w, err)
		return
	}
	writeJSON(w, 200, map[string]string{"status": "ok"})
}

// handleRoomUnregister 注销：POST /api/room/unregister
func (s *Server) handleRoomUnregister(w http.ResponseWriter, r *http.Request) {
	u, _, err := s.authUser(r)
	if err != nil {
		writeErr(w, 401, err.Error())
		return
	}
	var req struct {
		Token string `json:"token"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeErr(w, 400, "请求格式错误")
		return
	}
	if err := s.Hub.Unregister(req.Token, u.ID); err != nil {
		apiError(w, err)
		return
	}
	writeJSON(w, 200, map[string]string{"status": "ok"})
}

// ---------- 固定服务器 ----------

// handleServers 官方固定服务器列表：GET /api/servers
func (s *Server) handleServers(w http.ResponseWriter, r *http.Request) {
	type pub struct {
		Name    string `json:"name"`
		Port    int    `json:"port"`
		Running bool   `json:"running"`
	}
	var out []pub
	for _, st := range s.Fixed.StatusList() {
		out = append(out, pub{st.Name, st.Port, st.Running})
	}
	if out == nil {
		out = []pub{}
	}
	writeJSON(w, 200, map[string]any{"servers": out})
}

// ---------- 分享包（工坊） ----------

// handlePackageList 检索：GET /api/packages?type=map|mod&q=&limit=&offset=
func (s *Server) handlePackageList(w http.ResponseWriter, r *http.Request) {
	q := r.URL.Query()
	limit := queryInt(r, "limit", 20)
	offset := queryInt(r, "offset", 0)
	if limit > 100 {
		limit = 100
	}
	total, list := s.Pkgs.Search(q.Get("type"), q.Get("q"), limit, offset)
	if list == nil {
		list = nil
	}
	writeJSON(w, 200, map[string]any{"total": total, "packages": list})
}

// handlePackageMine 我的上传：GET /api/packages/mine
func (s *Server) handlePackageMine(w http.ResponseWriter, r *http.Request) {
	u, _, err := s.authUser(r)
	if err != nil {
		writeErr(w, 401, err.Error())
		return
	}
	writeJSON(w, 200, map[string]any{"packages": s.Pkgs.Mine(u.ID)})
}

// handlePackageUpload 上传：POST /api/packages
// multipart 字段：file（必填 .lnpkg/zip）、thumbnail（可选图片）
func (s *Server) handlePackageUpload(w http.ResponseWriter, r *http.Request) {
	u, _, err := s.authUser(r)
	if err != nil {
		writeErr(w, 401, err.Error())
		return
	}
	r.Body = http.MaxBytesReader(w, r.Body, 640<<20)
	if err := r.ParseMultipartForm(640 << 20); err != nil {
		writeErr(w, 400, "解析上传失败，可能超过大小限制")
		return
	}
	file, _, err := r.FormFile("file")
	if err != nil {
		writeErr(w, 400, "缺少 file 字段")
		return
	}
	defer file.Close()

	var thumb io.Reader
	if tf, _, err := r.FormFile("thumbnail"); err == nil {
		defer tf.Close()
		thumb = tf
	}

	pm, err := s.Pkgs.SaveUpload(u, file, thumb)
	if err != nil {
		apiError(w, err)
		return
	}
	writeJSON(w, 201, pm)
}

// handlePackageDownload 下载：GET /api/packages/{id}/download
func (s *Server) handlePackageDownload(w http.ResponseWriter, r *http.Request) {
	id := strings.TrimSuffix(strings.TrimPrefix(r.URL.Path, "/api/packages/"), "/download")
	f, meta, err := s.Pkgs.Open(id)
	if err != nil {
		writeErr(w, 404, err.Error())
		return
	}
	defer f.Close()
	w.Header().Set("Content-Type", "application/octet-stream")
	w.Header().Set("Content-Disposition", `attachment; filename="`+safeName(meta.Name)+`.lnpkg"`)
	http.ServeContent(w, r, meta.FileName, meta.CreatedAt, f)
}

// handlePackageThumb 缩略图：GET /api/packages/{id}/thumbnail
func (s *Server) handlePackageThumb(w http.ResponseWriter, r *http.Request) {
	id := strings.TrimSuffix(strings.TrimPrefix(r.URL.Path, "/api/packages/"), "/thumbnail")
	f, err := s.Pkgs.Thumbnail(id)
	if err != nil {
		writeErr(w, 404, err.Error())
		return
	}
	defer f.Close()
	if st, err := f.Stat(); err == nil {
		http.ServeContent(w, r, "thumb.png", st.ModTime(), f)
		return
	}
	http.ServeContent(w, r, "thumb.png", time.Time{}, f)
}

// handlePackageDelete 删除：DELETE /api/packages/{id}
func (s *Server) handlePackageDelete(w http.ResponseWriter, r *http.Request) {
	u, _, err := s.authUser(r)
	if err != nil {
		writeErr(w, 401, err.Error())
		return
	}
	id := strings.TrimPrefix(r.URL.Path, "/api/packages/")
	if err := s.Pkgs.Delete(id, u.ID); err != nil {
		apiError(w, err)
		return
	}
	writeJSON(w, 200, map[string]string{"status": "ok"})
}

// handlePackageDetail 详情：GET /api/packages/{id}
func (s *Server) handlePackageDetail(w http.ResponseWriter, r *http.Request) {
	id := strings.TrimPrefix(r.URL.Path, "/api/packages/")
	meta, ok := s.Store.GetPackage(id)
	if !ok {
		writeErr(w, 404, "包不存在")
		return
	}
	writeJSON(w, 200, meta)
}

func safeName(s string) string {
	var b strings.Builder
	for _, r := range s {
		if r < 32 || strings.ContainsRune(`/\:*?"<>|`, r) {
			b.WriteByte('_')
		} else {
			b.WriteRune(r)
		}
	}
	if b.Len() == 0 {
		return "package"
	}
	return b.String()
}
