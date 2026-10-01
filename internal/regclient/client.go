// Package regclient 是社区服务器房间注册 API 的客户端。
// roomd 用它完成：登录 → 注册房间 → 心跳 → 注销。
package regclient

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"time"
)

// Client 社区服务器客户端。
type Client struct {
	base string
	hc   *http.Client
}

// New 创建客户端，base 为社区服务器地址（不含末尾斜杠）。
func New(base string) *Client {
	for len(base) > 0 && base[len(base)-1] == '/' {
		base = base[:len(base)-1]
	}
	return &Client{
		base: base,
		hc:   &http.Client{Timeout: 15 * time.Second},
	}
}

// RoomInfo 注册时上报的房间信息。
type RoomInfo struct {
	Name        string `json:"name"`
	Host        string `json:"host"`
	Port        int    `json:"port"`
	GameID      string `json:"gameid"`
	World       string `json:"world"`
	MaxPlayers  int    `json:"max_players"`
	HasPassword bool   `json:"has_password"`
	Private     bool   `json:"private"`
	Source      string `json:"source"`
	Description string `json:"description"`
	Engine      string `json:"engine"`
	Protocol    int    `json:"protocol"`
}

func (c *Client) do(ctx context.Context, method, path, token string, body any, out any) error {
	var rd io.Reader
	if body != nil {
		b, err := json.Marshal(body)
		if err != nil {
			return err
		}
		rd = bytes.NewReader(b)
	}
	req, err := http.NewRequestWithContext(ctx, method, c.base+path, rd)
	if err != nil {
		return err
	}
	if body != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	if token != "" {
		req.Header.Set("Authorization", "Bearer "+token)
	}
	resp, err := c.hc.Do(req)
	if err != nil {
		return fmt.Errorf("请求社区服务器失败: %w", err)
	}
	defer resp.Body.Close()
	data, _ := io.ReadAll(io.LimitReader(resp.Body, 1<<20))
	if resp.StatusCode >= 400 {
		var e struct {
			Error string `json:"error"`
		}
		_ = json.Unmarshal(data, &e)
		if e.Error == "" {
			e.Error = string(data)
		}
		return fmt.Errorf("社区服务器返回 %d: %s", resp.StatusCode, e.Error)
	}
	if out != nil {
		return json.Unmarshal(data, out)
	}
	return nil
}

// Login 登录并返回访问令牌。
func (c *Client) Login(ctx context.Context, username, password string) (string, error) {
	var resp struct {
		Token string `json:"token"`
	}
	err := c.do(ctx, http.MethodPost, "/api/auth/login", "", map[string]string{
		"username": username, "password": password,
	}, &resp)
	if err != nil {
		return "", err
	}
	if resp.Token == "" {
		return "", fmt.Errorf("服务器未返回令牌")
	}
	return resp.Token, nil
}

// Register 注册房间，返回房间令牌与房间 ID。
func (c *Client) Register(ctx context.Context, accessToken string, info RoomInfo) (roomToken, roomID string, err error) {
	var resp struct {
		RoomToken string `json:"room_token"`
		Room      struct {
			ID string `json:"id"`
		} `json:"room"`
	}
	err = c.do(ctx, http.MethodPost, "/api/room/register", accessToken, info, &resp)
	if err != nil {
		return "", "", err
	}
	return resp.RoomToken, resp.Room.ID, nil
}

// Heartbeat 上报心跳与当前人数。
func (c *Client) Heartbeat(ctx context.Context, accessToken, roomToken string, players int) error {
	return c.do(ctx, http.MethodPost, "/api/room/heartbeat", accessToken,
		map[string]any{"token": roomToken, "players": players}, nil)
}

// Unregister 下架房间。
func (c *Client) Unregister(ctx context.Context, accessToken, roomToken string) error {
	return c.do(ctx, http.MethodPost, "/api/room/unregister", accessToken,
		map[string]string{"token": roomToken}, nil)
}
