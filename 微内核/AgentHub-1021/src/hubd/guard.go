package main

// 两道门口：文件系统根白名单（FsGuard）与出网主机白名单（NetGuard）。
// 默认一律收紧 —— 一个"能读整块盘、能打任意 URL"的 Agent 不需要用户先犯错就已经越界了。

import (
	"context"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"
)

type FsGuard struct {
	roots []string
}

func NewFsGuard(roots []string) *FsGuard {
	var out []string
	for _, r := range roots {
		if r == "" {
			continue
		}
		abs, err := filepath.Abs(r)
		if err != nil {
			continue
		}
		out = append(out, abs)
	}
	return &FsGuard{roots: out}
}

func (g *FsGuard) Roots() []string { return append([]string(nil), g.roots...) }

// Within 把用户/清单给的路径收进某个根里；越界返回 refused（不是 error，让循环把它当读数）。
func (g *FsGuard) Within(p string) (string, string) {
	if len(g.roots) == 0 {
		return "", "这台机器一个文件根都没开（-fs-roots 为空）⇒ 文件系统类工具没地方可去"
	}
	abs, err := filepath.Abs(p)
	if err != nil {
		return "", fmt.Sprintf("路径解析不了：%v", err)
	}
	norm, err := filepath.EvalSymlinks(filepath.Dir(abs))
	if err == nil {
		// 只在目录存在时归一化：符号链接逃逸走的就是这一步
		abs = filepath.Join(norm, filepath.Base(abs))
	}
	for _, r := range g.roots {
		rel, err := filepath.Rel(r, abs)
		if err != nil {
			continue
		}
		if rel != ".." && !strings.HasPrefix(rel, ".."+string(os.PathSeparator)) {
			return abs, ""
		}
	}
	return "", fmt.Sprintf("路径越界：%s 不在允许的文件根里（开了这些根：%s）", abs, strings.Join(g.roots, "、"))
}

type NetGuard struct {
	hosts    []string
	client   *http.Client
	MaxBytes int
}

func NewNetGuard(allow []string, perCall time.Duration) *NetGuard {
	if perCall <= 0 {
		perCall = 4 * time.Second
	}
	g := &NetGuard{hosts: allow, MaxBytes: 256 * 1024}
	d := &net.Dialer{Timeout: perCall}
	g.client = &http.Client{
		Timeout: perCall,
		Transport: &http.Transport{
			// 拨号前再判一次主机：URL 里写 127.0.0.1、DNS 却解析到外面，只看 URL 是拦不住的。
			DialContext: func(ctx context.Context, network, addr string) (net.Conn, error) {
				host, _, err := net.SplitHostPort(addr)
				if err != nil {
					return nil, err
				}
				if !g.allowedHost(&url.URL{Host: host}) {
					return nil, fmt.Errorf("拨号被门口挡下：%s 不在允许清单", host)
				}
				return d.DialContext(ctx, network, addr)
			},
			DisableCompression: false,
		},
		CheckRedirect: func(req *http.Request, via []*http.Request) error {
			if !g.allowedHost(req.URL) {
				return fmt.Errorf("重定向把请求带出了允许清单：%s", req.URL.Hostname())
			}
			if len(via) >= 3 {
				return fmt.Errorf("重定向超过 3 跳")
			}
			return nil
		},
	}
	return g
}

func (g *NetGuard) AllowList() []string { return append([]string(nil), g.hosts...) }

// 预检 给调度循环用：在调起工具之前先判主机在不在清单里。
// 放在工具内部判，循环就会把这一次算成"试过了"；门口挡的意思是一次也没打出去，
// 所以计数必须是 0 —— 否则"被挡"与"打了但失败"在账上长一个样。
func (g *NetGuard) 预检(rawurl string) (string, bool) {
	u, err := url.Parse(rawurl)
	if err != nil {
		return fmt.Sprintf("URL 解析不了：%v", err), false
	}
	if u.Scheme != "http" && u.Scheme != "https" {
		return fmt.Sprintf("只认 http/https，给的是 %q", u.Scheme), false
	}
	if !g.allowedHost(u) {
		return fmt.Sprintf("主机 %s 不在出网允许清单里（清单：%s）⇒ 这一发没打到外面，不是打失败了",
			u.Hostname(), strings.Join(g.hosts, "、")), false
	}
	return "", true
}

func (g *NetGuard) allowedHost(u *url.URL) bool {
	h := strings.ToLower(u.Hostname())
	for _, a := range g.hosts {
		if strings.EqualFold(a, h) {
			return true
		}
	}
	return false
}

// Get 只做 GET。返回的 class 决定上游要不要重试；Retry-After 原样带回来（降级策略吃它）。
func (g *NetGuard) Get(ctx context.Context, rawurl string) (Result, error) {
	u, err := url.Parse(rawurl)
	if err != nil {
		return Result{Class: ClassBadArgs, Text: fmt.Sprintf("URL 解析不了：%v", err)}, nil
	}
	if u.Scheme != "http" && u.Scheme != "https" {
		return Result{Class: ClassBadArgs, Text: fmt.Sprintf("只认 http/https，给的是 %q", u.Scheme)}, nil
	}
	if !g.allowedHost(u) {
		return Result{Class: ClassRefused, Text: fmt.Sprintf(
			"主机 %s 不在出网允许清单里（清单：%s）⇒ 这一发没打到外面，不是打失败了",
			u.Hostname(), strings.Join(g.hosts, "、"))}, nil
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, u.String(), nil)
	if err != nil {
		return Result{Class: ClassInternal, Text: err.Error()}, nil
	}
	start := time.Now()
	resp, err := g.client.Do(req)
	if err != nil {
		cls := ClassUpstream
		if os.IsTimeout(err) || strings.Contains(err.Error(), "context deadline") {
			cls = ClassTimeout
		}
		return Result{Class: cls, Text: fmt.Sprintf("取不回：%v（耗时 %dms）", err, time.Since(start).Milliseconds())}, nil
	}
	defer resp.Body.Close()
	body, err := io.ReadAll(io.LimitReader(resp.Body, int64(g.MaxBytes)))
	if err != nil {
		return Result{Class: ClassUpstream, Text: fmt.Sprintf("状态码 %d 但正文读不完：%v", resp.StatusCode, err)}, nil
	}
	truncated := len(body) >= g.MaxBytes
	ra := 0
	if v := resp.Header.Get("Retry-After"); v != "" {
		if n, e := strconv.Atoi(v); e == nil && n >= 0 {
			ra = n * 1000
		}
	}
	head := fmt.Sprintf("HTTP %d %s ｜ %d 字节 ｜ %dms", resp.StatusCode, resp.Status, len(body), time.Since(start).Milliseconds())
	if resp.StatusCode >= 500 {
		return Result{Class: ClassUpstream, RetryAfterMs: ra, Text: head + "（服务端 5xx，可重试）"}, nil
	}
	if resp.StatusCode >= 400 {
		return Result{Class: ClassUpstream, RetryAfterMs: ra, Text: head + fmt.Sprintf("（4xx：%s，按清单里的 no_retry_classes 决定要不要再来）", http.StatusText(resp.StatusCode))}, nil
	}
	data := map[string]any{"status": resp.StatusCode, "bytes": len(body), "ms": time.Since(start).Milliseconds(), "truncated": truncated}
	return Result{Class: ClassOK, Text: head + "\n" + string(body), Data: data}, nil
}

// readWithin 给清单式 fs_read 用：路径必须落在 root 内，并且最多读 max_bytes。
func readWithin(root, rel string, maxBytes int) (Result, error) {
	if root == "" {
		return Result{Class: ClassRefused, Text: "清单没写 invoke.root ⇒ 这个 fs_read 工具没有可读根，没放行"}, nil
	}
	g := NewFsGuard([]string{root})
	abs, why := g.Within(filepath.Join(root, rel))
	if why != "" {
		return Result{Class: ClassRefused, Text: fmt.Sprintf("不放行：%s（root=%s）", why, root)}, nil
	}
	if maxBytes <= 0 {
		maxBytes = 256 * 1024
	}
	f, err := os.Open(abs)
	if err != nil {
		return Result{Class: ClassUpstream, Text: fmt.Sprintf("打不开：%v", err)}, nil
	}
	defer f.Close()
	b, err := io.ReadAll(io.LimitReader(f, int64(maxBytes)))
	if err != nil {
		return Result{Class: ClassInternal, Text: fmt.Sprintf("读了但断了：%v", err)}, nil
	}
	return Result{Class: ClassOK,
		Text: fmt.Sprintf("%s ｜ %d 字节\n%s", abs, len(b), string(b)),
		Data: map[string]any{"path": abs, "bytes": len(b), "truncated": len(b) >= maxBytes}}, nil
}
