// Package packages 实现地图/模组分享包的上传、下载与检索。
// 包格式为 .lnpkg（zip），结构见 docs/05-分享包格式.md。
package packages

import (
	"archive/zip"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
	"time"

	"lunaticn/server/internal/store"
)

// Manifest 包内 manifest.json 的内容。
type Manifest struct {
	Type        string   `json:"type"` // map | mod
	Name        string   `json:"name"`
	Author      string   `json:"author"`
	Version     string   `json:"version"`
	Description string   `json:"description"`
	GameID      string   `json:"gameid"`
	Engine      string   `json:"engine"`
	Depends     []string `json:"depends"`
}

// Service 分享包服务。
type Service struct {
	store     *store.Store
	uploadDir string // 包文件目录
	thumbDir  string // 缩略图目录
	maxSize   int64  // 单包上限
}

// NewService 创建分享服务。
func NewService(st *store.Store, dataDir string, maxSizeMB int64) *Service {
	up := filepath.Join(dataDir, "packages")
	th := filepath.Join(dataDir, "thumbnails")
	_ = os.MkdirAll(up, 0o755)
	_ = os.MkdirAll(th, 0o755)
	if maxSizeMB <= 0 {
		maxSizeMB = 512
	}
	return &Service{store: st, uploadDir: up, thumbDir: th, maxSize: maxSizeMB << 20}
}

// ---------- 校验 ----------

func validType(t string) bool { return t == "map" || t == "mod" }

// ValidateZip 校验 zip 结构并读取 manifest：
// 必须含 manifest.json 与 content/，禁止路径穿越（..、绝对路径）。
func ValidateZip(path string) (*Manifest, error) {
	zr, err := zip.OpenReader(path)
	if err != nil {
		return nil, fmt.Errorf("无法读取包文件: %w", err)
	}
	defer zr.Close()

	var mf *Manifest
	for _, f := range zr.File {
		name := strings.ReplaceAll(f.Name, "\\", "/")
		if strings.HasPrefix(name, "/") || strings.Contains(name, "..") {
			return nil, errors.New("包内含非法路径，已拒绝")
		}
		if name == "manifest.json" {
			rc, err := f.Open()
			if err != nil {
				return nil, err
			}
			var m Manifest
			err = json.NewDecoder(rc).Decode(&m)
			rc.Close()
			if err != nil {
				return nil, errors.New("manifest.json 解析失败")
			}
			mf = &m
		}
	}
	if mf == nil {
		return nil, errors.New("缺少 manifest.json")
	}
	if !validType(mf.Type) {
		return nil, errors.New("manifest.type 必须是 map 或 mod")
	}
	if mf.Name == "" || mf.Version == "" {
		return nil, errors.New("manifest 缺少 name 或 version")
	}
	hasContent := false
	for _, f := range zr.File {
		if strings.HasPrefix(strings.ReplaceAll(f.Name, "\\", "/"), "content/") {
			hasContent = true
			break
		}
	}
	if !hasContent {
		return nil, errors.New("包内缺少 content/ 目录")
	}
	return mf, nil
}

// ---------- 上传 ----------

// SaveUpload 保存上传文件，完成校验与元数据登记。
// r 为上传的文件流，thumb 可为 nil。
func (s *Service) SaveUpload(author store.User, r io.Reader, thumb io.Reader) (store.PackageMeta, error) {
	id := newID()
	fileName := id + ".lnpkg"
	dst, err := os.Create(filepath.Join(s.uploadDir, fileName))
	if err != nil {
		return store.PackageMeta{}, err
	}
	n, err := io.Copy(dst, io.LimitReader(r, s.maxSize+1))
	closeErr := dst.Close()
	if err != nil {
		os.Remove(filepath.Join(s.uploadDir, fileName))
		return store.PackageMeta{}, err
	}
	if closeErr != nil {
		return store.PackageMeta{}, closeErr
	}
	if n > s.maxSize {
		os.Remove(filepath.Join(s.uploadDir, fileName))
		return store.PackageMeta{}, fmt.Errorf("包超过大小上限 %dMB", s.maxSize>>20)
	}

	full := filepath.Join(s.uploadDir, fileName)
	mf, err := ValidateZip(full)
	if err != nil {
		os.Remove(full)
		return store.PackageMeta{}, err
	}

	meta := store.PackageMeta{
		ID:          id,
		Type:        mf.Type,
		Name:        mf.Name,
		Author:      author.ID,
		AuthorName:  author.Nickname,
		Version:     mf.Version,
		Description: mf.Description,
		GameID:      mf.GameID,
		Engine:      mf.Engine,
		Depends:     mf.Depends,
		Size:        n,
		CreatedAt:   time.Now(),
		FileName:    fileName,
	}
	if meta.AuthorName == "" {
		meta.AuthorName = author.Username
	}

	// 缩略图（可选）：仅存 png/jpg，限制 2MB
	if thumb != nil {
		tb, err := io.ReadAll(io.LimitReader(thumb, 2<<20))
		if err == nil && len(tb) > 0 && looksLikeImage(tb) {
			tname := id + imgExt(tb)
			if err := os.WriteFile(filepath.Join(s.thumbDir, tname), tb, 0o644); err == nil {
				meta.Thumbnail = tname
			}
		}
	}

	if err := s.store.AddPackage(meta); err != nil {
		os.Remove(full)
		if meta.Thumbnail != "" {
			os.Remove(filepath.Join(s.thumbDir, meta.Thumbnail))
		}
		return store.PackageMeta{}, err
	}
	return meta, nil
}

// ---------- 下载 ----------

// Open 下载文件句柄并累计下载数。
func (s *Service) Open(id string) (*os.File, store.PackageMeta, error) {
	meta, ok := s.store.GetPackage(id)
	if !ok {
		return nil, store.PackageMeta{}, errors.New("包不存在")
	}
	f, err := os.Open(filepath.Join(s.uploadDir, meta.FileName))
	if err != nil {
		return nil, store.PackageMeta{}, errors.New("包文件缺失")
	}
	s.store.IncDownloads(id)
	return f, meta, nil
}

// Thumbnail 打开缩略图。
func (s *Service) Thumbnail(id string) (*os.File, error) {
	meta, ok := s.store.GetPackage(id)
	if !ok || meta.Thumbnail == "" {
		return nil, errors.New("缩略图不存在")
	}
	return os.Open(filepath.Join(s.thumbDir, meta.Thumbnail))
}

// Delete 删除包（仅作者本人）。
func (s *Service) Delete(id, uid string) error {
	meta, ok := s.store.GetPackage(id)
	if !ok {
		return errors.New("包不存在")
	}
	if meta.Author != uid {
		return errors.New("仅作者可删除")
	}
	s.removeFiles(meta)
	return nil
}

// DeleteAny 管理端强制删除包（跳过作者校验）。
func (s *Service) DeleteAny(id string) error {
	meta, ok := s.store.GetPackage(id)
	if !ok {
		return errors.New("包不存在")
	}
	s.removeFiles(meta)
	return nil
}

// removeFiles 删除元数据与磁盘上的包文件、缩略图。
func (s *Service) removeFiles(meta store.PackageMeta) {
	s.store.DeletePackage(meta.ID)
	os.Remove(filepath.Join(s.uploadDir, meta.FileName))
	if meta.Thumbnail != "" {
		os.Remove(filepath.Join(s.thumbDir, meta.Thumbnail))
	}
}

// Search 检索。
func (s *Service) Search(typeQuery, kw string, limit, offset int) (int, []store.PackageMeta) {
	return s.store.ListPackages(typeQuery, kw, limit, offset)
}

// Mine 我的上传。
func (s *Service) Mine(uid string) []store.PackageMeta {
	return s.store.ListUserPackages(uid)
}

// ---------- 工具 ----------

func newID() string {
	b := make([]byte, 8)
	_, _ = rand.Read(b)
	return hex.EncodeToString(b)
}

func looksLikeImage(b []byte) bool {
	if len(b) > 8 && b[0] == 0x89 && b[1] == 0x50 {
		return true // png
	}
	return len(b) > 3 && b[0] == 0xFF && b[1] == 0xD8 // jpg
}

func imgExt(b []byte) string {
	if len(b) > 8 && b[0] == 0x89 && b[1] == 0x50 {
		return ".png"
	}
	return ".jpg"
}
