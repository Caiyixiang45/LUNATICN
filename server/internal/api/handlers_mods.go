package api

import (
	"archive/zip"
	"errors"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strconv"
	"strings"
)

// ---------- 自托管模组仓库 ----------
//
// 仓库目录由 config.json 的 mods_repo 指定（相对路径按配置文件所在目录解析）。
// 目录下的每个 *.zip 即一个可安装的 Luanti 模组，zip 内（根目录或一层子目录）
// 带 mod.conf 描述文件。

// modZipRe 约束下载文件名，杜绝路径穿越。
var modZipRe = regexp.MustCompile(`^[A-Za-z0-9_\-.]+\.zip$`)

// modInfo 是 GET /api/mods 返回的单个模组。
type modInfo struct {
	Filename    string `json:"filename"`
	Name        string `json:"name"`
	Title       string `json:"title"`
	Description string `json:"description"`
	Author      string `json:"author"`
	Version     string `json:"version"`
	Depends     string `json:"depends"`
	Size        int64  `json:"size"`
}

// handleModList 模组列表：GET /api/mods?page=1&per_page=20&q=关键字
// 不带分页参数时返回全量（兼容旧客户端）；带参数时返回当前页与总数。
func (s *Server) handleModList(w http.ResponseWriter, r *http.Request) {
	q := r.URL.Query()
	all := s.listMods()
	if kw := strings.TrimSpace(q.Get("q")); kw != "" {
		kw = strings.ToLower(kw)
		filtered := make([]modInfo, 0, len(all))
		for _, m := range all {
			if strings.Contains(strings.ToLower(m.Name), kw) ||
				strings.Contains(strings.ToLower(m.Title), kw) ||
				strings.Contains(strings.ToLower(m.Description), kw) {
				filtered = append(filtered, m)
			}
		}
		all = filtered
	}
	total := len(all)
	page, _ := strconv.Atoi(q.Get("page"))
	per, _ := strconv.Atoi(q.Get("per_page"))
	if page <= 0 || per <= 0 {
		writeJSON(w, 200, map[string]any{
			"mods": all, "total": total, "page": 1,
			"per_page": total, "pages": 1,
		})
		return
	}
	if per > 100 {
		per = 100
	}
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
		"mods": all[start:end], "total": total, "page": page,
		"per_page": per, "pages": pages,
	})
}

// listMods 扫描模组仓库目录，解析每个 zip 的 mod.conf。
func (s *Server) listMods() []modInfo {
	dir := s.Cfg.ModsRepo
	entries, err := os.ReadDir(dir)
	if err != nil {
		// 目录不存在视为仓库为空，保持接口可用。
		return []modInfo{}
	}
	out := make([]modInfo, 0, len(entries))
	for _, e := range entries {
		if e.IsDir() || !strings.HasSuffix(strings.ToLower(e.Name()), ".zip") {
			continue
		}
		m := modInfo{Filename: e.Name(), Name: strings.TrimSuffix(e.Name(), ".zip")}
		if info, err := e.Info(); err == nil {
			m.Size = info.Size()
		}
		readModConf(filepath.Join(dir, e.Name()), &m)
		out = append(out, m)
	}
	sort.Slice(out, func(i, j int) bool { return out[i].Filename < out[j].Filename })
	return out
}

// readModConf 打开 zip 读取 mod.conf（根目录或一层子目录）。
// 无法作为 zip 打开时仅保留文件名兜底信息；缺 mod.conf 时同样以文件名兜底。
func readModConf(zipPath string, m *modInfo) {
	zr, err := zip.OpenReader(zipPath)
	if err != nil {
		return
	}
	defer zr.Close()

	var target *zip.File
	for _, f := range zr.File {
		if strings.TrimSuffix(filepath.Base(filepath.ToSlash(f.Name)), "/") != "mod.conf" {
			continue
		}
		depth := strings.Count(strings.Trim(filepath.ToSlash(f.Name), "/"), "/")
		if depth > 1 {
			continue
		}
		if target == nil || depth == 0 {
			target = f
		}
		if depth == 0 {
			break
		}
	}
	if target == nil {
		return
	}
	rc, err := target.Open()
	if err != nil {
		return
	}
	defer rc.Close()
	raw, err := io.ReadAll(io.LimitReader(rc, 64<<10))
	if err != nil {
		return
	}
	conf := parseModConf(string(raw))
	if v := conf["name"]; v != "" {
		m.Name = v
	}
	m.Title = conf["title"]
	m.Description = conf["description"]
	m.Author = conf["author"]
	m.Version = conf["version"]
	m.Depends = conf["depends"]
}

// parseModConf 解析 KEY=VALUE 文本，忽略空行与 # 注释。
func parseModConf(text string) map[string]string {
	out := map[string]string{}
	for _, line := range strings.Split(text, "\n") {
		line = strings.TrimSpace(line)
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		i := strings.IndexByte(line, '=')
		if i <= 0 {
			continue
		}
		key := strings.TrimSpace(line[:i])
		val := strings.TrimSpace(line[i+1:])
		if key == "" {
			continue
		}
		out[key] = val
	}
	return out
}

// handleModDownload 模组下载：GET /api/mods/{file}.zip
func (s *Server) handleModDownload(w http.ResponseWriter, r *http.Request) {
	name := strings.TrimPrefix(r.URL.Path, "/api/mods/")
	if !modZipRe.MatchString(name) {
		writeErr(w, 400, "模组文件名不合法")
		return
	}
	path := filepath.Join(s.Cfg.ModsRepo, name)
	f, err := os.Open(path)
	if err != nil {
		writeErr(w, 404, "模组不存在")
		return
	}
	defer f.Close()
	st, err := f.Stat()
	if err != nil || st.IsDir() {
		writeErr(w, 404, "模组不存在")
		return
	}
	w.Header().Set("Content-Type", "application/zip")
	w.Header().Set("Content-Disposition", `attachment; filename="`+name+`"`)
	http.ServeContent(w, r, name, st.ModTime(), f)
}

// ---------- 管理端：模组仓库维护 ----------

// maxModZip 上传模组 zip 上限 128MB。
const maxModZip = 128 << 20

// handleAdminModUpload 模组上传：POST /api/admin/mods（multipart 字段 file）。
// 校验为合法 zip 且含 mod.conf/init.lua/modpack.conf，文件名清洗后落盘。
func (s *Server) handleAdminModUpload(w http.ResponseWriter, r *http.Request) {
	if !s.requireAdmin(w, r) {
		return
	}
	r.Body = http.MaxBytesReader(w, r.Body, maxModZip+4096)
	file, hdr, err := r.FormFile("file")
	if err != nil {
		writeErr(w, 400, "请上传字段 file（multipart/form-data）")
		return
	}
	defer file.Close()

	name := sanitizeModFilename(hdr.Filename)
	if name == "" {
		writeErr(w, 400, "文件名无效")
		return
	}
	if err := os.MkdirAll(s.Cfg.ModsRepo, 0o755); err != nil {
		writeErr(w, 500, "无法创建模组仓库目录")
		return
	}
	final := filepath.Join(s.Cfg.ModsRepo, name)
	if _, err := os.Stat(final); err == nil {
		writeErr(w, 409, "同名模组已存在，请先删除再上传")
		return
	}
	tmp := final + ".uploading"
	dst, err := os.Create(tmp)
	if err != nil {
		writeErr(w, 500, "无法写入模组仓库")
		return
	}
	n, cerr := io.Copy(dst, io.LimitReader(file, maxModZip+1))
	if cerr != nil {
		dst.Close()
		os.Remove(tmp)
		writeErr(w, 500, "写入失败")
		return
	}
	if err := dst.Close(); err != nil {
		os.Remove(tmp)
		writeErr(w, 500, "写入失败")
		return
	}
	if n > maxModZip {
		os.Remove(tmp)
		writeErr(w, 400, "模组 zip 超过 128MB 上限")
		return
	}
	if err := validateModZip(tmp); err != nil {
		os.Remove(tmp)
		writeErr(w, 400, err.Error())
		return
	}
	if err := os.Rename(tmp, final); err != nil {
		os.Remove(tmp)
		writeErr(w, 500, "保存失败")
		return
	}
	writeJSON(w, 201, map[string]any{"ok": true, "filename": name})
}

// handleAdminModDelete 删除仓库模组：DELETE /api/admin/mods/{file}
func (s *Server) handleAdminModDelete(w http.ResponseWriter, r *http.Request) {
	if !s.requireAdmin(w, r) {
		return
	}
	name := strings.TrimSpace(r.PathValue("file"))
	if !modZipRe.MatchString(name) {
		writeErr(w, 400, "模组文件名不合法")
		return
	}
	path := filepath.Join(s.Cfg.ModsRepo, name)
	if _, err := os.Stat(path); err != nil {
		writeErr(w, 404, "模组不存在")
		return
	}
	if err := os.Remove(path); err != nil {
		writeErr(w, 500, "删除失败")
		return
	}
	writeJSON(w, 200, map[string]any{"ok": true})
}

// sanitizeModFilename 清洗上传文件名：仅保留安全字符并强制 .zip 后缀。
func sanitizeModFilename(orig string) string {
	base := filepath.Base(strings.ReplaceAll(orig, "\\", "/"))
	if modZipRe.MatchString(base) {
		return base
	}
	stem := strings.TrimSuffix(base, ".zip")
	var b strings.Builder
	for _, r := range stem {
		switch {
		case r >= 'a' && r <= 'z', r >= 'A' && r <= 'Z',
			r >= '0' && r <= '9', r == '_', r == '-', r == '.':
			b.WriteRune(r)
		default:
			b.WriteByte('_')
		}
	}
	out := strings.Trim(b.String(), "._-")
	if out == "" {
		out = "mod"
	}
	if len(out) > 80 {
		out = out[:80]
	}
	return out + ".zip"
}

// validateModZip 校验 zip 为有效 Luanti 模组/模组包且无路径穿越。
func validateModZip(zipPath string) error {
	zr, err := zip.OpenReader(zipPath)
	if err != nil {
		return errors.New("不是有效的 zip 压缩包")
	}
	defer zr.Close()
	if len(zr.File) == 0 {
		return errors.New("压缩包为空")
	}
	found := false
	for _, f := range zr.File {
		norm := strings.ReplaceAll(f.Name, "\\", "/")
		if strings.HasPrefix(norm, "/") || strings.Contains(norm, "..") {
			return errors.New("压缩包含非法路径，已拒绝")
		}
		depth := strings.Count(strings.Trim(norm, "/"), "/")
		if depth > 1 {
			continue
		}
		base := filepath.Base(norm)
		if base == "mod.conf" || base == "modpack.conf" || base == "init.lua" {
			found = true
			break
		}
	}
	if !found {
		return errors.New("压缩包中未找到 mod.conf / modpack.conf / init.lua，不是有效模组")
	}
	return nil
}
