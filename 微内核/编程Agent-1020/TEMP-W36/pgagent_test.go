package main

import (
	"encoding/json"
	"fmt"
	"io"
	"io/fs"
	"math"
	"net"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"testing"
	"time"
)

func nop(Step) {}

// 针 1：五档加总恒等式必须能红。
// 造一条没有合法档名的结论，mixOf 不许把它悄悄算进某一档 —— 塌档就是这套件最致命的假绿。
func TestMixIdentityCatchesCollapsedBucket(t *testing.T) {
	r := Result{
		Findings: []Finding{{Rule: "a", Basis: Measured, Severity: "minor"}, {Rule: "b", Basis: Basis("我觉得是"), Severity: "minor"}},
		Unknowns: []Unknown{{What: "x", Basis: Absent}},
	}
	mixOf(&r)
	if r.MixOK {
		t.Fatalf("非法档名被吞掉了：加总仍报「对得上」%+v —— 这根针就白配了", r.Mix)
	}
	if r.Mix.Total != 3 {
		t.Fatalf("总条数应为 3（含那条非法档），实际 %d", r.Mix.Total)
	}
	if r.Mix.Measured+r.Mix.Estimated+r.Mix.ModelSays+r.Mix.Relayed+r.Mix.Absent != 2 {
		t.Fatal("合法档只该收进 2 条")
	}
}

// 针 2：接缝没装时，内核那三步一律 absent，且**不许**长得像跑过。
// 这条是"缺口要看得见"的机械形态：装不装接缝，界面读的是同一份数。
func TestKernelStepsAreAbsentNotGreenWhenSeamMissing(t *testing.T) {
	res := runLoop(fixtureClean, "x", "go", "t", 1, nop, nil, "")
	for _, s := range res.Trace {
		if !strings.HasPrefix(s.Name, "kernel.") {
			continue
		}
		if s.Run || s.Basis != Absent {
			t.Fatalf("%s 在没接缝时被报成 ran=%v basis=%s —— 空档不许像绿", s.Name, s.Run, s.Basis)
		}
		if !strings.Contains(s.Summary, "W4") {
			t.Fatalf("%s 的 absent 没带理由：%q", s.Name, s.Summary)
		}
	}
}

// 针 3：接上真内核接缝 ⇒ 同三步翻成 measured，KPI ≥1，且 KPI 的数与 Decisions 的条数一致。
// 与针 2 配对：两读都得有数，不能一个恒绿一个恒红。
func TestSeamInstalledMakesTheLedgerDecide(t *testing.T) {
	defer func() { seam = nil; seamReadBack = false }()
	installSeam(0, true)
	res := runLoop(fixtureDirty, "这段有什么问题", "go", "seam-on", 1, nop, nil, "")
	for _, s := range res.Trace {
		if strings.HasPrefix(s.Name, "kernel.") && !s.Run {
			t.Fatalf("接缝装好了但 %s 仍记没跑：%s", s.Name, s.Summary)
		}
	}
	if res.KPI < 1 {
		t.Fatalf("KPI=%d —— 账上读回来的值一次都没改写结果，那「落账」只是走过场", res.KPI)
	}
	// KPI 只数"真的改写了结果"的格；读回来但没产生动作的不计（所以 KPI ≤ Decisions 是口径，不是 bug）。
	if res.KPI > len(res.Decisions) {
		t.Fatalf("KPI=%d 比读回的格数 %d 还多：数了没读过的东西", res.KPI, len(res.Decisions))
	}
	if res.Metrics.BytesSource == "" {
		t.Fatal("账上 content_bytes 没落成独立一格（BytesSource 空）")
	}
	// 两个量必须分列：账上的 content_bytes 含系统件+工具清单+问题+代码，比贴进来的代码字节大。
	// 谁把它们写成同一个数，谁就是在拿"送出量"冒充"代码量"。
	if res.Metrics.LedgerContentBytes <= 0 {
		t.Fatalf("账上 content_bytes 没读回来（=%d）", res.Metrics.LedgerContentBytes)
	}
	if res.Metrics.LedgerContentBytes == res.Metrics.Bytes {
		t.Fatalf("两个量撞成同一个数（%d）：说明有一格被冒名顶替", res.Metrics.LedgerContentBytes)
	}
	if res.Metrics.LedgerContentBytes < res.Metrics.Bytes {
		t.Fatalf("账上送出量 %d 比代码量 %d 还小：装配少了东西", res.Metrics.LedgerContentBytes, res.Metrics.Bytes)
	}
	t.Logf("读数自印：读回 %d 格、其中真改写结果 %d 格；五档=%+v；verify=%s",
		len(res.Decisions), res.KPI, res.Mix, lastLine(res.Trace, "kernel.verify"))
	// 声明读者：读过的每一格都署了名（内核自己核不到那一半，agentd 的 S7 同族）。
	rep := lastLine(res.Trace, "kernel.readers_report")
	if rep == "" || !strings.Contains(rep, "格") {
		t.Fatalf("readers_report 没回来或没数格：%q", rep)
	}
	t.Logf("读者声明后的读数：%s", rep)
}

// 针 3b：反臂 —— 把读回关掉 ⇒ KPI 必须掉回 0，且读回那步如实记没跑。
// 这条不掉，说明 KPI 数的不是"账真的决定了这一步"。
func TestAntiArmNoReadBackDropsKPIToZero(t *testing.T) {
	defer func() { seam = nil; seamReadBack = false }()
	installSeam(0, false)
	res := runLoop(fixtureDirty, "这段有什么问题", "go", "seam-off", 1, nop, nil, "")
	if res.KPI != 0 {
		t.Fatalf("不读回还有 KPI=%d —— 那这个数不是从账上来的", res.KPI)
	}
	for _, s := range res.Trace {
		if s.Name == "kernel.read_back" && s.Run {
			t.Fatal("反臂下读回这步还记跑过了")
		}
	}
}

// 针 3c：预检能红，且红了就不许落账。
func TestPrecheckRedMeansNothingRecorded(t *testing.T) {
	defer func() { seam = nil; seamReadBack = false }()
	installSeam(0, true)
	rpc := newPgRPC(0, false)
	// 发号写 0：内核自己的判据会当场拒（"第几发是 0，发号从 1 起"）。
	// 这一发之所以还能装配出来，是因为装配只管形状；判据在内核那侧。
	rep, err := runSeam(rpc, mustPair(t, "预检要红", 0, fixtureDirty), "预检要红", 0, true)
	if err == nil {
		t.Fatalf("发号 0 这一发居然过了预检：%s", rep.Verdict)
	}
	if rep.Recorded {
		t.Fatal("预检红了还落了账 —— 这条闸门等于没装")
	}
	if !strings.Contains(err.Error(), "预检被内核判据拒") {
		t.Fatalf("拒因不对：%v", err)
	}
	t.Logf("预检红的那句原话：%s", rep.Verdict)
}

func mustPair(t *testing.T, session string, call int, code string) map[string]any {
	t.Helper()
	pair, err := buildPair(session, call, code, "q", "本地分析件的一发结论")
	if err != nil {
		t.Fatalf("装配：%v", err)
	}
	return pair
}

// 针 4：默认不执行用户代码 —— 扫本模块自己的源码，os/exec 一条都不许有。
// 这条和内核那道隔离闸同族：一句"我们不执行"是散文，数 import 才是判据。
func TestModuleNeverExecutesUserCode(t *testing.T) {
	dir, err := os.Getwd()
	if err != nil {
		t.Fatal(err)
	}
	var hits []string
	filepath.Walk(dir, func(p string, info os.FileInfo, err error) error {
		if err != nil || info.IsDir() || !strings.HasSuffix(p, ".go") || strings.HasSuffix(p, "_test.go") {
			return nil
		}
		b, err := os.ReadFile(p)
		if err != nil {
			return nil
		}
		s := string(b)
		for _, pat := range []string{`"os/exec"`, `exec.Command`, `syscall`, `"unsafe"`} {
			if strings.Contains(s, pat) {
				hits = append(hits, filepath.Base(p)+":"+pat)
			}
		}
		return nil
	})
	if len(hits) > 0 {
		t.Fatalf("本模块出现了执行/越界能力：%s —— 设计件 §0 硬约束 1 破了", strings.Join(hits, ", "))
	}
}

// 针 5：干净样本不许被编出 critical（尺子不能凭空红），但脏样本必须红（尺子不能凭空绿）。
// 两头都测才叫一把尺子 —— 只测一头会退化成"永远放行"或"永远拒绝"。
func TestRulerDiscriminatesBothWays(t *testing.T) {
	dirty := runLoop(fixtureDirty, "x", "go", "t", 1, nop, nil, "")
	clean := runLoop(fixtureClean, "x", "go", "t", 2, nop, nil, "")
	if countSeverity(dirty.Findings, "critical") == 0 {
		t.Fatalf("脏样本一条 critical 都没命中：findings=%d —— 尺子钝了", len(dirty.Findings))
	}
	if countSeverity(clean.Findings, "critical") != 0 {
		t.Fatalf("干净样本被编出 critical：%+v —— 尺子在凭空红", clean.Findings)
	}
	t.Logf("读数自印：脏 %d 条（critical %d）/ 干净 %d 条（critical %d）",
		len(dirty.Findings), countSeverity(dirty.Findings, "critical"),
		len(clean.Findings), countSeverity(clean.Findings, "critical"))
}

// 针 6：非 Go 一律降 estimated，不许冒 measured。
func TestNonGoDowngradesToEstimated(t *testing.T) {
	res := runLoop(fixturePy, "x", "auto", "t", 3, nop, nil, "")
	if res.Metrics.Parsed {
		t.Fatal("Python 样本不该被标成真解析")
	}
	for _, f := range res.Findings {
		if f.Basis == Measured {
			t.Fatalf("非 Go 语言出了 measured 结论：%+v", f)
		}
	}
	if len(res.Findings) == 0 {
		t.Fatal("Python 样本一条都没命中（fixture 里有 except/pass 与 TODO）—— 降档扫描没跑")
	}
}

// 针 7：轨迹落盘要能跨进程往返 —— 写完读回来，条数与指纹对得上。
// 只看"写没报错"不算证；断开重开还在才算。
func TestStoreRoundTripKeepsCounts(t *testing.T) {
	dir := filepath.Join(t.TempDir(), "数据")
	s := newStore(dir)
	for i := 1; i <= 3; i++ {
		res := runLoop(fixtureDirty, "x", "go", "t-round", i, nop, nil, "")
		if err := s.append(recordOf(res, fixtureDirty)); err != nil {
			t.Fatalf("第 %d 发落盘：%v", i, err)
		}
	}
	got, err := s.history("t-round")
	if err != nil {
		t.Fatalf("读回：%v", err)
	}
	if len(got) != 3 {
		t.Fatalf("读回 %d 条，应为 3", len(got))
	}
	for _, r := range got {
		if r.Sha == "" || r.Findings == 0 || r.StepsRan == 0 {
			t.Fatalf("落盘那行是空的或不完整：%+v", r)
		}
		if r.StepsRan >= r.StepsAll {
			t.Fatalf("absent 的步骤被记成跑过：%+v", r)
		}
	}
}

// 针 9：考卷的判分器本身要能红。
// 「全绿」只有在尺子会红的时候才有意义 —— 这里故意喂一条假断言，Fails 必须 +1。
func TestReporterCanGoRed(t *testing.T) {
	rp := &reporter{}
	rp.check("真断言", hasRule(dirtyFindings(t), "ignore-error"), "")
	if rp.Fails != 0 {
		t.Fatalf("真断言被判红了（Fails=%d）", rp.Fails)
	}
	rp.check("假断言（干净样本不许有脏判据）", hasRule(runLoop(fixtureClean, "x", "go", "t", 9, nop, nil, "").Findings, "ignore-error"), "")
	if rp.Fails != 1 {
		t.Fatalf("判分器对假断言没记红：Fails=%d —— 那 selfcheck 的 [OK] 是白给的", rp.Fails)
	}
}

func dirtyFindings(t *testing.T) []Finding {
	t.Helper()
	return runLoop(fixtureDirty, "x", "go", "t", 8, nop, nil, "").Findings
}

// 针 10：前后端字段名是两份代码，改一边就会静默断。
// 这条把 app.js 真读的字段逐个点名，缺一根就红（W1 浏览器实测就撞过这个：
// 后端把步骤名标成 json:"tool"，前端读 s.name ⇒ 页面上 KPI 那句永远走"没装"分支）。
func TestFrontendFieldNamesExistInTheJSON(t *testing.T) {
	installSeam(0, true)
	defer func() { seam = nil; seamReadBack = false }()
	res := runLoop(fixtureDirty, "x", "go", "wire", 1, nop, nil, "")
	b, err := json.Marshal(res)
	if err != nil {
		t.Fatal(err)
	}
	var top map[string]any
	if err := json.Unmarshal(b, &top); err != nil {
		t.Fatal(err)
	}
	want := map[string][]string{
		"result":   {"session", "turn", "question", "answer_summary", "findings", "metrics", "trace", "unknowns", "provenance_mix", "mix_identity_ok", "code_executed", "kpi_ledger_decided", "kpi_why", "ledger_decisions", "stop_reason", "stop_why"},
		"step":     {"step", "name", "out", "ms", "basis", "ran"},
		"finding":  {"id", "rule", "severity", "where", "evidence", "basis", "claim", "verify"},
		"unknown":  {"what", "why_absent", "how_to_get", "basis"},
		"decision": {"key", "side", "basis", "claim", "effect"},
		"metrics":  {"bytes", "lines", "lang", "lang_how", "lang_why", "parsed", "funcs", "max_func_lines", "imports", "unused_imports", "ignored_error_sites", "print_calls", "sha256_of_code", "tokens_basis_from_ledger", "bytes_source", "ledger_content_bytes"},
		"mix":      {"measured", "estimated", "model_says", "relayed", "absent", "total"},
	}
	sub := func(v any, keys []string, tag string) {
		m, ok := v.(map[string]any)
		if !ok {
			t.Fatalf("%s 不是一个对象：%T", tag, v)
		}
		for _, k := range keys {
			if _, has := m[k]; !has {
				t.Fatalf("%s 少了前端要读的字段 %q（改名就得同时改 app.js，不然页面静默说假话）", tag, k)
			}
		}
	}
	sub(top, want["result"], "result")
	sub(top["trace"].([]any)[0], want["step"], "step")
	sub(top["findings"].([]any)[0], want["finding"], "finding")
	sub(top["unknowns"].([]any)[0], want["unknown"], "unknown")
	sub(top["ledger_decisions"].([]any)[0], want["decision"], "decision")
	sub(top["metrics"], want["metrics"], "metrics")
	sub(top["provenance_mix"], want["mix"], "mix")
	if _, old := top["trace"].([]any)[0].(map[string]any)["tool"]; old {
		t.Fatal("步骤名还在用旧字段 tool：前端读的是 name")
	}
}
func TestSessionNameIsSanitized(t *testing.T) {
	s := newStore("数据")
	p := s.path("../../Windows/临时")
	if strings.Contains(p, "..") {
		t.Fatalf("会话名没归一，路径逃逸：%s", p)
	}
	if filepath.Dir(p) != "数据" {
		t.Fatalf("落点跑出了数据目录：%s", p)
	}
}

// 针 11：一上来就被打断，也要收口 —— 但**没跑的步不许出现在轨迹里**。
// 这条盯的是另一种假绿：中断时"顺手把后面的步标成没跑"发出去，页面上看着像跑到了第 9 步。
func TestInterruptRightAwayStillFoldsButDoesNotFakeSteps(t *testing.T) {
	abort := make(chan struct{})
	close(abort)
	res := runLoop(fixtureDirty, "x", "go", "abort-early", 1, nop, abort, "")
	if res.StopReason != "被打断" {
		t.Fatalf("结束原因=%q，应为「被打断」", res.StopReason)
	}
	for _, s := range res.Trace {
		if strings.HasPrefix(s.Name, "kernel.") {
			t.Fatalf("一步就被打断，轨迹里却出现了 %s —— 没跑的步不许发", s.Name)
		}
	}
	if !res.MixOK {
		t.Fatalf("打断那一跳的加总恒等式塌了：%s", res.MixWhy)
	}
	if lastLine(res.Trace, "stop") == "" {
		t.Fatal("没有 stop 那一步：页面上看不出这一发是怎么结束的")
	}
	if res.Mix.Absent == 0 || len(res.Unknowns) == 0 {
		t.Fatalf("早停那一跳的五档=%+v、未决 %d 条 —— 全 0 会被读成\"量到 0\"，没走到的步骤必须记 absent", res.Mix, len(res.Unknowns))
	}
	t.Logf("读数自印：%s｜五档=%+v", lastLine(res.Trace, "stop"), res.Mix)
}

// 针 12：账落完、读回之后才被打断 ⇒ KPI 必须留着（已经发生的事不因打断而消失），
// 后面的网关那步不许出现。用 emitter 在收到第 7 步那一刻关通道 —— 不靠 sleep，测起来是确定的。
func TestInterruptAfterTheLedgerKeepsTheKPI(t *testing.T) {
	defer func() { seam = nil; seamReadBack = false }()
	installSeam(0, true)
	abort := make(chan struct{})
	seen := 0
	emit := func(s Step) {
		if s.Name == "kernel.read_back" {
			seen++
			if seen == 1 {
				close(abort)
			}
		}
	}
	res := runLoop(fixtureDirty, "x", "go", "abort-late", 1, emit, abort, "")
	if res.StopReason != "被打断" {
		t.Fatalf("结束原因=%q", res.StopReason)
	}
	if res.KPI < 1 {
		t.Fatalf("账都落了、也读回了，KPI 却是 %d —— 已发生的事不许因为打断就抹掉", res.KPI)
	}
	for _, s := range res.Trace {
		if s.Name == "gateway" {
			t.Fatal("打断之后还发了网关那一步")
		}
	}
	t.Logf("读数自印：%s", lastLine(res.Trace, "stop"))
}

// 针 13：不传 abort（= 页面正常跑完）⇒ 那九步一步不少，结束原因是「跑完」。
// 与针 11/12 配成三态：跑完 / 早停 / 晚停，各有各的读数，不许都长得像跑完。
func TestNoAbortRunsAllNineSteps(t *testing.T) {
	res := runLoop(fixtureDirty, "x", "go", "no-abort", 1, nop, nil, "")
	if res.StopReason != "跑完" {
		t.Fatalf("没打断却记成 %q", res.StopReason)
	}
	want := map[string]bool{"intake": false, "shape": false, "select-analyzers": false, "analyze": false,
		"kernel.check_call": false, "kernel.record_call": false, "kernel.read_back": false, "gateway": false, "fold": false}
	for _, s := range res.Trace {
		if _, ok := want[s.Name]; ok {
			want[s.Name] = true
		}
	}
	var miss []string
	for k, v := range want {
		if !v {
			miss = append(miss, k)
		}
	}
	if len(miss) > 0 {
		sort.Strings(miss)
		t.Fatalf("九步里缺了 %s（轨迹共 %d 步）", strings.Join(miss, ", "), len(res.Trace))
	}
}

// 针 14：历史那半边的字段名也要点名 —— 针 10 只护住了 /api/turn 的结果，
// 而 /api/history 是另一个结构体（Record）。刚才浏览器实测就撞上 `指纹 undefined`：
// 后端叫 sha256_of_code，前端读的是 t.sha。两个接口两张皮，就得两根针。
func TestHistoryRecordFieldNamesMatchFrontend(t *testing.T) {
	res := runLoop(fixtureDirty, "x", "go", "hist", 1, nop, nil, "")
	b, err := json.Marshal(recordOf(res, fixtureDirty))
	if err != nil {
		t.Fatal(err)
	}
	var m map[string]any
	if err := json.Unmarshal(b, &m); err != nil {
		t.Fatal(err)
	}
	for _, k := range []string{"ts", "session", "turn", "question", "answer_summary", "findings",
		"unknowns", "provenance_mix", "mix_identity_ok", "sha256_of_code", "steps_ran", "steps_total",
		"stop_reason", "stop_why",
		// W17 之后第 ① 步会当场说"超了不会落账"——这三件也得在历史里活着（针 29 管跨落盘，这里管名字）
		"parts_bytes", "budget_over"} {
		if _, ok := m[k]; !ok {
			t.Fatalf("history 那一发缺前端要读的 %q：%v", k, m["turn"])
		}
	}
	if m["stop_reason"] != "跑完" {
		t.Fatalf("没打断的一发被记成 %v", m["stop_reason"])
	}
}

// 针 15：结束那句读数里"已亮 N 步"必须与轨迹真实条数相等。
// 刚才页面上同时出现过"真跑了 12/13 步"和"已亮 12 步（真跑了 11 步）"——
// 同一发两个步数，就是 W4 那类"一格两数"的复发。
func TestStopSentenceCountsMatchTheTrace(t *testing.T) {
	for _, tc := range []struct {
		name   string
		close  bool
		afterN int // 在第几步之后关
	}{{"跑完", false, 0}, {"早停", true, 0}, {"晚停", true, 7}} {
		abort := make(chan struct{})
		n := 0
		emit := func(s Step) {
			n++
			if tc.close && tc.afterN > 0 && n == tc.afterN {
				close(abort)
			}
		}
		if tc.close && tc.afterN == 0 {
			close(abort)
		}
		res := runLoop(fixtureDirty, "x", "go", "counts-"+tc.name, 1, emit, abort, "")
		line := lastLine(res.Trace, "stop")
		if line == "" {
			t.Fatalf("%s：没有 stop 那一步", tc.name)
		}
		want := fmt.Sprintf("已亮 %d 步", len(res.Trace))
		if !strings.Contains(line, want) {
			t.Fatalf("%s：stop 那句写的是 %q，但轨迹实际 %d 步（缺 %q）—— 同一发不许两个步数", tc.name, line, len(res.Trace), want)
		}
		if got := ranCount(res.Trace); fmt.Sprintf("真跑了 %d 步", got) != extractRan(line) {
			t.Fatalf("%s：stop 那句里的\"真跑了 N 步\"与轨迹实数 %d 不符：%s", tc.name, got, line)
		}
		t.Logf("%s：%s", tc.name, line)
	}
}

func ranCount(ts []Step) int {
	n := 0
	for _, s := range ts {
		if s.Run {
			n++
		}
	}
	return n
}

func extractRan(line string) string {
	i := strings.Index(line, "真跑了 ")
	if i < 0 {
		return ""
	}
	rest := line[i+len("真跑了 "):]
	j := strings.Index(rest, " 步")
	if j < 0 {
		return ""
	}
	return "真跑了 " + rest[:j] + " 步"
}

// 针 16：栈那条路径的**两端**都要钉住（针 10/14 同族第三次：改名只改一边是静默断）。
// 三面各钉一件事：
// ① 页面有输入框且真把 stack 发出去，且 app.js 读的 debug 键名与 JSON 一致；
// ② 给了栈 ⇒ 有 stack-frame 结论、署 estimated、帧数与"指回贴入代码"的数自印出来；
// ③ 没给栈 ⇒ JSON 里**不许出现 debug 这个键**，且必须有一条带理由的 absent 未决项。
// ③ 盯的是"把没问印成问了说没有"：一行 stack_bytes:0 会被下一个人读成"给了栈但一帧没认出"。
// 反臂：把行号挪出贴入范围 ⇒ in_range 必须掉到 0（针不能对越界帧也点头）。
func TestStackPathEndsMatchAndAbsentStaysAbsent(t *testing.T) {
	jsB, err := os.ReadFile(filepath.Join("web", "app.js"))
	if err != nil {
		t.Fatalf("读不到 app.js：%v", err)
	}
	htmlB, err := os.ReadFile(filepath.Join("web", "index.html"))
	if err != nil {
		t.Fatalf("读不到 index.html：%v", err)
	}
	js, html := string(jsB), string(htmlB)

	if !strings.Contains(html, `id="stack"`) {
		t.Fatal("页面没有 id=\"stack\" 那一栏：后端加了栈输入，界面没地方贴")
	}
	if !strings.Contains(js, "stack: $('stack').value") {
		t.Fatal("app.js 没把 stack 框的值发出去：那一栏会变成装饰")
	}
	dbgKeys := []string{"stack_bytes", "frames_parsed", "frames_pointing_into_snippet"}
	for _, k := range dbgKeys {
		if !strings.Contains(js, "dbg."+k) {
			t.Fatalf("app.js 没读 debug.%s —— 前端改了名就要同步改这里，否则页面永远显示空读数", k)
		}
	}

	// ③ 没给栈
	none := runLoop(fixtureDirty, "x", "go", "stack-none", 1, nop, nil, "")
	b, err := json.Marshal(none)
	if err != nil {
		t.Fatal(err)
	}
	var top map[string]any
	if err := json.Unmarshal(b, &top); err != nil {
		t.Fatal(err)
	}
	if _, has := top["debug"]; has {
		t.Fatalf("没给栈却落了 debug 字段（%v）—— 那会被读成「给了栈但一帧没认出」，把没问写成问了", top["debug"])
	}
	if !hasUnknown(none.Unknowns, "报错/栈 → 行号") {
		t.Fatalf("没给栈要有一条带理由的 absent 未决项；现有 %d 条里没有", len(none.Unknowns))
	}

	// ② 给了栈
	yes := runLoop(fixtureDirty, "x", "go", "stack-some", 1, nop, nil, fixtureStack)
	b2, err := json.Marshal(yes)
	if err != nil {
		t.Fatal(err)
	}
	var top2 map[string]any
	if err := json.Unmarshal(b2, &top2); err != nil {
		t.Fatal(err)
	}
	dbg, ok := top2["debug"].(map[string]any)
	if !ok {
		t.Fatal("给了栈但 JSON 里没有 debug 读数")
	}
	for _, k := range dbgKeys {
		if _, has := dbg[k]; !has {
			t.Fatalf("debug 少了 app.js 要读的 %q（现有 %d 个键）", k, len(dbg))
		}
	}
	frames := int(dbg["frames_parsed"].(float64))
	inRange := int(dbg["frames_pointing_into_snippet"].(float64))
	n := 0
	for _, f := range yes.Findings {
		if f.Rule == "stack-frame" {
			n++
			if f.Basis != Estimated {
				t.Fatalf("栈帧结论署了 %s：文件名没跟贴入代码对上，不许升 %s", f.Basis, Measured)
			}
		}
	}
	if n == 0 {
		t.Fatalf("给了栈却没产出任何 stack-frame：%s —— 解析器漂了，不是代码没错", firstLine(yes.AnswerSummary))
	}
	if frames != n || inRange != 2 {
		t.Fatalf("栈读数自印对不上：frames=%d 与结论条数 %d 不等，或 in_range=%d 不是 2", frames, n, inRange)
	}
	if yes.Debug == nil || yes.Debug.StackBytes != len([]byte(fixtureStack)) {
		t.Fatalf("stack_bytes 不是贴入字节数：%+v vs %d", yes.Debug, len([]byte(fixtureStack)))
	}

	// 反臂：行号越界 ⇒ in_range 必须为 0（危害形态：把量不到的帧说成定位到了）
	far := runLoop(fixtureDirty, "x", "go", "stack-far", 1, nop, nil,
		"panic: boom\nmain.halo()\n\t/tmp/demo/main.go:99999 +0x1\n")
	if far.Debug == nil || far.Debug.Frames != 1 || far.Debug.InRange != 0 {
		t.Fatalf("越界帧的反臂没红：%+v（要 Frames=1、InRange=0）", far.Debug)
	}
	t.Logf("给了栈：%d 帧 / 指回贴入代码 %d 帧 / stack-frame 结论 %d 条；没给栈：debug 键不存在＋absent 未决 1 条",
		frames, inRange, n)
}

func findStep(ts []Step, name string) (Step, bool) {
	for _, s := range ts {
		if s.Name == name {
			return s, true
		}
	}
	return Step{}, false
}

func outputBases(res Result) map[string]string {
	m := map[string]string{}
	for _, d := range res.Decisions {
		if d.Side == "output" {
			m[d.Key] = d.Basis
		}
	}
	return m
}

// 针 17：第 ⑧ 步打本机假端点 ⇒ 账上那七格必须从 absent 翻成**有出处的档**，
// 端点回帧落成一条 model_says 卡片，读数里写死"演示件/出不了这台机"。
// 这条针证明的是**管路可量**，不证明模型答得对 —— 回帧是脚本写的（真实模型调用 0 次）。
func TestFakeEndpointFlipsThePipeCells(t *testing.T) {
	t.Setenv("PGAGENT_BASE_URL", "")
	t.Setenv("PGAGENT_MODEL", "")
	t.Setenv("PGAGENT_KEY", "")
	installSeam(0, true)
	defer func() { seam = nil; seamReadBack = false }()

	gatewayFake = false
	off := runLoop(fixtureDirty, "x", "go", "gw-off", 1, nop, nil, "") // 同一发不带通道时的对照
	gatewayFake = true
	defer func() { gatewayFake = false }()
	on := runLoop(fixtureDirty, "解释一下", "go", "gw-on", 1, nop, nil, "")

	gs, ok := findStep(on.Trace, "gateway")
	if !ok || !gs.Run || gs.Basis != Measured {
		t.Fatalf("第 ⑧ 步没如实记跑过：%+v", gs)
	}
	if !strings.Contains(gs.Summary, "出不了这台机") || !strings.Contains(gs.Summary, "演示件") {
		t.Fatalf("第 ⑧ 步那句没写明地址是本机且是演示件：%s", gs.Summary)
	}
	p := on.Gateway
	if p == nil {
		t.Fatal("跑了假端点但 JSON 里没有 gateway 读数")
	}
	if p.Chunks < 4 || p.BytesIn <= 0 || p.BytesOut <= 0 {
		t.Fatalf("管路读数不像真打过：帧=%d 进=%d 出=%d", p.Chunks, p.BytesIn, p.BytesOut)
	}
	if !p.UsageSaid || p.UsageIn != 0 || p.UsageOut != 0 {
		t.Fatalf("假端点刻意复刻了「流式 usage 全 0」那形状，读数却没记到：%+v", p)
	}
	if p.Loopback != true {
		t.Fatal("地址是本机回环但读数说不是 —— 那会被读成代码出这台机了")
	}

	// 七格翻档：读回来的档名里一个 absent 都不许剩。
	want := []string{"chunks", "first_byte_ms", "max_gap_ms", "wire_bytes_in", "wire_bytes_out", "usage_in", "usage_out"}
	seen := outputBases(on)
	for _, k := range want {
		b, has := seen[k]
		if !has {
			t.Fatalf("假端点跑完了，但读回里没有 %s 这一格（说明它根本没进账）", k)
		}
		if b == "absent" {
			t.Fatalf("%s 还记 absent：管路已经有真值了，保持缺席就是装没看见", k)
		}
	}
	if seen["usage_in"] != "relayed" || seen["usage_out"] != "relayed" {
		t.Fatalf("usage 两格是 %s/%s：端点自报的数只能转述，不许升 measured", seen["usage_in"], seen["usage_out"])
	}
	if n := countBasis(on.Findings, ModelSays); n == 0 {
		t.Fatal("端点的话没落成 model_says 卡片 —— 那是把它冒充成本地结论")
	}
	if hasUnknown(on.Unknowns, "模型给的额外解释与优化建议") {
		t.Fatal("第 ⑧ 步跑过了，「模型的额外建议」不许还挂着 absent")
	}
	// 那七格在结果区也不许再以"账上那一格…"的缺席名义出现（未决项里只该剩真正没量到的）。
	var pipeGhosts []string
	for _, u := range on.Unknowns {
		if strings.HasPrefix(u.What, "账上那一格") {
			pipeGhosts = append(pipeGhosts, u.What)
		}
	}
	if len(pipeGhosts) > 0 {
		t.Fatalf("管路已经有真值，未决项里还挂着这些「账上那一格」：%v", pipeGhosts)
	}
	// 对照：关掉假端点那一发，这七格必须回到 absent（针不能两头都绿）。
	offSeen := outputBases(off)
	if offSeen["chunks"] != "absent" {
		t.Fatalf("反臂不红：没开通道时 chunks 记成了 %s", offSeen["chunks"])
	}
	if off.Gateway != nil {
		t.Fatal("没跑第 ⑧ 步却带 gateway 读数 —— 会被读成「打了但没结果」")
	}
	if !on.MixOK || !off.MixOK {
		t.Fatalf("两发的五档加总都得对得上：on=%v off=%v", on.MixOK, off.MixOK)
	}
	if countBasis(off.Findings, ModelSays) != 0 {
		t.Fatal("没打端点那一发出现了 model_says：那是把本地结论署成模型说的")
	}
	// 前端读的那几个 gateway 字段名必须真在 JSON 里（针 10/14/16 同族：改名只改一边是静默断）。
	jsB, err := os.ReadFile(filepath.Join("web", "app.js"))
	if err != nil {
		t.Fatalf("读不到 app.js：%v", err)
	}
	pb, err := json.Marshal(on.Gateway)
	if err != nil {
		t.Fatal(err)
	}
	var gmap map[string]any
	if err := json.Unmarshal(pb, &gmap); err != nil {
		t.Fatal(err)
	}
	names := map[string]bool{}
	for _, m := range regexp.MustCompile(`gwv\.[a-z_]+`).FindAllString(string(jsB), -1) {
		names[strings.TrimPrefix(m, "gwv.")] = true
	}
	if len(names) < 6 {
		t.Fatalf("app.js 只读了 %d 个 gateway 字段，尺子大概漂了", len(names))
	}
	for k := range names {
		if _, has := gmap[k]; !has {
			t.Fatalf("app.js 读 gateway.%s，但 JSON 里没有这个键（现有 %d 个）", k, len(gmap))
		}
	}
	t.Logf("假端点一发：%s｜五档 %d/%d/%d/%d/%d=%d｜账上七格 %v｜对照发 chunks=%s｜这一发剩下的 absent=%v｜前端读 %d 个 gateway 字段",
		firstLine(p.gatewayLine()), on.Mix.Measured, on.Mix.Estimated, on.Mix.ModelSays, on.Mix.Relayed, on.Mix.Absent,
		on.Mix.Total, seen, offSeen["chunks"], absentNames(on.Unknowns), len(names))
}

func absentNames(us []Unknown) []string {
	var out []string
	for _, u := range us {
		if u.Basis == Absent {
			out = append(out, u.What)
		}
	}
	return out
}

// 针 18：第 ⑧ 步的三态不许塌。
// 没打（NOT_RUN）／打了但连不上（跑了、ran=true、有失败归因、账上状态码那格是缺席不是 0）。
// 顺带钉两条边界：别的工具的环境变量（AGNES_*）不能让本件自己发出去；目标端口 8797/8799 一律拒。
func TestGatewayThreeStatesAndGuards(t *testing.T) {
	t.Setenv("PGAGENT_BASE_URL", "")
	gatewayFake = false
	installSeam(0, true)
	defer func() { seam = nil; seamReadBack = false }()

	// ① 没打
	res := runLoop(fixtureDirty, "x", "go", "gw-none", 1, nop, nil, "")
	gs, ok := findStep(res.Trace, "gateway")
	if !ok || gs.Run || gs.Basis != Absent || !strings.Contains(gs.Summary, "NOT_RUN") {
		t.Fatalf("没配置时第 ⑧ 步必须是不跑的 NOT_RUN：%+v", gs)
	}
	if res.Gateway != nil {
		t.Fatal("没打也印了 gateway 读数 —— 会被读成「打了但没结果」")
	}
	// 别的工具设了凭据 ≠ 本件被批准发出去
	t.Setenv("AGNES_BASE", "https://example.invalid/v1")
	t.Setenv("AGNES_KEY", "哨兵串·不许外发")
	if _, why := detectGateway(false); why == "" {
		t.Fatal("AGNES_* 一设就自动打真端点：本件只认 PGAGENT_BASE_URL（显式批准）")
	}
	// ② 端口守卫
	for _, bad := range []string{"http://127.0.0.1:8797/v1", "https://api.example.com:8799/v1"} {
		if err := guardURL(bad); err == nil {
			t.Fatalf("守卫没拦住 %s：那两本是内核研究账", bad)
		} else if !strings.Contains(err.Error(), "879") {
			t.Fatalf("拦下了但理由不对：%v", err)
		}
	}
	// ③ 打了但连不上：拨一个没人听的端口（子发是叶子，不起服务、不落盘）
	dead, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Skip("拿不到临时端口：" + err.Error())
	}
	addr := dead.Addr().String()
	_ = dead.Close()
	t.Setenv("PGAGENT_BASE_URL", "http://"+addr+"/v1")
	t.Setenv("PGAGENT_KEY", "哨兵串·不许外发")
	hit := runLoop(fixtureDirty, "x", "go", "gw-dead", 1, nop, nil, "")
	hgs, ok := findStep(hit.Trace, "gateway")
	if !ok || !hgs.Run || hgs.Basis != Measured {
		t.Fatalf("打失败了这一步必须记「跑过且失败」，不许擦成没跑：%+v", hgs)
	}
	if hit.Gateway == nil || hit.Gateway.Kind != "transport" {
		t.Fatalf("失败归因没落成 transport：%+v", hit.Gateway)
	}
	if strings.Contains(hgs.Summary, "NOT_RUN") {
		t.Fatalf("这一发真打了，句子里不许有 NOT_RUN：%s", hgs.Summary)
	}
	if hasUnknown(hit.Unknowns, "模型给的额外解释与优化建议") &&
		!strings.Contains(unknownWhy(hit.Unknowns, "模型给的额外解释与优化建议"), "打失败了") {
		t.Fatal("「打失败了」与「根本没打」在未决项里必须分得开")
	}
	// 账上：状态码那格是缺席（没收到响应），不是 measured(0)
	bases := outputBases(hit)
	if b, has := bases["fail_kind"]; has && b == "absent" {
		t.Fatal("失败归因没进账：transport 那一发账上该看得见 kind")
	}
	// 口令不许出现在任何读数里。
	// 这一条端到端的检查本身是**空的**（transport 错的原文里不带口令），所以先拿一根能红的针盯 scrub 自己：
	// 不然它就是那种"永远绿"的装饰（写针之前要先确认它在今天会红）。
	if got := scrub("Post https://x/v1: Bearer 哨兵串·不许外发", "哨兵串·不许外发"); strings.Contains(got, "哨兵串") {
		t.Fatalf("scrub 没把口令擦掉：%q", got)
	}
	if got := scrub("没有口令的一句话", ""); !strings.Contains(got, "没有口令") {
		t.Fatalf("scrub 把不含口令的原文改坏了：%q", got)
	}
	b, err := json.Marshal(hit)
	if err != nil {
		t.Fatal(err)
	}
	all := string(b)
	for _, s := range hit.Trace {
		all += s.Summary
	}
	if strings.Contains(all, "哨兵串·不许外发") {
		t.Fatal("口令漏进了读数 —— 那正是记忆里点过三次的名")
	}
	t.Logf("三态各一发：没打=%s｜打了失败=%s（gateway 键在=%v）", firstLine(gs.Summary), firstLine(hgs.Summary), hit.Gateway != nil)
}

func unknownWhy(us []Unknown, what string) string {
	for _, u := range us {
		if u.What == what {
			return u.WhyAbsent
		}
	}
	return ""
}

// 针 19：W7 的多语言降档。钉四件事：
// ① 嗅探要能报出"凭什么"，并且**不许把推断说成解析**；
// ② 每族文本判据的命中一律 estimated（一条 measured 都不许有）；
// ③ 干净样本不许被编出 critical（尺子不能凭空红），但脏样本必须红够一族以上（不能凭空绿）；
// ④ 硬编码哨兵串那族：**命中的字面量不许被抄进任何读数**（这条项目点过三次名的一族错误）。
func TestMultiLanguageDowngradeAndNoEcho(t *testing.T) {
	// ① 嗅探
	for _, c := range []struct{ code, want string }{{fixturePyRich, "python"}, {fixtureJSRich, "javascript"}, {fixtureDirty, "go"}} {
		got, why := sniffLang(c.code)
		if got != c.want {
			t.Fatalf("嗅探把语言定成 %q（要 %q）｜凭什么：%s", got, c.want, why)
		}
		if !strings.Contains(why, "命中") {
			t.Fatalf("嗅探没给依据：%s", why)
		}
	}
	if got, _ := sniffLang("just some words\nnothing here\n"); got != "unknown" {
		t.Fatalf("没有标记的串应回 unknown，得到 %q", got)
	}

	// ② + ③ Python 脏样本
	a := analyze(fixturePyRich, "auto")
	if a.Metrics.Lang != "python" {
		t.Fatalf("auto 那一路把 Python 判成 %s（LangHow=%s）", a.Metrics.Lang, a.Metrics.LangHow)
	}
	if a.Metrics.Parsed {
		t.Fatal("Python 不可能被 Go 的 parser 解析成功，Parsed 却是 true")
	}
	if n := countBasis(a.Findings, Measured); n != 0 {
		t.Fatalf("文本级匹配里有 %d 条署了 measured —— 降档塌了", n)
	}
	if !allVerified(a.Findings) {
		t.Fatal("有一条文本判据没写「怎么复验」")
	}
	pyRules := map[string]bool{"bare-except": true, "except-pass": true, "mutable-default-arg": true,
		"none-compare": true, "print-as-log": true, "unused-import(maybe)": true}
	hit := 0
	var hitNames []string
	for r := range pyRules {
		if hasRule(a.Findings, r) {
			hit++
			hitNames = append(hitNames, r)
		}
	}
	// 阈值必须等于考卷准备的族数。刚才在复制件上做坏一把尺子（bare-except 永不命中）时，
	// "≥5 族"这种口径直接放过去了 —— 少一把尺子照样交卷，那就是把"漏判"说成"够用"。
	if hit != len(pyRules) {
		t.Fatalf("Python 考卷准备了 %d 族，只命中 %d 族：%v —— 有尺子没咬住", len(pyRules), hit, hitNames)
	}
	// import 的两个量必须分列（刚才页面把"疑似没用到的条数"当"导入总条数"印了出来 —— 一格两义）。
	if a.Metrics.Imports != 2 || a.Metrics.UnusedImports != 1 {
		t.Fatalf("import 两格没分开：总条数=%d（要 2）疑似未用=%d（要 1）", a.Metrics.Imports, a.Metrics.UnusedImports)
	}

	// 干净样本不许凭空红
	clean := analyze(fixturePyClean, "auto")
	if n := countSeverity(clean.Findings, "critical"); n != 0 {
		t.Fatalf("干净的 Python 样本被编出 %d 条 critical：%v", n, ruleNames(clean.Findings))
	}
	if !hasUnknown(clean.Unknowns, "python 的 AST 级判据（作用域、调用图、类型）") {
		t.Fatal("AST 级缺席没记 absent —— 空结果会被读成「这段没问题」")
	}

	// ② + ③ JavaScript
	j := analyze(fixtureJSRich, "auto")
	if j.Metrics.Lang != "javascript" {
		t.Fatalf("JS 考卷判成 %s", j.Metrics.Lang)
	}
	if n := countBasis(j.Findings, Measured); n != 0 {
		t.Fatalf("JS 文本判据里 %d 条署了 measured", n)
	}
	// 函数/import 两个数也是读数，得钉住：defRe 少了 `function name(` 那一支时这里数出 0。
	if j.Metrics.Funcs != 1 || j.Metrics.Imports != 1 || j.Metrics.UnusedImports != 0 {
		t.Fatalf("JS 那一份的数不对：函数=%d（要 1）import=%d（要 1）疑似未用=%d（要 0）",
			j.Metrics.Funcs, j.Metrics.Imports, j.Metrics.UnusedImports)
	}
	jsRules := []string{"loose-equality", "eval-or-new-function", "debugger-left", "console-log", "var-left", "empty-catch"}
	var jsHit []string
	for _, r := range jsRules {
		if hasRule(j.Findings, r) {
			jsHit = append(jsHit, r)
		}
	}
	if len(jsHit) != len(jsRules) {
		t.Fatalf("JS 考卷准备了 %d 族，只命中 %d 族：%v（漏了 %v）",
			len(jsRules), len(jsHit), jsHit, missing(jsRules, jsHit))
	}

	// 长函数（缩进跨度）—— 造一份 65 行的体，针才有东西可数
	body := "def big():\n" + strings.Repeat("    x = 1\n", 65)
	lf := analyze(body, "python")
	if !hasRule(lf.Findings, "long-def") {
		t.Fatalf("65 行的函数没命中 long-def｜max=%d", lf.Metrics.MaxFunc)
	}
	if lf.Metrics.MaxFunc <= 60 {
		t.Fatalf("long-def 命中了但 max_func_lines=%d，两个数对不上", lf.Metrics.MaxFunc)
	}

	// ④ 哨兵串：命中，但值不许出现在任何读数里
	sec := analyze(fixtureSecret, "python")
	if !hasRule(sec.Findings, "hardcoded-secret(maybe)") {
		t.Fatal("硬编码判据没命中（考卷就白准备了）")
	}
	sb, err := json.Marshal(sec)
	if err != nil {
		t.Fatal(err)
	}
	if strings.Contains(string(sb), "SENTINEL-VALUE-DO-NOT-USE-0123456789") {
		t.Fatal("命中的字面量被抄进了读数 —— 这正是「为说明扫过什么而把口令前缀落进同一份文档」那一族")
	}

	// 负对照：合规范写法不许命中（一根只会红的尺子与一根只会绿的尺子一样没用）。
	// 这一族刚错过一次 —— `==` 前面禁了空格，结果 `row.id == 3` 这种最常态的写法扫不出来。
	jsOK := analyze("function f(row) {\n  if (row.id === 3 && row.k !== 4) { return 1; }\n}\n", "javascript")
	if hasRule(jsOK.Findings, "loose-equality") {
		t.Fatalf("=== / !== 被判成松散相等（假红）：%v", ruleNames(jsOK.Findings))
	}
	pyOK := analyze("try:\n    x = 1\nexcept ValueError as e:\n    raise RuntimeError('坏了') from e\n", "python")
	for _, r := range []string{"bare-except", "except-pass"} {
		if hasRule(pyOK.Findings, r) {
			t.Fatalf("合规写法被 %s 命中（假红）：%v", r, ruleNames(pyOK.Findings))
		}
	}

	// 显式选定 ≠ 嗅探：不许事后混为一谈
	exp := analyze(fixtureJSRich, "python")
	if exp.Metrics.LangHow != "用户显式选定" {
		t.Fatalf("界面选了 python，LangHow 却是 %q", exp.Metrics.LangHow)
	}
	if !strings.Contains(exp.Metrics.LangWhy, "没嗅探") {
		t.Fatalf("显式选定那一路还留着嗅探依据：%s", exp.Metrics.LangWhy)
	}
	t.Logf("Python 命中 %v｜JS 命中 %v｜长函数 max=%d｜干净样本 critical=0", hitNames, jsHit, lf.Metrics.MaxFunc)
}

func missing(want, got []string) []string {
	have := map[string]bool{}
	for _, g := range got {
		have[g] = true
	}
	var out []string
	for _, w := range want {
		if !have[w] {
			out = append(out, w)
		}
	}
	return out
}

func ruleNames(fs []Finding) []string {
	var out []string
	for _, f := range fs {
		out = append(out, f.Rule+":"+f.Severity)
	}
	return out
}

// 针 20（W8 界面收口）。五件事各钉一处"页面自己说不清"的形状：
// ① app.js 里 `$('x')` 用到的每个 id 必须真的在 index.html 里（前后端字段名同族第四形：DOM 侧静默断）；
// ② 每个 input/select/textarea 必须有可及名（label[for] 或 aria-label —— placeholder 不算名字）；
// ③ 五档徽章的对比度按 WCAG 公式**现算**，低于 4.5:1 就红（不靠人眼看"应该够"）；
// ④ 探针引用的选择器与媒体查询必须真的存在于 CSS/HTML —— 不然探针在扫空气，恒绿；
// ⑤ HTML 里不许留会漂的波次号（"W5" 这种今天对、明天错，属于第②类会随 commit 漂的数）。
func TestUIIsAccessibleAndProbeIsNotVacuous(t *testing.T) {
	jsB, err := os.ReadFile(filepath.Join("web", "app.js"))
	if err != nil {
		t.Fatal(err)
	}
	htmlB, err := os.ReadFile(filepath.Join("web", "index.html"))
	if err != nil {
		t.Fatal(err)
	}
	cssB, err := os.ReadFile(filepath.Join("web", "style.css"))
	if err != nil {
		t.Fatal(err)
	}
	js, html, css := string(jsB), string(htmlB), string(cssB)

	// ① id 交叉核对
	ids := map[string]bool{}
	for _, m := range regexp.MustCompile(`id="([A-Za-z0-9_-]+)"`).FindAllStringSubmatch(html, -1) {
		ids[m[1]] = true
	}
	var missingIDs []string
	seen := map[string]bool{}
	for _, m := range regexp.MustCompile(`\$\('([A-Za-z0-9_-]+)'\)`).FindAllStringSubmatch(js, -1) {
		id := m[1]
		if seen[id] {
			continue
		}
		seen[id] = true
		if !ids[id] {
			missingIDs = append(missingIDs, id)
		}
	}
	if len(missingIDs) > 0 {
		t.Fatalf("app.js 读了页面里不存在的 id：%v（读不到就是 silently no-op，页面上那句永远不更新）", missingIDs)
	}

	// ② 可及名
	controls := regexp.MustCompile(`<(input|select|textarea)\b[^>]*\bid="([A-Za-z0-9_-]+)"`).FindAllStringSubmatch(html, -1)
	if len(controls) < 4 {
		t.Fatalf("只数到 %d 个表单控件，尺子大概漂了（页面本该有 code/stack/q/lang）", len(controls))
	}
	for _, c := range controls {
		id := c[2]
		hasLabel := strings.Contains(html, `for="`+id+`"`)
		// 那一行本身带 aria-label 也算有名字
		line := ""
		for _, l := range strings.Split(html, "\n") {
			if strings.Contains(l, `id="`+id+`"`) {
				line = l
			}
		}
		if !hasLabel && !strings.Contains(line, "aria-label") {
			t.Fatalf("%s#%s 没有可及名（placeholder 不算）—— 屏幕阅读器只会念「编辑框」", c[1], id)
		}
	}

	// ③ 对比度：白字对五档底色
	var report []string
	for _, v := range []string{"--m", "--e", "--s", "--r", "--a"} {
		hex := cssVar(css, v)
		if hex == "" {
			t.Fatalf("CSS 里找不到变量 %s：五档配色被改名了（探针与页面会各说一套）", v)
		}
		r := wcagRatio("#ffffff", hex)
		report = append(report, fmt.Sprintf("%s=%s→%.2f", v, hex, r))
		if r < 4.5 {
			t.Fatalf("徽章 %s（%s）对白的对比度 %.2f < 4.5:1 —— 11px 的小字根本读不清", v, hex, r)
		}
	}

	// ④ 探针扫的东西必须真存在
	probeB, err := os.ReadFile(filepath.Join("..", "..", "工具", "a11y_probe.js"))
	if err != nil {
		t.Fatalf("读不到探针件：%v", err)
	}
	probe := string(probeB)
	for _, sel := range []string{".b.m", ".b.e", ".b.s", ".b.r", ".b.a", ".dim", ".note"} {
		cls := strings.TrimPrefix(sel, ".")
		if !strings.Contains(probe, sel) {
			t.Fatalf("探针没量 %s：那档/那类颜色没人核（漏量就是假绿）", sel)
		}
		if !strings.Contains(css, cls) {
			t.Fatalf("探针量了 %s，但 CSS 里没有这个类 —— 它在扫空气", sel)
		}
	}
	for _, bp := range []string{"max-width: 1100px", "max-width: 760px"} {
		if !strings.Contains(css, bp) {
			t.Fatalf("CSS 里找不到断点 %s：探针按 3 栏/2 栏/1 栏的期望就成了猜的", bp)
		}
	}
	// ④b 断点几何**不许量空页面**。10-21 就是这条漏了：旧探针的 iframe 只带 `?probe=W`，
	// 那份页面没跑过 ⇒ 结论带是空的、九步不存在、溢出当然恒为 0。真跑完那一发在 390px 下把整页撑到 528px
	// （撑宽的是 `python:text(bare-except,…)` 这类不可断的长串），而旧归档写着"四档断点 overflow 0"。
	for _, need := range []string{"&run=1", "#trace li", "band_chars", "offenders"} {
		if !strings.Contains(probe, need) {
			t.Fatalf("探针少了 %q —— 少了它，断点几何量的就是没跑过的空页面，溢出永远是 0", need)
		}
	}
	for _, w := range []string{"320", "390"} {
		if !strings.Contains(probe, w+",") && !strings.Contains(probe, ","+w) && !strings.Contains(probe, "["+w) {
			t.Fatalf("探针的宽度表里没有 %spx 这一档（窄屏最容易撑宽，别把它摘掉）", w)
		}
	}
	if !strings.Contains(css, "overflow-wrap: anywhere") {
		t.Fatal("CSS 里没有 overflow-wrap: anywhere —— 长串判据名会把小屏整页撑宽（390px 实测撑出 138px 横向溢出）")
	}
	// 光"文件里有这句话"不够：它可能只写在 header 上，而撑宽的是 main 里的卡片与九步。
	// 所以要按规则块解析，要求**有一条带 overflow-wrap 的规则其选择器覆盖 main 的后代**。
	// （G 臂第一次就是这么漏的：把 main 那条摘掉，header 那条还在，针照样绿。）
	covers := false
	for _, m := range regexp.MustCompile(`([^{}]+)\{([^}]*)\}`).FindAllStringSubmatch(css, -1) {
		if strings.Contains(m[2], "overflow-wrap") && strings.Contains(m[1], "main *") {
			covers = true
		}
	}
	if !covers {
		t.Fatal(`没有任何一条 overflow-wrap 规则覆盖 "main *" —— 小屏撑宽没人守（写在 header 上不算，撑宽的是 main 里的卡）`)
	}
	if !strings.Contains(css, "button:focus,") || !strings.Contains(css, ":focus-visible") {
		t.Fatal("焦点轮廓只在 :focus-visible 里定义 —— 探针与读屏器路径下量到的是 outline:none（浏览器实测就抓到过这条）")
	}
	if !strings.Contains(css, ".sr-only") {
		t.Fatal(".sr-only 没定义：那些「只给读屏器看的名字」会变成看不见的空标签")
	}

	// ⑤ 不许留会漂的波次号
	if m := regexp.MustCompile(`>\s*W\d\s*<`).FindString(html); m != "" {
		t.Fatalf("HTML 里还留着波次号 %q —— 这类数会随轮次漂，页面上不许写它", m)
	}
	t.Logf("控件 %d 个都有可及名｜id 交叉 %d 个全对上｜五档对比度 %s｜探针件 %d 字节",
		len(controls), len(seen), strings.Join(report, " "), len(probe))
}

// cssVar 从 :root 里取一个十六进制颜色。
func cssVar(css, name string) string {
	re := regexp.MustCompile(`\` + name + `:\s*(#[0-9a-fA-F]{6})`)
	m := re.FindStringSubmatch(css)
	if m == nil {
		return ""
	}
	return m[1]
}

// wcagRatio 是 WCAG 2.1 的相对亮度比。公式自己实现，不"目测够不够"。
func wcagRatio(fg, bg string) float64 {
	l1, l2 := relLum(fg), relLum(bg)
	hi, lo := math.Max(l1, l2), math.Min(l1, l2)
	return (hi + 0.05) / (lo + 0.05)
}

func relLum(hex string) float64 {
	hex = strings.TrimPrefix(hex, "#")
	f := func(s string) float64 {
		v, _ := strconv.ParseUint(s, 16, 8)
		c := float64(v) / 255
		if c <= 0.03928 {
			return c / 12.92
		}
		return math.Pow((c+0.055)/1.055, 2.4)
	}
	r := f(hex[0:2])
	g := f(hex[2:4])
	b := f(hex[4:6])
	return 0.2126*r + 0.7152*g + 0.0722*b
}

// 针 21：浏览器拿到的那份 == 我们说"已改"的那份。
// W8 实测被这个坑挡过一次：CSS 里加了 :focus 轮廓，页面量出来还是 outline:none ——
// 因为 style.css 没有 cache-buster，浏览器给的是旧缓存。
// 这条针量三件：① 静态件带 no-store；② 三份内嵌资源都真在（少一份就是 embed 漏了，页面会 404 但不报错）；
// ③ 服务出去的 CSS/HTML 里必须带着 W8 立的那两条（button:focus 与 #code 的可及名）。
func TestServedAssetsAreFreshAndComplete(t *testing.T) {
	sub, err := fs.Sub(webFS, "web")
	if err != nil {
		t.Fatalf("内嵌的 web/ 打不开：%v", err)
	}
	srv := httptest.NewServer(staticHandler(sub))
	defer srv.Close()

	want := map[string][]string{
		"/style.css":  {"button:focus", ":focus-visible", "@media (max-width: 760px)", ".sr-only", "overflow-wrap: anywhere"},
		"/index.html": {`id="code"`, `for="code"`, `aria-live="polite"`},
		"/app.js":     {"stack: $('stack').value", "dbg.stack_bytes", "gwv.bytes_in"},
		"/":           {"看得见的编程 Agent"},
	}
	for path, needles := range want {
		resp, err := http.Get(srv.URL + path)
		if err != nil {
			t.Fatalf("取 %s 就失败：%v", path, err)
		}
		body, err := io.ReadAll(resp.Body)
		resp.Body.Close()
		if err != nil {
			t.Fatal(err)
		}
		if resp.StatusCode != http.StatusOK {
			t.Fatalf("%s 回 %d（内嵌资源少了这一份，页面会静默缺件）", path, resp.StatusCode)
		}
		if got := resp.Header.Get("Cache-Control"); got != "no-store" {
			t.Fatalf("%s 的 Cache-Control=%q：改了却让人看旧缓存，等于没改", path, got)
		}
		for _, n := range needles {
			if !strings.Contains(string(body), n) {
				t.Fatalf("%s 里找不到 %q —— 服务出去的不是盘上那份", path, n)
			}
		}
		t.Logf("%s：%d 字节，%d 条标记全在", path, len(body), len(needles))
	}
}

// 针 22：?run=1 这种"自己会跑一圈"的入口，必须**在页面上说清是谁触发的**。
// 危害不是"跑不起来"，是跑起来之后那张截图/那发历史被读成"真人点出来的一发"——
// 这一族在本项目点过三次名（剧本与离线判据不许冒充自主决定）。
// Go 这边只能钉形状：① HTML 里那个提示位存在且**默认 hidden**（不 hidden 就变成"每次都是自动的"）；
// ② JS 里"解析参数 / 封顶 5 / 串行发下一发 / 打开提示 / 那句自白"必须同时出现（少了自白就是悄悄跑；
//
//	少了串行就是拿 ?run=N 自己撞针 33 那条重入保护）；W32 起 ?run= 接的是**发数**（账满那一形要两发才现形），
//	带坏了（?run=abc、?run=0、?run=）按"不擅自跑"处理。
//
// ③ JS 引用的 id 在 HTML 里必须真有（针 10 同族：改名只改一边是静默断）；
// ④ 负对照：那句自白**不许预先写死在 HTML 里**（写死了就等于常态声明）。
// 真行为（带不带参数各跑一次）只能到浏览器里量，见 运行记录「截图件」一节。
func TestAutoRunParamTellsTheTruth(t *testing.T) {
	sub, err := fs.Sub(webFS, "web")
	if err != nil {
		t.Fatal(err)
	}
	srv := httptest.NewServer(staticHandler(sub))
	defer srv.Close()

	get := func(p string) string {
		resp, err := http.Get(srv.URL + p)
		if err != nil {
			t.Fatalf("取 %s 失败：%v", p, err)
		}
		defer resp.Body.Close()
		b, err := io.ReadAll(resp.Body)
		if err != nil {
			t.Fatal(err)
		}
		return string(b)
	}
	html, js := get("/index.html"), get("/app.js")

	slot := regexp.MustCompile(`id="autorun"[^>]*\bhidden\b`)
	if !slot.MatchString(html) {
		t.Fatalf("HTML 里没有「默认 hidden 的 #autorun」提示位：要么没有，要么默认就亮着（那等于宣称每一发都是自动的）")
	}
	for _, n := range []string{`params.get('run')`, "Math.min(n, 5)", "链 = 链.then(() => submit())",
		"a.hidden = false", "不是人点出来的"} {
		if !strings.Contains(js, n) {
			t.Fatalf("app.js 里缺 %q —— 参数解析、封顶、串行、打开提示、自白这几件少一件，自动跑就成了悄悄跑", n)
		}
	}
	idRe := regexp.MustCompile(`\$\('([a-z]+)'\)`)
	used := map[string]bool{}
	for _, m := range idRe.FindAllStringSubmatch(js, -1) {
		used[m[1]] = true
	}
	var dangling []string
	for u := range used {
		if !strings.Contains(html, `id="`+u+`"`) {
			dangling = append(dangling, u)
		}
	}
	sort.Strings(dangling)
	if len(dangling) > 0 {
		t.Fatalf("app.js 引用了 HTML 里不存在的 id：%v（页面会在这里抛异常，后面那圈一步都不亮）", dangling)
	}
	if strings.Contains(html, "不是人点出来的") {
		t.Fatal("那句自白写死在 HTML 里了：不带参数的人也会看到「这一发是自动跑的」")
	}
	// ⑤ 同一个 id 出现两次：getElementById 只认第一个，第二个永远是空的 —— 而"页面看起来没报错"。
	// 这条正是本轮自己造出来的形状：把 #autorun 从面板底下挪到顶上，忘了删原来那份。
	dup := map[string]int{}
	for _, m := range regexp.MustCompile(`id="([^"]+)"`).FindAllStringSubmatch(html, -1) {
		dup[m[1]]++
	}
	var twice []string
	for k, v := range dup {
		if v > 1 {
			twice = append(twice, fmt.Sprintf("%s×%d", k, v))
		}
	}
	sort.Strings(twice)
	if len(twice) > 0 {
		t.Fatalf("HTML 里有重复 id：%v（提示位会永远空着，页面不报错）", twice)
	}
	t.Logf("JS 引用到的 id 共 %d 个，逐个在 HTML 里点到了；%d 个 id 无重复；提示位默认 hidden", len(used), len(dup))
}

// 针 23：读者声明失败不许静默。
// 危害：declare_reader 被内核拒了（键名/侧不在表上、或调用本身失败），而这一发还在喊"读了 12 格"——
// 账上那 12 格却没人署名，readers_report 会把它们报成"没声明者读"。两边各说各话就是假账。
// ① 真接缝这一发：第 7 步那句话里不许出现"没落账"，且 readers_report 要数出格；
// ② 注入两格失败：第 7 步要点名是几格、未决区要带原话列出是哪两格（少了这一条，页面上只剩"一切正常"），
//
//	并且这条未决署 absent（我们缺的正是"谁在读"这件事本身），五档恒等不许被这条新条目弄塌。
func TestReaderDeclarationFailureIsNotSilent(t *testing.T) {
	defer func() { seam = nil; seamReadBack = false }()
	// 声明表是进程级的（一码事一次），针要跑得可重复 ⇒ 每段之前清一次。
	reset := func() {
		declMu.Lock()
		declaredCells = map[string]bool{}
		declMu.Unlock()
	}
	reset()
	installSeam(0, true)
	real := runLoop(fixtureDirty, "这段有什么问题", "go", "decl-real", 1, nop, nil, "")
	note := lastLine(real.Trace, "kernel.read_back")
	if strings.Contains(note, "没落账") {
		t.Fatalf("真接缝这一发就有声明没落账，说明调用方写错了却没人在看：%s", note)
	}
	if !strings.Contains(lastLine(real.Trace, "kernel.readers_report"), "格") {
		t.Fatalf("readers_report 没数格，这一条是空话：%s", lastLine(real.Trace, "kernel.readers_report"))
	}
	// ①b 第二发。10-21 那张截图就是这一条没做时拍下来的：第二发把 12 格又喊一遍，
	//     内核按"同一个读者声明两遍会把分母数大"全数拒收，而页面当时把这句**静默吞了**。
	//     现在的口径：声明是代码的属性、不是某一发的属性 ⇒ 第二发不该再出现任何拒收。
	second := runLoop(fixtureDirty, "这段有什么问题", "go", "decl-real", 2, nop, nil, "")
	if n2 := lastLine(second.Trace, "kernel.read_back"); strings.Contains(n2, "没落账") {
		t.Fatalf("第二发又把声明喊了一遍 ⇒ 全被内核拒收：%s", n2)
	}
	if !strings.Contains(lastLine(second.Trace, "kernel.read_back"), "读回") {
		t.Fatal("第二发的第 7 步没在说话（跳过重复声明不该把这步也一起哑掉）")
	}

	seam = func(string, string, string, int) (SeamReply, error) {
		return SeamReply{
			Checked: true, Recorded: true, ReadBack: true, Verdict: "副本预检",
			Decisions: []Decision{{Key: "content_bytes", Side: "input", Basis: "measured", Claim: "4321 字节", Effect: "立一格"}},
			DeclFail: []string{
				"input/parts：内核拒收（这一格不给声明读者）",
				"output/chunks：调用就失败了（rpc 断了）",
			},
		}, nil
	}
	bad := runLoop(fixtureDirty, "这段有什么问题", "go", "decl-fake", 2, nop, nil, "")
	bnote := lastLine(bad.Trace, "kernel.read_back")
	if !strings.Contains(bnote, "读者声明有 2 格没落账") {
		t.Fatalf("第 7 步没把失败数说出来，页面上看着就像一切正常：%s", bnote)
	}
	var named *Unknown
	for i := range bad.Unknowns {
		if strings.Contains(bad.Unknowns[i].What, "谁在读") {
			named = &bad.Unknowns[i]
		}
	}
	if named == nil {
		t.Fatal("未决区没列「这几格谁在读没进账」—— 失败被吞了")
	}
	if !strings.Contains(named.WhyAbsent, "input/parts") || !strings.Contains(named.WhyAbsent, "output/chunks") {
		t.Fatalf("未决条目没点名是哪两格（只写一句「有失败」等于没说）：%s", named.WhyAbsent)
	}
	if named.Basis != Absent {
		t.Fatalf("这条未决署了 %v —— 我们缺的正是「谁在读」这件事本身，只能是缺席 + 原话", named.Basis)
	}
	if !bad.MixOK {
		t.Fatalf("多一条未决之后五档加总塌了：%+v", bad.Mix)
	}

	// ③ 走真调用路：把 declare_reader 换成"内核拒收"，看 consume 有没有真接住。
	//    ②那半只证了"报出来好看"，这半才证"抓得到" —— 少了它，把 ledger 里那行改回 `_, _ =` 针照样绿。
	reset()
	rep, err := runSeam(declineDecls{newPgRPC(0, false)}, mustPair(t, "声明被拒", 3, fixtureDirty), "声明被拒", 3, true)
	if err != nil {
		t.Fatalf("这一发出不了账：%v", err)
	}
	if len(rep.DeclFail) == 0 {
		t.Fatal("declare_reader 全程被拒，DeclFail 还是空的 ⇒ 失败被吞了（就是那条静默假账）")
	}
	for _, f := range rep.DeclFail {
		if !strings.Contains(f, "内核拒收") || !strings.Contains(f, "哨兵") {
			t.Fatalf("失败条目没带上内核那句原话（日后没法归因是谁拒的）：%s", f)
		}
	}
	t.Logf("读数自印：真接缝 %s｜注入两格失败 ⇒ 第 7 步：%s｜真调用路全程被拒 ⇒ DeclFail=%d 格",
		lastLine(real.Trace, "kernel.readers_report"), bnote, len(rep.DeclFail))
}

// 针 25：页面是 textContent 渲染的 ⇒ 任何 markdown 记号都会原样出现在屏幕上。
// 10-21 那张截图里就印着「**这份件不猜业务意图**」—— 目标要求"排版清晰"，这种就是脏。
// 钉法：把整份 Result 序列化之后扫 `**`，四种意图 + 有栈/无栈 + 网关开/关各跑一发全覆盖；
// 再配正对照（自己造一条带星号的读数），否则这就是根恒绿的针。
func TestNoMarkdownLeaksIntoRenderedReadings(t *testing.T) {
	questions := []string{"这段能怎么优化？", "为什么偶尔返回空？", "解释一下这段在干什么", "有什么问题", ""}
	stacks := []string{"", fixtureStack}
	// 代码也两形：小样本，和**超预算那一形**。W17 就是在这里漏的 —— 新加的 ① 那句预告只在超预算时说话，
	// 而矩阵里全是小样本 ⇒ 它带着 `**` 上了屏，针 25 一路绿。覆盖面要跟着文案一起长，否则针只管得着老形状。
	codes := []string{fixtureDirty, fixtureDirty + strings.Repeat("// 填充一行给预算看 ", 4000)}
	runs := 0
	for _, q := range questions {
		for _, st := range stacks {
			for ci, code := range codes {
				for _, fake := range []bool{false, true} {
					runs++
					gatewayFake = fake
					res := runLoop(code, q, "auto", "no-md", runs, nop, nil, st)
					gatewayFake = false
					b, err := json.Marshal(res)
					if err != nil {
						t.Fatal(err)
					}
					if i := strings.Index(string(b), "**"); i >= 0 {
						lo, hi := i-40, i+60
						if lo < 0 {
							lo = 0
						}
						if hi > len(b) {
							hi = len(b)
						}
						t.Fatalf("第 %d 发（问题=%q 有栈=%v 代码形=%d 网关=%v）读数里带 markdown 星号，页面会原样印出来：…%s…",
							runs, q, st != "", ci+1, fake, string(b[lo:hi]))
					}
				}
			}
		}
	}
	// 正对照：这个检查必须抓得住真星号，否则上面这些发全绿说明不了任何事。
	if strings.Index("带**星号**的读数", "**") < 0 {
		t.Fatal("正对照失效：连手写的 ** 都没扫出来，这个检查是假的")
	}
	t.Logf("读数自印：扫了 %d 发（五种问题 × 有无栈 × 小样本/超预算 × 网关开关）⇒ 0 处 markdown 记号；正对照可抓", runs)
}

// declineDecls 只干一件事：把 kernel.declare_reader 换成"内核拒收"，其余原样透传。
type declineDecls struct{ inner seamCaller }

func (d declineDecls) call(tool string, args map[string]any) (pgReply, error) {
	if tool == "kernel.declare_reader" {
		return pgReply{Text: "哨兵：这一格的读者声明被拒（测试件造的，不是内核真的规则）", IsErr: true}, nil
	}
	return d.inner.call(tool, args)
}

// 针 24：问题必须真的动这一发。目标写的是"贴代码 + 提问题"，如果换问题输出不变，
// 那个输入框就是装饰 —— 而"看起来在工作"正是这一族最难发现的假绿。
// 钉五件：① 三种问题 ⇒ 三种不同的结论带（且 Kind 各自对得上）；
// ② 顺序真的动了（优化意图 ⇒ 第一张卡属于建议族；调试意图 + 贴栈 ⇒ 第一张属于栈族）；
// ③ 解释意图那句必须自带"不猜业务意图 / 那是第 ⑧ 步模型的活"，不许把关键词说成理解；
// ④ 空问题 ⇒ 未判定，且理由里带词表条数（分母自印）；
// ⑤ 早停那一发没走到 ④ ⇒ Intent 必须是空，不许补一句"看起来像路由过"的话。
func TestQuestionActuallyChangesTheTurn(t *testing.T) {
	one := runLoop(fixtureDirty, "这段能怎么优化？", "go", "intent-opt", 1, nop, nil, "")
	two := runLoop(fixtureDirty, "为什么偶尔返回空？", "go", "intent-dbg", 2, nop, nil, fixtureStack)
	three := runLoop(fixtureDirty, "解释一下这段在干什么", "go", "intent-exp", 3, nop, nil, "")
	four := runLoop(fixtureDirty, "", "go", "intent-none", 4, nop, nil, "")

	if one.Intent != "优化" || two.Intent != "调试" || three.Intent != "解释" || four.Intent != "未判定" {
		t.Fatalf("路由结果=%s/%s/%s/%s（要 优化/调试/解释/未判定）", one.Intent, two.Intent, three.Intent, four.Intent)
	}
	if one.AnswerSummary == two.AnswerSummary || two.AnswerSummary == three.AnswerSummary {
		t.Fatalf("换了问题结论带一模一样 ⇒ 那个输入框是装饰：%.40s / %.40s", one.AnswerSummary, two.AnswerSummary)
	}
	if len(one.Findings) == 0 || !inRules(optimizeRules, one.Findings[0].Rule) {
		t.Fatalf("优化意图那一发的第一张卡是 %q，不属于建议族 ⇒ 顺序没动（只改了文案）", one.Findings[0].Rule)
	}
	if len(two.Findings) == 0 || !inRules(debugRules, two.Findings[0].Rule) {
		t.Fatalf("调试意图那一发的第一张卡是 %q，不属于栈族", two.Findings[0].Rule)
	}
	// 平票不许偏向任何一边：这句同时带调试词（为什么）与优化词（慢）⇒ 明说平票并退回审查。
	tie := intentOf("为什么会这么慢？")
	if tie.Kind != "审查" || !strings.Contains(tie.Why, "平票") {
		t.Fatalf("平票的处置没写在理由里（或者偷偷偏了一边）：%s｜%s", tie.Kind, tie.Why)
	}
	if !strings.Contains(three.AnswerSummary, "不猜业务意图") || !strings.Contains(three.AnswerSummary, "NOT_RUN") {
		t.Fatalf("解释那一发把关键词说成了理解：%s", three.AnswerSummary)
	}
	if !strings.Contains(four.AnswerSummary, fmt.Sprintf("词表 %d 个", len(intentWords))) {
		t.Fatalf("未判定那句没带分母（词表几条）：%s", four.AnswerSummary)
	}
	for _, r := range []*Result{&one, &two, &three, &four} {
		if !strings.Contains(r.AnswerSummary, "问题路由="+r.Intent) {
			t.Fatalf("结论带没点名路由结果：%s", r.AnswerSummary)
		}
	}
	// ⑤ 早停：没走到 ④ ⇒ 不许有路由。
	ab := make(chan struct{})
	close(ab)
	early := runLoop(fixtureDirty, "这段能怎么优化？", "go", "intent-early", 5, nop, ab, "")
	if early.Intent != "" {
		t.Fatalf("早停那一发居然报出路由=%q（它没走到 ④）", early.Intent)
	}
	if strings.Contains(early.AnswerSummary, "问题路由") {
		t.Fatalf("早停那一发的结论带写了路由话术：%s", early.AnswerSummary)
	}
	t.Logf("读数自印：四种问题四种结论带｜第一张卡 %s / %s｜词表 %d 个词｜早停 Intent=%q",
		one.Findings[0].Rule, two.Findings[0].Rule, len(intentWords), early.Intent)
}

// 针 26：超预算那一发 —— 收口那三步（tally / verify / readers_report）不许整块缺席。
// 来源是 工具/边界那一发.py 的现场读数：贴进 200KB 时预检被内核拒，页面上只剩 ①-④⑧⑨，
// 这三步**根本没出现** ⇒「账没落成」这件事看不出发生在哪一步。缺席与"跑了但没东西可印"
// 在页面上长一个样，所以钉两条：三步都在场、每条带为什么；再配一条正对照防它恒红。
func TestOverBudgetPasteStillShowsClosingSteps(t *testing.T) {
	defer func() { seam = nil; seamReadBack = false }()
	installSeam(0, true)
	big := fixtureDirty + strings.Repeat("// 填充一行给预算看 ", 4000)
	if len(big) <= int(pgCeiling) {
		t.Fatalf("这份样本才 %d 字节，没越过预算 %d ⇒ 这一发量的不是「被拦」那一形，针是空的", len(big), pgCeiling)
	}
	res := runLoop(big, "这段有什么问题", "go", "over-budget", 1, nop, nil, "")
	seen := map[string]Step{}
	for _, s := range res.Trace {
		seen[s.Name] = s
	}
	if c, ok := seen["kernel.check_call"]; !ok || c.Run {
		t.Fatalf("预检这步 ran=%v —— 这一形本该被拦；正臂没成立，后面的断言都无意义", seen["kernel.check_call"].Run)
	}
	for _, name := range []string{"kernel.tally", "kernel.verify", "kernel.readers_report"} {
		s, ok := seen[name]
		if !ok {
			t.Fatalf("%s 整块缺席：超预算那一发页面上看不见这一步，等于没说账没落成 —— 要记成没跑 + 为什么", name)
		}
		if s.Run || s.Basis != Absent {
			t.Fatalf("%s 被报成 ran=%v basis=%s —— 没进账那一发不许把它印成跑过", name, s.Run, s.Basis)
		}
		if !strings.Contains(s.Summary, "没东西可印") {
			t.Fatalf("%s 的 absent 没带理由：%q", name, s.Summary)
		}
	}
	var 有未决 bool
	for _, u := range res.Unknowns {
		if strings.Contains(u.What, "收口读数") {
			有未决 = true
			if !strings.Contains(u.WhyAbsent, "预算") || u.Basis != Absent {
				t.Fatalf("未决那条没交代预算或署错档：%+v", u)
			}
		}
	}
	if !有未决 {
		t.Fatal("没落账这件事没进未决清单 —— 五档里那格 absent 得有原话陪着")
	}
	if !res.MixOK {
		t.Fatalf("这一发五档加总塌了：%+v", res.Mix)
	}
	// 第 7 步那句"没读回"后面必须跟着原因 —— 冒号后空着就是把原因咽回去（absent 必带理由）。
	rb := lastLine(res.Trace, "kernel.read_back")
	if !strings.Contains(rb, "预检被拒") {
		t.Fatalf("第 7 步没交代为什么没读回：%q", rb)
	}
	if res.KPI != 0 {
		t.Fatalf("没落账却有 KPI=%d —— 这个数不是从账上来的", res.KPI)
	}

	// 正对照：同一把尺子量小样本 ⇒ 三步都得真的跑过（这条针不能只会红）。
	res2 := runLoop(fixtureDirty, "这段有什么问题", "go", "over-budget-clean", 2, nop, nil, "")
	for _, name := range []string{"kernel.tally", "kernel.verify", "kernel.readers_report"} {
		var found bool
		for _, s := range res2.Trace {
			if s.Name == name {
				found = true
				if !s.Run {
					t.Fatalf("小样本那发 %s 仍记没跑：%s —— 反臂与正臂分不开，尺子坏了", name, s.Summary)
				}
			}
		}
		if !found {
			t.Fatalf("小样本那发也缺 %s：这条判据根本没在看这件事", name)
		}
	}
	t.Logf("读数自印：超预算那发 步=%d KPI=%d 五档=%+v；小样本那发 步=%d KPI=%d",
		len(res.Trace), res.KPI, res.Mix, len(res2.Trace), res2.KPI)
}

// 针 27：页面那三件资产的括号配平 —— 粗尺，但这一族它抓得住。
// 现场：改 app.js 那句结论带时少写了一个右括号，Go 侧一切照绿（vet/test/selfcheck 全过、exe 照样起、
// /api/turn 照样回 13 步），只有浏览器里 #go 点了不动 —— 因为整份 app.js 语法错、事件根本没挂上。
// 这条不替代浏览器实测（它抓不住逻辑错），只把「结构性少一个括号」这一形在 go test 阶段就拦下。
func TestWebAssetsBracketsBalance(t *testing.T) {
	pairs := [][2]string{{"(", ")"}, {"{", "}"}, {"[", "]"}}
	for _, f := range []string{"web/app.js", "web/index.html", "web/style.css"} {
		b, err := os.ReadFile(f)
		if err != nil {
			t.Fatalf("%s 读不到：%v", f, err)
		}
		for _, pr := range pairs {
			nl := strings.Count(string(b), pr[0]) - strings.Count(string(b), pr[1])
			if nl != 0 {
				t.Fatalf("%s 里 %s 比 %s 多 %d 个 —— 页面 JS 少一个括号时 Go 侧全绿但 #go 点不动", f, pr[0], pr[1], nl)
			}
		}
	}
	// 正对照：把这份件自己加一个左括号，这把尺子必须报不平（不然上面那段是装饰）。
	b, err := os.ReadFile("web/app.js")
	if err != nil {
		t.Fatal(err)
	}
	broken := strings.Replace(string(b), "function el(", "function el((", 1)
	if broken == string(b) {
		t.Fatal("正对照没改成东西（找不到 function el(）⇒ 这条正臂是空的")
	}
	if strings.Count(broken, "(")-strings.Count(broken, ")") == 0 {
		t.Fatal("加了左括号却没报不平：这把尺子量不到东西")
	}
	t.Logf("读数自印：app.js/index.html/style.css 三件各自 ()、{}、[] 配平；正对照注 1 处 ⇒ 检出")
}

// 针 28：① 那句"会不会落账"的预告，必须与第 ⑤ 步实际对得上（单向不变量 + 两读对账）。
// 现场：W14/W15 的边界读数里，贴 200KB 与写 50KB 问题都会把这一发挤出预算，
// 而用户要点完发、看到三条 absent 才知道。预告不是猜：它用内核 DeriveBudget 算出的生效额度，
// 与自己逐段加的字节比一次 —— 两处字节数不一致时 buildPair 直接报错（同一发不许数出两个数）。
func TestBudgetPredictionMatchesPrecheck(t *testing.T) {
	defer func() { seam = nil; seamReadBack = false }()
	installSeam(0, true)

	big := fixtureDirty + strings.Repeat("// 填充一行给预算看 ", 4000)
	resBig := runLoop(big, "这段有什么问题", "go", "pre-big", 1, nop, nil, "")
	if resBig.BudgetPreOK == nil {
		t.Fatal("没接缝外的路径漏了：这一发装了接缝却没算出预告对不对")
	}
	if !resBig.BudgetOver {
		t.Fatalf("这份 %d 字节的样本没被预告成超 ⇒ 预告那栏是恒绿的装饰", len(big))
	}
	if !*resBig.BudgetPreOK {
		t.Fatal("预告说超、第 ⑤ 步却落了账 ⇒ 那句预告在骗人")
	}
	if ranStep(resBig, "kernel.check_call") {
		t.Fatal("预告超了还过了预检：不变量破了")
	}
	if !strings.Contains(lastLine(resBig.Trace, "intake"), "超了") {
		t.Fatalf("① 那句没把话说出口（用户看不见预告）：%q", lastLine(resBig.Trace, "intake"))
	}

	resSmall := runLoop(fixtureDirty, "这段有什么问题", "go", "pre-small", 2, nop, nil, "")
	if resSmall.BudgetOver {
		t.Fatalf("小样本被预告成超（parts=%d、额度=%d）⇒ 这句会把人吓走",
			resSmall.PartsBytes, resSmall.EffectiveCeil)
	}
	if !*resSmall.BudgetPreOK || !ranStep(resSmall, "kernel.check_call") {
		t.Fatal("小样本那发预告或落账不对：这条针不能只会红")
	}
	if resSmall.PartsBytes <= int64(resSmall.Metrics.Bytes) {
		t.Fatalf("parts=%d 不大于代码字节=%d ⇒ parts 少算了系统件或工具清单（那是拿代码量冒充送出量）",
			resSmall.PartsBytes, resSmall.Metrics.Bytes)
	}
	// 两读对账：① 用的 pgPartsBytes 与 buildPair 逐段加的必须是同一个数（不一致时 buildPair 会直接报错）。
	if _, err := buildPair("pre-small", 2, fixtureDirty, "这段有什么问题", ""); err != nil {
		t.Fatalf("buildPair 与 ① 的字节数对不上：%v", err)
	}
	t.Logf("读数自印：超预算那发 parts=%d > 额度=%d 预告=%v ｜ 小样本 parts=%d 代码=%d 预告=%v",
		resBig.PartsBytes, resBig.EffectiveCeil, *resBig.BudgetPreOK,
		resSmall.PartsBytes, resSmall.Metrics.Bytes, *resSmall.BudgetPreOK)
}

// 针 29：额度那三件要**跨落盘活着**。第 ① 步当场说了「超了 ⇒ 这一发不会落账」，
// 翻往轮轨迹时如果只剩"findings 6 条 / KPI 0"，那就是半程诚实 —— 当场诚实、事后说不清。
func TestBudgetFieldsSurviveTheJournal(t *testing.T) {
	defer func() { seam = nil; seamReadBack = false }()
	installSeam(0, true)
	st := newStore(t.TempDir())
	big := fixtureDirty + strings.Repeat("// 填充一行给预算看 ", 4000)
	resOver := runLoop(big, "这段有什么问题", "go", "往返", 1, nop, nil, "")
	resOk := runLoop(fixtureDirty, "这段有什么问题", "go", "往返", 2, nop, nil, "")
	if err := st.append(recordOf(resOver, big)); err != nil {
		t.Fatal(err)
	}
	if err := st.append(recordOf(resOk, fixtureDirty)); err != nil {
		t.Fatal(err)
	}
	recs, err := st.history("往返")
	if err != nil {
		t.Fatal(err)
	}
	if len(recs) != 2 {
		t.Fatalf("往轮轨迹读回 %d 发，要 2 发", len(recs))
	}
	over, ok := recs[0], recs[1]
	if !over.BudgetOver || over.PartsBytes <= over.Effective || over.Effective == 0 {
		t.Fatalf("超预算那一发落盘后说不清自己为什么没落账：%+v", over)
	}
	if ok.BudgetOver || ok.PartsBytes == 0 || ok.Effective == 0 {
		t.Fatalf("正常那一发的额度字段被写坏了：%+v", ok)
	}
	// 不超 ⇒ 该落账。这里不拿"跑了几步"当证据：单测里没开假端点，gateway 本来就 NOT_RUN（12/13 是对的），
	// 我第一版就这么断错过一次 —— 判据要指向日志里那一步真跑了，不是步数凑满。
	if !ranStep(resOk, "kernel.record_call") {
		t.Fatalf("不超预算那一发居然没落账：%s", lastLine(resOk.Trace, "kernel.record_call"))
	}
	if ranStep(resOver, "kernel.record_call") {
		t.Fatal("超预算那一发落了账 ⇒ 上面那栏 budget_over=true 是假的")
	}
	// 前端读的是下划线名：再序列化一次点名字在（针 14 管名字，这条管值活着）
	b, err := json.Marshal(over)
	if err != nil {
		t.Fatal(err)
	}
	for _, k := range []string{"parts_bytes", "budget_over", "budget_effective_ceiling"} {
		if !strings.Contains(string(b), k) {
			t.Fatalf("落盘件里缺 %q ⇒ 历史页说不出为什么没落账：%s", k, string(b))
		}
	}
	t.Logf("读数自印：超预算那发 parts=%d > 额度=%d 落盘后仍写着 budget_over=true；正常那发 parts=%d 额度=%d",
		over.PartsBytes, over.Effective, ok.PartsBytes, ok.Effective)
}

// 针 30：app.js 往里写的每一个容器，探针必须点名普查。
// 出处是 10-21 我自己那次：在会话里手打 `#history li` 数到 0，读成「往轮轨迹没渲染」，实际容器叫 `#hist`。
// 拿**不存在的容器**数出来的 0，与「真的一条没渲染」在数字上一模一样；任何「==0 就通过」的断言在前一种情形恒过
// —— W9 那条「探针量空页面」换了个地方长回来。改名这条路两头都得有牙：离线红在这条针，浏览器红在普查那一栏。
func TestProbeCensusesEveryRenderedContainer(t *testing.T) {
	jsB, err := os.ReadFile(filepath.Join("web", "app.js"))
	if err != nil {
		t.Fatal(err)
	}
	probeB, err := os.ReadFile(filepath.Join("..", "..", "工具", "a11y_probe.js"))
	if err != nil {
		t.Fatal(err)
	}
	js, probe := string(jsB), string(probeB)

	// 1) `const ol = $('hist')` 这类：先把变量名映射回 id，否则 `ol.append(...)` 就看不见写的是哪个容器
	byVar := map[string]string{}
	for _, m := range regexp.MustCompile(`(?m)\b(?:const|let)\s+([A-Za-z_$][\w$]*)\s*=\s*\$\('([a-z0-9-]+)'\)`).FindAllStringSubmatch(js, -1) {
		byVar[m[1]] = m[2]
	}
	targets := map[string]bool{}
	for _, m := range regexp.MustCompile(`\$\('([a-z0-9-]+)'\)\s*\.(?:append|textContent|innerText|innerHTML)\b`).FindAllStringSubmatch(js, -1) {
		targets[m[1]] = true
	}
	for _, name := range regexp.MustCompile(`(?m)\b([A-Za-z_$][\w$]*)\s*\.(?:append|textContent|innerText|innerHTML)\b`).FindAllStringSubmatch(js, -1) {
		if id, ok := byVar[name[1]]; ok {
			targets[id] = true
		}
	}
	if len(targets) < 12 {
		t.Fatalf("只认出 %d 个渲染目标容器 ⇒ 抽取口径漂了，这条针现在是在数它自己（不去验页面）", len(targets))
	}

	censused := map[string]bool{}
	for _, m := range regexp.MustCompile(`census\('[^']*',\s*'#([a-z0-9-]+)'`).FindAllStringSubmatch(probe, -1) {
		censused[m[1]] = true
	}
	var missing []string
	for id := range targets {
		if !censused[id] {
			missing = append(missing, id+"（app.js 往里写，探针没普查）")
		}
	}
	sort.Strings(missing)
	if len(missing) > 0 {
		t.Fatalf("探针漏普查 %d 个容器：%s ⇒ 这些地方「数到 0」分不清是容器不存在还是真没渲染", len(missing), strings.Join(missing, "、"))
	}

	// 2) 负对照必须是"对照"而不是普通普查格：它往 failures 里塞一条预期红，"不达标"就永远 ≥1，判据恒红等于没判据
	if !strings.Contains(probe, "control('对照_假容器'") {
		t.Fatal("负对照那一格没了 ⇒ 整栏普查没人证它会红")
	}
	if strings.Contains(probe, "census('对照_假容器'") {
		t.Fatal("负对照用的是 census ⇒ 每次跑都往「不达标」里塞一条预期红，这一栏就再也当不了判据")
	}
	// 3) 一个都没有也算红：抽取口径崩了不能悄悄"通过"
	if len(censused) < len(targets) {
		t.Fatalf("探针普查 %d 格 < app.js 渲染目标 %d 个 ⇒ 上面那个漏检循环没跑全", len(censused), len(targets))
	}
	t.Logf("读数自印：app.js 写 %d 个容器，探针普查 %d 格全盖住，负对照单独记账（不进不达标）", len(targets), len(censused))
}

// 针 31：往轮轨迹那一栏必须有界、能键盘走到、且"最新在最后一行"这句 UI 话是真的。
// 出处是 10-21 W22 的实测：连发 20 发之后 #hist 高 1945px 且 scrollHeight==clientHeight —— 它不是内部滚动，
// 是**无界把整栏撑下去**（#code 有 52vh、.stackbox 有 28vh，唯独这里漏了界）。限高之后"最新在最后一行"
// 就必须滚出来才看得见，所以顺序、滚动、可聚焦三件事一起钉住。
func TestHistoryPaneBoundedAndKeyboardReachable(t *testing.T) {
	cssB, err := os.ReadFile(filepath.Join("web", "style.css"))
	if err != nil {
		t.Fatal(err)
	}
	htmlB, err := os.ReadFile(filepath.Join("web", "index.html"))
	if err != nil {
		t.Fatal(err)
	}
	jsB, err := os.ReadFile(filepath.Join("web", "app.js"))
	if err != nil {
		t.Fatal(err)
	}
	css, html, js := string(cssB), string(htmlB), string(jsB)

	// 1) ol#hist 那条规则里必须同时有 max-height 与 overflow-y: auto（只加其一会退化成"看不见"或"整页狂滚"）
	rule := regexp.MustCompile(`(?s)ol#hist\s*\{([^}]*)\}`).FindStringSubmatch(css)
	if rule == nil {
		t.Fatal("CSS 里找不到 ol#hist 那条规则 ⇒ 这条针在数它自己")
	}
	if !strings.Contains(rule[1], "max-height") || !strings.Contains(rule[1], "overflow-y: auto") {
		t.Fatalf("ol#hist 缺界或缺内部滚动：%s", strings.TrimSpace(rule[1]))
	}

	// 2) 可聚焦 + 有可及名（滚动区键盘走不到 = 只用鼠标能看全，WCAG 2.1.1 不过）
	li := regexp.MustCompile(`<ol id="hist"[^>]*>`).FindString(html)
	if li == "" {
		t.Fatal(`index.html 里找不到 <ol id="hist" …>`)
	}
	if !strings.Contains(li, `tabindex="0"`) {
		t.Fatalf("历史面板没挂 tabindex ⇒ 滚不动它：%s", li)
	}
	m := regexp.MustCompile(`aria-labelledby="([^"]+)"`).FindStringSubmatch(li)
	if m == nil {
		t.Fatalf("历史面板没有 aria-labelledby ⇒ 滚动区没人能说出它是干嘛的：%s", li)
	}
	if !strings.Contains(html, `id="`+m[1]+`"`) {
		t.Fatalf("aria-labelledby 指向的 id %q 在页面上不存在 ⇒ 可及名是空的", m[1])
	}

	// 3) 渲染必须"贴底才跟"，不许每发都硬拽回底部（用户往上翻旧发时被抢焦点）
	if !strings.Contains(js, "贴底") || !strings.Contains(js, "ol.scrollTop = ol.scrollHeight") {
		t.Fatal("app.js 里没有『贴底才滚到最新』那段 ⇒ 面板限高后最新那一发在视野外")
	}

	// 4) UI 那句"最新在最后一行"要属实：history 必须旧在前、新在后
	defer func() { seam = nil; seamReadBack = false }()
	installSeam(0, true)
	st := newStore(t.TempDir())
	a := runLoop(fixtureDirty, "这段有什么问题", "go", "有界", 1, nop, nil, "")
	b := runLoop(fixtureClean, "这段有什么问题", "go", "有界", 2, nop, nil, "")
	if err := st.append(recordOf(a, fixtureDirty)); err != nil {
		t.Fatal(err)
	}
	if err := st.append(recordOf(b, fixtureClean)); err != nil {
		t.Fatal(err)
	}
	recs, err := st.history("有界")
	if err != nil {
		t.Fatal(err)
	}
	if len(recs) != 2 {
		t.Fatalf("往轮轨迹读回 %d 条（要 2 条）⇒ 上面那句 UI 话没人验过", len(recs))
	}
	if !(recs[0].Turn < recs[1].Turn) {
		t.Fatalf("history 回来的顺序是 新→旧（%d, %d）⇒ 「最新在最后一行」是假话，得改成「最新在第一行」并改滚动方向",
			recs[0].Turn, recs[1].Turn)
	}
	t.Logf("读数自印：ol#hist 有 max-height+overflow-y｜面板 tabindex=0 且可及名指向 %q｜贴底才跟｜history 顺序 旧(%d)→新(%d)",
		m[1], recs[0].Turn, recs[1].Turn)
}

// 针 32：把 W22 那一条从"一个实例"升成"一类" —— 会随会话增长的容器必须有界，只随单发重画的容器必须有清空。
// 两者的区别正是 W22 学到的：`#hist` 每发都先 `textContent=”` 再把**服务端全部发次**重画一遍 ——
// "清一次再全量重画"不等于"有界"，行数还是随会话一路涨（20 发实测 1945px）。
// 所以按"这个容器的数据来源是谁"分两类判：读 /api/history 的 ⇒ CSS 必须有 max-height；读单发 Result 的 ⇒ 必须有清空语句。
func TestGrowingContainersBoundedOrCleared(t *testing.T) {
	jsB, err := os.ReadFile(filepath.Join("web", "app.js"))
	if err != nil {
		t.Fatal(err)
	}
	cssB, err := os.ReadFile(filepath.Join("web", "style.css"))
	if err != nil {
		t.Fatal(err)
	}
	js, css := string(jsB), string(cssB)

	// 按函数体切块（顶层 function / async function）
	type fn struct{ name, body string }
	var fns []fn
	idx := regexp.MustCompile(`(?m)^async function ([A-Za-z_$][\w$]*)|^function ([A-Za-z_$][\w$]*)`).FindAllStringIndex(js, -1)
	name := regexp.MustCompile(`(?m)^(?:async )?function ([A-Za-z_$][\w$]*)`)
	for i, m := range idx {
		end := len(js)
		if i+1 < len(idx) {
			end = idx[i+1][0]
		}
		fns = append(fns, fn{name.FindStringSubmatch(js[m[0]:])[1], js[m[0]:end]})
	}
	if len(fns) < 6 {
		t.Fatalf("只切出 %d 个函数体 ⇒ 抽取口径漂了，这条针在数它自己", len(fns))
	}

	// 一个函数体往哪些容器里 append（直写 $('id').append 与先赋值给变量再 append 两种）
	targets := func(body string) map[string]bool {
		out := map[string]bool{}
		for _, m := range regexp.MustCompile(`\$\('([a-z0-9-]+)'\)\s*\.append\(`).FindAllStringSubmatch(body, -1) {
			out[m[1]] = true
		}
		byVar := map[string]string{}
		for _, m := range regexp.MustCompile(`(?:const|let)\s+([A-Za-z_$][\w$]*)\s*=\s*\$\('([a-z0-9-]+)'\)`).FindAllStringSubmatch(body, -1) {
			byVar[m[1]] = m[2]
		}
		for _, m := range regexp.MustCompile(`(?m)\b([A-Za-z_$][\w$]*)\s*\.append\(`).FindAllStringSubmatch(body, -1) {
			if id, ok := byVar[m[1]]; ok {
				out[id] = true
			}
		}
		return out
	}

	var 增长, 单发 []string
	for _, f := range fns {
		for id := range targets(f.body) {
			if strings.Contains(f.body, "/api/history") {
				增长 = append(增长, id)
			} else {
				单发 = append(单发, id)
			}
		}
	}
	sort.Strings(增长)
	sort.Strings(单发)
	if len(增长) == 0 {
		t.Fatal("一个「读历史往里写」的容器都没找到 ⇒ 抽取口径漂了（app.js 改过写法？这条针要跟着改，不是判过）")
	}

	var 缺界, 缺清空 []string
	for _, id := range 增长 {
		rule := regexp.MustCompile(`[^{}\n]*#` + regexp.QuoteMeta(id) + `[^{}\n]*\{([^}]*)\}`).FindStringSubmatch(css)
		if rule == nil || !strings.Contains(rule[1], "max-height") {
			缺界 = append(缺界, id)
		}
	}
	for _, id := range 单发 {
		clear := regexp.MustCompile(`\$\('` + regexp.QuoteMeta(id) + `'\)\s*\.textContent\s*=\s*''`).MatchString(js)
		if !clear {
			for _, m := range regexp.MustCompile(`(?:const|let)\s+([A-Za-z_$][\w$]*)\s*=\s*\$\('`+regexp.QuoteMeta(id)+`'\)`).FindAllStringSubmatch(js, -1) {
				if regexp.MustCompile(`(?m)\b` + regexp.QuoteMeta(m[1]) + `\s*\.textContent\s*=\s*''`).MatchString(js) {
					clear = true
				}
			}
		}
		if !clear {
			缺清空 = append(缺清空, id)
		}
	}
	if len(缺界) > 0 {
		t.Fatalf("这些容器按会话增长却没被 CSS 限住：%s ⇒ 会把整栏无界撑下去（W22 实测 20 发 1945px）", strings.Join(缺界, "、"))
	}
	if len(缺清空) > 0 {
		t.Fatalf("这些容器只画单发结果却没有清空：%s ⇒ 跨发累积，上一发的卡片还挂在下面", strings.Join(缺清空, "、"))
	}
	t.Logf("读数自印：按会话增长(必须限高)=%v｜只随单发重画(必须清空)=%v｜函数体切出 %d 个", 增长, 单发, len(fns))
}

// 针 33：面板不许把两发的步骤写进同一列 —— submit() 必须有重入保护。
// 出处是 10-21 W24 的实测：带 -step-delay 的服务上连点两次 #go，#trace 变成
// `1,8,2,9,10,11,12,13,3,4,5,6,7,8,9,10,11,12,13` —— 两发混在同一列里。数据侧没事（各自落盘），
// 坏的是这块"看得见循环"的面板。修法是在跑的时候禁掉 #go（finally 恢复），这条针盯的就是那个保护在不在。
func TestSubmitHasReentrancyGuard(t *testing.T) {
	b, err := os.ReadFile(filepath.Join("web", "app.js"))
	if err != nil {
		t.Fatal(err)
	}
	js := string(b)
	i := strings.Index(js, "async function submit()")
	if i < 0 {
		t.Fatal("找不到 submit() ⇒ 这条针在数它自己")
	}
	// 取 submit 的函数体（到下一个顶层 function 之前）
	rest := js[i:]
	if j := strings.Index(rest[len("async function submit()"):], "\nfunction "); j > 0 {
		rest = rest[:len("async function submit()")+j]
	}
	if !strings.Contains(rest, "$('go').disabled = true") {
		t.Fatal("submit() 里没有『开跑就把 #go 禁用』⇒ 连点会把两发的步骤写进同一列")
	}
	if !strings.Contains(rest, "} finally {") || !strings.Contains(rest, "$('go').disabled = false") {
		t.Fatal("禁用没有配 finally 里的恢复 ⇒ 一旦服务端报错，按钮就永久点不动了（比混列更糟）")
	}
	if !strings.Contains(rest, "if (running") {
		t.Fatal("没有 running 这道闸 ⇒ 按钮被绕过（回车、脚本 click）时照样能并发")
	}
	t.Logf("读数自印：submit() 里禁用/finally 恢复/running 闸门三件都在（函数体 %d 字节）", len(rest))
}

// 针 34：落账被拒的那句原话要跨落盘活着（W26 实测：账到上限那一形，历史行与落了账的行长得一模一样）。
// 三条各证：拒收时 Result/Record/JSON 三处都在；没拒收时那个键**不许出现**；超额度那一形由 budget_over 说话，不许两条抢同一个事实。
func TestLedgerRejectSurvivesTheRoundTrip(t *testing.T) {
	defer func() { seam = nil; seamReadBack = false }()
	原话 := "落账被拒：写入被挡：这本账已到上限 200 条（现有 245 条），一条都不写"
	seam = func(string, string, string, int) (SeamReply, error) {
		return SeamReply{Checked: false, Reason: "预检被拒"}, fmt.Errorf("%s", 原话)
	}
	bad := runLoop(fixtureDirty, "这段有什么问题", "go", "reject-pin", 1, nop, nil, "")
	if !strings.Contains(bad.LedgerReject, "已到上限") {
		t.Fatalf("拒收原话没进 Result ⇒ 页面翻回来又是一发看不出为什么的 KPI 0：%q", bad.LedgerReject)
	}
	bb, err := json.Marshal(bad)
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(string(bb), `"ledger_reject"`) {
		t.Fatal("Result 序列化里没有 ledger_reject 键（omitempty 把真事写没了）")
	}
	rec := recordOf(bad, fixtureDirty)
	if rec.LedgerReject != bad.LedgerReject {
		t.Fatalf("Record 与原话不一致：%q", rec.LedgerReject)
	}
	st := newStore(t.TempDir())
	if err := st.append(rec); err != nil {
		t.Fatal(err)
	}
	back, err := st.history("reject-pin")
	if err != nil {
		t.Fatal(err)
	}
	if len(back) != 1 || !strings.Contains(back[0].LedgerReject, "已到上限") {
		t.Fatalf("落盘往返读回来 %d 行、原话没活着：%+v", len(back), back)
	}
	seam = func(string, string, string, int) (SeamReply, error) {
		return SeamReply{Checked: true, Recorded: true, ReadBack: true, Verdict: "预检过了"}, nil
	}
	clean := runLoop(fixtureDirty, "这段有什么问题", "go", "reject-pin-clean", 2, nop, nil, "")
	if clean.LedgerReject != "" {
		t.Fatalf("这一发没被拒，LedgerReject 却有话：%q", clean.LedgerReject)
	}
	cb, err := json.Marshal(clean)
	if err != nil {
		t.Fatal(err)
	}
	if strings.Contains(string(cb), "ledger_reject") {
		t.Fatal("没拒收那一发也带上了 ledger_reject ⇒ 把没问写成问了")
	}
	installSeam(0, true)
	over := runLoop(strings.Repeat("x", 200*1024), "这段有什么问题", "go", "reject-pin-budget", 3, nop, nil, "")
	if !over.BudgetOver {
		t.Fatalf("200KB 那一发本该超额度（BudgetOver=false ⇒ 这一臂没造出现场，不算量过）")
	}
	if over.LedgerReject != "" {
		t.Fatalf("超额度那一形已由 budget_over 那条红字说话，LedgerReject 又写一遍 ⇒ 两条抢同一个事实：%q", over.LedgerReject)
	}
	app, err := os.ReadFile(filepath.Join("web", "app.js"))
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(string(app), "if (t.ledger_reject) li.append(el('div', 'red'") {
		t.Fatal("页面没把 ledger_reject 渲染成红字（或渲染被 if(false…) 那种死形糊过去）⇒ 落盘活着但屏幕上看不见")
	}
	t.Logf("读数自印：拒收原话 %d 字｜落盘往返 %d 行仍带原话｜干净那一发 JSON 里 0 个 ledger_reject｜超额度那一发 BudgetOver=true 且 LedgerReject 空",
		len([]rune(原话)), len(back))
}

// 针 35：发号是**会话内**的身份，不是进程内的。W28 实测到反例：换一次进程，同一会话又出现一遍
// 「第 1 发 / 第 2 发 / 第 3 发」——页面上 6 行里有三对重号，而 /api/stop 正是按 session+发号点名停哪一发。
// 这条针盯 nextTurn 会不会从盘上接续：盘上最大号 9 ⇒ 下一发必须是 10（不是 1）。
func TestTurnNumbersSurviveProcessRestart(t *testing.T) {
	oldNo, oldSeeded, oldStore := turnNo, turnSeeded, storeRef
	defer func() { turnNo, turnSeeded, storeRef = oldNo, oldSeeded, oldStore }()

	st := newStore(t.TempDir())
	for _, n := range []int{7, 9} { // 故意留洞：行数 2、最大号 9 ⇒ 地板必须取大的那个
		if err := st.append(Record{Session: "重启接续", Turn: n}); err != nil {
			t.Fatal(err)
		}
	}
	turnNo = map[string]int{}
	turnSeeded = map[string]bool{}
	storeRef = st
	if got := nextTurn("重启接续"); got != 10 {
		t.Fatalf("换进程后第一发的号是 %d，要 10 ⇒ 盘上的号没接续，两个身份会写进同一本会话文件", got)
	}
	if got := nextTurn("重启接续"); got != 11 {
		t.Fatalf("第二发是 %d，要 11", got)
	}
	if got := nextTurn("没文件的会话"); got != 1 {
		t.Fatalf("全新会话第一发是 %d，要 1（没文件不是错误，不许垫高）", got)
	}

	st2 := newStore(t.TempDir())
	raw := `{"turn":1}` + "\n" + `{"turn":2}` + "\n" + "这行不是 JSON（进程被掐在写一半）" + "\n"
	if err := os.WriteFile(st2.path("坏行"), []byte(raw), 0o644); err != nil {
		t.Fatal(err)
	}
	floor, rows, bad, err := st2.turnFloor("坏行")
	if err != nil {
		t.Fatal(err)
	}
	if floor != 3 || rows != 3 || bad != 1 {
		t.Fatalf("坏行那一本：地板=%d 行数=%d 坏行=%d，要 3/3/1 ⇒ 解析不开的行就不该让号退回去占别人的身份", floor, rows, bad)
	}
	turnNo = map[string]int{}
	turnSeeded = map[string]bool{}
	storeRef = st2
	if got := nextTurn("坏行"); got != 4 {
		t.Fatalf("坏行会话第一发是 %d，要 4", got)
	}
	// 盘上读不回来（比如目录被换到别处）时也要照旧出号，但不能悄悄：这里只验"不 panic、继续给号"
	storeRef = newStore(filepath.Join(t.TempDir(), "不存在也没关系"))
	if got := nextTurn("另一本"); got != 1 {
		t.Fatalf("读不到盘时第一发是 %d，要 1", got)
	}
	t.Logf("读数自印：盘上最大 9 / 行 2 ⇒ 接续后 10、11｜坏行那一本 行 3 最大 2 坏 1 ⇒ 地板 3、下一发 4｜新会话仍从 1 起")
}

// 针 36：第 ⑩ 步那句「账 N 条」必须说清是哪一本账。W28 实测：换一次进程，内核账是新的（本进程 3 发 = 147 条），
// 会话文件是旧的（那时已有 6 发）—— 两个数不写在一起，「147 条」就会被读成整本会话的账。
func TestTallyStepNamesWhichLedger(t *testing.T) {
	oldStore, oldLanded, oldSeam := storeRef, procLanded, seam
	defer func() { storeRef, procLanded, seam = oldStore, oldLanded, oldSeam }()
	installSeam(0, true)
	st := newStore(t.TempDir())
	storeRef = st
	for _, n := range []int{1, 2} { // 模拟"上一个进程留下的往轮轨迹"
		if err := st.append(Record{Session: "哪一本账", Turn: n}); err != nil {
			t.Fatal(err)
		}
	}
	procLanded = 0
	res := runLoop(fixtureDirty, "这段有什么问题", "go", "哪一本账", 3, nop, nil, "")
	line := lastLine(res.Trace, "kernel.tally")
	if !strings.Contains(line, "这本账是本进程的") {
		t.Fatalf("第 ⑩ 步没标这是哪一本账，读的人会把这一发的 49 条当成整本会话的账：%s", line)
	}
	if !strings.Contains(line, "本进程至今落了 1 发") {
		t.Fatalf("本进程落了几发不对（要 1）：%s", line)
	}
	if !strings.Contains(line, "此前有 2 发") {
		t.Fatalf("会话文件那头的数没进来（要 2）：%s", line)
	}
	storeRef = nil
	line2 := lastLine(runLoop(fixtureDirty, "这段有什么问题", "go", "哪一本账", 4, nop, nil, "").Trace, "kernel.tally")
	if !strings.Contains(line2, "不知道") || strings.Contains(line2, "有 0 发") {
		t.Fatalf("store 没接上时把「不知道」写成了 0：%s", line2)
	}
	st2 := newStore(t.TempDir())
	storeRef = st2
	line4 := lastLine(runLoop(fixtureDirty, "这段有什么问题", "go", "新开张的一本", 9, nop, nil, "").Trace, "kernel.tally")
	if !strings.Contains(line4, "此前没有往轮") || strings.Contains(line4, "那 0 发") {
		t.Fatalf("会话文件是空的时候把空集说成了有东西：%s", line4)
	}
	seam = nil
	line3 := lastLine(runLoop(fixtureDirty, "这段有什么问题", "go", "哪一本账", 5, nop, nil, "").Trace, "kernel.tally")
	if strings.Contains(line3, "这本账是本进程的") {
		t.Fatalf("没装接缝却印出了本进程落账数（把没装说成了装了）：%s", line3)
	}
	t.Logf("读数自印：本进程 1 发 / 会话文件此前 2 行 ⇒ %s", line)
}

// 针 37：口径句的形状判据本身要有判据 —— W29 那条教训不能只靠"我下次记得读一遍"。
// 六形 + 一条反向（内核那句诚实的"拒 0 发"不许被误伤）+ 一条真跑一圈。
func TestScopeClauseShapeJudge(t *testing.T) {
	cases := []struct {
		名  string
		句  string
		该过 bool
	}{
		{"老会话", "这本账是本进程的（不分会话）：本进程至今落了 3 发；这一本会话文件此前有 2 发 ⇒ 那 2 发的账不在这个进程里", true},
		{"新开张的一本", "这本账是本进程的（不分会话）：本进程至今落了 1 发；这一本会话文件此前没有往轮（新开张的一本）", true},
		{"store 没接上", "这本账是本进程的（不分会话）：本进程至今落了 1 发；这一本会话文件没接上（store 未装）⇒ 此前有几发不知道，这里不写 0", true},
		{"空集说成有东西", "这本账是本进程的（不分会话）：本进程至今落了 1 发；这一本会话文件里此前记着 0 发 ⇒ 那 0 发不在这本账上", false},
		{"两个数没带标签", "这本账是本进程的：本进程落了 1 发；会话文件里此前有 2 发", false},
		{"整句缺失", "", false},
	}
	过了 := 0
	for _, c := range cases {
		ok, why := scopeSane(c.句)
		if ok != c.该过 {
			t.Fatalf("形「%s」判错（该过=%v 实判=%v）：%s", c.名, c.该过, ok, why)
		}
		if ok {
			过了++
		} else if !strings.Contains(why, c.名[:2]) && why == "" {
			t.Fatalf("形「%s」判红却没给理由", c.名)
		}
	}
	full := "账 49 条（absent=12）；被内核判据拒 0 发；预检在门口被挡下 0 次"
	if got := clauseOf(full); got != "" {
		t.Fatalf("内核那句诚实的「拒 0 发」被切进口径句了（判据会误伤量到的零）：%s", got)
	}
	oldStore, oldSeam := storeRef, seam
	defer func() { storeRef, seam = oldStore, oldSeam }()
	installSeam(0, true)
	storeRef = nil
	res := runLoop(fixtureDirty, "这段有什么问题", "go", "形状判据", 1, nop, nil, "")
	ok, why := scopeSane(clauseOf(lastLine(res.Trace, "kernel.tally")))
	if !ok {
		t.Fatalf("真跑一圈的口径句没过自己的判据：%s", why)
	}
	t.Logf("读数自印：六形里 %d 形该过（判据全对上）｜内核那句 0 发不被误伤｜真跑那一形：%s", 过了, why)
}

// 针 38：账满那一形里「谁拒的」必须说对。W32 实测到三句假话挤在同一列：
// 第 ⑤ 步亮着「预检过了内核判据」、第 ⑥ 步硬说「没落账（预检就拒了）」、第 ⑦ 步「没读回：」后面是空的。
// 这一形只有装了 -entry-cap 的实例才走得到 ⇒ 之前 37 根针一次没碰过这条失败路。
func TestLedgerFullNamesWhoRefused(t *testing.T) {
	旧落了, 旧接缝 := procLanded, seam
	defer func() { procLanded, seam = 旧落了, 旧接缝 }()
	installSeam(49, true) // 一发恰好 49 格 ⇒ 第一发装满、第二发必被门口挡（这个整除关系就是这一臂的前提）
	procLanded = 0
	一发 := runLoop(fixtureDirty, "这段有什么问题", "go", "账满针", 1, nop, nil, "")
	二发 := runLoop(fixtureDirty, "这段有什么问题", "go", "账满针", 2, nop, nil, "")
	if 一发.LedgerReject != "" || 一发.KPI < 1 {
		t.Fatalf("第一发没把账装满（KPI=%d 拒=%q）⇒ 第二发那一臂没造出现场，不算量过", 一发.KPI, 一发.LedgerReject)
	}
	五 := lastLine(二发.Trace, "kernel.check_call")
	六 := lastLine(二发.Trace, "kernel.record_call")
	一发六 := lastLine(一发.Trace, "kernel.record_call")
	七 := lastLine(二发.Trace, "kernel.read_back")
	牙 := []struct {
		名  string
		合  bool
		读数 string
	}{
		{"第 ⑤ 步说的是内核预检那句原话（不是第 ⑥ 步的错）",
			strings.Contains(五, "输入侧") && !strings.HasPrefix(五, "接缝报错：落账被拒"), 五},
		{"第 ⑤ 步自己那列亮着 ran（预检是真过了）", stepRan(二发, "kernel.check_call"), "看 Trace 里那一步的 ran 字段"},
		{"第 ⑥ 步不许把门口挡说成预检拒", !strings.Contains(六, "预检就拒了"), 六},
		{"第 ⑥ 步带上内核那句容量原话", strings.Contains(六, "已到上限"), 六},
		{"第 ⑦ 步那句「没读回：」后面必须有字", strings.TrimSpace(strings.TrimPrefix(七, "没读回：")) != "", 七},
		{"第二发的 LedgerReject 活着且带容量原话", strings.Contains(二发.LedgerReject, "已到上限"), 二发.LedgerReject},
		{"第二发 KPI 是量到的 0（不是这一发没跑）", 二发.KPI == 0 && len(二发.Trace) > 0, fmt.Sprint(二发.KPI, len(二发.Trace))},
		{"第二发五档加总不塌", 二发.MixOK, fmt.Sprint(二发.Mix)},
		{"本进程落的发数不把没落账那发算进去", landedCount() == 1, fmt.Sprint(landedCount())},
		{"第 ⑤ 步不再替第 ⑥ 步说话（一列里落账只有一处写）", !strings.Contains(五, "落账"), 五},
		{"第 ⑥ 步把内核那句旗标名接到这一台（照抄不改，但说清该敲哪个）", strings.Contains(六, "-entry-cap"), 六},
		{"落了账那一发的第 ⑥ 步带的是内核原话", strings.Contains(一发六, "整发落账 49 条") && !strings.Contains(一发六, "两侧共 49 格"), 一发六},
	}
	没咬住 := []string{}
	for _, x := range 牙 {
		if !x.合 {
			没咬住 = append(没咬住, x.名+"（读数："+x.读数+"）")
		}
	}
	if len(没咬住) > 0 {
		t.Fatalf("账满那一形还有 %d 条假话站着：%v", len(没咬住), 没咬住)
	}
	app, err := os.ReadFile(filepath.Join("web", "app.js"))
	if err != nil {
		t.Fatal(err)
	}
	a := string(app)
	if !strings.Contains(a, "if (t.ledger_reject) li.append(el('div', 'red'") {
		t.Fatal("历史页没渲染 ledger_reject ⇒ 落盘活着但屏幕上看不见")
	}
	if !strings.Contains(a, "谁拒的(t.ledger_reject)") || !strings.Contains(a, "if (r.startsWith('落账被拒'))") {
		t.Fatal("历史页还把所有拒收一律写成「第 ⑤ 步说的」⇒ 账满那一形会和第 ⑤ 步自己那句「预检过了」当场打脸")
	}
	t.Logf("读数自印：牙 %d 条全咬住 ｜ ⑤ %s ｜ ⑥ %s ｜ ⑦ %s", len(牙), 五, 六, 七)
}

// stepRan 按步名找那一格的 ran（不按序号：序号会把"第几步"这件事写进考卷，
// 步骤一挪位置就红得没道理 —— 与本件"点名不点序号"的口径一致）。
func stepRan(r Result, name string) bool {
	for _, s := range r.Trace {
		if s.Name == name {
			return s.Run
		}
	}
	return false
}

// 针 39：第 ⑧ 步的三种「打了但没成」形状必须各说各话，而且**失败那一发也要进得了账**。
// W33 实测到的三件事：① 429 那一形把帧数/首帧/帧间/入线字节署成 measured(0)（正文是刻意没读的）；
// ② 半路断流被记成正常回帧（fail_kind 空）；③ 连不上/超时那一形因为把"请求要流式"署成"这发是流式的"
// 而被内核整发拒收（原话："这一发是流式的，分帧数却报缺席"）⇒ 失败发在账上只剩一个拒收计数。
func TestGatewayFailureShapesStillBook(t *testing.T) {
	旧落了, 旧接缝 := procLanded, seam
	defer func() { procLanded, seam = 旧落了, 旧接缝 }()

	形 := "正常"
	假口令 := "SK-TEST-SECRET-in-error-body"
	端 := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch 形 {
		case "429":
			w.Header().Set("Retry-After", "7")
			w.WriteHeader(http.StatusTooManyRequests)
			_, _ = w.Write([]byte(`{"error":"rate_limited","echo":"` + 假口令 + `"}`))
		case "半路断":
			w.Header().Set("Content-Type", "text/event-stream")
			fl, _ := w.(http.Flusher)
			_, _ = w.Write([]byte("data: {\"object\":\"chat.completion.chunk\",\"choices\":[{\"delta\":{\"content\":\"head\"}}]}\n\n"))
			if fl != nil {
				fl.Flush()
			}
			_, _ = w.Write([]byte("data: {\"choices\":[{\"delta\":{\"content\":")) // 半条 JSON，然后收摊
		default:
			w.Header().Set("Content-Type", "text/event-stream")
			_, _ = w.Write([]byte("data: {\"object\":\"chat.completion.chunk\",\"choices\":[{\"delta\":{\"content\":\"ok\"},\"finish_reason\":\"stop\"}]}\n\n"))
			_, _ = w.Write([]byte("data: [DONE]\n\n"))
		}
	}))
	defer 端.Close()
	t.Setenv("PGAGENT_BASE_URL", 端.URL+"/v1")
	t.Setenv("PGAGENT_MODEL", "测试起的坏端点（不是真模型）")
	installSeam(0, true)
	procLanded = 0

	量过 := []string{"chunks", "first_byte_ms", "max_gap_ms", "wire_bytes_in"}
	跑 := func(形状, 会话 string, 第几发 int) Result {
		形 = 形状
		return runLoop(fixtureDirty, "这段有什么问题", "go", 会话, 第几发, nop, nil, "")
	}
	档名 := func(r Result, 格 string) string {
		for _, d := range r.Decisions {
			if d.Key == 格 {
				return d.Basis
			}
		}
		return ""
	}

	正常 := 跑("正常", "网关-正常", 1)
	四二九 := 跑("429", "网关-429", 2)
	半路 := 跑("半路断", "网关-半路断", 3)
	超额 := runLoop(strings.Repeat("x", 200*1024), "这段有什么问题", "go", "网关-超额度", 4, nop, nil, "")
	五 := lastLine(超额.Trace, "kernel.check_call")
	八四二九 := lastLine(四二九.Trace, "gateway")
	八半路 := lastLine(半路.Trace, "gateway")

	牙 := []struct {
		名  string
		合  bool
		读数 string
	}{
		{"正常那一发落了账（这一臂的前提）", 正常.KPI >= 1 && 正常.LedgerReject == "", fmt.Sprint(正常.KPI, 正常.LedgerReject)},
		{"429 那一发也落了账（不是只剩一个拒收计数）", 四二九.KPI >= 1 && 四二九.LedgerReject == "", fmt.Sprint(四二九.KPI, 四二九.LedgerReject)},
		{"半路断那一发也落了账", 半路.KPI >= 1 && 半路.LedgerReject == "", fmt.Sprint(半路.KPI, 半路.LedgerReject)},
		{"429：正文没读 ⇒ 那四格只能是缺席", func() bool {
			for _, g := range 量过 {
				if 档名(四二九, g) != "absent" {
					return false
				}
			}
			return true
		}(), fmt.Sprint(四二九.Decisions)},
		{"半路断：真读到的帧数仍署 measured（不许连坐降档）", 档名(半路, "chunks") == "measured", 档名(半路, "chunks")},
		{"429 的错误体没被抄进读数（假口令不许出现）", !strings.Contains(串(四二九), 假口令), 假口令},
		{"三发五档都不塌", 正常.MixOK && 四二九.MixOK && 半路.MixOK, fmt.Sprint(正常.MixOK, 四二九.MixOK, 半路.MixOK)},
		{"三发都跑完（失败归因不改变「这一发走完了」）",
			正常.StopReason == "跑完" && 四二九.StopReason == "跑完" && 半路.StopReason == "跑完",
			正常.StopReason + "/" + 四二九.StopReason + "/" + 半路.StopReason},
		{"429：第 ⑧ 步自带「错误体刻意没读」的免责（不许让 0 帧看着像量到的）",
			strings.Contains(八四二九, "错误体刻意没读") && strings.Contains(八四二九, "归因 http"), 八四二九},
		{"半路断：第 ⑧ 步点名归因=protocol 且说清「没收完」（不许当正常回帧）",
			strings.Contains(八半路, "归因 protocol") && strings.Contains(八半路, "没收完"), 八半路},
		{"预检被拒那一发：第 ⑤ 步给的是完整三行（不是只截第一行）",
			strings.Contains(五, "预检结论") && strings.Contains(五, "输出侧"), 五},
	}
	没咬住 := []string{}
	for _, x := range 牙 {
		if !x.合 {
			没咬住 = append(没咬住, x.名+"（读数："+clipLine(x.读数)+"）")
		}
	}
	if len(没咬住) > 0 {
		t.Fatalf("网关失败形状还有 %d 条没咬住：%v", len(没咬住), 没咬住)
	}
	t.Logf("读数自印：牙 %d 条全咬住 ｜ 正常 KPI=%d ｜ 429 KPI=%d 那四档=%s ｜ 半路断 KPI=%d chunks=%s",
		len(牙), 正常.KPI, 四二九.KPI, 档名(四二九, "chunks"), 半路.KPI, 档名(半路, "chunks"))
}

// 串 把整个 Result 序列化成一坨，用来扫"不该上屏的东西有没有上屏"（比逐字段判更笨也更不容易漏）。
func 串(r Result) string {
	b, err := json.Marshal(r)
	if err != nil {
		return fmt.Sprint(r)
	}
	return string(b)
}

// clipLine 按字（不是按字节）截断，免得把中文截成半个。
func clipLine(s string) string {
	n := []rune(s)
	if len(n) > 160 {
		return string(n[:160]) + "…"
	}
	return s
}

// 针 40：端点"只回 reasoning 没回正文"那一形，与 Retry-After 那两形。
// W34 实测到三件事：① 第 ⑧ 步只报"读回 384 字节"，而那是过网线的字节 —— 正文其实一个字都没有，
//
//	屏幕上看着就像"它答了"；② 账上 finish 那一格曾被填成我们自己的句子（"只有 reasoning、正文为空"），
//	而那一格署的是**端点说的**收尾原因 —— 替端点编话就是这一族最贵的错；
//
// ③ Retry-After 永远记 absent（"这一版没解析"），于是"对端明明说了要等 7 秒"在账上长成"没说"。
func TestReasoningOnlyAndRetryAfterShapes(t *testing.T) {
	旧落了, 旧接缝 := procLanded, seam
	defer func() { procLanded, seam = 旧落了, 旧接缝 }()

	形 := "正常"
	端 := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		写 := func(行 ...string) {
			w.Header().Set("Content-Type", "text/event-stream")
			w.WriteHeader(200)
			for _, s := range 行 {
				_, _ = w.Write([]byte(s + "\n\n"))
			}
		}
		思 := `data: {"object":"chat.completion.chunk","choices":[{"delta":{"reasoning_content":"想了一大段"}}]}`
		switch 形 {
		case "reasoning有收尾":
			写(思, `data: {"object":"chat.completion.chunk","choices":[{"delta":{},"finish_reason":"length"}],"usage":{"prompt_tokens":11,"completion_tokens":0,"total_tokens":11}}`, "data: [DONE]")
		case "reasoning无收尾":
			写(思, "data: [DONE]")
		case "429带等待":
			w.Header().Set("Retry-After", "7")
			w.WriteHeader(429)
			_, _ = w.Write([]byte(`{"error":"rate_limited"}`))
		case "429等待看不懂":
			w.Header().Set("Retry-After", "Wed, 21 Oct 2026 07:00:00 GMT")
			w.WriteHeader(429)
			_, _ = w.Write([]byte(`{"error":"rate_limited"}`))
		default:
			写(`data: {"object":"chat.completion.chunk","choices":[{"delta":{"content":"答了"}}]}`,
				`data: {"object":"chat.completion.chunk","choices":[{"delta":{},"finish_reason":"stop"}]}`, "data: [DONE]")
		}
	}))
	defer 端.Close()
	t.Setenv("PGAGENT_BASE_URL", 端.URL+"/v1")
	t.Setenv("PGAGENT_MODEL", "测试起的端点（不是真模型）")
	installSeam(0, true)
	旧落了 = procLanded
	procLanded = 0

	跑 := func(形状, 会话 string, 号 int) Result {
		形 = 形状
		return runLoop(fixtureDirty, "这段有什么问题", "go", 会话, 号, nop, nil, "")
	}
	找 := func(r Result, 格 string) (string, string, bool) {
		for _, d := range r.Decisions {
			if d.Key == 格 {
				return d.Basis, d.Claim, true
			}
		}
		return "", "", false
	}
	正常 := 跑("正常", "reason-正常", 1)
	有收尾 := 跑("reasoning有收尾", "reason-有收尾", 2)
	无收尾 := 跑("reasoning无收尾", "reason-无收尾", 3)
	等待 := 跑("429带等待", "reason-等待", 4)
	怪等待 := 跑("429等待看不懂", "reason-怪等待", 5)

	档, 话, _ := 找(有收尾, "finish")
	档2, 话2, 有2 := 找(正常, "retry_after_ms")
	档3, 话3, _ := 找(等待, "retry_after_ms")
	档4, 话4, _ := 找(怪等待, "retry_after_ms")
	八有 := lastLine(有收尾.Trace, "gateway")
	八等 := lastLine(等待.Trace, "gateway")
	牙 := []struct {
		名  string
		合  bool
		读数 string
	}{
		{"五发都落了账（失败形也要进账）",
			正常.KPI >= 1 && 有收尾.KPI >= 1 && 无收尾.KPI >= 1 && 等待.KPI >= 1 && 怪等待.KPI >= 1,
			fmt.Sprint(正常.KPI, 有收尾.KPI, 无收尾.KPI, 等待.KPI, 怪等待.KPI)},
		{"只有 reasoning 那一形：第 ⑧ 步说清正文是 0 字（384 字节那种说法不许冒充答案）",
			strings.Contains(八有, "正文 0 字") && strings.Contains(八有, "reasoning"), 八有},
		{"账上 finish 那一格署的是端点原话 length，不是我们填的句子",
			strings.Contains(话, "length") && !strings.Contains(话, "reasoning") && 档 != "", 档 + "｜" + 话},
		{"端点没给 finish_reason 时，那一格不许被我们填话",
			func() bool { _, 话无, _ := 找(无收尾, "finish"); return !strings.Contains(话无, "reasoning") }(),
			"看无收尾那一发的 finish 格"},
		{"正常那一形不读 retry_after_ms（没这回事就别挂成未决）", !有2, 档2 + "｜" + 话2},
		{"429 + Retry-After:7 ⇒ 那一格 measured 7000（对端说了就别记没说）",
			档3 == "measured" && strings.Contains(话3, "7000"), 档3 + "｜" + 话3},
		{"429 + Retry-After:7 ⇒ 值从账上落进结果区那一格",
			等待.Metrics.LedgerRetryAfterMs == 7000 && strings.Contains(等待.Metrics.RetryAfterSource, "响应头"),
			fmt.Sprint(等待.Metrics.LedgerRetryAfterMs, 等待.Metrics.RetryAfterSource)},
		{"第 ⑧ 步把等待话原样带上（7000ms + 原话 7）", strings.Contains(八等, "端点要等 7000ms"), 八等},
		{"Retry-After 是 HTTP-date 那种 ⇒ 记缺席且把原话留在理由里（不猜）",
			档4 == "absent" && strings.Contains(话4, "GMT"), 档4 + "｜" + 话4},
		{"五发五档都不塌", 正常.MixOK && 有收尾.MixOK && 无收尾.MixOK && 等待.MixOK && 怪等待.MixOK,
			fmt.Sprint(正常.Mix, 等待.Mix)},
	}
	没咬住 := []string{}
	for _, x := range 牙 {
		if !x.合 {
			没咬住 = append(没咬住, x.名+"（读数："+clipLine(x.读数)+"）")
		}
	}
	if len(没咬住) > 0 {
		t.Fatalf("reasoning / Retry-After 这两族还有 %d 条没咬住：%v", len(没咬住), 没咬住)
	}
	t.Logf("读数自印：牙 %d 条全咬住 ｜ finish 格=%s｜%s ｜ 等待格=%s｜%s ｜ 正常那发读回 %d 格（无 retry 格）",
		len(牙), 档, 话, 档3, 话3, len(正常.Decisions))
}

// ── 针 41：整列自洽判据本体（traceSane 九条，loop.go:146）───────────────────────
// W32 / W33 / W34 三波各抓到一句假话，形状其实只有一个：同一发里两句话对同一个事实说法不一，
// 或者把「没量／没读／没收到」演成「量到／答了／收完」。三句都单独修过 —— 可「记得住三条」不等于
// 「守得住第四条」，所以把这族矛盾收成一条每发都过的判据，红必须落进读数并上屏。
// 两半缺一不可：只跑甲（真发全过）会把判据写成永远绿；只跑乙（谎发会红）会把判据写成只吃我编的题目。
// 端点脚本在这里另抄一份是有意的：针 39/40 各管自己那一族形状，共用夹具会让"改一处"同时动两卷发。
func TestWholeTraceStaysSelfConsistent(t *testing.T) {
	旧落了, 旧接缝 := procLanded, seam
	defer func() { procLanded, seam = 旧落了, 旧接缝 }()

	形 := "正常"
	端 := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		写 := func(行 ...string) {
			w.Header().Set("Content-Type", "text/event-stream")
			w.WriteHeader(200)
			for _, s := range 行 {
				_, _ = w.Write([]byte(s + "\n\n"))
			}
		}
		switch 形 {
		case "429":
			w.Header().Set("Retry-After", "7")
			w.WriteHeader(429)
			_, _ = w.Write([]byte(`{"error":"rate_limited"}`))
		case "半路断":
			写(`data: {"object":"chat.completion.chunk","choices":[{"delta":{"content":"head"}}]}`,
				`data: {"choices":[{"delta":{"content":`)
		case "不回":
			time.Sleep(4300 * time.Millisecond) // 越过网关那 4s 超时 ⇒ transport 那一形
			写(`data: {"object":"chat.completion.chunk","choices":[{"delta":{"content":"来晚了"},"finish_reason":"stop"}]}`,
				"data: [DONE]")
		case "只有reasoning":
			写(`data: {"object":"chat.completion.chunk","choices":[{"delta":{"reasoning_content":"想了一大段"}}]}`,
				`data: {"object":"chat.completion.chunk","choices":[{"delta":{},"finish_reason":"stop"}]}`,
				"data: [DONE]")
		default:
			写(`data: {"object":"chat.completion.chunk","choices":[{"delta":{"content":"答了"},"finish_reason":"stop"}]}`,
				"data: [DONE]")
		}
	}))
	defer 端.Close()
	t.Setenv("PGAGENT_BASE_URL", 端.URL+"/v1")
	t.Setenv("PGAGENT_MODEL", "自洽针的端点（不是真模型）")
	procLanded = 0

	大 := fixtureDirty + strings.Repeat("// 填充一行给预算看 ", 4000)
	网 := func(形状, 会话 string, 号 int) func() Result {
		return func() Result {
			形 = 形状
			installSeam(0, true)
			return runLoop(fixtureDirty, "这段有什么问题", "go", 会话, 号, nop, nil, "")
		}
	}
	甲 := []struct {
		名 string
		跑 func() Result
	}{
		{"没接缝", func() Result {
			seam = nil
			return runLoop(fixtureDirty, "这段有什么问题", "go", "自洽-没接缝", 1, nop, nil, "")
		}},
		{"落账", func() Result {
			installSeam(0, true)
			return runLoop(fixtureDirty, "这段有什么问题", "go", "自洽-落账", 2, nop, nil, "")
		}},
		{"反臂", func() Result {
			installSeam(0, false)
			return runLoop(fixtureDirty, "这段有什么问题", "go", "自洽-反臂", 3, nop, nil, "")
		}},
		{"账满", func() Result {
			installSeam(49, true)
			_ = runLoop(fixtureDirty, "这段有什么问题", "go", "自洽-账满", 4, nop, nil, "")
			二发 := runLoop(fixtureDirty, "这段有什么问题", "go", "自洽-账满", 5, nop, nil, "")
			if 二发.LedgerReject == "" {
				t.Fatal("账满那一形没造出现场（LedgerReject 空）⇒ 底子不发，甲乙两半都成空转")
			}
			return 二发
		}},
		{"超额度", func() Result {
			installSeam(0, true)
			return runLoop(大, "这段有什么问题", "go", "自洽-超额度", 6, nop, nil, "")
		}},
		{"早停", func() Result {
			seam = nil
			断 := make(chan struct{})
			close(断)
			return runLoop(fixtureDirty, "这段有什么问题", "go", "自洽-早停", 7, nop, 断, "")
		}},
		{"账后打断", func() Result {
			installSeam(0, true)
			断 := make(chan struct{})
			关 := false
			发 := func(s Step) {
				if s.Name == "kernel.read_back" && !关 {
					关 = true
					close(断)
				}
			}
			return runLoop(fixtureDirty, "这段有什么问题", "go", "自洽-账后打断", 8, 发, 断, "")
		}},
		{"网关-正常", 网("正常", "自洽-网关正常", 9)},
		{"网关-429", 网("429", "自洽-网关429", 10)},
		{"网关-半路断", 网("半路断", "自洽-网关半路断", 11)},
		{"网关-不回", 网("不回", "自洽-网关不回", 12)},
		{"网关-只有reasoning", 网("只有reasoning", "自洽-网关reasoning", 13)},
		{"带栈的Go", func() Result {
			installSeam(0, true)
			return runLoop(fixtureDirty, "这里为什么崩", "go", "自洽-带栈", 14, nop, nil, fixtureStack)
		}},
		{"降档的Python", func() Result {
			installSeam(0, true)
			return runLoop(fixturePyRich, "这段有什么问题", "python", "自洽-降档", 15, nop, nil, "")
		}},
	}
	发 := map[string]Result{}
	红甲 := []string{}
	for _, x := range 甲 {
		r := x.跑()
		发[x.名] = r
		合, 话 := traceSane(r)
		if !合 {
			红甲 = append(红甲, x.名+" ⇒ "+strings.Join(话, " ∥ "))
		}
		// 判据必须跟着产物走：上屏那格与当场重算不一致，说明有一处是硬写的绿。
		if r.TraceSane != 合 {
			红甲 = append(红甲, fmt.Sprintf("%s ⇒ 上屏 trace_sane=%v，判据当场重算=%v（有一处是硬写的）", x.名, r.TraceSane, 合))
		}
		if 合 && strings.TrimSpace(r.TraceSaneWhy) == "" {
			红甲 = append(红甲, x.名+" ⇒ 判据过了却没留读数（过与不过都得写在脸上）")
		}
	}
	if len(红甲) > 0 {
		t.Fatalf("甲半边：%d/%d 发真读数没过自洽判据：%v", len(红甲), len(甲), 红甲)
	}

	// 乙：在**甲的真读数**上只改一处，每条必须咬住指名的那条规则。
	// 底子先自证是过的 —— 底子本来就红，"谎发会红"就一句都没证明。
	型 := []struct {
		名 string // 与 loop.go 里 咬() 的第一参数一字不差
		底 string
		改 func(*Result) string
	}{
		{"谁拒的没对上", "账满", func(r *Result) string {
			s := "没落账（第 ⑤ 步预检就拒了 ⇒ 一条都不该写）"
			if !改步骤(r, "kernel.record_call", func(x *Step) { x.Summary = s }) {
				return ""
			}
			return s
		}},
		{"缺席没理由", "落账", func(r *Result) string {
			if !改步骤(r, "kernel.read_back", func(x *Step) { x.Summary = "没读回："; x.Run = false }) {
				return ""
			}
			return "没读回："
		}},
		{"0帧没来历", "网关-429", func(r *Result) string {
			换 := strings.NewReplacer("没读", "未取", "没收到", "未收到过")
			s := ""
			ok := 改步骤(r, "gateway", func(x *Step) { x.Summary = 换.Replace(x.Summary); s = x.Summary })
			if !ok {
				return ""
			}
			return s
		}},
		{"空正文装答了", "网关-只有reasoning", func(r *Result) string {
			s := ""
			ok := 改步骤(r, "gateway", func(x *Step) {
				x.Summary = strings.Replace(x.Summary, "正文 0 字", "正文（见下面那栏）", 1)
				s = x.Summary
			})
			if !ok {
				return ""
			}
			return s
		}},
		{"一格两数", "落账", func(r *Result) string {
			s := ""
			ok := 改步骤(r, "kernel.read_back", func(x *Step) {
				x.Summary = reReadBack.ReplaceAllString(x.Summary, "读回 99 格，其中 99 格")
				s = x.Summary
			})
			if !ok {
				return ""
			}
			return s
		}},
		{"落了账收口却说没进账", "落账", func(r *Result) string {
			s := "这一步没东西可印：这一发没进账（夹具照抄改前那句写法）"
			if !改步骤(r, "kernel.tally", func(x *Step) { x.Summary = s; x.Run = false }) {
				return ""
			}
			return s
		}},
		{"拒了又说落了", "落账", func(r *Result) string {
			r.LedgerReject = "写入被挡：这本账已到上限（内核原话，抄来当夹具）"
			return r.LedgerReject
		}},
		{"没量写成measured", "网关-429", func(r *Result) string {
			r.Decisions = append(r.Decisions, Decision{
				Key: "chunks", Side: "output", Basis: "measured", Claim: "0",
				Effect: "把「正文没读」演成「量到 0 帧」",
			})
			return "chunks measured(0)"
		}},
		{"落了账却说没落", "落账", func(r *Result) string {
			s := "这一发压根没落账 ⇒ 内核那边没有五档（夹具照抄改前那句写法）"
			r.Unknowns = append(r.Unknowns, Unknown{What: "针 41 的夹具", WhyAbsent: s, HowToGet: "看第 ⑥ 步", Basis: Absent})
			return s
		}},
		{"自洽句自己数错了步", "落账", func(r *Result) string {
			r.TraceSaneWhy = "整列 99 步自洽（夹具：把步数喊成另一个数）"
			return r.TraceSaneWhy
		}},
		{"执行了用户代码", "落账", func(r *Result) string {
			r.Executed = true
			return "code_executed=true"
		}},
	}
	// 规则清单与夹具必须双向对得上：清单里有名却没配臂 = 那条判据从没被证明会红；
	// 臂里的名不在清单上 = 判据夹带（traceSane 的 咬() 会把它自己记成一条红）。
	在名 := map[string]bool{}
	for _, 名 := range traceSane规则 {
		在名[名] = true
	}
	配臂 := map[string]int{}
	for _, x := range 型 {
		配臂[x.名]++
	}
	没配臂, 夹带 := []string{}, []string{}
	for _, 名 := range traceSane规则 {
		if 配臂[名] == 0 {
			没配臂 = append(没配臂, 名)
		}
	}
	for _, x := range 型 {
		if !在名[x.名] {
			夹带 = append(夹带, x.名)
		}
	}
	if len(没配臂) > 0 || len(夹带) > 0 {
		t.Fatalf("判据 %d 条与夹具 %d 条没配上：漏臂 %v ｜ 夹带 %v", len(traceSane规则), len(型), 没配臂, 夹带)
	}
	红乙 := []string{}
	咬过 := map[string]bool{}
	for _, x := range 型 {
		底子, 有 := 发[x.底]
		if !有 {
			红乙 = append(红乙, x.名+" ⇒ 底子「"+x.底+"」没跑出来（甲半边挂了，这一条无从谈起）")
			continue
		}
		对 := 克隆发(底子)
		if 合, 话 := traceSane(对); !合 {
			红乙 = append(红乙, fmt.Sprintf("%s ⇒ 底子「%s」本身就没过（%v）⇒ 谎发会红这条什么都没证明", x.名, x.底, 话))
			continue
		}
		谎 := 克隆发(底子)
		改后 := x.改(&谎)
		if 改后 == "" {
			红乙 = append(红乙, x.名+" ⇒ 夹具是空的：那一格不在这发的轨迹里，改无可改")
			continue
		}
		合, 话 := traceSane(谎)
		并 := strings.Join(话, " ∥ ")
		if 合 {
			红乙 = append(红乙, x.名+" ⇒ 这句假话没让它红（改后："+clipLine(改后)+"）")
		} else if !strings.Contains(并, x.名) {
			红乙 = append(红乙, x.名+" ⇒ 红了，响的却是指名之外的那条（"+clipLine(并)+"）")
		} else {
			咬过[x.名] = true
		}
	}
	没咬 := []string{}
	for _, x := range 型 {
		if !咬过[x.名] {
			没咬 = append(没咬, x.名)
		}
	}
	if len(红乙) > 0 || len(没咬) > 0 {
		t.Fatalf("乙半边：%d 条谎发有问题（%v）｜该咬住 %d 条、实际点名咬住 %d 条：%v",
			len(红乙), 红乙, len(型), len(咬过), 没咬)
	}

	// 判据的红必须上屏：app.js 里那行没接住 trace_sane，判据就只活在返回值里。
	app, err := os.ReadFile(filepath.Join("web", "app.js"))
	if err != nil {
		t.Fatal(err)
	}
	a := string(app)
	if !strings.Contains(a, "res.trace_sane") || !strings.Contains(a, "res.trace_sane_why") {
		t.Fatal("横幅没接 trace_sane / trace_sane_why ⇒ 判据红了屏幕上看不出来")
	}
	t.Logf("读数自印：甲 %d 发全过 ｜ 乙 %d 条谎发各咬住指名的那条 ｜ 判据规则 %d 条（条条配臂）｜ 上屏接线 2 处",
		len(甲), len(型), len(traceSane规则))
}

// 克隆发 深拷轨迹/读数/网关那三块：夹具改的是拷贝，底子那一发必须留着原样当对照。
func 克隆发(r Result) Result {
	c := r
	c.Trace = append([]Step(nil), r.Trace...)
	c.Decisions = append([]Decision(nil), r.Decisions...)
	if r.Gateway != nil {
		g := *r.Gateway
		c.Gateway = &g
	}
	return c
}

// 改步骤 按步名改一句话；这一步不在列里就返回 false —— 返回 false 的夹具是空的，
// 空夹具会让"这条规则会红"变成一句没量过的好话。
func 改步骤(r *Result, 名 string, 改 func(*Step)) bool {
	for i := range r.Trace {
		if r.Trace[i].Name == 名 {
			改(&r.Trace[i])
			return true
		}
	}
	return false
}
