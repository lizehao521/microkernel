package main

// W7：非 Go 语言的保守降档件。
//
// 三条写死的规矩：
//  1. 这里**没有** Python/JS 的解析器，只有逐行文本匹配 ⇒ 每条命中的出处一律 estimated，
//     一条都不许署 measured（署错了就是把"我猜的"写成"我量到的"）。
//  2. 判据只说"这条形状通常为什么糟" + "怎么自己复验"，不说"这段有 bug"。
//  3. 语言判定本身也要能追溯：`auto` 那一路是**嗅探**（estimated 的推断），
//     用户在界面上选定了语言才算数出来的；两条都写在读数里，不许事后混为一谈。

import (
	"fmt"
	"regexp"
	"strings"
)

type langSniff struct {
	lang   string
	marks  []*regexp.Regexp
	counts []*regexp.Regexp // 按命中条数加权的标记
}

var sniffs = []langSniff{
	{
		lang:   "python",
		marks:  []*regexp.Regexp{re(`^\s*(?:from\s+[\w.]+\s+)?import\s+\w+`), re(`:\s*$`), re(`^\s*(?:elif|lambda|with\s+\w)`), re(`__name__\s*==`)},
		counts: []*regexp.Regexp{re(`^\s*def\s+\w+\s*\(`), re(`^\s*except\b`), re(`\bprint\(`)},
	},
	{
		lang: "javascript",
		marks: []*regexp.Regexp{re(`=>`), re(`\bfunction\s*\(`), re(`\bconsole\.\w+\(`), re(`^\s*(?:export\s+)?(?:const|let)\s+\w+\s*=`),
			re(`\brequire\(['"]`)},
		counts: []*regexp.Regexp{re(`;\s*$`), re(`\bvar\s+\w+`), re(`\bawait\s+`)},
	},
	{
		lang:   "go",
		marks:  []*regexp.Regexp{re(`^\s*package\s+\w+`), re(`^\s*(?:import\s+\(|\w+\s*:=)`), re(`^\s*func\s+[\w()]+\s*[\w*\[\]]+\s*\{`)},
		counts: []*regexp.Regexp{re(`\bfunc\s+\w+\(`), re(`^\s*var\s+\w+`)},
	},
}

// sniffLang 只给"最像什么 + 凭什么"，不给事实。定不下来就回 unknown（并让调用方记一条 absent）。
func sniffLang(code string) (string, string) {
	best, bestScore := "unknown", 0
	why := ""
	for _, s := range sniffs {
		score := 0
		var hit []string
		for _, m := range s.marks {
			if m.MatchString(code) {
				score++
				hit = append(hit, m.String())
			}
		}
		for _, c := range s.counts {
			if n := len(c.FindAllString(code, -1)); n > 0 {
				score += n
				hit = append(hit, fmt.Sprintf("%s×%d", c.String(), n))
			}
		}
		if score > bestScore {
			best, bestScore = s.lang, score
			why = strings.Join(hit, "、")
		}
	}
	return best, fmt.Sprintf("得分 %d；命中 %s", bestScore, orNone(why))
}

func orNone(s string) string {
	if s == "" {
		return "没有可用标记"
	}
	return s
}

func re(p string) *regexp.Regexp { return regexp.MustCompile(p) }

// —— 各语言的保守判据 ——

var (
	pyBareExcept = re(`^\s*except\s*:\s*$`)
	pyDefLine    = re(`^\s*def\s+(\w+)\s*\(`)
	pyMutableDef = re(`^\s*def\s+\w+\s*\([^)]*=\s*(?:\[\]|\{\})`)
	pyPrint      = re(`^\s*print\s*\(`)
	pyNoneEq     = re(`[!=]=\s*None\b`)

	jsEval    = re(`\beval\s*\(|new\s+Function\s*\(`)
	jsDebug   = re(`^\s*debugger\s*[;{]`)
	jsConsole = re(`\bconsole\.(log|debug|info)\s*\(`)
	jsVar     = re(`^\s*var\s+\w+`)

	todoRe    = re(`\b(?:TODO|FIXME|XXX|HACK)\b`)
	secretRe  = re(`(?i)\b(api[_-]?key|secret|token|password|passwd|access[_-]?key|private[_-]?key)\b["']?\s*[:=]\s*["']([^"']{8,})["']`)
	catchRe   = re(`^\s*\}\s*catch\s*\([^)]*\)\s*\{\s*\}$`)
	jsCatchOp = re(`\bcatch\s*\([^)]*\)\s*\{\s*$`)
)

// hasLooseEq / hasLooseNe：Go 的 regexp 是 RE2，没有前视/后视 ⇒ `==` 与 `===` 的区分只能自己扫字节。
// （第一版我写成"前面不许是空格"的字符类，结果 `row.id == 3` 这种最常态的写法扫不出来 —— 那是假绿。）
func hasLooseEq(s string) bool {
	for i := 0; i+1 < len(s); i++ {
		if s[i] == '=' && s[i+1] == '=' {
			p, n := byteAt(s, i-1), byteAt(s, i+2)
			if p != '=' && p != '!' && p != '<' && p != '>' && n != '=' {
				return true
			}
			i++
		}
	}
	return false
}

func hasLooseNe(s string) bool {
	for i := 0; i+1 < len(s); i++ {
		if s[i] == '!' && s[i+1] == '=' {
			if byteAt(s, i+2) != '=' {
				return true
			}
			i++
		}
	}
	return false
}

// byteAt 越界时回空格：行首/行尾按"没有相邻符号"处理，而不是 panic。
func byteAt(s string, i int) byte {
	if i < 0 || i >= len(s) {
		return ' '
	}
	return s[i]
}

func (a *Analysis) textRules(code, lang string) {
	lines := strings.Split(code, "\n")
	add := func(rule, sev string, lo, hi int, ev, claim, how, risk, verify string) {
		a.Findings = append(a.Findings, Finding{
			Rule: rule, Severity: sev, Where: Where{Lines: [2]int{lo, hi}},
			Evidence: ev, Basis: Estimated, Claim: claim,
			Fix: &Fix{Patch: "", Rationale: how, Risk: risk}, Verify: verify,
		})
	}

	switch lang {
	case "python":
		for i, s := range lines {
			t := strings.TrimSpace(s)
			if pyBareExcept.MatchString(t) {
				add("bare-except", "critical", i+1, i+1,
					"第 "+fmt.Sprint(i+1)+" 行是光秃秃的 except:（没写异常类型）",
					"裸 except 连 SystemExit / KeyboardInterrupt 一起吞 ⇒ Ctrl-C 停不住、初始化失败也看不见",
					"写成 except 具体异常类型；实在要兜底就记一笔再抛", "改窄可能让原本被吞的失败浮出来",
					"复跑本件：bare-except 应为 0；或跑 ruff E722（本件不代跑）")
			}
			if i+1 < len(lines) && strings.HasPrefix(t, "except") && strings.TrimSpace(lines[i+1]) == "pass" {
				add("except-pass", "critical", i+1, i+2,
					fmt.Sprintf("第 %d 行 except 之后紧跟 pass（文本级匹配，没解析语法树）", i+1),
					"异常被吞 ⇒ 失败变成静悄悄，上层只看到东西是空的",
					"要么处理、要么记一笔再抛；pass 两者都不是", "低",
					"换成显式记一笔后再复跑本件")
			}
			if pyMutableDef.MatchString(t) {
				add("mutable-default-arg", "major", i+1, i+1,
					"第 "+fmt.Sprint(i+1)+" 行的默认参数是 [] 或 {}（跨行 def 不判）",
					"Python 的默认值是共享对象（同一个 list/dict）：多次调用会在同一份 list/dict 上累积，症状是「偶尔多一条」",
					"默认写 None，函数体内 `if x is None: x = []`", "改了签名要一起看调用点",
					"连调两次同一函数，看第二次进来时那个参数是不是空的")
			}
			if pyNoneEq.MatchString(t) {
				add("none-compare", "minor", i+1, i+1,
					"第 "+fmt.Sprint(i+1)+" 行用 == / != 比 None",
					"None 是单例，`is` 才是本意；`==` 会被自定义 __eq__ 改写 ⇒ 判定跟着变味",
					"改成 is / is not", "低", "复跑本件：none-compare 应为 0")
			}
			if m := pyDefLine.FindStringSubmatch(t); m != nil {
				if span, ok := pyBlockSpan(lines, i); ok {
					if span > a.Metrics.MaxFunc {
						a.Metrics.MaxFunc = span
					}
					if span > 60 {
						add("long-def", "major", i+1, i+1+span,
							fmt.Sprintf("函数 %s 按缩进量出跨 %d 行（阈值 60；缩进不是语法树，可能算错）", m[1], span),
							"一处要同时改的事太多 ⇒ 改对了也没人能证",
							"按「做什么」切块，先切出能单独验的那半", "切分本身不改行为；验法是切完指标不劣化",
							"复跑本件 max_func_lines 落到阈值下")
					}
				}
			}
			if pyPrint.MatchString(t) {
				a.Metrics.PrintCalls++
				add("print-as-log", "minor", i+1, i+1,
					"第 "+fmt.Sprint(i+1)+" 行是 print(...)（本文件数到第 "+fmt.Sprint(a.Metrics.PrintCalls)+" 处）",
					"输出走 stdout ⇒ 生产里进不了任何日志管道，也没有级别",
					"换 logging 或结构化输出，带上能归因的字段", "注意别把数据打进日志",
					"复跑本件 print_calls 归零")
			}
		}
		a.unusedImportHint(lines, `^\s*import\s+(\w+)`, `^\s*from\s+[\w.]+\s+import\s+(\w+)`)

	case "javascript", "typescript":
		for i, s := range lines {
			t := strings.TrimSpace(s)
			if hasLooseEq(s) || hasLooseNe(s) {
				add("loose-equality", "major", i+1, i+1,
					"第 "+fmt.Sprint(i+1)+" 行用了 == 或 !=（不是 === / !==）",
					"松散相等会做隐式转换：`0 == ''`、`null == undefined` 都为真 ⇒ 判定跟类型走，不跟值走",
					"换 === / !==；需要判空就写 `x == null` 并注释这一处是故意的",
					"少数地方本来就是想靠隐式转换，改严会暴露出原本就错的条件",
					"复跑本件该行为 0；或跑 eslint eqeqeq（本件不代跑）")
			}
			if jsEval.MatchString(s) {
				add("eval-or-new-function", "critical", i+1, i+1,
					"第 "+fmt.Sprint(i+1)+" 行出现 eval( 或 new Function(",
					"把字符串当代码执行 ⇒ 任何能进到这里的字符串都拿到了执行权。这一格只说形状，不声称已经被人利用",
					"换成数据驱动（表、映射、白名单）；非要解析就用 JSON.parse",
					"改写会碰到调用方，别顺手删",
					"grep 一次这个调用点还在不在；再看数据从哪来")
			}
			if jsDebug.MatchString(t) {
				add("debugger-left", "major", i+1, i+1,
					"第 "+fmt.Sprint(i+1)+" 行是 debugger 语句",
					"线上带着 debugger ⇒ 打开 devtools 的人会把流程停在这一点；它是没删干净的现场，不是注释",
					"删掉，或包进只在本地构建里保留的分支", "低", "复跑本件：debugger-left 应为 0")
			}
			if jsConsole.MatchString(s) {
				a.Metrics.PrintCalls++
				add("console-log", "minor", i+1, i+1,
					"第 "+fmt.Sprint(i+1)+" 行是 console.*（本文件数到第 "+fmt.Sprint(a.Metrics.PrintCalls)+" 处）",
					"控制台输出在生产抓不到，而且容易顺手把用户数据打出去",
					"换有级别的 logger，字段化输出", "低", "复跑本件 print_calls 归零")
			}
			if jsVar.MatchString(t) {
				add("var-left", "cosmetic", i+1, i+1,
					"第 "+fmt.Sprint(i+1)+" 行还在用 var",
					"var 是函数作用域且会提升 ⇒ 块内的同名变量其实在块外也能看见，这类 bug 长得像「值莫名其妙被改了」",
					"换 let（要重赋值）或 const", "改 const 后要确认没有再赋值的地方",
					"复跑本件：var-left 应为 0")
			}
			if catchRe.MatchString(t) {
				add("empty-catch", "critical", i+1, i+1,
					"第 "+fmt.Sprint(i+1)+" 行 catch 的块里 0 条语句",
					"看见异常然后什么都不做 —— 比没看见更难查（错误到此为止，没有痕迹）",
					"要么处理，要么带上下文记一笔；空 catch 两者都不是", "低",
					"复跑本件：empty-catch 应为 0")
			} else if jsCatchOp.MatchString(t) {
				// 多行写法：下一行就是 } ⇒ 也是空的
				for j := i + 1; j < len(lines) && j <= i+2; j++ {
					if strings.TrimSpace(lines[j]) == "}" {
						add("empty-catch", "critical", i+1, j+1,
							fmt.Sprintf("第 %d 行 catch 打开、第 %d 行就闭合并中间 0 条语句", i+1, j+1),
							"看见异常然后什么都不做 —— 比没看见更难查",
							"要么处理，要么带上下文记一笔", "低", "复跑本件：empty-catch 应为 0")
						break
					}
				}
			}
		}
		a.unusedImportHint(lines, jsImportES, jsImportRequire)

	case "go":
		// Go 的专属判据在 AST 那一族（goRules）；走到这里说明没解析过 ⇒ 只跑通用两族，
		// "AST 没跑"这件事由 analyze() 记 absent，不在这里重复说一遍（一处两数是假绿的入口）。
	default:
		// 语言定不下来：只跑通用判据，并且明确说"这一路按什么规则扫的"没说清就是缺口
		a.Unknowns = append(a.Unknowns, Unknown{
			What: "语言专属判据（Python / JS 那一族）",
			WhyAbsent: fmt.Sprintf("语言没定下来（%s）⇒ 只跑通用两族（TODO、看起来像口令的硬编码）；"+
				"不许把「专属判据没命中」读成「这段没问题」", a.Metrics.LangWhy),
			HowToGet: "在界面上的「语言」下拉里显式选一个；或把文件后缀/入口语句一起贴进来",
			Basis:    Absent,
		})
	}

	// 通用：任何语言都扫这两族。
	for i, s := range lines {
		if todoRe.MatchString(s) {
			add("todo-left", "cosmetic", i+1, i+1,
				"第 "+fmt.Sprint(i+1)+" 行有 TODO/FIXME 残留",
				"写着「回头再说」的地方，回头通常没人知道要不要紧",
				"删掉，或变成有归属的条目", "低", "复跑本件：todo-left 应为 0")
		}
		if m := secretRe.FindStringSubmatch(s); m != nil {
			// 命中的值本身**不进读数**：把口令前缀抄进卡片/账本，是这条项目点过三次名的一族错误。
			add("hardcoded-secret(maybe)", "critical", i+1, i+1,
				fmt.Sprintf("第 %d 行有个看起来被硬编码的敏感值：键名 %q、值 %d 个字符（值没抄到这里，也不进日志与账本）",
					i+1, strings.ToLower(m[1]), len(m[2])),
				"命中只是线索：可能是测试夹具或占位符；不能写成「已泄露」，也不能反过来写成「没问题」",
				"是人眼确认一次：真口令 ⇒ 旋转它并改走环境变量（这是动作，扫描替你决定不了）",
				"改走 env 会让依赖它的测试挂掉，要一起改",
				"确认它是真值还是夹具；要查历史泄露用 git-secrets / trufflehog（本件不代跑）")
		}
	}
}

const (
	jsImportES      = `^\s*import\s+(\w+)\s+from`
	jsImportRequire = `const\s+(\w+)\s*=\s*require\(`
)

// unusedImportHint：文本级"这个名字除了那行 import 之外没出现过"。
// 没建作用域信息 ⇒ 一律 maybe，且只作线索。
func (a *Analysis) unusedImportHint(lines []string, pats ...string) {
	for _, pat := range pats {
		r := re(pat)
		for i, s := range lines {
			m := r.FindStringSubmatch(s)
			if m == nil {
				continue
			}
			name := m[1]
			if name == "" {
				continue
			}
			used := 0
			for j, o := range lines {
				if j == i {
					continue
				}
				used += len(re(`\b`+name+`\b`).FindAllString(o, -1))
			}
			if used == 0 {
				a.Metrics.UnusedImports++
				a.Findings = append(a.Findings, Finding{
					Rule: "unused-import(maybe)", Severity: "minor",
					Where: Where{Lines: [2]int{i + 1, i + 1}, Symbol: name},
					Evidence: fmt.Sprintf("第 %d 行导入 %s，之后整份文件再没出现过这个名字（文本级，没建作用域信息）",
						i+1, name),
					Basis:  Estimated,
					Claim:  "可能未使用；也可能只在字符串、注释或动态取值里被用到 —— 那种用法本件看不见",
					Fix:    &Fix{Patch: "", Rationale: "删之前先让该语言的官方检查看一眼", Risk: "低；删错会直接改行为"},
					Verify: fmt.Sprintf("%s 那条工具说了算：Python 用 pyflakes，JS 用 eslint no-unused-vars（本件不代跑）", name),
				})
			}
		}
	}
}

// pyBlockSpan：从 def 那一行往下，按缩进找块尾。**没有语法树**，所以：
// 返回 ok=false 就什么都不说；算出来的跨度只当线索（estimated）。
func pyBlockSpan(lines []string, i int) (int, bool) {
	ind := indentOf(lines[i])
	if ind < 0 {
		return 0, false
	}
	end := i
	for j := i + 1; j < len(lines); j++ {
		t := lines[j]
		if strings.TrimSpace(t) == "" {
			continue
		}
		if indentOf(t) <= ind {
			break
		}
		end = j
	}
	if end <= i {
		return 0, false
	}
	return end - i, true
}

func indentOf(s string) int {
	n := 0
	for _, c := range s {
		if c == ' ' {
			n++
		} else if c == '\t' {
			n += 4
		} else {
			break
		}
	}
	return n
}

// familiesFor 是"这一发到底武装了哪几族尺子"的清单 —— 第 ③ 步念的就是它，
// 族数从清单来（不是手写常量），否则清单改了数还没改，又是一处一格两数。
func familiesFor(lang string, parsed bool) (string, int) {
	switch lang {
	case "go":
		if parsed {
			return "go:ast(long-function,dup-name-same-scope,dup-func-name,ignore-error,empty-err-block," +
				"print-as-log,deep-nesting,unused-import(maybe))", 8
		}
		return "go:AST 没跑成 ⇒ 专属判据这一族整族缺席", 0
	case "python":
		return "python:text(bare-except,except-pass,mutable-default-arg,none-compare,long-def," +
			"print-as-log,unused-import(maybe))", 7
	case "javascript", "typescript":
		return "js:text(loose-equality,empty-catch,eval-or-new-function,debugger-left,console-log," +
			"var-left,unused-import(maybe))", 7
	default:
		return "unknown:语言没定下来 ⇒ 只跑通用那一族", 0
	}
}
