// Package auth 提供密码哈希（argon2id）与 JWT 令牌签发/校验。
package auth

import (
	"crypto/hmac"
	"crypto/rand"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"strings"
	"time"

	"golang.org/x/crypto/argon2"
)

// ---------- 密码哈希（argon2id） ----------

const (
	argonTime    = 1
	argonMemory  = 64 * 1024 // 64 MiB
	argonThreads = 4
	argonKeyLen  = 32
	argonSaltLen = 16
)

// HashPassword 生成 argon2id 密码哈希，格式：
// $argon2id$v=19$m=65536,t=1,p=4$<salt>$<hash>（标准 PHC 字符串）
func HashPassword(password string) (string, error) {
	salt := make([]byte, argonSaltLen)
	if _, err := rand.Read(salt); err != nil {
		return "", err
	}
	hash := argon2.IDKey([]byte(password), salt, argonTime, argonMemory, argonThreads, argonKeyLen)
	return fmt.Sprintf("$argon2id$v=19$m=%d,t=%d,p=%d$%s$%s",
		argonMemory, argonTime, argonThreads,
		base64.RawStdEncoding.EncodeToString(salt),
		base64.RawStdEncoding.EncodeToString(hash),
	), nil
}

// VerifyPassword 校验密码，采用定长时间比较防旁路。
func VerifyPassword(encoded, password string) bool {
	parts := strings.Split(encoded, "$")
	if len(parts) != 6 || parts[1] != "argon2id" {
		return false
	}
	var memory uint32
	var time uint32
	var threads uint8
	if _, err := fmt.Sscanf(parts[3], "m=%d,t=%d,p=%d", &memory, &time, &threads); err != nil {
		return false
	}
	salt, err := base64.RawStdEncoding.DecodeString(parts[4])
	if err != nil {
		return false
	}
	want, err := base64.RawStdEncoding.DecodeString(parts[5])
	if err != nil {
		return false
	}
	got := argon2.IDKey([]byte(password), salt, time, memory, threads, uint32(len(want)))
	return subtle.ConstantTimeCompare(got, want) == 1
}

// ---------- JWT（HS256，自实现以减少依赖） ----------

// Claims 是 LUNATICN 令牌载荷。
type Claims struct {
	Sub  string `json:"sub"`  // 用户 ID
	Name string `json:"name"` // 用户名
	Exp  int64  `json:"exp"`  // 过期时间（Unix 秒）
	Iat  int64  `json:"iat"`  // 签发时间
}

// TokenIssuer 负责签发与校验 JWT。
type TokenIssuer struct {
	secret []byte
	ttl    time.Duration
}

// NewTokenIssuer 创建签发器，ttl 为令牌有效期。
func NewTokenIssuer(secret string, ttl time.Duration) *TokenIssuer {
	return &TokenIssuer{secret: []byte(secret), ttl: ttl}
}

func b64(b []byte) string { return base64.RawURLEncoding.EncodeToString(b) }

// Issue 签发 HS256 JWT。
func (t *TokenIssuer) Issue(userID, username string) string {
	now := time.Now()
	header := b64([]byte(`{"alg":"HS256","typ":"JWT"}`))
	claims := Claims{Sub: userID, Name: username, Iat: now.Unix(), Exp: now.Add(t.ttl).Unix()}
	payload, _ := json.Marshal(claims)
	signing := header + "." + b64(payload)
	mac := hmac.New(sha256.New, t.secret)
	mac.Write([]byte(signing))
	return signing + "." + b64(mac.Sum(nil))
}

// Verify 校验令牌并返回载荷；无效返回错误。
func (t *TokenIssuer) Verify(token string) (*Claims, error) {
	parts := strings.Split(token, ".")
	if len(parts) != 3 {
		return nil, errors.New("令牌格式错误")
	}
	signing := parts[0] + "." + parts[1]
	mac := hmac.New(sha256.New, t.secret)
	mac.Write([]byte(signing))
	want, err := base64.RawURLEncoding.DecodeString(parts[2])
	if err != nil || !hmac.Equal(mac.Sum(nil), want) {
		return nil, errors.New("签名校验失败")
	}
	raw, err := base64.RawURLEncoding.DecodeString(parts[1])
	if err != nil {
		return nil, errors.New("载荷解码失败")
	}
	var c Claims
	if err := json.Unmarshal(raw, &c); err != nil {
		return nil, errors.New("载荷解析失败")
	}
	if time.Now().Unix() > c.Exp {
		return nil, errors.New("令牌已过期")
	}
	return &c, nil
}

// Refresh 验证旧令牌后签发新令牌。
func (t *TokenIssuer) Refresh(token string) (string, *Claims, error) {
	c, err := t.Verify(token)
	if err != nil {
		return "", nil, err
	}
	return t.Issue(c.Sub, c.Name), c, nil
}
