package main

import (
	"encoding/json"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

// E2 要证的几件事，一件一支：
//   每一发的第一条恒为 turn_accepted（先回执再干活 —— 落点在装配/驱动/内核调用之前）；
//   回执带得出载荷：余量、上限、停止入口、能不能续；
//   ack_ms 是从「请求入口那一刻」到落盘的**真实延迟**，不是恒 0 的装饰；
//   resumable 写成 false 时必须给为什么，且这条流的任何一处不许出现没兑现的「可续」声称；
//   判据是可达的：坏值从公开路径（读回来的整本日志）喂进去就能红。

// mkAccept 造一条回执载荷（臂用：坏值要能进判据，判据才不是散文）。
func mkAccept(t *testing.T, ackMS int64, resumable *bool, why, stopVia string, evs *[]Event, turn int) {
	t.Helper()
	a := &Accept{Planned: intp(3), Limit: intp(20), StopVia: stopVia, Resumable: resumable}
	ms := ackMS
	a.AckMS = &ms
	*evs = append(*evs, Event{V: 1, Session: "arm", Turn: turn, Seq: len(*evs) + 1,
		Kind: "turn_accepted", State: "running", Evidence: "measured", Why: why, Accept: a})
}

func TestTurnAcceptedLeadsEveryTurn(t *testing.T) {
	dir := t.TempDir()
	r := newRun(t, "full", true, "included", 20)
	path := filepath.Join(dir, "acc.events.jsonl")
	r.journalPath = filepath.Join(dir, "journal.jsonl")
	r.events = newEventBus(path)
	r.loop()
	r.closeOut()

	evs := mustReadEvents(t, path)
	if err := ValidateLog(evs); err != nil {
		t.Fatalf("序号不合格：%v", err)
	}
	if err := ValidateTurnShape(evs); err != nil {
		t.Fatalf("轴混了：%v", err)
	}
	if err := ValidateAccepts(evs); err != nil {
		t.Fatalf("回执判据红：%v", err)
	}
	accepts, shots := 0, 0
	for _, e := range evs {
		switch e.Kind {
		case "turn_accepted":
			accepts++
		case "shot_started":
			shots++
		}
	}
	// 回执数必须不少于干活数：一发可以先回执后失败，反过来就是「没受理就干活」。
	if accepts < shots || accepts == 0 {
		t.Fatalf("回执 %d 条、干活 %d 条 —— 受理与干活的对应关系不对", accepts, shots)
	}
	if got := r.events.written; got != len(evs) {
		t.Fatalf("自印 %d 条，文件 %d 条", got, len(evs))
	}
}

func TestReceiptPayloadIsHonest(t *testing.T) {
	r := newRun(t, "happy", true, "included", 20)
	path := filepath.Join(t.TempDir(), "p.events.jsonl")
	r.events = newEventBus(path)
	r.loop()
	r.closeOut()

	first := 0
	for _, e := range mustReadEvents(t, path) {
		if e.Kind != "turn_accepted" {
			continue
		}
		first++
		if first > 2 {
			break
		}
		a := e.Accept
		if a == nil {
			t.Fatalf("回执没带载荷：%+v", e)
		}
		if a.StopVia == "" {
			t.Fatal("回执没说停止入口在哪 —— 界面拿着这条流没法喊停")
		}
		if a.Limit == nil || *a.Limit != r.maxTurns {
			t.Fatalf("回执的上限 %v 应与 --max-turns %d 一致", a.Limit, r.maxTurns)
		}
		// 剧本驱动知道余量；不知道必须给 nil，不许给 0。
		if a.Planned == nil {
			t.Fatal("scripted 驱动应当知道还剩几发，给了 nil")
		}
		if *a.Planned <= 0 || *a.Planned > len(r.drv.(*scripted).q) {
			t.Fatalf("planned_steps=%d 不在 (0, 剧本长度] 里 —— 余量数错了", *a.Planned)
		}
		if a.Resumable == nil {
			t.Fatal("resumable 不许留 nil：能不能续要当场给个话")
		}
		if *a.Resumable {
			t.Fatal("E4 没落地，resumable 不能写 true")
		}
		if e.Why == "" {
			t.Fatal("写了不可续却没给为什么")
		}
		if a.AckMS == nil {
			t.Fatal("回执没有 ack_ms —— 针1 无从判断")
		}
	}
	if first == 0 {
		t.Fatal("一条回执都没有")
	}
}

// 叶子臂：ack_ms 必须真反映「入口时刻 → 落盘」这段延迟。
// 把入口时刻往前拨 250ms 再落盘，判据必须红 —— 若 Emit 是「落盘时才现取时刻」，
// ack_ms 恒为 0，这条臂就永远不红，针1 是装饰。
func TestLateReceiptGoesRed(t *testing.T) {
	b := newEventBus(filepath.Join(t.TempDir(), "late.events.jsonl"))
	defer b.Close()
	e := Event{Kind: "turn_accepted", State: "running", Evidence: "measured", Turn: 1,
		Why: "断开不能续：没做 SSE", Accept: &Accept{Planned: intp(1), Limit: intp(20),
			StopVia: "signal:SIGINT", Resumable: boolp(false)}}
	e.enteredAt = time.Now().Add(-250 * time.Millisecond)
	if err := b.Emit(e); err != nil {
		t.Fatalf("迟到那条该收下（判据在读回侧）：%v", err)
	}
	evs := mustReadEvents(t, b.path)
	if evs[0].Accept.AckMS == nil || *evs[0].Accept.AckMS < 200 {
		t.Fatalf("ack_ms=%v，没量到那 250ms —— 说明时刻是落盘时现取的", evs[0].Accept.AckMS)
	}
	if err := ValidateAccepts(evs); err == nil {
		t.Fatal("回执距入口 250ms（上限 100ms）判据却没红 —— 针1 恒绿")
	}
}

// 回执没带入口时刻就必须被拒 —— 放过去等于让 ack_ms 变成自证的 0。
func TestReceiptWithoutEntryInstantIsRefused(t *testing.T) {
	b := newEventBus(filepath.Join(t.TempDir(), "noentry.events.jsonl"))
	defer b.Close()
	err := b.Emit(Event{Kind: "turn_accepted", State: "running", Evidence: "measured", Turn: 1,
		Why: "断开不能续：没做 SSE", Accept: &Accept{Limit: intp(20), StopVia: "signal:SIGINT", Resumable: boolp(false)}})
	if err == nil || !strings.Contains(err.Error(), "入口时刻") {
		t.Fatalf("缺入口时刻的回执居然落了（err=%v）—— ack_ms 会是恒 0 的假数", err)
	}
}

// 判据接坏值：每一族坏值各红一次，一条不许误伤诚实的否定句。
func TestAcceptArmsCatchEachBadShape(t *testing.T) {
	type bad struct {
		name   string
		mutate func(ev *Event)
	}
	cases := []bad{
		{"ack 超限", func(e *Event) { ms := int64(101); e.Accept.AckMS = &ms }},
		{"ack 没给", func(e *Event) { e.Accept.AckMS = nil }},
		{"停止入口空着", func(e *Event) { e.Accept.StopVia = "" }},
		{"resumable 留 nil", func(e *Event) { e.Accept.Resumable = nil }},
		{"不可续没给为什么", func(e *Event) { e.Why = "" }},
		{"声称可续（没兑现）", func(e *Event) { e.Why = "断开可续" }},
	}
	for _, c := range cases {
		evs := []Event{}
		mkAccept(t, 5, boolp(false), "断开不能续：没做 SSE", "signal:SIGINT", &evs, 1)
		evs = append(evs, Event{V: 1, Session: "arm", Turn: 1, Seq: 2, Kind: "shot_started",
			State: "running", Evidence: "measured", Step: &EventStep{No: intp(1), Name: "assemble"}})
		c.mutate(&evs[0])
		if err := ValidateAccepts(evs); err == nil {
			t.Fatalf("坏法 %q 没被抓到 —— 这一族判据瞎了", c.name)
		}
	}

	// 顺序坏了：第一条不是回执。
	late := []Event{
		{V: 1, Session: "arm", Turn: 1, Seq: 1, Kind: "shot_started", State: "running",
			Evidence: "measured", Step: &EventStep{No: intp(1), Name: "assemble"}},
	}
	mkAccept(t, 5, boolp(false), "断开不能续：没做 SSE", "signal:SIGINT", &late, 1)
	late[1].Seq = 2
	if err := ValidateAccepts(late); err == nil || !strings.Contains(err.Error(), "第一条") {
		t.Fatalf("「先干活后回执」没被抓到（err=%v）—— E2 的落点约束等于没写", err)
	}

	// 双回执。
	dup := []Event{}
	mkAccept(t, 5, boolp(false), "断开不能续：没做 SSE", "signal:SIGINT", &dup, 1)
	mkAccept(t, 6, boolp(false), "断开不能续：没做 SSE", "signal:SIGINT", &dup, 1)
	dup[1].Seq = 2
	if err := ValidateAccepts(dup); err == nil {
		t.Fatal("一发两条回执没被抓到")
	}

	// 回执挂了 step：轴混格。
	step := []Event{}
	mkAccept(t, 5, boolp(false), "断开不能续：没做 SSE", "signal:SIGINT", &step, 1)
	step[0].Step = &EventStep{No: intp(1), Name: "assemble"}
	if err := ValidateTurnShape(step); err == nil {
		t.Fatal("受理带上 step 没被抓到")
	}

	// 不许误伤：诚实的否定句里含「可续」三字，不能当谎抓。
	ok := []Event{}
	mkAccept(t, 5, boolp(false), "断开即取消，不可续：没做 SSE", "signal:SIGINT", &ok, 1)
	if err := ValidateAccepts(ok); err != nil {
		t.Fatalf("把「不可续」当谎抓了：%v —— 这会把诚实的话挤掉", err)
	}
}

// 三态：resumable=true 是 E4 以后的合法值，判据不许把它当坏值；
// 但 true 也不许在 E4 之前由生产路径写出来 —— 这一支钉住「今天生产只会写 false」。
func TestResumableTrueIsAcceptedButNotProduced(t *testing.T) {
	r := newRun(t, "happy", true, "included", 20)
	path := filepath.Join(t.TempDir(), "true.events.jsonl")
	r.events = newEventBus(path)
	r.loop()
	r.closeOut()
	for _, e := range mustReadEvents(t, path) {
		if e.Accept != nil && e.Accept.Resumable != nil && *e.Accept.Resumable {
			t.Fatal("E4 没落地就写了 resumable=true —— 那是这条流最不该出现的一种谎")
		}
	}
	evs := []Event{}
	mkAccept(t, 5, boolp(true), "", "signal:SIGINT", &evs, 1)
	if err := ValidateAccepts(evs); err != nil {
		t.Fatalf("resumable=true 被判据当坏值拒了（%v）—— E4 落地那天这条会挡路", err)
	}
}

// 落盘形状：resumable 不带 omitempty —— 旧记录读回来是 nil（没量过），
// 而不是被 JSON 折叠成 false（真不是）。这一支就是它的对照。
func TestResumableFieldSurvivesFalse(t *testing.T) {
	line, err := json.Marshal(mustAcceptEvent(t))
	if err != nil {
		t.Fatalf("序列化：%v", err)
	}
	s := string(line)
	if !strings.Contains(s, `"resumable":false`) {
		t.Fatalf("resumable=false 被 omitempty 吃掉了：%s", s)
	}
	var back Event
	if err := json.Unmarshal(line, &back); err != nil {
		t.Fatalf("读回：%v", err)
	}
	if back.Accept.Resumable == nil || *back.Accept.Resumable {
		t.Fatalf("读回来的 resumable 不是 false：%v", back.Accept.Resumable)
	}
}

func mustAcceptEvent(t *testing.T) Event {
	t.Helper()
	evs := []Event{}
	mkAccept(t, 5, boolp(false), "断开不能续：没做 SSE", "signal:SIGINT", &evs, 1)
	return evs[0]
}

func boolp(v bool) *bool { return &v }
