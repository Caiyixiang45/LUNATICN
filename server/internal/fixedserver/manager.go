// Package fixedserver 守护官方固定服务器进程（崩溃自动拉起）。
// 支持运行时动态新增/删除/启动/停止/重启（管理后台调用）。
package fixedserver

import (
	"context"
	"errors"
	"log"
	"os"
	"os/exec"
	"strconv"
	"sync"
	"time"

	"lunaticn/server/internal/config"
)

// Status 单台固定服务器状态。
type Status struct {
	Name    string `json:"name"`
	Bin     string `json:"bin"`
	World   string `json:"world"`
	GameID  string `json:"gameid"`
	Port    int    `json:"port"`
	Running bool   `json:"running"`
	Restart int    `json:"restarts"`
	PID     int    `json:"pid"`
}

// Manager 管理一组常驻 luantiserver 进程。
type Manager struct {
	mu      sync.Mutex
	entries map[string]*managed // name -> entry
	order   []string            // 展示顺序
}

// managed 单台服务器的守护状态。
type managed struct {
	cfg     config.FixedServer
	cmd     *exec.Cmd        // 当前进程（未运行时为 nil）
	cancel  context.CancelFunc // 杀掉当前进程
	stopped bool               // 人为停止或已删除 → 守护协程退出
	active  bool               // 守护协程运行中
	killed  bool               // 本次退出是人为 kill（重启免退避）
	restart int                // 连续异常退出计数
	wake    chan struct{}      // 打断退避等待（Start/Restart 时关闭）
}

// NewManager 创建守护管理器。
func NewManager() *Manager {
	return &Manager{entries: make(map[string]*managed)}
}

// StartAll 启动全部固定服务器（启动时调用）。
func (m *Manager) StartAll(cfgs []config.FixedServer) {
	for _, cf := range cfgs {
		if err := m.Add(cf); err != nil {
			log.Printf("[fixed] %v", err)
		}
	}
}

// Add 新增一台并立即启动。name 不得重复。
func (m *Manager) Add(cf config.FixedServer) error {
	if cf.Name == "" {
		return errors.New("服务器名不能为空")
	}
	if cf.Bin == "" {
		return errors.New("服务器缺少可执行文件路径")
	}
	if cf.Port <= 0 || cf.Port > 65535 {
		return errors.New("端口号无效")
	}
	m.mu.Lock()
	if _, ok := m.entries[cf.Name]; ok {
		m.mu.Unlock()
		return errors.New("服务器名已存在")
	}
	e := &managed{cfg: cf, active: true, wake: make(chan struct{})}
	m.entries[cf.Name] = e
	m.order = append(m.order, cf.Name)
	m.mu.Unlock()
	go m.supervise(cf.Name, e)
	return nil
}

// Remove 停止并删除一台（config.json 的持久化由调用方负责）。
func (m *Manager) Remove(name string) error {
	m.mu.Lock()
	e, ok := m.entries[name]
	if !ok {
		m.mu.Unlock()
		return errors.New("服务器不存在")
	}
	e.stopped = true
	if e.cancel != nil {
		e.cancel()
	}
	delete(m.entries, name)
	for i, n := range m.order {
		if n == name {
			m.order = append(m.order[:i], m.order[i+1:]...)
			break
		}
	}
	m.mu.Unlock()
	return nil
}

// Start 启动一台（人为停止后的恢复；运行中则无操作）。
func (m *Manager) Start(name string) error {
	m.mu.Lock()
	e, ok := m.entries[name]
	if !ok {
		m.mu.Unlock()
		return errors.New("服务器不存在")
	}
	if !e.stopped {
		m.mu.Unlock()
		return nil // 已在运行或正在退避重启
	}
	e.stopped = false
	e.killed = false
	e.restart = 0
	wasActive := e.active
	if !wasActive {
		e.active = true
	}
	m.mu.Unlock()
	if !wasActive {
		go m.supervise(name, e)
	}
	return nil
}

// Stop 人为停止一台（守护协程退出，不再自动拉起）。
func (m *Manager) Stop(name string) error {
	m.mu.Lock()
	e, ok := m.entries[name]
	if !ok {
		m.mu.Unlock()
		return errors.New("服务器不存在")
	}
	e.stopped = true
	e.killed = true
	e.restart = 0
	if e.cancel != nil {
		e.cancel()
	}
	m.mu.Unlock()
	return nil
}

// Restart 重启一台：杀掉当前进程立即拉起；处于退避等待时也立即拉起。
func (m *Manager) Restart(name string) error {
	m.mu.Lock()
	e, ok := m.entries[name]
	if !ok {
		m.mu.Unlock()
		return errors.New("服务器不存在")
	}
	if e.stopped { // 停止状态下的重启等价于启动
		e.stopped = false
		wasActive := e.active
		if !wasActive {
			e.active = true
		}
		m.mu.Unlock()
		if !wasActive {
			go m.supervise(name, e)
		}
		return nil
	}
	e.killed = true
	e.restart = 0
	if e.cancel != nil {
		e.cancel() // 进程运行中 → 退出后免退避立即重启
	} else {
		// 退避等待中 → 打断等待立即重启
		close(e.wake)
		e.wake = make(chan struct{})
	}
	m.mu.Unlock()
	return nil
}

// supervise 守护单台进程：退出后按退避策略重启；stopped 或被删除时退出。
func (m *Manager) supervise(name string, e *managed) {
	for {
		m.mu.Lock()
		if m.entries[name] != e || e.stopped {
			e.active = false
			m.mu.Unlock()
			return
		}
		cf := e.cfg
		ctx, cancel := context.WithCancel(context.Background())
		e.cancel = cancel

		args := []string{"--server", "--port", strconv.Itoa(cf.Port)}
		if cf.World != "" {
			args = append(args, "--world", cf.World)
		}
		if cf.GameID != "" {
			args = append(args, "--gameid", cf.GameID)
		}
		if cf.Config != "" {
			args = append(args, "--config", cf.Config)
		}
		cmd := exec.CommandContext(ctx, cf.Bin, args...)
		cmd.Stdout = os.Stdout
		cmd.Stderr = os.Stderr
		e.cmd = cmd
		m.mu.Unlock()

		log.Printf("[fixed] 启动 %s (端口 %d)", cf.Name, cf.Port)
		err := cmd.Run()

		m.mu.Lock()
		e.cmd = nil
		e.cancel = nil
		if m.entries[name] != e || e.stopped {
			e.active = false
			m.mu.Unlock()
			return
		}
		var wait time.Duration
		if e.killed {
			// 人为重启：清零退避，立即拉起
			e.killed = false
			e.restart = 0
		} else {
			e.restart++
			wait = time.Duration(e.restart) * 5 * time.Second
			if wait > 60*time.Second {
				wait = 60 * time.Second
			}
		}
		wake := e.wake
		m.mu.Unlock()

		if wait > 0 {
			log.Printf("[fixed] %s 异常退出 (%v)，%s 后重启", cf.Name, err, wait)
			select {
			case <-time.After(wait):
			case <-wake: // Start/Restart 打断退避
			}
		}
	}
}

// StopAll 全部停止（进程退出时调用）。
func (m *Manager) StopAll() {
	m.mu.Lock()
	defer m.mu.Unlock()
	for _, e := range m.entries {
		e.stopped = true
		if e.cancel != nil {
			e.cancel()
		}
	}
}

// StatusList 返回全部状态（按创建顺序）。
func (m *Manager) StatusList() []Status {
	m.mu.Lock()
	defer m.mu.Unlock()
	out := make([]Status, 0, len(m.order))
	for _, name := range m.order {
		e, ok := m.entries[name]
		if !ok {
			continue
		}
		st := Status{
			Name: e.cfg.Name, Bin: e.cfg.Bin, World: e.cfg.World,
			GameID: e.cfg.GameID, Port: e.cfg.Port,
			Restart: e.restart,
		}
		if e.cmd != nil && e.cmd.Process != nil && !e.stopped {
			st.Running = true
			st.PID = e.cmd.Process.Pid
		}
		out = append(out, st)
	}
	return out
}
