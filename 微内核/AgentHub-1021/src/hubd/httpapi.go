package main

// HTTP 面：一个 POST /api/chat 走 SSE 把整圈推进前端；其余是只读的自述端点
// （工具清单、记忆、历史发）。只监听 127.0.0.1 —— 这是一台本机应用，不是公网服务。

import (
	"context"
	"embed"
	"encoding/json"
	"fmt"
	"io"
	"io/fs"
	"net"
	"net/http"
	"strconv"
	"strings"
	"sync"
	"time"
)

//go:embed all:web
var 页面 embed.FS

type hub struct {
	cfg Config
	x   *EnvX
	a   *Agent
	mu  sync.Mutex // 一发一把锁：连点两次不许把两发的步骤混进同一列

	// 停止柄与 mu 分开：/api/stop 若也要拿 mu，就得等这一发跑完才轮到它 —— 那正好是它要打断的东西。
	stopMu sync.Mutex
	在跑     *turnCtl
}

type turnCtl struct {
	cancel context.CancelFunc
	at     time.Time
}

func (h *hub) 装停止柄(c *turnCtl) {
	h.stopMu.Lock()
	h.在跑 = c
	h.stopMu.Unlock()
}

func (h *hub) 卸停止柄(c *turnCtl) {
	h.stopMu.Lock()
	if h.在跑 == c {
		h.在跑 = nil
	}
	h.stopMu.Unlock()
}

func 起服务(cfg Config, x *EnvX) *http.Server {
	h := &hub{cfg: cfg, x: x, a: NewAgent(x.Env, cfg)}
	mux := http.NewServeMux()
	子, err := fs.Sub(页面, "web")
	if err != nil {
		panic(err)
	}
	mux.Handle("/", http.FileServer(http.FS(子)))
	mux.HandleFunc("/api/chat", h.chat)
	mux.HandleFunc("/api/stop", h.stop)
	mux.HandleFunc("/api/tools", h.tools)
	mux.HandleFunc("/api/turns", h.turns)
	mux.HandleFunc("/api/session/new", h.newSession)
	mux.HandleFunc("/api/health", func(w http.ResponseWriter, r *http.Request) {
		写JSON(w, map[string]any{"ok": true, "tools": x.reg.Count(), "memory": x.mem.Count(),
			"next_turn": x.mem.NextTurn(), "model_endpoint": 端点话(cfg),
			"allow_write": cfg.AllowWrite, "allow_exec": cfg.AllowExec})
	})
	return &http.Server{
		Addr:              fmt.Sprintf("127.0.0.1:%d", cfg.Port),
		Handler:           mux,
		ReadHeaderTimeout: 5 * time.Second,
	}
}

func (h *hub) chat(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		写JSON(w, map[string]any{"ok": false, "why": "POST only"})
		return
	}
	body, _ := io.ReadAll(io.LimitReader(r.Body, 1<<20))
	var 入 struct {
		Text string `json:"text"`
	}
	if err := json.Unmarshal(body, &入); err != nil {
		写JSON(w, map[string]any{"ok": false, "why": fmt.Sprintf("请求体不是那形状：%v", err)})
		return
	}
	if strings.TrimSpace(入.Text) == "" {
		写JSON(w, map[string]any{"ok": false, "why": "text 是空的 ⇒ 这一发没话可规划"})
		return
	}
	准, ok := h.拿到锁()
	if !ok {
		写JSON(w, map[string]any{"ok": false, "why": "上一发还在跑 ⇒ 这一发被门口挡下（不排队、不混列）"})
		return
	}
	defer 准()
	// 两路取消汇到同一个 ctx：客户端断开（r.Context()）与 /api/stop。
	// 循环里每步都查 ctx；工具调用本身也吃 ctx，所以慢端点不会把"停下"拖到超时。
	ctx, cancel := context.WithCancel(r.Context())
	ctl := &turnCtl{cancel: cancel, at: time.Now()}
	h.装停止柄(ctl)
	defer h.卸停止柄(ctl)
	defer cancel()
	fl, err := 流头(w)
	if err != nil {
		return
	}
	流 := 推{w: w, fl: fl}
	事件数 := 0
	emit := func(kind string, payload any) {
		事件数++
		流.发(kind, payload)
		if h.cfg.StepDelay > 0 && ctx.Err() == nil {
			time.Sleep(h.cfg.StepDelay)
		}
	}
	res := h.a.RunTurn(ctx, 入.Text, emit)
	// 正文分帧推：流式的是这台机器已经算完的结论，边算边推要靠规划器逐步 emit（已经在发了）。
	for _, 段 := range 切段(res.Answer, 24) {
		if ctx.Err() != nil {
			break
		}
		流.发("answer_delta", map[string]any{"turn": res.Turn, "text": 段})
		if h.cfg.StepDelay > 0 {
			time.Sleep(h.cfg.StepDelay / 2)
		}
	}
	流.发("done", map[string]any{"events": 事件数, "turn": res.Turn})
}

// stop 打断正在跑的那一发。它不拿 hub.mu —— 那把锁正被要打断的这一发握着。
func (h *hub) stop(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		写JSON(w, map[string]any{"ok": false, "stopped": false, "why": "POST only"})
		return
	}
	h.stopMu.Lock()
	c := h.在跑
	h.stopMu.Unlock()
	if c == nil {
		写JSON(w, map[string]any{"ok": false, "stopped": false,
			"why": "现在没有在跑的一发 ⇒ 没有可打断的东西"})
		return
	}
	c.cancel()
	写JSON(w, map[string]any{"ok": true, "stopped": true,
		"why": "取消信号已发给在跑的那一发；它会交出「被打断」的结果（已经亮出来的步留在账上）"})
}

func (h *hub) 拿到锁() (func(), bool) {
	if h.mu.TryLock() {
		return h.mu.Unlock, true
	}
	return nil, false
}

func 流头(w http.ResponseWriter) (http.Flusher, error) {
	fl, ok := w.(http.Flusher)
	if !ok {
		http.Error(w, "streaming unsupported", http.StatusInternalServerError)
		return nil, fmt.Errorf("这个 ResponseWriter 不会 flush")
	}
	w.Header().Set("Content-Type", "text/event-stream; charset=utf-8")
	w.Header().Set("Cache-Control", "no-cache")
	w.Header().Set("Connection", "keep-alive")
	w.Header().Set("X-Accel-Buffering", "no")
	fl.Flush()
	return fl, nil
}

type 推 struct {
	w  io.Writer
	fl http.Flusher
}

func (p 推) 发(kind string, payload any) {
	b, err := json.Marshal(payload)
	if err != nil {
		b = []byte(fmt.Sprintf(`{"marshal_error":%q}`, err.Error()))
	}
	fmt.Fprintf(p.w, "event: %s\ndata: %s\n\n", kind, b)
	p.fl.Flush()
}

func 写JSON(w http.ResponseWriter, v any) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	json.NewEncoder(w).Encode(v)
}

func (h *hub) tools(w http.ResponseWriter, r *http.Request) {
	写JSON(w, map[string]any{
		"count":       h.x.reg.Count(),
		"builtin":     h.x.内置数,
		"manifest":    h.x.清单数,
		"rejected":    h.x.清单拒,
		"shadow":      h.x.reg.shadow,
		"tools_dir":   h.cfg.ToolsDir,
		"specs":       h.x.reg.Specs(),
		"fs_roots":    h.x.fs.Roots(),
		"net_allow":   h.x.net.AllowList(),
		"allow_write": h.cfg.AllowWrite,
		"allow_exec":  h.cfg.AllowExec,
	})
}

func (h *hub) turns(w http.ResponseWriter, r *http.Request) {
	n := 数参数(r, "limit", 20)
	写JSON(w, map[string]any{"next_turn": h.x.mem.NextTurn(), "file": h.x.会话文件,
		"msgs": h.x.mem.按发(n)})
}

func (h *hub) newSession(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		写JSON(w, map[string]any{"ok": false, "why": "POST only"})
		return
	}
	旧 := h.x.mem.Count()
	文件 := fmt.Sprintf("%s/会话-%d-%d.jsonl", h.cfg.DataDir, h.cfg.Port, time.Now().Unix())
	m := NewMemory(文件)
	n, 坏, err := m.Load()
	if err != nil {
		写JSON(w, map[string]any{"ok": false, "why": err.Error()})
		return
	}
	// 换记忆要同时换 Env 与 Agent 里的那一份指针 —— 只换一处，下一发还会写进旧会话文件。
	h.mu.Lock()
	h.x.mem = m
	h.a = NewAgent(h.x.Env, h.cfg)
	h.mu.Unlock()
	写JSON(w, map[string]any{"ok": true, "上一本几条": 旧, "新文件": 文件, "读回行": n, "坏行": 坏})
}

func 数参数(r *http.Request, key string, def int) int {
	if v := r.URL.Query().Get(key); v != "" {
		if n, err := strconv.Atoi(v); err == nil && n > 0 {
			return n
		}
	}
	return def
}

func 切段(s string, n int) []string {
	r := []rune(s)
	var out []string
	for i := 0; i < len(r); i += n {
		e := i + n
		if e > len(r) {
			e = len(r)
		}
		out = append(out, string(r[i:e]))
	}
	if len(out) == 0 {
		out = append(out, "")
	}
	return out
}

// 端口给人用之前先确认没人占 —— 这是"有人在听先验 owner"那条规矩的机器版。
func 端口可占(port int) (string, error) {
	ln, err := net.Listen("tcp", fmt.Sprintf("127.0.0.1:%d", port))
	if err != nil {
		return "", fmt.Errorf("127.0.0.1:%d 起不来（可能被占）：%v", port, err)
	}
	ln.Close()
	return fmt.Sprintf("127.0.0.1:%d", port), nil
}
