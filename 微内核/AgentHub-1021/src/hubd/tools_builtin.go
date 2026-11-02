package main

// 内置工具：每一个都真的在跑，返回的 Text 里带单位与分母（字节 vs 码元、几项/几行）。
// 这些数是量出来的，不是话术 —— 调度循环拿它们做下一步判断，前端把它们原样画出来。

import (
	"context"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
	"strings"
	"time"
	"unicode/utf8"
)

type Env struct {
	fs         *FsGuard
	net        *NetGuard
	mem        *Memory
	reg        *Registry
	cfg        Config
	now        func() time.Time
	慢          time.Duration // demo.flaky 用：让重试的等待看得见
	resetFlaky func()        // 自检/测试用：把 demo.flaky 的次数归零
}

type dirRow struct {
	name string
	size int64
	mod  time.Time
	dir  bool
}

type funcTool struct {
	spec ToolSpec
	fn   func(ctx context.Context, args map[string]any) (Result, error)
}

func (t *funcTool) Spec() ToolSpec { return t.spec }
func (t *funcTool) Run(ctx context.Context, args map[string]any) (Result, error) {
	if err := 校验参数(t.spec, args); err != nil {
		return Result{Class: ClassBadArgs, Text: err.Error()}, nil
	}
	return t.fn(ctx, args)
}

func quick(spec ToolSpec, fn func(context.Context, map[string]any) (Result, error)) Tool {
	if spec.Source == "" {
		spec.Source = "builtin"
	}
	if spec.TimeoutMs == 0 {
		spec.TimeoutMs = 3000
	}
	if spec.Retry.Attempts == 0 {
		spec.Retry = RetryPolicy{Attempts: 1, BackoffMs: 100, BackoffMaxMs: 1000,
			NoRetryClasses: []string{ClassBadArgs, ClassRefused, ClassUnsupported}}
	}
	return &funcTool{spec: spec, fn: fn}
}

// RegisterBuiltins 返回注册上的工具名清单；撞名/被规则拒的一律进 rejected，不静默。
func RegisterBuiltins(reg *Registry, env *Env) (names, rejected []string) {
	add := func(t Tool) {
		if err := reg.Add(t); err != nil {
			rejected = append(rejected, err.Error())
			return
		}
		names = append(names, t.Spec().Name)
	}

	add(quick(ToolSpec{
		Name: "fs.list", Summary: "列一个目录：条目名、字节数、修改时间；只走允许的文件根",
		Params: []ParamSpec{
			{Name: "path", Type: "string", Desc: "目录路径（必须在 -fs-roots 里）", Required: true, Example: "."},
			{Name: "limit", Type: "int", Desc: "最多列几条（默认 40）", Required: false, Example: "20"},
			{Name: "sort", Type: "string", Desc: "name 或 size（默认 name）", Required: false, Example: "size"},
			{Name: "contains", Type: "string", Desc: "只留名字含这段的", Required: false},
		},
		Risk: RiskLocalRead, Fallback: "fs.read",
	}, func(ctx context.Context, a map[string]any) (Result, error) {
		abs, why := env.fs.Within(getString(a, "path", "."))
		if why != "" {
			return Result{Class: ClassRefused, Text: why}, nil
		}
		ents, err := os.ReadDir(abs)
		if err != nil {
			return Result{Class: ClassUpstream, Text: fmt.Sprintf("读目录失败：%v（%s）", err, abs)}, nil
		}
		lim := getInt(a, "limit", 40)
		want := getString(a, "contains", "")
		var rows []dirRow
		skipped := 0
		for _, e := range entssafe(ents) {
			if want != "" && !strings.Contains(strings.ToLower(e.name), strings.ToLower(want)) {
				skipped++
				continue
			}
			rows = append(rows, e)
		}
		if getString(a, "sort", "name") == "size" {
			sort.Slice(rows, func(i, j int) bool { return rows[i].size > rows[j].size })
		} else {
			sort.Slice(rows, func(i, j int) bool { return rows[i].name < rows[j].name })
		}
		总 := len(rows)
		if lim > 0 && 总 > lim {
			rows = rows[:lim]
		}
		// top 要说清是"最大的那个文件"，就得真按字节挑一个文件；
		// 以前取 rows[0] 且它是目录时留空 —— 于是"再统计最大的那个文件"这种指代接不上。
		var top string
		var 最大 int64 = -1
		for i := range rows {
			if rows[i].dir {
				continue
			}
			if rows[i].size > 最大 {
				最大, top = rows[i].size, rows[i].name
			}
		}
		var b strings.Builder
		fmt.Fprintf(&b, "%s ｜ 目录下共 %d 条", abs, len(ents))
		if top != "" {
			fmt.Fprintf(&b, " ｜ 这里最大的文件是 %s（%d 字节）", top, 最大)
		}
		if skipped > 0 {
			fmt.Fprintf(&b, "（按 contains=%q 滤掉 %d 条）", want, skipped)
		}
		if 总 > len(rows) {
			fmt.Fprintf(&b, "，这里只列前 %d 条（limit）", len(rows))
		}
		b.WriteString("\n")
		for _, r := range rows {
			kind := "文件"
			sz := r.size
			if r.dir {
				kind = "目录"
				sz = 0
			}
			fmt.Fprintf(&b, "%s %s %d 字节 %s\n", kind, r.name, sz, r.mod.Format("2006-01-02 15:04"))
		}
		return Result{Class: ClassOK, Text: b.String(),
			Data: map[string]any{"dir": abs, "entries": len(ents), "listed": len(rows), "top": top}}, nil
	}))

	add(quick(ToolSpec{
		Name: "fs.read", Summary: "读一个文件的正文（默认最多 8192 字节，超出会明说截断）",
		Params: []ParamSpec{
			{Name: "path", Type: "string", Desc: "文件路径（必须在 -fs-roots 里）", Required: true},
			{Name: "max_bytes", Type: "int", Desc: "最多读多少字节（默认 8192，上限 65536）", Required: false},
		},
		Risk: RiskLocalRead, Fallback: "fs.list",
	}, func(ctx context.Context, a map[string]any) (Result, error) {
		abs, why := env.fs.Within(getString(a, "path", ""))
		if why != "" {
			return Result{Class: ClassRefused, Text: why}, nil
		}
		maxb := getInt(a, "max_bytes", 8192)
		if maxb > 65536 {
			maxb = 65536
		}
		f, err := os.Open(abs)
		if err != nil {
			return Result{Class: ClassUpstream, Text: fmt.Sprintf("打不开：%v", err)}, nil
		}
		defer f.Close()
		buf := make([]byte, maxb)
		n, err := f.Read(buf)
		if err != nil && n == 0 {
			return Result{Class: ClassUpstream, Text: fmt.Sprintf("读了但失败：%v", err)}, nil
		}
		body := string(buf[:n])
		st, serr := f.Stat()
		size := int64(-1)
		if serr == nil {
			size = st.Size()
		}
		尾 := ""
		if size >= 0 && int64(n) < size {
			尾 = fmt.Sprintf("（只读了前 %d 字节，整个文件 %d 字节 ⇒ 后面 %d 字节没在这份读数里）", n, size, size-int64(n))
		}
		return Result{Class: ClassOK,
			Text: fmt.Sprintf("%s ｜ 读到 %d 字节（UTF-8 码元 %d 个）%s\n%s", abs, n, utf8.RuneCountInString(body), 尾, body),
			Data: map[string]any{"path": abs, "bytes": n, "runes": utf8.RuneCountInString(body), "truncated": 尾 != ""}}, nil
	}))

	add(quick(ToolSpec{
		Name: "text.stats", Summary: "给一段文本或一个文件算行数、字节、码元、最长行与空行数",
		Params: []ParamSpec{
			{Name: "text", Type: "string", Desc: "要统计的文本（与 path 二选一）", Required: false},
			{Name: "path", Type: "string", Desc: "要统计的文件（与 text 二选一）", Required: false},
		},
		Risk: RiskCompute,
	}, func(ctx context.Context, a map[string]any) (Result, error) {
		body := getString(a, "text", "")
		src := "参数 text"
		if body == "" {
			p := getString(a, "path", "")
			if p == "" {
				return Result{Class: ClassBadArgs, Text: "text 和 path 都是空的 ⇒ 没东西可统计"}, nil
			}
			abs, why := env.fs.Within(p)
			if why != "" {
				return Result{Class: ClassRefused, Text: why}, nil
			}
			if st, e := os.Stat(abs); e == nil && st.IsDir() {
				// 目录不是"读失败"，是参数给错了对象 —— 说成 bad_args 才不会招来一轮重试
				return Result{Class: ClassBadArgs, Text: fmt.Sprintf("%s 是个目录 ⇒ text.stats 要 path 指一个文件（想先看目录里有啥就调 fs.list）", abs)}, nil
			}
			b, err := os.ReadFile(abs)
			if err != nil {
				return Result{Class: ClassUpstream, Text: fmt.Sprintf("读 %s 失败：%v", abs, err)}, nil
			}
			body, src = string(b), abs
		}
		lines := strings.Split(body, "\n")
		空, 最长, 最长号 := 0, 0, 0
		for i, l := range lines {
			l = strings.TrimRight(l, "\r")
			if strings.TrimSpace(l) == "" {
				空++
			}
			if len(l) > 最长 {
				最长, 最长号 = len(l), i+1
			}
		}
		return Result{Class: ClassOK,
			Text: fmt.Sprintf("%s ｜ 字节 %d ｜ UTF-8 码元 %d ｜ 行 %d（空行 %d）｜ 最长一行 %d 字节，在第 %d 行",
				src, len(body), utf8.RuneCountInString(body), len(lines), 空, 最长, 最长号),
			Data: map[string]any{"bytes": len(body), "runes": utf8.RuneCountInString(body),
				"lines": len(lines), "blank": 空, "longest_line": 最长, "longest_at": 最长号}}, nil
	}))

	add(quick(ToolSpec{
		Name: "calc.eval", Summary: "算一个算式（+ - * / % ** 括号），不执行任何代码",
		Params: []ParamSpec{{Name: "expr", Type: "string", Desc: "算式，如 (2+3)*4**2", Required: true, Example: "(2+3)*4"}},
		Risk:   RiskCompute,
	}, func(ctx context.Context, a map[string]any) (Result, error) {
		e := getString(a, "expr", "")
		v, err := evalExpr(e)
		if err != nil {
			return Result{Class: ClassBadArgs, Text: fmt.Sprintf("算式 %q 没过解析：%v", e, err)}, nil
		}
		return Result{Class: ClassOK, Text: fmt.Sprintf("%s = %v", strings.TrimSpace(e), v),
			Data: map[string]any{"expr": e, "value": v}}, nil
	}))

	add(quick(ToolSpec{
		Name: "time.now", Summary: "这台机器的当前时间（本地钟与毫秒刻度）",
		Params: []ParamSpec{{Name: "zone_note", Type: "string", Desc: "只想备注一句，可留空", Required: false}},
		Risk:   RiskCompute, TimeoutMs: 1000,
	}, func(ctx context.Context, a map[string]any) (Result, error) {
		t := env.now()
		return Result{Class: ClassOK,
			Text: fmt.Sprintf("本地钟 %s ｜ epoch 毫秒 %d ｜ 时区 %s", t.Format("2006-01-02 15:04:05 -0700"), t.UnixMilli(), t.Format("MST")),
			Data: map[string]any{"epoch_ms": t.UnixMilli(), "iso": t.Format(time.RFC3339)}}, nil
	}))

	add(quick(ToolSpec{
		Name: "http.get", Summary: "取一个 URL 的正文（GET；主机必须落在 -net-allow 清单里）",
		Params: []ParamSpec{{Name: "url", Type: "string", Desc: "http(s) 地址", Required: true, Example: "http://127.0.0.1:8788/api/tools"}},
		Risk:   RiskNetLocal, TimeoutMs: 4000,
		Retry: RetryPolicy{Attempts: 3, BackoffMs: 120, BackoffMaxMs: 900,
			NoRetryClasses: []string{ClassBadArgs, ClassRefused}},
	}, func(ctx context.Context, a map[string]any) (Result, error) {
		return env.net.Get(ctx, getString(a, "url", ""))
	}))

	add(quick(ToolSpec{
		Name: "tools.list", Summary: "把这台 Agent 现在认识的工具原样列出来（含清单挂载的）",
		Params: []ParamSpec{{Name: "risk", Type: "string", Desc: "只看某一风险档，可留空", Required: false}},
		Risk:   RiskCompute, TimeoutMs: 1000,
	}, func(ctx context.Context, a map[string]any) (Result, error) {
		want := getString(a, "risk", "")
		var b strings.Builder
		n, 亮 := 0, 0
		for _, s := range reg.Specs() {
			n++
			if want != "" && string(s.Risk) != want {
				continue
			}
			亮++
			fmt.Fprintf(&b, "%s [%s] %s（参数：%s；来源：%s）\n", s.Name, s.Risk, s.Summary,
				strings.Join(paramNames(s.Params), "、"), s.Source)
		}
		总 := fmt.Sprintf("认识的工具共 %d 个", n)
		if want != "" {
			总 = fmt.Sprintf("认识的工具共 %d 个，风险档 %q 的 %d 个", n, want, 亮)
		}
		return Result{Class: ClassOK, Text: 总 + "\n" + b.String(),
			Data: map[string]any{"tools": n, "shown": 亮, "shadowed": len(reg.shadow)}}, nil
	}))

	add(quick(ToolSpec{
		Name: "memory.recall", Summary: "往回找这轮会话里说过的话与做过的工具调用",
		Params: []ParamSpec{
			{Name: "query", Type: "string", Desc: "要找的词（子串匹配，大小写不敏感）", Required: true},
			{Name: "limit", Type: "int", Desc: "最多回几条（默认 5）", Required: false},
		},
		Risk: RiskLocalRead, TimeoutMs: 1500,
	}, func(ctx context.Context, a map[string]any) (Result, error) {
		q := strings.ToLower(getString(a, "query", ""))
		lim := getInt(a, "limit", 5)
		hits := env.mem.Find(q, lim)
		var b strings.Builder
		fmt.Fprintf(&b, "会话里匹配 %q 的命中 %d 条（这轮一共 %d 条记忆）\n", q, len(hits), env.mem.Count())
		for _, h := range hits {
			fmt.Fprintf(&b, "第 %d 发 %s：%s\n", h.Turn, h.Role, h.Text)
		}
		return Result{Class: ClassOK, Text: b.String(),
			Data: map[string]any{"hits": len(hits), "total": env.mem.Count()}}, nil
	}))

	add(quick(ToolSpec{
		Name: "notes.write", Summary: "往笔记目录写一个 .md 文件（要 -allow-write 才开）",
		Params: []ParamSpec{
			{Name: "name", Type: "string", Desc: "文件名，不带路径", Required: true, Example: "结论.md"},
			{Name: "content", Type: "string", Desc: "正文", Required: true},
		},
		Risk: RiskFsWrite, RequiresFlag: "allow-write", TimeoutMs: 1500,
	}, func(ctx context.Context, a map[string]any) (Result, error) {
		dir, why := env.fs.Within(env.cfg.NotesDir)
		if why != "" {
			return Result{Class: ClassRefused, Text: "笔记目录不在允许的文件根里：" + why}, nil
		}
		name := strings.ReplaceAll(getString(a, "name", "note.md"), string(filepath.Separator), "_")
		body := getString(a, "content", "")
		if err := os.MkdirAll(dir, 0o755); err != nil {
			return Result{Class: ClassUpstream, Text: fmt.Sprintf("目录建不起来：%v", err)}, nil
		}
		p := filepath.Join(dir, name)
		if err := os.WriteFile(p, []byte(body), 0o644); err != nil {
			return Result{Class: ClassUpstream, Text: fmt.Sprintf("写失败：%v", err)}, nil
		}
		return Result{Class: ClassOK, Text: fmt.Sprintf("写了 %s ｜ %d 字节", p, len(body)),
			Data: map[string]any{"path": p, "bytes": len(body)}}, nil
	}))

	add(quick(ToolSpec{
		Name: "exec.run", Summary: "跑一条本机命令（默认关；开了要临时目录 + 超时）",
		Params: []ParamSpec{
			{Name: "argv", Type: "strings", Desc: "命令与参数，逐个给，例如 [\"go\",\"version\"]", Required: true},
		},
		Risk: RiskExec, RequiresFlag: "allow-exec", TimeoutMs: 8000,
	}, func(ctx context.Context, a map[string]any) (Result, error) {
		var argv []string
		switch x := a["argv"].(type) {
		case []string:
			argv = x
		case []any:
			for _, item := range x {
				s, _ := item.(string)
				argv = append(argv, s)
			}
		}
		if len(argv) == 0 || argv[0] == "" {
			return Result{Class: ClassBadArgs, Text: "argv 是空的 ⇒ 没命令可跑（这条不是失败，是没给参数）"}, nil
		}
		tmp, err := os.MkdirTemp("", "hubd-exec-")
		if err != nil {
			return Result{Class: ClassInternal, Text: fmt.Sprintf("临时目录建不起来：%v（这一发不放行执行）", err)}, nil
		}
		defer os.RemoveAll(tmp)
		cctx, cancel := context.WithTimeout(ctx, time.Duration(env.cfg.ExecTimeoutMs)*time.Millisecond)
		defer cancel()
		cmd := exec.CommandContext(cctx, argv[0], argv[1:]...)
		cmd.Dir = tmp
		var out, errb strings.Builder
		cmd.Stdout, cmd.Stderr = &out, &errb
		rerr := cmd.Run()
		尾 := ""
		if cctx.Err() == context.DeadlineExceeded {
			尾 = fmt.Sprintf(" ｜ 到 %d ms 被超时掐掉", env.cfg.ExecTimeoutMs)
		}
		return Result{Class: ClassOK,
			Text: fmt.Sprintf("%v ｜ 退出码=%v%s\nstdout：%s\nstderr：%s", argv, rerr, 尾, strings.TrimSpace(out.String()), strings.TrimSpace(errb.String())),
			Data: map[string]any{"exit_error": fmt.Sprint(rerr), "cwd": tmp}}, nil
	}))

	// demo.flaky —— 专门给重试/降级当活体证人：前 N 次故意回坏，第 N+1 次成功。
	// 没有它，"重试策略真的会再来一次"就只是一句代码存在性证据。
	flaky := &struct {
		calls int
	}{calls: 0}
	add(quick(ToolSpec{
		Name: "demo.flaky", Summary: "自检用：前 N 次回 upstream 坏，第 N+1 次成功（用来量重试与降级）",
		Params: []ParamSpec{{Name: "fail_first", Type: "int", Desc: "前几次要失败（默认 1）", Required: false}},
		Risk:   RiskCompute, TimeoutMs: 2000, Fallback: "time.now",
		Retry: RetryPolicy{Attempts: 3, BackoffMs: 40, BackoffMaxMs: 200},
	}, func(ctx context.Context, a map[string]any) (Result, error) {
		fail := getInt(a, "fail_first", 1)
		flaky.calls++
		if flaky.calls <= fail {
			return Result{Class: ClassUpstream, RetryAfterMs: int(env.慢 / time.Millisecond),
				Text: fmt.Sprintf("第 %d 次调用：按脚本回坏（fail_first=%d）", flaky.calls, fail)}, nil
		}
		return Result{Class: ClassOK, Text: fmt.Sprintf("第 %d 次调用：成功", flaky.calls),
			Data: map[string]any{"calls": flaky.calls}}, nil
	}))
	env.resetFlaky = func() { flaky.calls = 0 }

	return names, rejected
}

// entssafe：把目录项拍成 dirRow；Info() 失败不 panic，那条只留名字与目录标记。
func entssafe(ents []os.DirEntry) []dirRow {
	var out []dirRow
	for _, e := range ents {
		r := dirRow{name: e.Name(), dir: e.IsDir()}
		if st, err := e.Info(); err == nil {
			r.size, r.mod = st.Size(), st.ModTime()
		}
		out = append(out, r)
	}
	return out
}
