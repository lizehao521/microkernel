package main

// 调试那半：把报错/栈指回贴进来的行。
//
// 这台机不执行用户代码 ⇒ 我们**不可能**说"根因找到了"。能做且值得做的是把栈里每一帧
// 落到贴入内容的行号上，并把"文件名没对上"这件事如实标成 estimated ——
// 行号是我们数出来的（measured），"这一帧说的就是你贴的第 12 行"这一步是推断（estimated）。

import (
	"fmt"
	"regexp"
	"strconv"
	"strings"
)

type frame struct {
	File   string
	Line   int
	Symbol string
	Raw    string
}

var (
	goFrame  = regexp.MustCompile(`([\w./\\-]+\.go):(\d+)`)
	pyFrame  = regexp.MustCompile(`File "([^"]+)", line (\d+), in ([\w.<>]+)`)
	jsFrame  = regexp.MustCompile(`at\s+.*?([\w./\\-]+\.(?:js|ts|mjs|cjs)):(\d+):(\d+)`)
	jvFrame  = regexp.MustCompile(`at\s+([\w.$]+)\.([\w<>]+)\(([\w.$]+\.java):(\d+)\)`)
	headRe   = regexp.MustCompile(`(?i)(panic:|fatal error:|runtime error|Traceback \(most recent call last\)|^\s*\w*Error\b|Exception\b|error:)`)
	lineSpan = 2 // 引用上下文各取几行
)

// parseStack 只认四种常见形状。认不出不是「没有报错」，是"这四种格式没命中" —— 后面按这个口径记 absent。
func parseStack(text string) (frames []frame, header string) {
	lines := strings.Split(text, "\n")
	for _, ln := range lines {
		if header == "" && headRe.MatchString(ln) {
			header = clipOne(strings.TrimSpace(ln), 140)
		}
		if m := pyFrame.FindStringSubmatch(ln); m != nil {
			appendFrame(&frames, m[1], m[2], m[3], ln)
			continue
		}
		if m := jvFrame.FindStringSubmatch(ln); m != nil {
			appendFrame(&frames, m[3], m[4], m[1]+"."+m[2], ln)
			continue
		}
		if m := jsFrame.FindStringSubmatch(ln); m != nil {
			appendFrame(&frames, m[1], m[2], "", ln)
			continue
		}
		if m := goFrame.FindStringSubmatch(ln); m != nil {
			appendFrame(&frames, m[1], m[2], "", ln)
		}
	}
	return frames, header
}

func appendFrame(dst *[]frame, file, lineStr, symbol, raw string) {
	n, err := strconv.Atoi(strings.TrimSpace(lineStr))
	if err != nil || n <= 0 {
		return
	}
	*dst = append(*dst, frame{File: file, Line: n, Symbol: symbol, Raw: clipOne(strings.TrimSpace(raw), 160)})
}

func clipOne(s string, n int) string {
	if len(s) > n {
		return s[:n] + "…"
	}
	return s
}

// debugFindings 把栈与贴入的代码对起来。codeLines 是贴入内容按行切开（1 起）。
func debugFindings(stack string, codeLines []string) ([]Finding, []Unknown, int, int) {
	frames, header := parseStack(stack)
	fs := []Finding{}
	un := []Unknown{}
	if header != "" {
		fs = append(fs, Finding{
			ID: "S0", Rule: "error-header", Severity: "major",
			Evidence: fmt.Sprintf("扫了 %d 行栈文本，第一个像报错抬头的是：%q", len(strings.Split(stack, "\n")), header),
			Basis:    Measured,
			Claim:    "这是复现线索的原文，不是诊断 —— 没执行代码，就不许说原因已经找到",
			Verify:   "把这一段和最小复现一起再发一发；或贴出触发它的那几行调用方代码",
		})
	}
	inRange := 0
	for i, f := range frames {
		if f.Line < 1 || f.Line > len(codeLines) {
			continue
		}
		inRange++
		lo, hi := f.Line-lineSpan, f.Line+lineSpan
		if lo < 1 {
			lo = 1
		}
		if hi > len(codeLines) {
			hi = len(codeLines)
		}
		var ctx []string
		for l := lo; l <= hi; l++ {
			ctx = append(ctx, fmt.Sprintf("%d| %s", l, strings.TrimSpace(codeLines[l-1])))
		}
		fs = append(fs, Finding{
			ID:   fmt.Sprintf("F%d", i+1),
			Rule: "stack-frame", Severity: "critical",
			Where: Where{Lines: [2]int{f.Line, f.Line}, Symbol: f.File},
			Evidence: fmt.Sprintf("第 %d/%d 帧 %s；落进贴入范围的帧共 %d 个（栈里一共 %d 个）；上下文：%s",
				i+1, len(frames), f.Raw, inRange, len(frames), strings.Join(ctx, " ⏎ ")),
			Basis: Estimated,
			Claim: fmt.Sprintf("这一行最值得先看。注意：贴进来的内容里没有文件名可对照（帧里的 %s 对不上任何声明），"+
				"所以「指到第 %d 行」是推断出来的，不是核对过的事实", f.File, f.Line),
			Fix: &Fix{Patch: "", Rationale: "先确认这一行真的会走到（栈与代码对得上吗）；对不上就去看上一帧",
				Risk: "按行号改可能改到另一份文件 —— 同一行号在两处出现是常见的假阳性"},
			Verify: "把整个文件贴进来（或贴文件名），让行号映射从 estimated 升成 measured",
		})
	}
	if len(frames) == 0 {
		un = append(un, Unknown{
			What: "栈帧 → 行号", WhyAbsent: "这段栈文本里没认出任何一帧（试了 Go / Python / JS / Java 四种常见形状）—— 不是「没有报错」，是这四种格式没命中",
			HowToGet: "原样贴终端输出（别只贴截图里的中文提示），或告诉我是哪种运行时的格式", Basis: Absent,
		})
	} else if inRange == 0 {
		un = append(un, Unknown{
			What: "栈帧 → 行号", WhyAbsent: fmt.Sprintf("认出 %d 帧，但没有一帧的行号落在贴入的 %d 行之内 —— 十有八九是贴的代码不是栈指的那个文件", len(frames), len(codeLines)),
			HowToGet: "把栈里那个文件的内容贴进来（行号能对上才有意义）", Basis: Absent,
		})
	}
	return fs, un, inRange, len(frames)
}

// optimize 把度量换成"改哪一处 + 为什么 + 改完怎么验"。
// 出处一律 estimated：数是量到的，**建议是判断**，把判断署成 measured 就是越权。
func optimize(m Metrics) ([]Finding, []Unknown) {
	out := []Finding{}
	add := func(rule, sev, evidence, claim, how, verify string) {
		out = append(out, Finding{
			Rule: rule, Severity: sev, Evidence: evidence, Basis: Estimated,
			Claim: claim, Fix: &Fix{Patch: "", Rationale: how, Risk: "建议不是补丁：动手前自己看一遍上下文"}, Verify: verify,
		})
	}
	if m.MaxFunc > 60 {
		add("split-long-function", "major",
			fmt.Sprintf("最长函数 %d 行（阈值 60）；本段共 %d 个函数", m.MaxFunc, m.Funcs),
			"一处要同时决定太多事 ⇒ 改对了没人能验", "按「做什么」切块，先切出能单独验的那半",
			"复跑本件，max_func_lines 应降到 60 以下")
	}
	if m.BlankErrs > 0 {
		add("handle-dropped-errors", "critical",
			fmt.Sprintf("%d 处把返回值丢给 _", m.BlankErrs),
			"失败变成零值返回 ⇒ 上层只看到东西是空的", "逐处决定：上抛、降级，还是记一笔并给默认值",
			"复跑本件 ignored_error_sites 应为 0")
	}
	if m.PrintCalls > 0 {
		add("replace-print-with-logger", "minor",
			fmt.Sprintf("%d 处 fmt.Print*/println", m.PrintCalls),
			"输出进不了任何地方，也没有级别", "换 log 或结构化输出，带上能归因的字段",
			"复跑本件 print_calls 归零")
	}
	if m.Lines > 0 && m.Funcs > 0 && m.MaxFunc*3 < m.Lines {
		add("coverage-check", "cosmetic",
			fmt.Sprintf("整段 %d 行里最长函数只占 %d 行（<1/3）", m.Lines, m.MaxFunc),
			"函数都不长 ⇒ 若还有难改的地方，多半在函数之间的接线处",
			"看导入集合与调用点是否重复；不是必改项", "复跑本件，看 nesting 与 dup 类判据是否也干净")
	}
	if len(out) == 0 {
		return out, []Unknown{{
			What: "优化建议", WhyAbsent: "这几把尺子（长度、丢错、print、嵌套、重名）今天都没量到东西 —— 不等于代码好，只等于这几条量不到",
			HowToGet: "贴更多上下文（调用方、基准测试、真实负载），或批准在临时目录跑一次拿实测数据", Basis: Absent,
		}}
	}
	return out, nil
}
