package main

import (
	"crypto/sha256"
	"fmt"
	"go/ast"
	"go/parser"
	"go/token"
	"path"
	"regexp"
	"strconv"
	"strings"
)

// 分析件只有一条铁律：读字节、解析 AST，**不执行代码**。
// 这里没有任何 os/exec，也没有把用户代码引进本进程的路径 —— 安全针在 pgagent_test.go 的「针 4」盯着这件事。

type Analysis struct {
	Metrics  Metrics
	Findings []Finding
	Unknowns []Unknown
}

func analyze(code, wantLang string) Analysis {
	var a Analysis
	// 空数组而不是 nil：nil 会序列化成 null，前端就得靠运气才知道"0 条"和"没这个字段"是两件事。
	a.Findings = []Finding{}
	a.Unknowns = []Unknown{}
	a.Metrics.Bytes = len([]byte(code))
	a.Metrics.Lines = strings.Count(code, "\n") + 1
	a.Metrics.SHA256 = fmt.Sprintf("%x", sha256.Sum256([]byte(code)))[:16]

	lang, parsed, fset, file := parseGo(code)
	how, why := "", ""
	switch {
	case wantLang != "" && wantLang != "auto":
		lang, how, why = wantLang, "用户显式选定", "没嗅探（界面上选了语言，判定就不靠猜）"
	case parsed:
		how, why = "Go 语法树解析过了", "这是硬证据，不是猜的"
	default:
		sn, w := sniffLang(code)
		why = w
		if sn == "unknown" {
			lang, how = "unknown", "嗅探没有可用标记"
		} else {
			lang, how = sn, "嗅探推断（不是解析出来的）"
		}
	}
	a.Metrics.Lang = lang
	a.Metrics.LangHow = how
	a.Metrics.LangWhy = why
	a.Metrics.Parsed = parsed

	switch {
	case lang == "go" && parsed:
		a.Metrics.Imports = len(file.Imports)
		a.goRules(fset, file)
	case lang == "go" && !parsed:
		a.Unknowns = append(a.Unknowns, Unknown{
			What:      "Go 结构类结论（函数、嵌套、忽略 err）",
			WhyAbsent: "这段贴进来的 Go 过不了 parser（语法不完整），AST 拿不到 ⇒ 结构类判据根本没跑，不是「跑过且没问题」",
			HowToGet:  "把完整文件或报错那一行一起贴进来",
			Basis:     Absent,
		})
		a.textRules(code, lang)
	default:
		a.textRules(code, lang)
		a.Unknowns = append(a.Unknowns, Unknown{
			What: fmt.Sprintf("%s 的 AST 级判据（作用域、调用图、类型）", lang),
			WhyAbsent: "本件不引第三方解析器：这一族的命中全部来自逐行文本匹配 ⇒ 只能署 estimated，" +
				"跨行的形状（比如 def 的括号换行、字符串里的关键字）会漏也会误报",
			HowToGet: "让该语言自己的工具判一次（pyflakes / eslint / go vet）—— 本件不代跑，也不替它们下结论",
			Basis:    Absent,
		})
	}

	a.Metrics.Funcs = countFuncs(code, lang)
	if !(lang == "go" && parsed) {
		a.Metrics.Imports = countImports(code, lang)
	}
	a.Unknowns = append(a.Unknowns, Unknown{
		What:      "运行时行为（这段实际会返回什么、慢在哪）",
		WhyAbsent: "本件默认不执行用户代码（设计件 §0 硬约束 1）；也没有日志与断点信息",
		HowToGet:  "贴一段真日志或复现步骤；或显式批准在临时目录里带超时跑一次",
		Basis:     Absent,
	})
	return a
}

func parseGo(code string) (string, bool, *token.FileSet, *ast.File) {
	fset := token.NewFileSet()
	file, err := parser.ParseFile(fset, "snippet.go", code, parser.AllErrors)
	if err != nil {
		return "go", false, fset, nil
	}
	return "go", true, fset, file
}

// —— Go：AST 判据。数的是解析出来的节点 ⇒ 一律 measured ——

func (a *Analysis) goRules(fset *token.FileSet, file *ast.File) {
	maxNest := 0
	blank := 0
	prints := 0
	longest := 0

	ast.Inspect(file, func(n ast.Node) bool {
		switch x := n.(type) {
		case *ast.FuncDecl:
			start := fset.Position(x.Pos()).Line
			end := fset.Position(x.End()).Line
			if end-start > longest {
				longest = end - start
			}
			if end-start > 60 {
				a.Findings = append(a.Findings, Finding{
					Rule:     "long-function",
					Severity: "major",
					Where:    Where{Lines: [2]int{start, end}, Symbol: x.Name.Name},
					Evidence: fmt.Sprintf("函数体跨 %d 行（阈值 60）；本文件共 %d 个函数", end-start, a.Metrics.Funcs),
					Basis:    Measured,
					Claim:    "一处要同时改的事太多 ⇒ 改对了也没人能证",
					Fix:      &Fix{Patch: "", Rationale: "按「做什么」切块，先切出能单独验的那半", Risk: "切分本身不改行为；验法是切完指标不劣化"},
					Verify:   "复跑本件，max_func_lines 落到阈值下",
				})
			}
			if d := nestDepth(x); d > maxNest {
				maxNest = d
			}
			if h, names := sameScopeDup(x); h > 0 {
				l := fset.Position(x.Pos()).Line
				a.Findings = append(a.Findings, Finding{
					Rule:     "dup-name-same-scope",
					Severity: "critical",
					Where:    Where{Lines: [2]int{l, fset.Position(x.End()).Line}, Symbol: x.Name.Name},
					Evidence: fmt.Sprintf("函数 %s 里有 %d 个名字在同一层块里被 := 声明了两次（%s）", x.Name.Name, h, strings.Join(names, ", ")),
					Basis:    Measured,
					Claim:    "同层重名在 Go 里编译不过；能解析出来却没报，说明这段是残缺片段 ⇒ 「看起来在跑其实没跑」这一族要人工确认",
					Fix:      &Fix{Patch: "", Rationale: "改名或删掉多余那份；先确认哪份是活的", Risk: "删错会改行为，要连调用点一起看"},
					Verify:   "复跑本件，该计数应为 0；或让编译器判一次",
				})
			}
		case *ast.AssignStmt:
			if x.Tok.String() == ":=" && blankAtErrorSlot(x) {
				blank++
				l := fset.Position(x.Pos()).Line
				a.Findings = append(a.Findings, Finding{
					Rule:     "ignore-error",
					Severity: "critical",
					Where:    Where{Lines: [2]int{l, l}},
					Evidence: fmt.Sprintf("第 %d 行把多返回值里的一个位置丢给 _；本文件数到 %d 处同类", l, blank),
					Basis:    Measured,
					Claim:    "失败路径变成零值返回 ⇒ 上层看到「没报错但东西是空的」",
					Fix:      &Fix{Patch: "", Rationale: "接住 err 并决定：上抛、降级还是记一笔", Risk: "改完可能暴露原本被吞的失败，要连着看调用方"},
					Verify:   "复跑本件，ignored_error_sites 减少且没新增 empty-err-block",
				})
			}
		case *ast.IfStmt:
			if isEmptyErrBlock(x) {
				l := fset.Position(x.Pos()).Line
				a.Findings = append(a.Findings, Finding{
					Rule:     "empty-err-block",
					Severity: "critical",
					Where:    Where{Lines: [2]int{l, l}},
					Evidence: fmt.Sprintf("第 %d 行 if err != nil 的块里 0 条语句", l),
					Basis:    Measured,
					Claim:    "看见了错误然后什么都不做 —— 比没看见更难查",
					Fix:      &Fix{Patch: "", Rationale: "要么处理，要么写清为什么可以不处理；空块两者都不是", Risk: "低"},
					Verify:   "复跑本件，empty-err-block 计数应为 0",
				})
			}
		case *ast.CallExpr:
			if isPrintCall(x) {
				prints++
				l := fset.Position(x.Pos()).Line
				a.Findings = append(a.Findings, Finding{
					Rule:     "print-as-log",
					Severity: "minor",
					Where:    Where{Lines: [2]int{l, l}},
					Evidence: fmt.Sprintf("第 %d 行是 fmt.Print*/println 调用；本文件共 %d 处", l, prints),
					Basis:    Measured,
					Claim:    "输出走 stdout ⇒ 在生产里落不进任何地方，也没有级别",
					Fix:      &Fix{Patch: "", Rationale: "换 log 或结构化输出，带上能归因的字段", Risk: "低；注意别把数据打进日志"},
					Verify:   "复跑本件 print_calls 归零",
				})
			}
		}
		return true
	})

	if maxNest > 4 {
		a.Findings = append(a.Findings, Finding{
			Rule:     "deep-nesting",
			Severity: "major",
			Evidence: fmt.Sprintf("最深控制块嵌套 %d 层（阈值 4）", maxNest),
			Basis:    Measured,
			Claim:    "分支到第 5 层之后没人能列出全路径 ⇒ 调试只能猜",
			Verify:   "复跑本件，看最深函数是否降到阈值下",
		})
	}
	for _, nm := range dupFuncNames(file) {
		a.Findings = append(a.Findings, Finding{
			Rule: "dup-func-name", Severity: "critical",
			Evidence: fmt.Sprintf("文件里有两个非方法函数都叫 %s —— 后一份把前一份整块盖掉（这一族在本项目造成过 137 行读不到的伪活代码）", nm),
			Basis:    Measured,
			Claim:    "前一份定义永远不会被执行 ⇒ 改它等于白改",
			Fix:      &Fix{Patch: "", Rationale: "删掉死的那份或改名；先确认哪份在真被调用", Risk: "删错直接改行为"},
			Verify:   "复跑本件，dup-func-name 应为 0",
		})
	}

	a.Metrics.MaxFunc = longest
	a.Metrics.BlankErrs = blank
	a.Metrics.PrintCalls = prints

	// 未用导入：没有类型信息，只做文本级核对 ⇒ 命中标 estimated，别冒充 AST 判出来的。
	for _, imp := range file.Imports {
		p, err := strconv.Unquote(imp.Path.Value)
		if err != nil {
			continue
		}
		name := path.Base(p)
		if imp.Name != nil {
			name = imp.Name.Name
		}
		if name == "_" || name == "." {
			continue
		}
		if !usesQualifiedIdent(file, name) {
			l := fset.Position(imp.Pos()).Line
			a.Findings = append(a.Findings, Finding{
				Rule:     "unused-import(maybe)",
				Severity: "minor",
				Where:    Where{Lines: [2]int{l, l}, Symbol: name},
				Evidence: fmt.Sprintf("包名 %s 在 import 块之外没作为限定符出现（文本级核对，没建类型信息）", name),
				Basis:    Estimated,
				Claim:    "可能未使用；也可能只在注释或字符串里出现被漏掉",
				Verify:   "让编译器判：go vet 或 goimports —— 这条是线索不是结论",
			})
		}
	}
}

// —— 其余语言的保守扫描在 langs.go（W7）——

// —— 小工具 ——

func blankAtErrorSlot(x *ast.AssignStmt) bool {
	if _, ok := x.Rhs[0].(*ast.CallExpr); !ok {
		return false
	}
	for _, lhs := range x.Lhs {
		if id, ok := lhs.(*ast.Ident); ok && id.Name == "_" {
			return true
		}
	}
	return false
}

func isEmptyErrBlock(x *ast.IfStmt) bool {
	if x.Body == nil || len(x.Body.List) != 0 {
		return false
	}
	b, ok := x.Cond.(*ast.BinaryExpr)
	if !ok {
		return false
	}
	return exprString(b.X) == "err" && b.Op.String() == "!=" && exprString(b.Y) == "nil"
}

func exprString(e ast.Expr) string {
	if v, ok := e.(*ast.Ident); ok {
		return v.Name
	}
	return ""
}

func isPrintCall(x *ast.CallExpr) bool {
	switch f := x.Fun.(type) {
	case *ast.SelectorExpr:
		if exprString(f.X) == "fmt" {
			switch f.Sel.Name {
			case "Print", "Printf", "Println":
				return true
			}
		}
	case *ast.Ident:
		return f.Name == "print" || f.Name == "println"
	}
	return false
}

func stmtsOf(b *ast.BlockStmt) []ast.Stmt {
	if b == nil {
		return nil
	}
	return b.List
}

// nestDepth：一层控制块 +1；else-if 链算同一层（否则一个普通分支链会被报成"很深"）。
func nestDepth(fn *ast.FuncDecl) int {
	if fn.Body == nil {
		return 0
	}
	return blockDepth(fn.Body.List, 0)
}

func blockDepth(stmts []ast.Stmt, d int) int {
	max := d
	for _, s := range stmts {
		var inner []ast.Stmt
		switch x := s.(type) {
		case *ast.IfStmt:
			inner = flattenIf(x)
		case *ast.ForStmt:
			inner = stmtsOf(x.Body)
		case *ast.RangeStmt:
			inner = stmtsOf(x.Body)
		case *ast.SwitchStmt:
			inner = caseStmts(x.Body)
		case *ast.SelectStmt:
			inner = commStmts(x.Body)
		default:
			continue
		}
		if cd := blockDepth(inner, d+1); cd > max {
			max = cd
		}
	}
	return max
}

// flattenIf：把 else-if 链摊平到同层，else 块里的语句算进本层分支。
func flattenIf(x *ast.IfStmt) []ast.Stmt {
	out := stmtsOf(x.Body)
	e := x.Else
	for e != nil {
		switch v := e.(type) {
		case *ast.BlockStmt:
			out = append(out, v.List...)
			e = nil
		case *ast.IfStmt:
			out = append(out, stmtsOf(v.Body)...)
			e = v.Else
		default:
			e = nil
		}
	}
	return out
}

func caseStmts(b *ast.BlockStmt) []ast.Stmt {
	var out []ast.Stmt
	if b == nil {
		return nil
	}
	for _, c := range b.List {
		if cc, ok := c.(*ast.CaseClause); ok {
			out = append(out, cc.Body...)
		}
	}
	return out
}

func commStmts(b *ast.BlockStmt) []ast.Stmt {
	var out []ast.Stmt
	if b == nil {
		return nil
	}
	for _, c := range b.List {
		if cc, ok := c.(*ast.CommClause); ok {
			out = append(out, cc.Body...)
		}
	}
	return out
}

// sameScopeDup：**每一层块只看它自己的直接语句**，不下钻。
// 嵌套层里重名是合法 shadowing，报成缺陷就是假红；同层重名才是真事故（本项目栽过这一族）。
func sameScopeDup(fn *ast.FuncDecl) (int, []string) {
	if fn.Body == nil {
		return 0, nil
	}
	hits := 0
	var names []string
	var walk func(b *ast.BlockStmt)
	inspectLevel := func(b *ast.BlockStmt) {
		seen := map[string]int{}
		for _, st := range b.List {
			as, ok := st.(*ast.AssignStmt)
			if !ok || as.Tok.String() != ":=" {
				continue
			}
			for _, l := range as.Lhs {
				id, ok := l.(*ast.Ident)
				if !ok || id.Name == "_" {
					continue
				}
				seen[id.Name]++
				if seen[id.Name] == 2 {
					hits++
					names = append(names, id.Name)
				}
			}
		}
	}
	walk = func(b *ast.BlockStmt) {
		if b == nil {
			return
		}
		inspectLevel(b)
		for _, st := range b.List {
			for _, inner := range nestedBlocks(st) {
				walk(inner)
			}
		}
	}
	walk(fn.Body)
	return hits, names
}

func nestedBlocks(st ast.Stmt) []*ast.BlockStmt {
	switch x := st.(type) {
	case *ast.IfStmt:
		out := []*ast.BlockStmt{x.Body}
		if x.Else != nil {
			if b, ok := x.Else.(*ast.BlockStmt); ok {
				out = append(out, b)
			}
			if i, ok := x.Else.(*ast.IfStmt); ok {
				out = append(out, nestedBlocks(i)...)
			}
		}
		return out
	case *ast.ForStmt:
		return []*ast.BlockStmt{x.Body}
	case *ast.RangeStmt:
		return []*ast.BlockStmt{x.Body}
	case *ast.BlockStmt:
		return []*ast.BlockStmt{x}
	case *ast.CaseClause:
		return nil
	}
	return nil
}

// dupFuncNames：同一个文件里两个非方法函数重名 —— Go 里这是编译期就炸的形状，
// 但语法树能解析出来，所以贴进来的片段也能当场看见。
func dupFuncNames(file *ast.File) []string {
	seen := map[string]int{}
	order := []string{}
	for _, d := range file.Decls {
		fn, ok := d.(*ast.FuncDecl)
		if !ok || fn.Recv != nil || fn.Name == nil {
			continue
		}
		if seen[fn.Name.Name] == 0 {
			order = append(order, fn.Name.Name)
		}
		seen[fn.Name.Name]++
	}
	var out []string
	for _, nm := range order {
		if seen[nm] > 1 {
			out = append(out, nm)
		}
	}
	return out
}

func usesQualifiedIdent(file *ast.File, name string) bool {
	found := false
	ast.Inspect(file, func(n ast.Node) bool {
		if _, ok := n.(*ast.ImportSpec); ok {
			return false
		}
		if se, ok := n.(*ast.SelectorExpr); ok {
			if exprString(se.X) == name {
				found = true
			}
		}
		return true
	})
	return found
}

// defRe 数的是"看起来像函数定义的行"。JS 的具名函数（`function pick(row) {`）单独有一支 ——
// 少了它 JS 那份考卷数出 0 个函数，而针 19 会当场报出来（这一条就是这么被抓到的）。
var defRe = regexp.MustCompile(`(?m)^\s*(func\s+\w+|def\s+\w+|fn\s+\w+|function\s+\w*\s*\(|(?:const|let|var)\s+\w+\s*=\s*(?:async\s*)?(?:function|\())`)

func countFuncs(code, lang string) int {
	if lang == "go" {
		n := 0
		for _, l := range strings.Split(code, "\n") {
			if strings.HasPrefix(strings.TrimSpace(l), "func ") {
				n++
			}
		}
		return n
	}
	return len(defRe.FindAllString(code, -1))
}

// countImports 数的是"这个片段里有几条导入语句"。它与"其中几条疑似没用到"是两个量，
// 必须分列两格 —— 刚才页面把后者当总数印了出来（一格两义是假绿的一半）。
func countImports(code, lang string) int {
	var ps []*regexp.Regexp
	switch lang {
	case "python":
		ps = []*regexp.Regexp{re(`(?m)^\s*import\s+\w+`), re(`(?m)^\s*from\s+[\w.]+\s+import\s+`)}
	case "javascript", "typescript":
		ps = []*regexp.Regexp{re(`(?m)^\s*import\s+`), re(`\brequire\(`)}
	default:
		return 0
	}
	n := 0
	for _, p := range ps {
		n += len(p.FindAllString(code, -1))
	}
	return n
}
