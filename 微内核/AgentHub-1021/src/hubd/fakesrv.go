package main

// 本机假端点：只用来证明"模型这一路的管路是通的"，不是模型。
// 它听 127.0.0.1 的随机端口，按剧本回一个工具选择；坏形状那一档用来量降级。

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net"
	"net/http"
	"strings"
	"time"
)

type 假端点 struct {
	srv *http.Server
	地址  string
	收到  int
	最后  map[string]any
	坏   bool
}

func 起假端点(坏 bool) (*假端点, error) {
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		return nil, err
	}
	f := &假端点{地址: fmt.Sprintf("http://%s/v1/chat", ln.Addr().String()), 坏: 坏}
	mux := http.NewServeMux()
	mux.HandleFunc("/v1/chat", func(w http.ResponseWriter, r *http.Request) {
		// 必须 ReadAll：一次 Read 只拿到第一个块，正文几 KB（12 个工具的说明书 + 记忆历史）时
		// Unmarshal 静默失败 ⇒ 入是空的 ⇒ 每次都走默认分支回 time.now，
		// 看上去"端点在选件"，其实它一个字都没读到。
		b, _ := io.ReadAll(r.Body)
		var 入 map[string]any
		json.Unmarshal(b, &入)
		f.收到++
		f.最后 = 入
		w.Header().Set("Content-Type", "application/json")
		if f.坏 {
			fmt.Fprint(w, `{"这不是那形状"`)
			return
		}
		工具, 参 := "time.now", map[string]any{}
		话 := 最后一句用户话(入)
		// 剧本的第二条：已经走过一步就自己说收口。没有这一条，带它的每一发都只能撞到"步数上限"，
		// 页面上永远演不出"端点自己收口"那一形 —— 而那一形正是 done 分支存在的理由。
		if 已做 := 已做步数(入); 已做 >= 1 {
			json.NewEncoder(w).Encode(map[string]any{"done": true,
				"answer": "端点说可以收口（剧本：看到「已做过 ≥1 步」就 done，不是它读懂了正文）"})
			return
		}
		if strings.Contains(话, "列") || strings.Contains(话, "目录") {
			工具, 参 = "fs.list", map[string]any{"path": "."}
		}
		if strings.Contains(话, "算") {
			工具, 参 = "calc.eval", map[string]any{"expr": "2+3"}
		}
		json.NewEncoder(w).Encode(map[string]any{"tool": 工具, "args": 参})
	})
	f.srv = &http.Server{Handler: mux, ReadHeaderTimeout: 3 * time.Second}
	go f.srv.Serve(ln)
	time.Sleep(60 * time.Millisecond)
	return f, nil
}

func (f *假端点) 收() {
	ctx, cancel := context.WithTimeout(context.Background(), 300*time.Millisecond)
	defer cancel()
	f.srv.Shutdown(ctx)
}

// 已做步数 从 system 那句"已做过：N 步"里读 N。读不到就返回 0（宁可让它继续选件，
// 也不要拿一个没交来的数当"已经走过步了"—— 那会凭空造出一次收口）。
func 已做步数(入 map[string]any) int {
	s, _ := 入["system"].(string)
	i := strings.Index(s, "已做过：")
	if i < 0 {
		return 0
	}
	余 := s[i+len("已做过："):]
	n := 0
	for _, r := range 余 {
		if r < '0' || r > '9' {
			break
		}
		n = n*10 + int(r-'0')
	}
	return n
}

// 最后一句用户话 只取 messages 里最后那条 user 的 content。
// 原先是对整个请求 json.Marshal 之后找关键词 —— 那个串里永远带着 tools 的说明书
// （"算一个算式…"、"目录下共 N 条"），于是任何一句话都会命中"算"和"目录"，
// 假端点就变成"永远选 calc.eval + 只带 path 参数"，每一步都撞 bad_args。
// 汇总行里的计数词不算证据：要盯的是那一句用户话本身。
func 最后一句用户话(入 map[string]any) string {
	列, _ := 入["messages"].([]any)
	话 := ""
	for _, x := range 列 {
		m, _ := x.(map[string]any)
		r, _ := m["role"].(string)
		c, _ := m["content"].(string)
		if r == "user" && c != "" {
			话 = c
		}
	}
	return 话
}
