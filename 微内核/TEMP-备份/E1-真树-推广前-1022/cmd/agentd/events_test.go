package main

import (
	"bytes"
	"encoding/json"
	"path/filepath"
	"regexp"
	"strings"
	"testing"
)

// E1 要证的几件事，一件一支：
//   序号在同一发内严格递增；absent 没带 why 必须被拒（不是被写成空串）；
//   序号判据本身接得住「重复」与「回退」两种坏值（臂）；
//   开不开事件层，stdout 那一份正文逐字相同（不许污染既有 34 根针比对的输出）；
//   事件里不许出现原话正文（默认不显示 payload，与轨迹页同一条禁区）。

func TestEventSeqMonotonicWithinEachTurn(t *testing.T) {
	dir := t.TempDir()
	r := newRun(t, "full", true, "included", 6)
	evPath := filepath.Join(dir, "run.events.jsonl")
	r.journalPath = filepath.Join(dir, "journal.jsonl")
	r.events = newEventBus(evPath)
	r.loop()
	r.closeOut()

	evs, err := ReadEvents(evPath)
	if err != nil {
		t.Fatalf("事件读不回来：%v", err)
	}
	if len(evs) == 0 {
		t.Fatalf("事件层开了却一条都没落")
	}
	if len(evs) != r.eventsWritten {
		t.Fatalf("文件里 %d 条，总线自印 %d 条 —— 两个数不许并存", len(evs), r.eventsWritten)
	}
	last := map[int]int{}
	seen := map[string]bool{}
	for _, e := range evs {
		if e.V != 1 {
			t.Fatalf("版本号不是 1：%+v", e)
		}
		if e.Session != r.session || e.TS == "" {
			t.Fatalf("事件缺 session 或时刻：%+v", e)
		}
		if err := seqCanFollow(last[e.Turn], e.Seq); err != nil {
			t.Fatalf("第 %d 发序号不合格：%v", e.Turn, err)
		}
		if want := last[e.Turn] + 1; e.Seq != want {
			t.Fatalf("第 %d 发序号跳号：上一条 %d，这条 %d（应为 %d）", e.Turn, last[e.Turn], e.Seq, want)
		}
		last[e.Turn] = e.Seq
		seen[e.Kind] = true
		if e.Evidence == "absent" && e.Why == "" {
			t.Fatalf("落盘的 absent 事件没带 why：%+v", e)
		}
	}
	for _, k := range []string{"run_started", "shot_started", "precheck", "recorded", "run_settled"} {
		if !seen[k] {
			t.Fatalf("事件种类 %q 一条都没有 —— 挂点没生效（现有：%v）", k, keysOf(seen))
		}
	}
	var settled *Event
	for i, e := range evs {
		if e.Kind == "run_settled" {
			settled = &evs[i]
		}
	}
	if settled == nil || settled.Progress == nil || settled.Progress.Total == nil {
		t.Fatalf("收口事件缺 done/total：%+v", settled)
	}
	if settled.Progress.Done != r.shot || *settled.Progress.Total != r.maxTurns {
		t.Fatalf("收口计数与运行态不符：done=%d 应 %d，total=%d 应 %d",
			settled.Progress.Done, r.shot, *settled.Progress.Total, r.maxTurns)
	}
}

func TestAbsentWithoutWhyIsRefusedAndNotWritten(t *testing.T) {
	path := filepath.Join(t.TempDir(), "x.events.jsonl")
	b := newEventBus(path)
	defer b.Close()
	if err := b.Emit(Event{Kind: "step_finished", Turn: 1, Evidence: "absent"}); err == nil {
		t.Fatalf("absent 没带 why 居然落了 —— 这正是「把没量到写成 0」那一族")
	}
	if err := b.Emit(Event{Kind: "step_finished", Turn: 1, Evidence: "guessed"}); err == nil {
		t.Fatalf("出处档不认识也落了：五档之外的词不该进这本账")
	}
	if err := b.Emit(Event{Kind: "", Turn: 1, Evidence: "measured"}); err == nil {
		t.Fatalf("没有 kind 的事件也落了")
	}
	if b.written != 0 {
		t.Fatalf("三条全不合格，却自印落了 %d 条", b.written)
	}
	if err := b.Emit(Event{Kind: "step_finished", Turn: 1, Evidence: "absent", Why: "这一发没走到读回"}); err != nil {
		t.Fatalf("带 why 的 absent 该被收：=%v", err)
	}
	if b.written != 1 {
		t.Fatalf("合格那条没计数：%d", b.written)
	}
}

// 臂：序号判据必须接得住「重复」与「回退」。它红不了，上面那条「全递增」就是恒绿装饰。
func TestSeqArmCatchesDuplicateAndRegress(t *testing.T) {
	if err := seqCanFollow(3, 3); err == nil {
		t.Fatalf("重复序号 3→3 没被抓到")
	}
	if err := seqCanFollow(3, 2); err == nil {
		t.Fatalf("回退序号 3→2 没被抓到")
	}
	if err := seqCanFollow(3, 4); err != nil {
		t.Fatalf("正常递增被误伤：%v", err)
	}
}

// 这一支是 E1 的硬约束：事件层不许改写 stdout 那份可逐字比对的正文。
// 两趟用同一个 journal 路径；但**不能直接比字节** —— stdout 里印了账本字节数，
// 而 encode_journal 内嵌时间戳，同一趟跑两次那个数也会变（现场老规矩：跨进程别比字节，
// 时钟刻度就是抖动源）。所以先把「（N 字节」这一类宽度不定的读数掩掉再比，
// 并单列一条臂证明掩码没把真污染一起掩掉。
func TestEventLayerLeavesStdoutUnchanged(t *testing.T) {
	dir := t.TempDir()
	jp := filepath.Join(dir, "journal.jsonl")

	on := newRun(t, "happy", true, "included", 20)
	on.journalPath = jp
	on.events = newEventBus(filepath.Join(dir, "on.events.jsonl"))
	on.loop()
	on.closeOut()

	off := newRun(t, "happy", true, "included", 20)
	off.journalPath = jp
	off.loop()
	off.closeOut()

	gotOn, gotOff := normVolatile(on.log.(*bytes.Buffer).String()), normVolatile(off.log.(*bytes.Buffer).String())
	if gotOn != gotOff {
		i := 0
		for i < len(gotOn) && i < len(gotOff) && gotOn[i] == gotOff[i] {
			i++
		}
		lo, hi := i-60, i+90
		if lo < 0 {
			lo = 0
		}
		if hi > len(gotOn) {
			hi = len(gotOn)
		}
		if hi > len(gotOff) {
			hi = len(gotOff)
		}
		t.Fatalf("事件层改变了 stdout（掩掉时钟类读数后仍不同）｜第一处差异在第 %d 字节：\n  开：%q\n  关：%q",
			i, gotOn[lo:hi], gotOff[lo:hi])
	}
	if on.eventsWritten == 0 {
		t.Fatalf("这一趟事件层根本没落东西，那「两趟相同」是空对空")
	}
	if on.kpi != off.kpi || on.shot != off.shot {
		t.Fatalf("开事件层改变了账上的数：kpi %d vs %d，发数 %d vs %d", on.kpi, off.kpi, on.shot, off.shot)
	}
}

// 叶子臂：事件层一旦拒收，必须**在 stdout 上喊出来**。
// 这条要是不红，上面那条「两趟相同」就可能是「事件层坏了也没人知道」的另一种写法。
func TestEmitFailureIsLoudOnStdout(t *testing.T) {
	r := newRun(t, "happy", true, "included", 20)
	r.events = newEventBus(filepath.Join(t.TempDir(), "arm.events.jsonl"))
	before := r.log.(*bytes.Buffer).Len()
	r.emit(Event{Kind: "step_finished", Evidence: "absent"}) // 故意不给 why
	after := r.log.(*bytes.Buffer).String()
	if !strings.Contains(after[before:], "事件层拒了") {
		t.Fatalf("拒收没在 stdout 上喊出来 —— 事件层坏了会静默")
	}
	if !strings.Contains(after[before:], "absent 事件没带 why") {
		t.Fatalf("喊是喊了，没说要紧的是哪一条：%q", after[before:])
	}
	r.events.Close()
}

var reVolatile = regexp.MustCompile(`（[0-9]+ 字节`)

func normVolatile(s string) string { return reVolatile.ReplaceAllString(s, "（N 字节") }

// 禁区：事件默认不带原话正文（与轨迹页同一条）。
func TestEventsCarryNoPayloadText(t *testing.T) {
	path := filepath.Join(t.TempDir(), "p.events.jsonl")
	r := newRun(t, "full", true, "included", 6)
	r.journalPath = filepath.Join(t.TempDir(), "journal.jsonl")
	r.events = newEventBus(path)
	r.loop()
	r.closeOut()
	raw, err := json.Marshal(mustReadEvents(t, path))
	if err != nil {
		t.Fatalf("序列化事件：%v", err)
	}
	s := string(raw)
	for _, banned := range []string{nums, userAsk, systemPrompt, "把 27"} {
		if strings.Contains(s, banned) {
			t.Fatalf("事件里出现了原话正文（%q）—— 默认不显示 payload 这条禁区破了", banned)
		}
	}
}

func keysOf(m map[string]bool) []string {
	out := []string{}
	for k := range m {
		out = append(out, k)
	}
	return out
}

func mustReadEvents(t *testing.T, path string) []Event {
	t.Helper()
	evs, err := ReadEvents(path)
	if err != nil {
		t.Fatalf("读事件：%v", err)
	}
	return evs
}
