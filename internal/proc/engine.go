// Package proc 负责启动并看护 luanti --server 进程，
// 从其标准输出中解析当前在线人数。
package proc

import (
	"bufio"
	"io"
	"os/exec"
	"strings"
	"sync"
	"syscall"
	"time"
)

// Engine 受管的 Luanti 服务器进程。
type Engine struct {
	mu      sync.Mutex
	cmd     *exec.Cmd
	players map[string]bool // 在线玩家名集合
	running bool
	done    chan struct{}
}

// New 创建引擎实例（尚未启动）。
func New(bin string, args []string) *Engine {
	e := &Engine{
		players: make(map[string]bool),
		done:    make(chan struct{}),
	}
	e.cmd = exec.Command(bin, args...)
	// Windows 下隐藏子进程弹窗，输出走管道
	e.cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true}
	return e
}

// Start 启动进程并开始解析输出；失败返回错误。
func (e *Engine) Start() error {
	stdout, err := e.cmd.StdoutPipe()
	if err != nil {
		return err
	}
	e.cmd.Stderr = e.cmd.Stdout
	if err := e.cmd.Start(); err != nil {
		return err
	}
	e.mu.Lock()
	e.running = true
	e.mu.Unlock()

	go e.watchOutput(stdout)
	go e.watchExit()
	return nil
}

// watchOutput 逐行解析，识别加入/离开。
// 兼容多种日志格式：
//
//	"JOIN: player" / "LEAVE: player"（测试输出）
//	"* player joins game." / "player leaves game."（服务端日志）
func (e *Engine) watchOutput(r io.Reader) {
	sc := bufio.NewScanner(r)
	sc.Buffer(make([]byte, 0, 64*1024), 1024*1024)
	for sc.Scan() {
		line := sc.Text()
		e.parseLine(line)
	}
}

func (e *Engine) parseLine(line string) {
	l := strings.ToLower(line)

	switch {
	case strings.Contains(l, "join:") || strings.Contains(l, "joins game") || strings.Contains(l, "joined the game"):
		if name := extractName(line); name != "" {
			e.mu.Lock()
			e.players[name] = true
			e.mu.Unlock()
		}
	case strings.Contains(l, "leave:") || strings.Contains(l, "leaves game") || strings.Contains(l, "left the game"):
		if name := extractName(line); name != "" {
			e.mu.Lock()
			delete(e.players, name)
			e.mu.Unlock()
		}
	}
}

// extractName 从日志行提取玩家名。
// 形如 "JOIN: Steve"、"* Steve joins game."、"[Server] Steve leaves game."
func extractName(line string) string {
	// 去时间戳前缀 "2026-10-01 12:00:00 [INFO]: "
	if idx := strings.Index(line, "]"); idx >= 0 && idx+1 < len(line) {
		line = line[idx+1:]
	}
	line = strings.TrimSpace(line)

	for _, marker := range []string{"JOIN:", "LEAVE:"} {
		if i := strings.Index(line, marker); i >= 0 {
			return strings.TrimSpace(line[i+len(marker):])
		}
	}
	// "* Steve joins game."
	line = strings.TrimPrefix(line, "*")
	line = strings.TrimSpace(line)
	for _, suffix := range []string{" joins game.", " joins game", " leaves game.", " leaves game",
		" joined the game", " left the game"} {
		if i := strings.Index(line, suffix); i >= 0 {
			return strings.TrimSpace(line[:i])
		}
	}
	return ""
}

// watchExit 等进程退出后关闭 done。
func (e *Engine) watchExit() {
	_ = e.cmd.Wait()
	e.mu.Lock()
	e.running = false
	e.mu.Unlock()
	close(e.done)
}

// Done 进程结束时关闭的通道。
func (e *Engine) Done() <-chan struct{} { return e.done }

// PID 进程号（未启动返回 0）。
func (e *Engine) PID() int {
	if e.cmd == nil || e.cmd.Process == nil {
		return 0
	}
	return e.cmd.Process.Pid
}

// Players 当前在线人数。
func (e *Engine) Players() int {
	e.mu.Lock()
	defer e.mu.Unlock()
	return len(e.players)
}

// Stop 结束进程（先请求退出，超时后强杀）。
func (e *Engine) Stop() {
	e.mu.Lock()
	running := e.running
	e.mu.Unlock()
	if !running || e.cmd.Process == nil {
		return
	}
	// Windows 上无优雅信号，直接 Kill；Luanti 会自行落盘
	_ = e.cmd.Process.Kill()
	select {
	case <-e.done:
	case <-time.After(5 * time.Second):
	}
}
