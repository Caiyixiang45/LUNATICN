package api

import (
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"net/http"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"sync"
	"time"

	"lunaticn/server/internal/config"
)

// ---------- 公告与客户端更新推送 ----------
//
// 数据落在 data/announcements.json 与 data/client_update.json，
// 首次启动由 config.json 的 announcements / client_update 播种。
// 管理接口需携带 X-Admin-Token: <config.admin_token>。

const (
	annFileName = "announcements.json"
	updFileName = "client_update.json"
)

type noticeStore struct {
	mu       sync.RWMutex
	annPath  string
	updPath  string
	adminTok string
	anns     []config.Announcement
	upd      config.ClientUpdate
}

func newNoticeStore(dataDir, adminTok string, seedAnns []config.Announcement, seedUpd *config.ClientUpdate) *noticeStore {
	n := &noticeStore{
		annPath:  filepath.Join(dataDir, annFileName),
		updPath:  filepath.Join(dataDir, updFileName),
		adminTok: adminTok,
	}
	n.anns = loadAnnFile(n.annPath)
	if n.anns == nil {
		if seedAnns == nil {
			n.anns = []config.Announcement{}
		} else {
			n.anns = append([]config.Announcement{}, seedAnns...)
		}
		n.saveAnns()
	}
	if b, err := os.ReadFile(n.updPath); err == nil {
		_ = json.Unmarshal(b, &n.upd)
	} else if seedUpd != nil {
		n.upd = *seedUpd
		n.saveUpd()
	}
	return n
}

func loadAnnFile(path string) []config.Announcement {
	b, err := os.ReadFile(path)
	if err != nil {
		return nil
	}
	var list []config.Announcement
	if err := json.Unmarshal(b, &list); err != nil {
		return nil
	}
	return list
}

func (n *noticeStore) saveAnns() {
	writeJSONFile(n.annPath, n.anns)
}

func (n *noticeStore) saveUpd() {
	writeJSONFile(n.updPath, n.upd)
}

func writeJSONFile(path string, v any) {
	b, err := json.MarshalIndent(v, "", "  ")
	if err != nil {
		return
	}
	_ = os.WriteFile(path, b, 0o644)
}

// sorted 返回置顶优先、按时间倒序的公告快照。
func (n *noticeStore) sorted() []config.Announcement {
	n.mu.RLock()
	out := append([]config.Announcement{}, n.anns...)
	n.mu.RUnlock()
	sort.SliceStable(out, func(i, j int) bool {
		if out[i].Pinned != out[j].Pinned {
			return out[i].Pinned
		}
		return out[i].CreatedAt.After(out[j].CreatedAt)
	})
	return out
}

// ---------- 公开读取 ----------

// handleAnnouncements GET /api/announcements —— 公告列表（无需登录）。
func (s *Server) handleAnnouncements(w http.ResponseWriter, r *http.Request) {
	list := s.Notices.sorted()
	if list == nil {
		list = []config.Announcement{}
	}
	writeJSON(w, 200, map[string]any{"announcements": list})
}

// handleClientUpdate GET /api/client-update?version=1.0.0 —— 更新检查（无需登录）。
func (s *Server) handleClientUpdate(w http.ResponseWriter, r *http.Request) {
	cur := strings.TrimSpace(r.URL.Query().Get("version"))
	s.Notices.mu.RLock()
	upd := s.Notices.upd
	s.Notices.mu.RUnlock()

	has := upd.Version != "" && cur != "" && compareVer(upd.Version, cur) > 0
	writeJSON(w, 200, map[string]any{
		"has_update":   has,
		"current":      cur,
		"latest":       upd.Version,
		"notes":        upd.Notes,
		"mirrors":      upd.Mirrors,
		"published_at": upd.PublishedAt,
	})
}

// compareVer 比较 "1.2.3" 形式版本号：a>b 返回 1，a<b 返回 -1，相等返回 0。
func compareVer(a, b string) int {
	pa, pb := strings.Split(a, "."), strings.Split(b, ".")
	for i := 0; i < len(pa) || i < len(pb); i++ {
		na, nb := 0, 0
		if i < len(pa) {
			na = atoiSafe(pa[i])
		}
		if i < len(pb) {
			nb = atoiSafe(pb[i])
		}
		if na != nb {
			if na > nb {
				return 1
			}
			return -1
		}
	}
	return 0
}

func atoiSafe(s string) int {
	n := 0
	for _, c := range s {
		if c < '0' || c > '9' {
			break
		}
		n = n*10 + int(c-'0')
	}
	return n
}

// ---------- 管理写入 ----------

func (s *Server) adminOK(r *http.Request) bool {
	if s.Cfg.AdminToken == "" {
		return false
	}
	return r.Header.Get("X-Admin-Token") == s.Cfg.AdminToken
}

// handleAnnCreate POST /api/announcements —— 新增公告（管理令牌）。
func (s *Server) handleAnnCreate(w http.ResponseWriter, r *http.Request) {
	if !s.adminOK(r) {
		writeErr(w, 403, "管理令牌无效")
		return
	}
	var req struct {
		Title  string `json:"title"`
		Body   string `json:"body"`
		Level  string `json:"level"`
		Pinned bool   `json:"pinned"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeErr(w, 400, "请求格式错误")
		return
	}
	req.Title = strings.TrimSpace(req.Title)
	req.Body = strings.TrimSpace(req.Body)
	if req.Title == "" || req.Body == "" {
		writeErr(w, 400, "标题与正文不能为空")
		return
	}
	switch req.Level {
	case "", "info":
		req.Level = "info"
	case "warning", "update":
	default:
		writeErr(w, 400, "level 仅支持 info / warning / update")
		return
	}
	idB := make([]byte, 6)
	_, _ = rand.Read(idB)
	ann := config.Announcement{
		ID:        hex.EncodeToString(idB),
		Title:     req.Title,
		Body:      req.Body,
		Level:     req.Level,
		Pinned:    req.Pinned,
		CreatedAt: time.Now(),
	}
	s.Notices.mu.Lock()
	s.Notices.anns = append(s.Notices.anns, ann)
	s.Notices.saveAnns()
	s.Notices.mu.Unlock()
	s.WsHub.BroadcastNotice()
	writeJSON(w, 201, ann)
}

// handleAnnDelete DELETE /api/announcements/{id} —— 删除公告（管理令牌）。
func (s *Server) handleAnnDelete(w http.ResponseWriter, r *http.Request) {
	if !s.adminOK(r) {
		writeErr(w, 403, "管理令牌无效")
		return
	}
	id := strings.TrimPrefix(r.URL.Path, "/api/announcements/")
	s.Notices.mu.Lock()
	out := s.Notices.anns[:0]
	found := false
	for _, a := range s.Notices.anns {
		if a.ID == id {
			found = true
			continue
		}
		out = append(out, a)
	}
	if found {
		s.Notices.anns = out
		s.Notices.saveAnns()
	}
	s.Notices.mu.Unlock()
	if !found {
		writeErr(w, 404, "公告不存在")
		return
	}
	s.WsHub.BroadcastNotice()
	writeJSON(w, 200, map[string]string{"deleted": id})
}

// handleUpdateSet PUT /api/client-update —— 设置客户端更新推送（管理令牌）。
func (s *Server) handleUpdateSet(w http.ResponseWriter, r *http.Request) {
	if !s.adminOK(r) {
		writeErr(w, 403, "管理令牌无效")
		return
	}
	var upd config.ClientUpdate
	if err := json.NewDecoder(r.Body).Decode(&upd); err != nil {
		writeErr(w, 400, "请求格式错误")
		return
	}
	upd.Version = strings.TrimSpace(upd.Version)
	if upd.Version == "" {
		writeErr(w, 400, "version 不能为空")
		return
	}
	if upd.PublishedAt.IsZero() {
		upd.PublishedAt = time.Now()
	}
	s.Notices.mu.Lock()
	s.Notices.upd = upd
	s.Notices.saveUpd()
	s.Notices.mu.Unlock()
	s.WsHub.BroadcastNotice()
	writeJSON(w, 200, upd)
}
