// Package store 提供 JSON 文件持久化存储（用户、好友、分享包元数据）。
package store

import (
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"sync"
	"time"
)

// User 平台账号。
type User struct {
	ID           string    `json:"id"`
	Username     string    `json:"username"` // 登录名（小写唯一）
	Nickname     string    `json:"nickname"` // 展示名
	PasswordHash string    `json:"password_hash"`
	CreatedAt    time.Time `json:"created_at"`
}

// Friend 好友关系（双向，仅当双方互相确认后存在）。
type Friend struct {
	UserA string    `json:"user_a"` // 较小 ID，保证唯一性
	UserB string    `json:"user_b"`
	Since time.Time `json:"since"`
}

// FriendRequest 待处理的好友请求。
type FriendRequest struct {
	From      string    `json:"from"`
	To        string    `json:"to"`
	CreatedAt time.Time `json:"created_at"`
}

// PackageMeta 分享包（地图/模组）元数据。
type PackageMeta struct {
	ID          string    `json:"id"`
	Type        string    `json:"type"` // map | mod
	Name        string    `json:"name"`
	Author      string    `json:"author"`      // 用户 ID
	AuthorName  string    `json:"author_name"` // 展示名（冗余，便于列表渲染）
	Version     string    `json:"version"`
	Description string    `json:"description"`
	GameID      string    `json:"gameid"`
	Engine      string    `json:"engine"`
	Depends     []string  `json:"depends"`
	Size        int64     `json:"size"`
	Downloads   int       `json:"downloads"`
	CreatedAt   time.Time `json:"created_at"`
	FileName    string    `json:"file_name"` // 存储文件名（服务端生成）
	Thumbnail   string    `json:"thumbnail"` // 缩略图文件名，可空
}

// ChatMessage 好友间即时聊天消息（双向会话按 From/To 成对存储）。
type ChatMessage struct {
	ID        int64  `json:"id"`
	From      string `json:"from"`
	To        string `json:"to"`
	Text      string `json:"text"`
	CreatedAt int64  `json:"created_at"` // Unix 毫秒
}

// maxMessages 聊天消息全量保留上限，超出后裁掉最旧的。
const maxMessages = 5000

// dataFile 是磁盘上的文件结构。
type dataFile struct {
	Users     []User          `json:"users"`
	Friends   []Friend        `json:"friends"`
	Requests  []FriendRequest `json:"friend_requests"`
	Packages  []PackageMeta   `json:"packages"`
	Messages  []ChatMessage   `json:"messages"`
	MsgSeq    int64           `json:"msg_seq"`       // 消息 ID 自增计数
	TokenVers int             `json:"token_version"` // 全局注销令牌用
}

// Store 进程内存储：内存持有 + 写时落盘。
type Store struct {
	mu   sync.RWMutex
	path string
	data dataFile
}

// Open 加载（或初始化）数据文件。
func Open(dataDir string) (*Store, error) {
	if err := os.MkdirAll(dataDir, 0o755); err != nil {
		return nil, err
	}
	s := &Store{path: filepath.Join(dataDir, "db.json")}
	b, err := os.ReadFile(s.path)
	if errors.Is(err, os.ErrNotExist) {
		return s, s.flushLocked()
	}
	if err != nil {
		return nil, fmt.Errorf("读取数据文件失败: %w", err)
	}
	if err := json.Unmarshal(b, &s.data); err != nil {
		return nil, fmt.Errorf("数据文件损坏: %w", err)
	}
	return s, nil
}

// flushLocked 必须在持有锁时调用。
func (s *Store) flushLocked() error {
	b, err := json.MarshalIndent(&s.data, "", "  ")
	if err != nil {
		return err
	}
	tmp := s.path + ".tmp"
	if err := os.WriteFile(tmp, b, 0o644); err != nil {
		return err
	}
	return os.Rename(tmp, s.path)
}

// ---------- 用户 ----------

// CreateUser 创建账号，用户名已存在时返回错误。
func (s *Store) CreateUser(u User) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	for _, x := range s.data.Users {
		if x.Username == u.Username {
			return fmt.Errorf("用户名已存在")
		}
	}
	s.data.Users = append(s.data.Users, u)
	return s.flushLocked()
}

// FindUser 按登录名（小写）查找。
func (s *Store) FindUser(username string) (User, bool) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	for _, x := range s.data.Users {
		if x.Username == username {
			return x, true
		}
	}
	return User{}, false
}

// GetUser 按 ID 查找。
func (s *Store) GetUser(id string) (User, bool) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	for _, x := range s.data.Users {
		if x.ID == id {
			return x, true
		}
	}
	return User{}, false
}

// UpdateUser 更新用户资料（昵称/密码）。
func (s *Store) UpdateUser(u User) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	for i, x := range s.data.Users {
		if x.ID == u.ID {
			s.data.Users[i] = u
			return s.flushLocked()
		}
	}
	return fmt.Errorf("用户不存在")
}

// ListUsers 返回全部用户，按创建时间倒序。
func (s *Store) ListUsers() []User {
	s.mu.RLock()
	defer s.mu.RUnlock()
	out := append([]User{}, s.data.Users...)
	sort.Slice(out, func(i, j int) bool { return out[i].CreatedAt.After(out[j].CreatedAt) })
	return out
}

// DeleteUser 删除用户，并级联清理其好友关系与好友请求；
// 分享包与聊天记录保留不动。用户不存在时返回错误。
func (s *Store) DeleteUser(id string) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	found := false
	users := make([]User, 0, len(s.data.Users))
	for _, u := range s.data.Users {
		if u.ID == id {
			found = true
			continue
		}
		users = append(users, u)
	}
	if !found {
		return fmt.Errorf("用户不存在")
	}
	friends := make([]Friend, 0, len(s.data.Friends))
	for _, f := range s.data.Friends {
		if f.UserA == id || f.UserB == id {
			continue
		}
		friends = append(friends, f)
	}
	reqs := make([]FriendRequest, 0, len(s.data.Requests))
	for _, r := range s.data.Requests {
		if r.From == id || r.To == id {
			continue
		}
		reqs = append(reqs, r)
	}
	s.data.Users = users
	s.data.Friends = friends
	s.data.Requests = reqs
	return s.flushLocked()
}

// Counts 返回概览统计：用户 / 好友 / 待处理请求 / 分享包 数量。
func (s *Store) Counts() (users, friends, requests, packages int) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	return len(s.data.Users), len(s.data.Friends), len(s.data.Requests), len(s.data.Packages)
}

// ---------- 聊天消息 ----------

// AppendMessage 追加一条消息（ID 为 0 时由自增计数分配），全量保留最多 maxMessages 条。
func (s *Store) AppendMessage(m ChatMessage) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if m.ID <= 0 {
		s.data.MsgSeq++
		m.ID = s.data.MsgSeq
	} else if m.ID > s.data.MsgSeq {
		s.data.MsgSeq = m.ID
	}
	s.data.Messages = append(s.data.Messages, m)
	if len(s.data.Messages) > maxMessages {
		s.data.Messages = append([]ChatMessage(nil), s.data.Messages[len(s.data.Messages)-maxMessages:]...)
	}
	return s.flushLocked()
}

// ListMessages 返回 a 与 b 双向会话中 beforeID 之前的最近 limit 条，按 ID 升序。
// beforeID 为 0 表示不限制。
func (s *Store) ListMessages(a, b string, beforeID int64, limit int) []ChatMessage {
	s.mu.RLock()
	defer s.mu.RUnlock()
	matched := make([]ChatMessage, 0, 16)
	for _, m := range s.data.Messages {
		if (m.From != a || m.To != b) && (m.From != b || m.To != a) {
			continue
		}
		if beforeID > 0 && m.ID >= beforeID {
			continue
		}
		matched = append(matched, m)
	}
	sort.Slice(matched, func(i, j int) bool { return matched[i].ID < matched[j].ID })
	if limit > 0 && len(matched) > limit {
		matched = matched[len(matched)-limit:]
	}
	return matched
}

// ---------- 好友 ----------

func pairKey(a, b string) (string, string) {
	if a < b {
		return a, b
	}
	return b, a
}

// SendRequest 发送好友请求；已是好友或请求已存在时报错。
func (s *Store) SendRequest(from, to string) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	a, b := pairKey(from, to)
	for _, f := range s.data.Friends {
		if f.UserA == a && f.UserB == b {
			return fmt.Errorf("你们已经是好友了")
		}
	}
	for _, r := range s.data.Requests {
		if r.From == from && r.To == to {
			return fmt.Errorf("请求已发送，请等待对方确认")
		}
		if r.From == to && r.To == from {
			return fmt.Errorf("对方已向你发送请求，请直接确认")
		}
	}
	s.data.Requests = append(s.data.Requests, FriendRequest{From: from, To: to, CreatedAt: time.Now()})
	return s.flushLocked()
}

// AcceptRequest 接受好友请求。
func (s *Store) AcceptRequest(from, to string) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	idx := -1
	for i, r := range s.data.Requests {
		if r.From == from && r.To == to {
			idx = i
			break
		}
	}
	if idx < 0 {
		return fmt.Errorf("请求不存在或已处理")
	}
	s.data.Requests = append(s.data.Requests[:idx], s.data.Requests[idx+1:]...)
	a, b := pairKey(from, to)
	s.data.Friends = append(s.data.Friends, Friend{UserA: a, UserB: b, Since: time.Now()})
	return s.flushLocked()
}

// RejectRequest 拒绝好友请求。
func (s *Store) RejectRequest(from, to string) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	for i, r := range s.data.Requests {
		if r.From == from && r.To == to {
			s.data.Requests = append(s.data.Requests[:i], s.data.Requests[i+1:]...)
			return s.flushLocked()
		}
	}
	return fmt.Errorf("请求不存在")
}

// RemoveFriend 删除好友。
func (s *Store) RemoveFriend(userA, userB string) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	a, b := pairKey(userA, userB)
	for i, f := range s.data.Friends {
		if f.UserA == a && f.UserB == b {
			s.data.Friends = append(s.data.Friends[:i], s.data.Friends[i+1:]...)
			return s.flushLocked()
		}
	}
	return fmt.Errorf("好友关系不存在")
}

// ListRequests 返回发给 uid 的请求与 uid 发出的请求。
func (s *Store) ListRequests(uid string) (incoming, outgoing []FriendRequest) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	for _, r := range s.data.Requests {
		if r.To == uid {
			incoming = append(incoming, r)
		}
		if r.From == uid {
			outgoing = append(outgoing, r)
		}
	}
	return
}

// ListFriends 返回 uid 的好友 ID 列表。
func (s *Store) ListFriends(uid string) []Friend {
	s.mu.RLock()
	defer s.mu.RUnlock()
	var out []Friend
	for _, f := range s.data.Friends {
		if f.UserA == uid || f.UserB == uid {
			out = append(out, f)
		}
	}
	return out
}

// AreFriends 判断两用户是否好友。
func (s *Store) AreFriends(a, b string) bool {
	s.mu.RLock()
	defer s.mu.RUnlock()
	x, y := pairKey(a, b)
	for _, f := range s.data.Friends {
		if f.UserA == x && f.UserB == y {
			return true
		}
	}
	return false
}

// FriendIDs 返回 uid 的好友 ID 列表。
func (s *Store) FriendIDs(uid string) []string {
	s.mu.RLock()
	defer s.mu.RUnlock()
	var out []string
	for _, f := range s.data.Friends {
		if f.UserA == uid {
			out = append(out, f.UserB)
		} else if f.UserB == uid {
			out = append(out, f.UserA)
		}
	}
	sort.Strings(out)
	return out
}

// ---------- 分享包 ----------

// AddPackage 登记分享包元数据。
func (s *Store) AddPackage(p PackageMeta) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.data.Packages = append(s.data.Packages, p)
	return s.flushLocked()
}

// DeletePackage 删除元数据，返回被删包。
func (s *Store) DeletePackage(id string) (PackageMeta, bool) {
	s.mu.Lock()
	defer s.mu.Unlock()
	for i, p := range s.data.Packages {
		if p.ID == id {
			s.data.Packages = append(s.data.Packages[:i], s.data.Packages[i+1:]...)
			_ = s.flushLocked()
			return p, true
		}
	}
	return PackageMeta{}, false
}

// GetPackage 按 ID 取包。
func (s *Store) GetPackage(id string) (PackageMeta, bool) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	for _, p := range s.data.Packages {
		if p.ID == id {
			return p, true
		}
	}
	return PackageMeta{}, false
}

// ListPackages 列出分享包；typeQuery 为空表示全部，kw 为名称/描述关键字。
func (s *Store) ListPackages(typeQuery, kw string, limit, offset int) (total int, out []PackageMeta) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	var matched []PackageMeta
	kw = lower(kw)
	for _, p := range s.data.Packages {
		if typeQuery != "" && p.Type != typeQuery {
			continue
		}
		if kw != "" && !contains(lower(p.Name), kw) && !contains(lower(p.Description), kw) {
			continue
		}
		matched = append(matched, p)
	}
	// 最新在前
	sort.Slice(matched, func(i, j int) bool {
		return matched[i].CreatedAt.After(matched[j].CreatedAt)
	})
	total = len(matched)
	if offset > total {
		offset = total
	}
	matched = matched[offset:]
	if limit > 0 && len(matched) > limit {
		matched = matched[:limit]
	}
	return total, matched
}

// IncDownloads 增加下载计数。
func (s *Store) IncDownloads(id string) {
	s.mu.Lock()
	defer s.mu.Unlock()
	for i, p := range s.data.Packages {
		if p.ID == id {
			s.data.Packages[i].Downloads++
			_ = s.flushLocked()
			return
		}
	}
}

// ListUserPackages 列出某用户上传的包。
func (s *Store) ListUserPackages(uid string) []PackageMeta {
	s.mu.RLock()
	defer s.mu.RUnlock()
	var out []PackageMeta
	for _, p := range s.data.Packages {
		if p.Author == uid {
			out = append(out, p)
		}
	}
	sort.Slice(out, func(i, j int) bool { return out[i].CreatedAt.After(out[j].CreatedAt) })
	return out
}

func lower(s string) string {
	b := []byte(s)
	for i := range b {
		if b[i] >= 'A' && b[i] <= 'Z' {
			b[i] += 'a' - 'A'
		}
	}
	return string(b)
}

func contains(s, sub string) bool {
	return len(sub) == 0 || (len(s) >= len(sub) && indexOf(s, sub) >= 0)
}

func indexOf(s, sub string) int {
	for i := 0; i+len(sub) <= len(s); i++ {
		if s[i:i+len(sub)] == sub {
			return i
		}
	}
	return -1
}
