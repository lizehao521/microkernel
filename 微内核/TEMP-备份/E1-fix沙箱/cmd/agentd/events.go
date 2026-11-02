package main

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sync"
	"time"
)

// 事件层是宿主侧的东西：内核 v1 已冻结（48 键 / 49 格），这里一格都不新增，
// 只是把循环「已经落进账的那些事实」按发按序另写一份，给界面与断线续传当底。
// 形状照 研究-协同工作-1022.md §5.1。

// 五档出处的名字与内核那本账一致。写不进这五个就算不合格 ——
// 宁可当场拒，也不要落一条「看起来像 measured」的假凭据。
var evidenceTiers = map[string]bool{
	"measured": true, "estimated": true, "model_says": true, "relayed": true, "absent": true,
}

// 状态是「这一条在讲什么阶段」，必须是个可分档的 token；
// 结束原因的整句话走 Stop 字段，不许塞进 state（下游就没法按 state 归并了）。
var eventStates = map[string]bool{
	"running": true, "ok": true, "refused": true, "failed": true, "settled": true, "interrupted": true,
}

type EventStep struct {
	No   *int   `json:"no,omitempty"`
	Name string `json:"name,omitempty"`
	Tool string `json:"tool,omitempty"`
}

// Progress 的 Total 用指针：算不出来就是「没这个数」，写 0 会被读成「总共 0 步」，
// 那是这本账最恨的那一族。Limit 另放：额度是额度、工作量是工作量，
// 混在一个字段里会把「跑完」印成「跑了一半」。
type Progress struct {
	Done  int  `json:"done"`
	Total *int `json:"total,omitempty"`
	Limit *int `json:"limit,omitempty"`
}

type Event struct {
	V         int        `json:"v"`
	Session   string     `json:"session"`
	Turn      int        `json:"turn"`
	Seq       int        `json:"seq"`
	TS        string     `json:"ts"`
	Kind      string     `json:"kind"`
	Step      *EventStep `json:"step,omitempty"`
	State     string     `json:"state"`
	Evidence  string     `json:"evidence"`
	Why       string     `json:"why,omitempty"`
	Stop      string     `json:"stop,omitempty"` // 六态结束原因的整句话走这里
	Progress  *Progress  `json:"progress,omitempty"`
	ElapsedMS int64      `json:"elapsed_ms"`
}

type eventBus struct {
	mu       sync.Mutex // seq 与 written 都是「数出来的」，第二个生产者一进来，没锁就是竞态
	path     string
	f        *os.File
	seq      map[int]int
	t0       time.Time
	written  int
	closed   bool
	degraded string // 为什么没落成文件；横幅要说，不许静默降级
}

// newEventBus：path 为空就不开文件，只在内存里数序（用于「关掉事件层」那一趟与单元测试）。
func newEventBus(path string) *eventBus {
	b := &eventBus{path: path, seq: map[int]int{}, t0: time.Now()}
	if path == "" {
		return b
	}
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		b.degraded = "建不了落点目录：" + err.Error()
		b.path = ""
		return b
	}
	// O_APPEND 而不是 O_TRUNC：这本日志是 E4「Last-Event-ID 重放」要读的底，
	// 开文件就把上一趟抹了，等于把别人要续的那个游标源删掉。
	f, err := os.OpenFile(path, os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0o644)
	if err != nil {
		b.degraded = "开不了日志文件：" + err.Error()
		b.path = ""
		return b
	}
	b.f = f
	// 同一本日志可能留着上一趟：append-only 就不许让 seq 重新从 1 开始，
	// 否则 (session,turn,seq) 这个三元组不再唯一，续传会指向两条。
	prev, err := ReadEvents(path)
	if err != nil {
		b.degraded = "读不回既有事件日志，序号没法接续，这一趟不落盘：" + err.Error()
		_ = b.f.Close()
		b.f, b.path = nil, ""
		return b
	}
	for _, e := range prev {
		if e.Seq > b.seq[e.Turn] {
			b.seq[e.Turn] = e.Seq
		}
	}
	return b
}

func (b *eventBus) Close() {
	if b == nil {
		return
	}
	b.mu.Lock()
	defer b.mu.Unlock()
	if b.f != nil {
		_ = b.f.Close()
		b.f = nil
	}
	b.closed = true
}

// stats 是给横幅用的那一读：落了哪、落了几条、为什么没落成。
// 三个都要，少一个就把「量不到」写成「没有」。
func (b *eventBus) stats() (path string, written int, degraded string) {
	if b == nil {
		return "", 0, "事件层没开（--events=false）"
	}
	b.mu.Lock()
	defer b.mu.Unlock()
	return b.path, b.written, b.degraded
}

// seqCanFollow 是序号判据本体：同一发内必须严格 +1。
// 它现在只被 ValidateLog（读回来的整本日志）与臂调用 —— 早先在 Emit 里也调一次，
// 但那里的 next 恒等于 prev+1，是不可达的死牙，删了。
func seqCanFollow(prev, next int) error {
	switch {
	case next == prev:
		return fmt.Errorf("序号重复：%d 又来一次", next)
	case next < prev:
		return fmt.Errorf("序号回退：%d 之后来了 %d", prev, next)
	}
	return nil
}

// ValidateLog 是序号针的**可达**形态：判「读回来的这本日志同一发内严格递增」。
// 判据只有从公开路径走得到，红才是真红。
func ValidateLog(evs []Event) error {
	last := map[int]int{}
	for i, e := range evs {
		if err := seqCanFollow(last[e.Turn], e.Seq); err != nil {
			return fmt.Errorf("第 %d 条不合格：%v", i+1, err)
		}
		last[e.Turn] = e.Seq
	}
	return nil
}

// validate 不合格就返回错误且**不落盘**：absent 没理由、档名不认识、kind 或 state 乱写，都属这一族。
func (e *Event) validate() error {
	switch {
	case e.Kind == "":
		return fmt.Errorf("事件没有 kind")
	case !evidenceTiers[e.Evidence]:
		return fmt.Errorf("出处档 %q 不在五档里", e.Evidence)
	case !eventStates[e.State]:
		return fmt.Errorf("状态 %q 不在白名单里 —— 五档有门禁而状态没有，是不对称的", e.State)
	case e.Evidence == "absent" && e.Why == "":
		return fmt.Errorf("absent 事件没带 why —— 量不到要写为什么量不到，不许静默")
	}
	return nil
}

// Emit 落一条事件。返回的 error 只可能来自这条事件自己不合格或写盘失败；
// 调用方（宿主循环）拿到错误要喊出来，不许吞 —— 吞掉就是「事件层坏了但没人知道」。
func (b *eventBus) Emit(e Event) error {
	if b == nil {
		return nil
	}
	b.mu.Lock()
	defer b.mu.Unlock()
	if b.closed {
		return fmt.Errorf("事件层已关闭，这条不落盘（kind=%s）", e.Kind)
	}
	e.V = 1
	e.TS = time.Now().Format(time.RFC3339Nano)
	e.ElapsedMS = time.Since(b.t0).Milliseconds()
	e.Seq = b.seq[e.Turn] + 1
	ne := e
	if err := ne.validate(); err != nil {
		return err
	}
	line, err := json.Marshal(ne)
	if err != nil {
		return err
	}
	if b.f != nil {
		// 先落盘（含 Sync）再算落了：写失败或 sync 失败都不推进计数与序号，
		// 否则会留下一本「自印条数比文件里多」的假账。
		if _, err := b.f.Write(append(line, '\n')); err != nil {
			return err
		}
		if err := b.f.Sync(); err != nil {
			return err
		}
	}
	b.seq[e.Turn] = e.Seq
	b.written++
	return nil
}

// ReadEvents 把落出去的那份读回来逐条解析 —— 自证用：只数文件字节数不算数，
// 读不回同样条数与同样顺序，就是写了一堆看不见的字。
func ReadEvents(path string) ([]Event, error) {
	b, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	out := []Event{}
	for _, ln := range splitLines(string(b)) {
		var e Event
		if err := json.Unmarshal([]byte(ln), &e); err != nil {
			return out, fmt.Errorf("第 %d 行解析不了：%v", len(out)+1, err)
		}
		out = append(out, e)
	}
	return out, nil
}

func splitLines(s string) []string {
	out := []string{}
	start := 0
	for i := 0; i < len(s); i++ {
		if s[i] == '\n' {
			if i > start {
				out = append(out, s[start:i])
			}
			start = i + 1
		}
	}
	if start < len(s) {
		out = append(out, s[start:])
	}
	return out
}

// emit 是 run 上的薄壳：事件层关掉（bus 为 nil）时整条路径就是零成本。
// 拒收要喊，但喊去 stderr —— stdout 那份正文是能被逐字比对的运行账，
// 诊断写进去等于事件层一坏就把上一条针也一起弄红（分不清是谁在响）。
func (r *run) emit(e Event) {
	if r.events == nil {
		return
	}
	e.Session = r.session
	if err := r.events.Emit(e); err != nil {
		r.errf("    事件层拒了（第 %d 发，kind=%s）：%v —— 这条没落盘", r.turns, e.Kind, err)
	}
}

func intp(v int) *int { return &v }

func (r *run) stepEv(kind, state, evidence, why, name string, no int) Event {
	return Event{
		Kind: kind, State: state, Evidence: evidence, Why: why, Turn: r.turns,
		Step: &EventStep{No: intp(no), Name: name},
	}
}
