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
		"stop_reason", "stop_why"} {
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
// ② JS 里"解析参数 / 打开提示 / 那句自白"三件必须同时出现（少了自白就是悄悄跑）；
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
	for _, n := range []string{`params.get('run') === '1'`, "a.hidden = false", "不是人点出来的"} {
		if !strings.Contains(js, n) {
			t.Fatalf("app.js 里缺 %q —— 参数解析、打开提示、自白三件少一件，自动跑就成了悄悄跑", n)
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
	runs := 0
	for _, q := range questions {
		for _, st := range stacks {
			for _, fake := range []bool{false, true} {
				runs++
				gatewayFake = fake
				res := runLoop(fixtureDirty, q, "auto", "no-md", runs, nop, nil, st)
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
					t.Fatalf("第 %d 发（问题=%q 有栈=%v 网关=%v）读数里带 markdown 星号，页面会原样印出来：…%s…",
						runs, q, st != "", fake, string(b[lo:hi]))
				}
			}
		}
	}
	// 正对照：这个检查必须抓得住真星号，否则上面 20 发全绿说明不了任何事。
	if strings.Index("带**星号**的读数", "**") < 0 {
		t.Fatal("正对照失效：连手写的 ** 都没扫出来，这个检查是假的")
	}
	t.Logf("读数自印：扫了 %d 发（五种问题 × 有无栈 × 网关开关）⇒ 0 处 markdown 记号；正对照可抓", runs)
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
