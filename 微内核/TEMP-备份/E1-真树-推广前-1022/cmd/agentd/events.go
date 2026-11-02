package main

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
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

type EventStep struct {
	No   *int   `json:"no,omitempty"`
	Name string `json:"name,omitempty"`
	Tool string `json:"tool,omitempty"`
}

// Progress 的 Total 用指针：算不出来就是「没这个数」，写 0 会被读成「总共 0 步」，
// 那是这本账最恨的那一族。
type Progress struct {
	Done  int  `json:"done"`
	Total *int `json:"total,omitempty"`
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
	Progress  *Progress  `json:"progress,omitempty"`
	ElapsedMS int64      `json:"elapsed_ms"`
}

type eventBus struct {
	path    string
	f       *os.File
	seq     map[int]int
	t0      time.Time
	written int
	turn    int // 事件属于哪一发；run 级事件用 0
}

// newEventBus：path 为空就不开文件，只在内存里数序（用于「关掉事件层」那一趟与单元测试）。
func newEventBus(path string) *eventBus {
	b := &eventBus{path: path, seq: map[int]int{}, t0: time.Now()}
	if path == "" {
		return b
	}
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		b.path = ""
		return b
	}
	f, err := os.OpenFile(path, os.O_CREATE|os.O_WRONLY|os.O_TRUNC, 0o644)
	if err != nil {
		b.path = ""
		return b
	}
	b.f = f
	return b
}

func (b *eventBus) Close() {
	if b != nil && b.f != nil {
		_ = b.f.Close()
		b.f = nil
	}
}

// seqCanFollow 是序号判据本体：同一发内必须严格 +1。
// 单独拆出来是为了让反臂能直接喂「重复」和「回退」两种坏值 —— 判据不接坏值，就等于没牙。
func seqCanFollow(prev, next int) error {
	switch {
	case next == prev:
		return fmt.Errorf("序号重复：%d 又来一次", next)
	case next < prev:
		return fmt.Errorf("序号回退：%d 之后来了 %d", prev, next)
	}
	return nil
}

// validate 不合格就返回错误且**不落盘**：absent 没理由、档名不认识、kind 空，都属这一族。
func (e *Event) validate() error {
	switch {
	case e.Kind == "":
		return fmt.Errorf("事件没有 kind")
	case !evidenceTiers[e.Evidence]:
		return fmt.Errorf("出处档 %q 不在五档里", e.Evidence)
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
	e.V = 1
	e.TS = time.Now().Format(time.RFC3339Nano)
	e.ElapsedMS = time.Since(b.t0).Milliseconds()
	e.Seq = b.seq[e.Turn] + 1
	if err := seqCanFollow(b.seq[e.Turn], e.Seq); err != nil {
		return err
	}
	ne := e
	if err := ne.validate(); err != nil {
		return err
	}
	line, err := json.Marshal(ne)
	if err != nil {
		return err
	}
	b.seq[e.Turn] = e.Seq
	b.written++
	if b.f == nil {
		return nil
	}
	if _, err := b.f.Write(append(line, '\n')); err != nil {
		return err
	}
	// 先落盘再上屏：sync 失败就不算这条落了账。
	return b.f.Sync()
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
func (r *run) emit(e Event) {
	if r.events == nil {
		return
	}
	e.Session = r.session
	if err := r.events.Emit(e); err != nil {
		r.say("    事件层拒了（第 %d 发，kind=%s）：%v —— 这条没落盘", r.turns, e.Kind, err)
	}
}

func intp(v int) *int { return &v }

func (r *run) stepEv(kind, state, evidence, why, name string, no int) Event {
	return Event{
		Kind: kind, State: state, Evidence: evidence, Why: why, Turn: r.turns,
		Step: &EventStep{No: intp(no), Name: name},
	}
}
