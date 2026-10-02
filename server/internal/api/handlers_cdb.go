package api

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strconv"
	"strings"
	"sync"
	"time"
)

// ---------- ContentDB 代理：分页 + 游戏适配过滤 ----------
//
// 上游 /api/packages/ 不支持服务端分页（仅 limit 生效，page/offset 被忽略），
// 官方客户端也是全量拉取后本地切片。这里由服务端代为拉取并缓存 10 分钟，
// 为模组中心提供稳定的 page/per_page 翻页与总数；
// game 参数按客户端所选游戏过滤，只列出适配该玩法的模组。

const (
	cdbUpstream  = "https://content.minetest.net"
	cdbCacheTTL  = 10 * time.Minute
	cdbFetchWait = 45 * time.Second
)

// cdbEntry 一份上游查询结果的缓存（loading 非 nil 表示正在拉取）。
type cdbEntry struct {
	loading chan struct{}
	fetched time.Time
	items   []json.RawMessage
	err     error
	loaded  bool
}

var (
	cdbMu    sync.Mutex
	cdbCache = map[string]*cdbEntry{}
)

// handleCdbMods 模组中心翻页代理：
// GET /api/cdb/mods?page=1&per_page=20&q=&sort=&game=
// 返回 {mods, total, page, per_page, pages}，mods 为上游原始条目切片。
func (s *Server) handleCdbMods(w http.ResponseWriter, r *http.Request) {
	q := r.URL.Query()
	up := url.Values{}
	up.Set("type", "mod")
	if g := strings.TrimSpace(q.Get("game")); g != "" {
		up.Set("game", g)
	}
	if kw := strings.TrimSpace(q.Get("q")); kw != "" {
		up.Set("q", kw)
	}
	if sd := strings.TrimSpace(q.Get("sort")); sd != "" && cdbSortOK[sd] {
		up.Set("sort", sd)
	}

	page, _ := strconv.Atoi(q.Get("page"))
	if page < 1 {
		page = 1
	}
	per, _ := strconv.Atoi(q.Get("per_page"))
	if per < 1 {
		per = 20
	}
	if per > 100 {
		per = 100
	}

	items, err := cdbFetch(up)
	if err != nil {
		writeErr(w, 502, "ContentDB 获取失败: "+err.Error())
		return
	}
	total := len(items)
	pages := (total + per - 1) / per
	if pages < 1 {
		pages = 1
	}
	if page > pages {
		page = pages
	}
	start := (page - 1) * per
	end := start + per
	if end > total {
		end = total
	}
	writeJSON(w, 200, map[string]any{
		"mods": items[start:end], "total": total, "page": page,
		"per_page": per, "pages": pages,
	})
}

// cdbSortOK 白名单：与 ContentDB 文档一致，防非法值触发上游 400。
var cdbSortOK = map[string]bool{
	"name": true, "title": true, "score": true, "reviews": true,
	"downloads": true, "created_at": true, "approved_at": true,
	"last_release": true,
}

// cdbFetch 带缓存与并发合并的上游拉取：同一查询只发一次请求，
// 拉取失败时若有过期数据则继续用旧数据兜底。
func cdbFetch(q url.Values) ([]json.RawMessage, error) {
	key := q.Encode()
	cdbMu.Lock()
	e := cdbCache[key]
	if e == nil {
		e = &cdbEntry{}
		cdbCache[key] = e
	}
	if e.loaded && time.Since(e.fetched) < cdbCacheTTL {
		defer cdbMu.Unlock()
		return e.items, nil
	}
	if e.loading != nil {
		ch := e.loading
		cdbMu.Unlock()
		select {
		case <-ch:
		case <-time.After(cdbFetchWait):
			return nil, fmt.Errorf("等待上游结果超时")
		}
		cdbMu.Lock()
		defer cdbMu.Unlock()
		if len(e.items) == 0 && e.err != nil {
			return nil, e.err
		}
		return e.items, nil
	}
	e.loading = make(chan struct{})
	ch := e.loading
	cdbMu.Unlock()

	items, ferr := cdbDownload(q)

	cdbMu.Lock()
	defer cdbMu.Unlock()
	if ferr != nil {
		e.err = ferr
		if len(e.items) == 0 {
			e.loaded = false
			e.loading = nil
			close(ch)
			return nil, ferr
		}
		// 拉取失败但有旧数据：继续用旧数据，fetched 不更新以便尽快重试。
	} else {
		e.items = items
		e.err = nil
		e.loaded = true
		e.fetched = time.Now()
	}
	e.loading = nil
	close(ch)
	return e.items, nil
}

// cdbDownload 向 ContentDB 拉取一次全量结果（不带 limit 即全量）。
func cdbDownload(q url.Values) ([]json.RawMessage, error) {
	ctx, cancel := context.WithTimeout(context.Background(), cdbFetchWait)
	defer cancel()
	req, err := http.NewRequestWithContext(
		ctx, http.MethodGet, cdbUpstream+"/api/packages/?"+q.Encode(), nil)
	if err != nil {
		return nil, err
	}
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != 200 {
		return nil, fmt.Errorf("上游返回 %d", resp.StatusCode)
	}
	body, err := io.ReadAll(io.LimitReader(resp.Body, 64<<20))
	if err != nil {
		return nil, err
	}
	var items []json.RawMessage
	if err := json.Unmarshal(body, &items); err != nil {
		return nil, fmt.Errorf("上游响应解析失败")
	}
	return items, nil
}
