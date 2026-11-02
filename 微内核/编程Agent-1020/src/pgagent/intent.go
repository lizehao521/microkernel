package main

import (
	"fmt"
	"strings"
	"unicode/utf8"
)

// 问题路由。目标写的是"贴代码 **+ 提问题**"，所以那个问题必须真的改变这一发的输出；
// 不然输入框只是装饰（这一族错法在本项目叫"恒绿的针"：看着有，其实不动）。
//
// 这里用的是**关键词表**，不是模型理解：词表条数、命中的词、命中在第几个字，全部印进读数，
// 谁都能自己复算。真·语义理解属于第 ⑧ 步那条模型路，本机 NOT_RUN —— 不许把关键词说成"看懂了"。

type Intent struct {
	Kind string `json:"kind"`
	Why  string `json:"why"`
}

var intentWords = []struct{ kind, word string }{
	{"调试", "为什么挂"}, {"调试", "为什么"}, {"调试", "报错"}, {"调试", "栈"}, {"调试", "panic"}, {"调试", "traceback"},
	{"调试", "崩"}, {"调试", "返回空"}, {"调试", "偶尔"},
	{"优化", "优化"}, {"优化", "太慢"}, {"优化", "更快"}, {"优化", "性能"}, {"优化", "开销"}, {"优化", "慢"},
	{"解释", "解释"}, {"解释", "干什么"}, {"解释", "什么用"}, {"解释", "看懂"}, {"解释", "讲讲"},
	{"审查", "有什么问题"}, {"审查", "风险"}, {"审查", "bug"}, {"审查", "有没有错"},
}

// 这几族是"改哪一处"的建议与栈的读数：路由要按问题把它们挪到前面。
var optimizeRules = []string{"split-long-function", "handle-dropped-errors", "replace-print-with-logger", "coverage-check"}
var debugRules = []string{"stack-frame", "error-header"}

// intentOf 按**命中个数**投票，不是"第一个命中的词说了算"：
// 「为什么这么慢」同时带调试词（为什么）与优化词（慢）—— 谁赢要说得清，
// 平票就明说平票并退回审查，不许偷偷偏向某一边。
func intentOf(question string) Intent {
	q := strings.ToLower(strings.TrimSpace(question))
	n := len(intentWords)
	if q == "" {
		return Intent{Kind: "未判定", Why: fmt.Sprintf("问题栏是空的 ⇒ 没有可路由的意图，按审查那一套全量给（词表 %d 个词一个都没得匹配）", n)}
	}
	hits := map[string]int{}
	first := map[string]int{}
	kinds := []string{"调试", "优化", "解释", "审查"}
	for _, w := range intentWords {
		if i := strings.Index(q, strings.ToLower(w.word)); i >= 0 {
			hits[w.kind]++
			if _, ok := first[w.kind]; !ok {
				first[w.kind] = utf8.RuneCountInString(q[:i]) + 1
			}
		}
	}
	var parts []string
	best, bestKind, tie := 0, "", 0
	for _, k := range kinds {
		if hits[k] > 0 {
			parts = append(parts, fmt.Sprintf("%s 命中 %d 个词（最早在第 %d 个字）", k, hits[k], first[k]))
		}
		if hits[k] > best {
			best, bestKind, tie = hits[k], k, 0
		} else if hits[k] == best && best > 0 {
			tie++
		}
	}
	why := strings.Join(parts, "；")
	if best == 0 {
		return Intent{Kind: "未判定", Why: fmt.Sprintf("问题里没找到词表里的词（词表 %d 个）⇒ 按审查那一套全量给", n)}
	}
	if tie > 0 {
		return Intent{Kind: "审查", Why: fmt.Sprintf("平票（%s）⇒ 不偷偷偏向哪一边，退回审查全量给；词表共 %d 个词", why, n)}
	}
	return Intent{Kind: bestKind, Why: fmt.Sprintf("%s；词表共 %d 个词，按命中个数投票，这是关键词规则不是模型理解", why, n)}
}

// inRules 是给判据与读数用的成员检查（"第一张卡属不属于建议族"）。
func inRules(list []string, s string) bool {
	for _, x := range list {
		if x == s {
			return true
		}
	}
	return false
}

// prioritize 只改顺序、不改内容：命中的那一族挪到最前，其余保持原序（稳定）。
func prioritize(fs []Finding, kind string) []Finding {
	var want []string
	switch kind {
	case "优化":
		want = optimizeRules
	case "调试":
		want = debugRules
	default:
		return fs
	}
	head := []Finding{}
	tail := []Finding{}
	for _, f := range fs {
		hit := false
		for _, r := range want {
			if f.Rule == r {
				hit = true
			}
		}
		if hit {
			head = append(head, f)
		} else {
			tail = append(tail, f)
		}
	}
	return append(head, tail...)
}

// answerFor 让结论带按问题说不同的话。三件事不许混：
// 这份件量到了什么（measured/estimated）、建议（estimated，判断不是测量）、模型那一层（NOT_RUN）。
func answerFor(it Intent, f []Finding, unknowns int, m Metrics, stackGiven bool) string {
	crit := 0
	for _, x := range f {
		if x.Severity == "critical" {
			crit++
		}
	}
	head := fmt.Sprintf("问题路由=%s（%s）｜", it.Kind, it.Why)
	tail := fmt.Sprintf("命中 %d 条、critical %d 条；每条带出处档与自己数出来的分母；未决 %d 条", len(f), crit, unknowns)
	switch it.Kind {
	case "优化":
		return head + "先看上面挪到最前的那几处建议（都是 estimated：数是真的，建议是判断）；" +
			"运行时没量到 ⇒ 每条都写了怎么复验。" + tail
	case "调试":
		if !stackGiven {
			return head + "这一路要栈：没贴报错/栈 ⇒ 行号映射那格只能是 absent（不是 0、更不是「没有 bug」）；" +
				"能给的只有结构类判据。" + tail
		}
		return head + "栈帧挪到最前（帧→行号一律 estimated：文件名没对上贴进来的代码就没有可核对的对应关系）；" + tail
	case "解释":
		return head + fmt.Sprintf("按解析出的结构说：判为 %s、函数 %d 个、import %d 条（其中 %d 条疑似没用到）；"+
			"这份件不猜业务意图 —— 那是第 ⑧ 步模型的活，本机 NOT_RUN。", m.Lang, m.Funcs, m.Imports, m.UnusedImports) + tail
	default:
		return head + "按审查那一套全量给（没按问题挑过重点）。" + tail
	}
}
