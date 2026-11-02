package main

// 上下文记忆：一台只在本发说话的应用不算有记忆。这里做三件事 ——
// ①会话跨进程续（append-only JSONL，重启后发号接着走）；
// ②给规划器喂"窗口 + 摘要"（超出窗口的条数明说，不静默丢）；
// ③留住每一次工具调用的 Data，让"刚才那个文件"这种指代能被解析（这是"记忆"真正被用到的地方）。

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"sync"
	"time"
)

type Msg struct {
	Turn  int            `json:"turn"`
	Role  string         `json:"role"` // user | agent | tool | system
	Text  string         `json:"text"`
	Tool  string         `json:"tool,omitempty"`
	Class string         `json:"class,omitempty"`
	Args  map[string]any `json:"args,omitempty"`
	Data  map[string]any `json:"data,omitempty"` // 工具真跑出来的结构化读数（供后续指代）
	MS    int64          `json:"ms,omitempty"`
	At    time.Time      `json:"at"`
}

type Memory struct {
	mu   sync.Mutex
	msgs []Msg
	path string
	next int
}

func NewMemory(path string) *Memory {
	return &Memory{path: path, next: 1}
}

// Load 读回会话文件。文件不存在 = 新会话（从第 1 发起），不是错误。
// 坏行不静默跳：它记进返回的 bad 计数，让 selfcheck 能说"这台机器上有几行读不回来"。
func (m *Memory) Load() (lines, bad int, err error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	if m.path == "" {
		return 0, 0, nil
	}
	b, err := os.ReadFile(m.path)
	if os.IsNotExist(err) {
		return 0, 0, nil
	}
	if err != nil {
		return 0, 0, err
	}
	for _, l := range strings.Split(string(b), "\n") {
		if strings.TrimSpace(l) == "" {
			continue
		}
		lines++
		var msg Msg
		if e := json.Unmarshal([]byte(l), &msg); e != nil {
			bad++
			continue
		}
		m.msgs = append(m.msgs, msg)
		if msg.Turn >= m.next {
			m.next = msg.Turn + 1
		}
	}
	return lines, bad, nil
}

func (m *Memory) Append(msg Msg) {
	m.mu.Lock()
	m.msgs = append(m.msgs, msg)
	m.mu.Unlock()
	m.写一行(msg)
}

func (m *Memory) 写一行(msg Msg) {
	if m.path == "" {
		return
	}
	if dir := filepath.Dir(m.path); dir != "" && dir != "." {
		os.MkdirAll(dir, 0o755)
	}
	f, err := os.OpenFile(m.path, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o644)
	if err != nil {
		return
	}
	defer f.Close()
	b, _ := json.Marshal(msg)
	f.Write(append(b, '\n'))
}

func (m *Memory) Count() int {
	m.mu.Lock()
	defer m.mu.Unlock()
	return len(m.msgs)
}

func (m *Memory) NextTurn() int {
	m.mu.Lock()
	defer m.mu.Unlock()
	return m.next
}

func (m *Memory) SetNextTurn(n int) {
	m.mu.Lock()
	m.next = n
	m.mu.Unlock()
}

// 窗口 给规划器/模型适配器喂上下文：从最近一条往前收，收到 maxChars 码元为止。
// 被挤掉的条数记在 m.dropped 里 —— 只说"给了上下文"而不说"少给了几条"，等于把裁剪藏起来。
func (m *Memory) 窗口(turn int, maxChars int) (out []Msg, 用了码元 int, 挤掉 int) {
	m.mu.Lock()
	defer m.mu.Unlock()
	var 候选 []Msg
	for _, x := range m.msgs {
		if x.Turn <= turn {
			候选 = append(候选, x)
		}
	}
	var take []Msg
	n := 0
	for i := len(候选) - 1; i >= 0; i-- {
		c := len([]rune(候选[i].Text))
		if maxChars > 0 && n+c > maxChars {
			break
		}
		take = append(take, 候选[i])
		n += c
	}
	sort.SliceStable(take, func(i, j int) bool { return take[i].Turn <= take[j].Turn })
	return take, n, len(候选) - len(take)
}

// 摘要 是本机算出来的digest（工具名计数 + 结论句），出处档记 estimated —— 不许说成模型写的。
func (m *Memory) 摘要(turn int) (string, int) {
	列, _, 挤掉 := m.窗口(turn, 1<<30)
	计数 := map[string]int{}
	var 最近一句 string
	for _, x := range 列 {
		if x.Tool != "" {
			计数[x.Tool]++
		}
		if x.Role == "user" {
			最近一句 = x.Text
		}
	}
	var 名 []string
	for k, v := range 计数 {
		名 = append(名, fmt.Sprintf("%s×%d", k, v))
	}
	sort.Strings(名)
	s := fmt.Sprintf("这轮会话共 %d 条记忆；工具调用统计：%s；最后一句用户话：%s；窗口外挤掉 %d 条（本机摘要，不是模型写的）",
		len(列), strings.Join(名, "、"), 截(最近一句, 60), 挤掉)
	return s, len(列)
}

// Find 给 memory.recall 用：子串匹配，最近优先。
func (m *Memory) Find(q string, limit int) []Msg {
	m.mu.Lock()
	defer m.mu.Unlock()
	var hits []Msg
	for i := len(m.msgs) - 1; i >= 0; i-- {
		x := m.msgs[i]
		if q == "" || strings.Contains(strings.ToLower(x.Text), strings.ToLower(q)) ||
			strings.Contains(strings.ToLower(x.Tool), strings.ToLower(q)) {
			hits = append(hits, x)
			if limit > 0 && len(hits) >= limit {
				break
			}
		}
	}
	return hits
}

// 发视图的字段名必须是大写开头的导出名：中文首字母在 Go 里算"未导出"，
// 带着 json 标签也不会被编码出去 —— 那样 /api/turns 会回一列空对象，前端看着像"没有历史"。
type 发视图 struct {
	Turn  int      `json:"turn"`
	User  string   `json:"user"`
	Agent string   `json:"agent"`
	Tools []string `json:"tools"`
	Stop  string   `json:"stop"`
}

// 按发 把记忆拍成"每一发一行"，给历史栏用（最近 n 发）。
func (m *Memory) 按发(n int) []发视图 {
	m.mu.Lock()
	defer m.mu.Unlock()
	序 := map[int]*发视图{}
	var 列 []int
	for _, x := range m.msgs {
		v, ok := 序[x.Turn]
		if !ok {
			v = &发视图{Turn: x.Turn}
			序[x.Turn] = v
			列 = append(列, x.Turn)
		}
		switch x.Role {
		case "user":
			v.User = x.Text
		case "agent":
			v.Agent = x.Text
			v.Stop = x.Class
		case "tool":
			v.Tools = append(v.Tools, x.Tool)
		}
	}
	var out []发视图
	for i := len(列) - 1; i >= 0 && len(out) < n; i-- {
		out = append(out, *序[列[i]])
	}
	return out
}

// 最后一次读数 解析指代：往上找最近一次某工具（tool 为空则任意）成功调用留下的 Data[key]。
func (m *Memory) 最后一次读数(tool, key string) (any, bool, int) {
	m.mu.Lock()
	defer m.mu.Unlock()
	for i := len(m.msgs) - 1; i >= 0; i-- {
		x := m.msgs[i]
		if x.Class != ClassOK || x.Data == nil {
			continue
		}
		if tool != "" && x.Tool != tool {
			continue
		}
		if v, ok := x.Data[key]; ok {
			return v, true, x.Turn
		}
	}
	return nil, false, 0
}

// 抽路径 把用户话里像路径/URL/算式的片段扒出来。这是"自然语言 → 工具参数"的机械那半，
// 扒不出来时返回空串，由调用方决定用记忆里的读数还是直接问用户（不许编一个路径）。
func 抽路径(s string) string {
	toks := strings.FieldsFunc(s, func(r rune) bool {
		return r == ' ' || r == '\t' || r == '，' || r == '。' || r == '、' || r == '：' || r == '"' || r == '\'' || r == '(' || r == ')' || r == '（' || r == '）'
	})
	var best string
	for _, t := range toks {
		t = strings.Trim(t, "「」『』[]{};,!?")
		if t == "" {
			continue
		}
		像路径 := strings.ContainsAny(t, `/\`) || strings.Contains(t, ".go") || strings.Contains(t, ".md") ||
			strings.Contains(t, ".json") || strings.Contains(t, ".txt") || strings.HasPrefix(t, ".")
		像URL := strings.HasPrefix(t, "http://") || strings.HasPrefix(t, "https://")
		if (像路径 || 像URL) && len(t) > len(best) {
			best = t
		}
	}
	return best
}

func 抽URL(s string) string {
	i := strings.Index(s, "http://")
	if i < 0 {
		i = strings.Index(s, "https://")
	}
	if i < 0 {
		return ""
	}
	rest := s[i:]
	for j, r := range rest {
		if r == ' ' || r == '\t' || r == '，' || r == '。' || r == '"' || r == '\'' {
			return rest[:j]
		}
	}
	return rest
}

// 抽算式：取一段只含数字与运算符号的最长片段（允许括号与空格）。
func 抽算式(s string) string {
	var 片 []string
	cur := strings.Builder{}
	flush := func() {
		if cur.Len() > 0 {
			片 = append(片, cur.String())
			cur.Reset()
		}
	}
	for _, r := range s {
		允许 := (r >= '0' && r <= '9') || r == '+' || r == '-' || r == '*' || r == '/' || r == '%' ||
			r == '(' || r == ')' || r == '.' || r == '^' || r == ' '
		if 允许 {
			cur.WriteRune(r)
			continue
		}
		flush()
	}
	flush()
	best := ""
	for _, p := range 片 {
		q := strings.TrimSpace(p)
		if !strings.ContainsAny(q, "+-*/%^") {
			continue
		}
		if len(q) > len(best) {
			best = q
		}
	}
	return best
}

func 截(s string, n int) string {
	r := []rune(s)
	if len(r) <= n {
		return s
	}
	return string(r[:n]) + "…"
}
