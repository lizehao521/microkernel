package main

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
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
	Accept    *Accept    `json:"accept,omitempty"` // 只有 turn_accepted 带
	ElapsedMS int64      `json:"elapsed_ms"`

	// enteredAt 是「请求入口那一刻」，由造回执的那里定死，不落盘（json:"-"）。
	// Emit 拿它算 ts 与 ack_ms —— 等 emit 时才现取，ack_ms 恒为 0，针1 就是装饰。
	enteredAt time.Time
}

// Accept 是回执的载荷：收到的是哪一发、打算走几步、上限多少、从哪儿能把它停下、
// 断了能不能续。少一样，界面就只能猜 —— 而「猜出来的可续」正是这份研究要治的那一族。
type Accept struct {
	Planned   *int   `json:"planned_steps"` // 只有剧本知道余量；别的驱动不知道就 nil（绝不写 0）
	Limit     *int   `json:"turn_limit"`
	StopVia   string `json:"stop_via"`
	Resumable *bool  `json:"resumable"` // 指针且不带 omitempty：旧记录读回 nil = 没量过，不许塌成 false
	AckMS     *int64 `json:"ack_ms"`    // 距入口多久才回执 —— 针1 数的就是这个
}

// 针1 的口径：回执距请求入口超过这个数就红。
const ackLimitMS = 100

// reCanResume 判「这句话在声称能续」。它必须放过否定式：
// 「断开即取消，不可续」里含「可续」三字，按裸子串判就是把诚实的话当谎抓。
var reCanResume = regexp.MustCompile(`(^|[^不])可续`)

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

// ValidateAccepts 是针1（回执）+ 针6（续传口径）的**可达**形态：判读回来的这本日志 ——
// 每一发的第一条必须是 turn_accepted；ack_ms 给得出来且不超上限；停止入口说得出；
// resumable 不许缺（缺=没量过，另记一笔，不塌成 false）；写成 false 时要有为什么，
// 且这一发的任何一条都不许出现「可续」这种没兑现的声称。
func ValidateAccepts(evs []Event) error {
	order := map[int][]Event{}
	var turns []int
	for _, e := range evs {
		if e.Turn == 0 {
			continue // run 级事件不属于任何一发
		}
		if _, has := order[e.Turn]; !has {
			turns = append(turns, e.Turn)
		}
		order[e.Turn] = append(order[e.Turn], e)
	}
	if len(turns) == 0 {
		return fmt.Errorf("这本日志一条发级事件都没有 —— 回执针没东西可判")
	}
	for _, t := range turns {
		group := order[t]
		if first := group[0]; first.Kind != "turn_accepted" {
			return fmt.Errorf("第 %d 发第一条是 %q，不是 turn_accepted —— 「先回执再干活」落点错了", t, first.Kind)
		}
		var acc *Accept
		claims := []string{}
		for _, e := range group {
			if e.Accept != nil {
				if acc != nil {
					return fmt.Errorf("第 %d 发有两条回执 —— 受理只能有一次", t)
				}
				acc = e.Accept
			}
			for _, s := range []string{e.Why, e.Stop, nameOf(e)} {
				if reCanResume.MatchString(s) {
					claims = append(claims, s)
				}
			}
		}
		if acc == nil {
			return fmt.Errorf("第 %d 发的 turn_accepted 没带载荷", t)
		}
		switch {
		case acc.AckMS == nil:
			return fmt.Errorf("第 %d 发的回执没有 ack_ms —— 针1 无从判断", t)
		case *acc.AckMS > ackLimitMS:
			return fmt.Errorf("第 %d 发的回执距入口 %dms，超上限 %dms", t, *acc.AckMS, ackLimitMS)
		case acc.StopVia == "":
			return fmt.Errorf("第 %d 发的回执没说停止入口在哪", t)
		case acc.Resumable == nil:
			return fmt.Errorf("第 %d 发的 resumable 是 nil —— 能不能续要当场给个话，不许留成没量过", t)
		}
		if acc.Resumable != nil && !*acc.Resumable {
			if group[0].Why == "" {
				return fmt.Errorf("第 %d 发写了不可续却没给为什么", t)
			}
			if len(claims) > 0 {
				return fmt.Errorf("第 %d 发写着 resumable=false，流里却出现「可续」字样：%q —— 界面据此画可续就是谎", t, claims[0])
			}
		}
		if group[0].Step != nil {
			return fmt.Errorf("第 %d 发的回执带了 step —— 受理是发级，不是某一步", t)
		}
	}
	return nil
}

func nameOf(e Event) string {
	if e.Step == nil {
		return ""
	}
	return e.Step.Name + " " + e.Step.Tool
}

// ValidateTurnShape 单独管「回执不许挂 step、run 级事件不许挂发号」这一族轴问题。
// 为什么拆出来：混在序号判据里，红了不知道是哪条在响。
func ValidateTurnShape(evs []Event) error {
	for _, e := range evs {
		switch {
		case e.Turn == 0 && e.Step != nil:
			return fmt.Errorf("run 级事件 %q 带了 step —— 两个轴混在一格", e.Kind)
		case e.Kind == "turn_accepted" && e.Step != nil:
			return fmt.Errorf("turn_accepted 带了 step —— 受理不是某一步")
		}
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
	case e.Accept != nil && e.enteredAt.IsZero():
		// 回执没带入口时刻就没法算 ack_ms；放过去等于让针1 恒过。
		return fmt.Errorf("turn_accepted 没带请求入口时刻 —— ack_ms 会变成 0，那是自证不是度量")
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
	// 时刻优先用「请求入口那一刻」（回执的意义就是那一刻到的多早）；没有入口的其他事件用现在。
	at := time.Now()
	if !e.enteredAt.IsZero() {
		at = e.enteredAt
	}
	e.TS = at.Format(time.RFC3339Nano)
	e.ElapsedMS = time.Since(b.t0).Milliseconds()
	e.Seq = b.seq[e.Turn] + 1
	ne := e
	if ne.Accept != nil && ne.Accept.AckMS == nil {
		// ack_ms 由总线在落盘这一刻现算：把回执挪到内核调用之后，这个数自己会涨 ——
		// 不靠调用方自觉填（填了就能填 0）。
		ms := time.Since(ne.enteredAt).Milliseconds()
		ne.Accept.AckMS = &ms
	}
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

// acceptedEv 造这一发的回执。**入口时刻在这里就定死**，不等 emit 时现取 ——
// 现取的话 ack_ms 恒为 0，针1 就成了挂在没人走的枝上的装饰。
//
// resumable 今天只能写 false：SSE 与 Last-Event-ID 还没落（E4）。
// 诚实地说不可续，比假装能续更协同（研究件 §5.2.4 / 引用 P25-P26）。
func (r *run) acceptedEv() Event {
	resumable := false
	return Event{
		Kind: "turn_accepted", State: "running", Evidence: "measured", Turn: r.turns,
		Why: "断开不能续：还没做 SSE 投送与 Last-Event-ID 重放（E4）",
		// 上限只放一处（Accept.Limit）——同一件事在两格里各写一份，改一份就分叉。
		Accept:    &Accept{Planned: r.plannedLeft(), Limit: intp(r.maxTurns), StopVia: "signal:SIGINT", Resumable: &resumable},
		enteredAt: time.Now(),
	}
}

// plannedLeft：只有剧本驱动知道还剩几发；其他驱动给 nil —— 不知道就写 nil，绝不写 0。
func (r *run) plannedLeft() *int {
	if s, ok := r.drv.(*scripted); ok {
		return intp(s.Left())
	}
	return nil
}
