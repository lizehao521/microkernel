package main

import (
	"embed"
	"encoding/json"
	"flag"
	"fmt"
	"io/fs"
	"net"
	"net/http"
	"os"
	"strconv"
	"strings"
	"sync"
)

//go:embed web
var webFS embed.FS

var (
	mu     sync.Mutex
	turnNo = map[string]int{}
	// aborts：每一发挂一个可关的通道。「点停」= 服务端自己关它 ⇒ 循环照样收口、照样把剩下的事件发完，
	// 页面上看得见"停在哪里、停下来时手里有什么"。掐断 fetch 也能停，但那等于把读数撕掉。
	aborts = map[string]chan struct{}{}
)

func armKey(session string, turn int) string { return session + "#" + strconv.Itoa(turn) }

func registerAbort(session string, turn int) chan struct{} {
	ch := make(chan struct{})
	mu.Lock()
	aborts[armKey(session, turn)] = ch
	mu.Unlock()
	return ch
}

func fireAbort(session string, turn int) bool {
	mu.Lock()
	ch, ok := aborts[armKey(session, turn)]
	mu.Unlock()
	if !ok {
		return false
	}
	select {
	case <-ch:
		return false // 已经关过了：重复点停不产生第二次停止
	default:
		close(ch)
		return true
	}
}

func clearAbort(session string, turn int) {
	mu.Lock()
	delete(aborts, armKey(session, turn))
	mu.Unlock()
}

func nextTurn(session string) int {
	mu.Lock()
	defer mu.Unlock()
	turnNo[session]++
	return turnNo[session]
}

type request struct {
	Session  string `json:"session"`
	Code     string `json:"code"`
	Question string `json:"question"`
	Lang     string `json:"lang"`
	Stack    string `json:"stack"`
}

// staticHandler 是内嵌前端的出口。加 no-store 不是洁癖：这台应用会被人改完 CSS 直接刷新看效果，
// 拿到旧缓存就把"我改了"看成"没生效"—— W8 的焦点轮廓就是这么被旧样式挡了一次（针 21 钉这条）。
func staticHandler(sub fs.FS) http.Handler {
	fileServer := http.FileServer(http.FS(sub))
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Cache-Control", "no-store")
		fileServer.ServeHTTP(w, r)
	})
}

func main() {
	port := flag.String("port", "4319", "只听 127.0.0.1 的哪个端口（不许是 8797/8799，那两本是内核研究账）")
	data := flag.String("data", "数据", "轨迹 JSONL 落在哪个目录")
	kernel := flag.Bool("kernel", true, "装不装内核接缝（预检/落账/读回/声明读者）；关掉 ⇒ 那三步如实记 absent")
	readBack := flag.Bool("read-back", true, "读回开关。关掉就是核心 KPI 的反臂：不读回 ⇒ 账本触发次数必须掉回 0")
	entryCap := flag.Int("entry-cap", 0, "这本账最多几条；0 = 不设上限")
	delay := flag.Duration("step-delay", 0, "每步之间等多久：真开浏览器要看清逐条亮，也要让「点停」来得及（0 = 几十毫秒跑完，中断就只能靠程序自己造）")
	selfcheck := flag.Bool("selfcheck", false, "不接浏览器，跑内置 fixture 考卷并打印读数（该红的必须红）")
	fakeEP := flag.Bool("fake-endpoint", false, "开第 ⑧ 步：打**本机 127.0.0.1 随机端口**的假端点，把管路那七格变成有出处的读数。"+
		"它是演示件（脚本回帧，真实模型 0 次），出不了这台机；真端点要 PGAGENT_BASE_URL 显式给")
	flag.Parse()

	gatewayFake = *fakeEP

	stepDelay = *delay
	if *kernel {
		installSeam(*entryCap, *readBack)
	}

	if *selfcheck {
		os.Exit(selfcheckRun())
	}

	st := newStore(*data)
	sub, err := fs.Sub(webFS, "web")
	if err != nil {
		fmt.Fprintln(os.Stderr, "内嵌的 web/ 没打进去（构建有问题）："+err.Error())
		os.Exit(2)
	}
	mux := http.NewServeMux()
	mux.Handle("/", staticHandler(sub))

	mux.HandleFunc("/api/health", func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, map[string]any{"ok": true, "seam_installed": seam != nil, "executes_code": false})
	})

	mux.HandleFunc("/api/stop", func(w http.ResponseWriter, r *http.Request) {
		var q struct {
			Session string `json:"session"`
			Turn    int    `json:"turn"`
		}
		if err := json.NewDecoder(r.Body).Decode(&q); err != nil {
			http.Error(w, "停的请求体解不开："+err.Error(), http.StatusBadRequest)
			return
		}
		// 停了不等于这一发没跑过：点完停，循环仍会把已亮的步数、已落的账、五档读数收口发完。
		ok := fireAbort(q.Session, q.Turn)
		writeJSON(w, map[string]any{"stopped": ok, "session": q.Session, "turn": q.Turn,
			"note": "stopped=false 也可能是这一发已经跑完了或早就停了 —— 不是一条新事实"})
	})

	mux.HandleFunc("/api/history", func(w http.ResponseWriter, r *http.Request) {
		s := r.URL.Query().Get("session")
		recs, err := st.history(s)
		if err != nil {
			w.WriteHeader(http.StatusInternalServerError)
			fmt.Fprintln(w, err.Error())
			return
		}
		writeJSON(w, map[string]any{"session": s, "turns": recs, "count": len(recs)})
	})

	// 一发 = 一条 SSE 流：九步逐步亮，最后一步带整份结果。
	mux.HandleFunc("/api/turn", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			http.Error(w, "POST only", http.StatusMethodNotAllowed)
			return
		}
		var req request
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			http.Error(w, "请求体解不开："+err.Error(), http.StatusBadRequest)
			return
		}
		if strings.TrimSpace(req.Code) == "" {
			http.Error(w, "代码是空的 —— 空输入不出结论，出结论也是假绿", http.StatusBadRequest)
			return
		}
		if req.Session == "" {
			req.Session = "default"
		}
		w.Header().Set("Content-Type", "text/event-stream; charset=utf-8")
		w.Header().Set("Cache-Control", "no-cache")
		fl, _ := w.(http.Flusher)

		n := nextTurn(req.Session)
		// abort：客户端断开（页面点「停」= fetch 的 reader.cancel）就关这个通道。
		// 循环在每一步之间看它一眼；看到了就**照样收口、照样落盘**，只是写明"被打断"。
		abort := registerAbort(req.Session, n)
		defer clearAbort(req.Session, n)
		go func() {
			select {
			case <-r.Context().Done():
				fireAbort(req.Session, n) // 客户端把连接掐了也算一次停
			case <-abort:
			}
		}()
		emit := func(s Step) {
			b, _ := json.Marshal(s)
			fmt.Fprintf(w, "event: step\ndata: %s\n\n", b)
			if fl != nil {
				fl.Flush()
			}
		}
		// 先把"这一发是第几发"发出去：页面上的「停」按钮要点名停哪一发，不能靠猜。
		fmt.Fprintf(w, "event: meta\ndata: {\"session\":%q,\"turn\":%d}\n\n", req.Session, n)
		if fl != nil {
			fl.Flush()
		}
		res := runLoop(req.Code, req.Question, req.Lang, req.Session, n, emit, abort, req.Stack)
		if err := st.append(recordOf(res, req.Code)); err != nil {
			bad := Step{No: 10, Name: "store.append", Summary: "落盘失败：" + err.Error(), Basis: Absent, Run: false}
			res.Trace = append(res.Trace, bad)
			emit(bad)
		}
		body, _ := json.Marshal(res)
		fmt.Fprintf(w, "event: result\ndata: %s\n\n", body)
		if fl != nil {
			fl.Flush()
		}
	})

	ln, err := net.Listen("tcp", "127.0.0.1:"+*port)
	if err != nil {
		fmt.Fprintf(os.Stderr, "端口 %s 起不来：%v\n（起不来就换端口，别去 kill 不明进程 —— 那可能是别的会话在听）\n", *port, err)
		os.Exit(2)
	}
	fmt.Fprintf(os.Stderr, "pgagent 在 http://127.0.0.1:%s（只监听本机；不执行用户代码；内核接缝=%v）\n",
		*port, seam != nil)
	if err := http.Serve(ln, mux); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}

func writeJSON(w http.ResponseWriter, v any) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	_ = json.NewEncoder(w).Encode(v)
}

// reporter 是考卷的判分器。它被 selfcheck 与针共用 —— 这样"考卷会不会判红"这件事本身也能被测（见 TestReporterCanGoRed）。
type reporter struct{ Fails int }

func (rp *reporter) check(name string, ok bool, detail string) {
	if ok {
		fmt.Printf("[OK ] %s｜%s\n", name, detail)
		return
	}
	rp.Fails++
	fmt.Printf("[RED] %s｜%s\n", name, detail)
}

// selfcheckRun 跑内置考卷：一份"该红"的 fixture、一份干净的 fixture、一份非 Go 的降档样本。
// 读数量：命中条数、五档加总、以及最要紧的一条 —— 干净那份不许被编出问题。
func selfcheckRun() int {
	rp := &reporter{}
	check := rp.check

	dirty := runLoop(fixtureDirty, "这段有什么问题", "go", "selfcheck", 1, func(Step) {}, nil, "")
	check("脏样本命中 ignore-error", hasRule(dirty.Findings, "ignore-error"), fmt.Sprintf("findings=%d", len(dirty.Findings)))
	check("脏样本命中 empty-err-block", hasRule(dirty.Findings, "empty-err-block"), "")
	check("脏样本命中 dup-name-same-scope", hasRule(dirty.Findings, "dup-name-same-scope"), "")
	check("脏样本命中 print-as-log", hasRule(dirty.Findings, "print-as-log"), "")
	check("五档加总恒等", dirty.MixOK, fmt.Sprintf("%+v", dirty.Mix))

	// 内核三步有三种状态，各有一条自己的读数 —— 别用两个布尔凑出三种语义：
	// ① 没装接缝 ② 装了且读回 ③ 装了但读回被关（反臂）。
	switch {
	case seam == nil:
		check("接缝没装：内核三步一律 absent 且带理由", absentSteps(dirty.Trace) >= 4,
			fmt.Sprintf("absent 步数=%d（预检/落账/读回/模型）", absentSteps(dirty.Trace)))
	case !seamReadBack:
		check("反臂：装了接缝但读回被关 ⇒ 预检/落账照跑、读回如实记没跑",
			ranStep(dirty, "kernel.check_call") && ranStep(dirty, "kernel.record_call") && !ranStep(dirty, "kernel.read_back"),
			lastLine(dirty.Trace, "kernel.read_back"))
		check("反臂：没有读回就没有一格是被账改写的 ⇒ KPI=0",
			dirty.KPI == 0 && len(dirty.Decisions) == 0, fmt.Sprintf("KPI=%d 读回格数=%d", dirty.KPI, len(dirty.Decisions)))
	default:
		check("接缝已装：内核三步都真跑了",
			ranStep(dirty, "kernel.check_call") && ranStep(dirty, "kernel.record_call") && ranStep(dirty, "kernel.read_back"),
			lastLine(dirty.Trace, "kernel.read_back"))
		check("KPI：读回的格里有格真的改写了结果，且 ≥1",
			dirty.KPI >= 1 && dirty.KPI <= len(dirty.Decisions),
			fmt.Sprintf("读回 %d 格 / 改写 %d 格", len(dirty.Decisions), dirty.KPI))
		check("账上 content_bytes 落成了独立一格（不冒充代码字节）",
			dirty.Metrics.BytesSource != "",
			fmt.Sprintf("BytesSource=%q｜账上那一格的读数：%s", dirty.Metrics.BytesSource, dumpDecision(dirty, "content_bytes")))
		// 读者声明：读过的每一格都要署名。声明被拒却静默 ⇒ 账上那格"没人声明读过"，
		// 而页面上还在喊"读了 N 格" —— 两边各说各话就是假账，所以这一条单独判。
		check("读者声明全落账（第 7 步里没有「N 格没落账」那句，且 readers_report 数了格）",
			!strings.Contains(lastLine(dirty.Trace, "kernel.read_back"), "没落账") &&
				strings.Contains(lastLine(dirty.Trace, "kernel.readers_report"), "格"),
			fmt.Sprintf("readers_report=%s", lastLine(dirty.Trace, "kernel.readers_report")))
		// 再就地跑一遍反臂：同一份分析件，只把读回关掉 ⇒ 一个数都不许数出来。
		defer func() { seam = nil; seamReadBack = false }()
		installSeam(0, false)
		arm := runLoop(fixtureDirty, "反臂", "go", "selfcheck-arm", 4, func(Step) {}, nil, "")
		check("反臂：不 read_back ⇒ KPI 掉回 0",
			arm.KPI == 0 && !ranStep(arm, "kernel.read_back"), fmt.Sprintf("KPI=%d", arm.KPI))
		installSeam(0, true)
		seamReadBack = true

		// 边界那一发（W14 现场）：贴进超预算的代码时预检被内核拒，收口那三步（tally/verify/readers_report）
		// 不许跟着整块缺席 —— 缺席与"跑了但没东西可印"在页面上长一个样，看不出"账没落成"发生在哪一步。
		big := runLoop(fixtureDirty+strings.Repeat("// 填充一行给预算看 ", 4000), "这段有什么问题",
			"go", "selfcheck-big", 6, func(Step) {}, nil, "")
		var bigBad []string
		for _, n := range []string{"kernel.tally", "kernel.verify", "kernel.readers_report"} {
			var seen bool
			for _, s := range big.Trace {
				if s.Name != n {
					continue
				}
				seen = true
				if s.Run || s.Basis != Absent || !strings.Contains(s.Summary, "没东西可印") {
					bigBad = append(bigBad, fmt.Sprintf("%s(ran=%v basis=%v)", n, s.Run, s.Basis))
				}
			}
			if !seen {
				bigBad = append(bigBad, n+"(整块缺席)")
			}
		}
		check("超预算那一发：收口三步都在场、各署 absent 并带为什么（整块缺席=页面上看不见账没落成）",
			len(bigBad) == 0 && !ranStep(big, "kernel.check_call") && big.KPI == 0 && big.MixOK &&
				strings.Contains(lastLine(big.Trace, "kernel.read_back"), "预检被拒"),
			fmt.Sprintf("预检被拦=%v ｜ 缺/错=%v ｜ 步=%d ｜ KPI=%d ｜ 未决=%d ｜ 第 7 步那句=%s",
				!ranStep(big, "kernel.check_call"), bigBad, len(big.Trace), big.KPI, len(big.Unknowns),
				lastLine(big.Trace, "kernel.read_back")))
	}

	clean := runLoop(fixtureClean, "这段有什么问题", "go", "selfcheck", 2, func(Step) {}, nil, "")
	check("干净样本不许被编出 critical（反臂：尺子不能凭空红）",
		countSeverity(clean.Findings, "critical") == 0, fmt.Sprintf("findings=%d", len(clean.Findings)))

	py := runLoop(fixturePy, "帮我看看", "auto", "selfcheck", 3, func(Step) {}, nil, "")
	check("Python 样本整份降 estimated（不冒充 measured）",
		countBasis(py.Findings, Measured) == 0 && len(py.Findings) > 0,
		fmt.Sprintf("measured=%d estimated=%d", countBasis(py.Findings, Measured), countBasis(py.Findings, Estimated)))

	// W5：调试（栈→行）与优化（度量→建议）两条路径各自的读数。
	stk := runLoop(fixtureDirty, "为什么会 panic", "go", "selfcheck", 5, func(Step) {}, nil, fixtureStack)
	check("栈那一发认出帧并落进贴入范围",
		stk.Debug != nil && stk.Debug.Frames >= 2 && stk.Debug.InRange >= 2, fmt.Sprintf("%+v", stk.Debug))
	check("行号映射署 estimated（文件名没对上，不许升 measured）",
		countRule(stk.Findings, "stack-frame", Estimated) >= 2,
		fmt.Sprintf("stack-frame(estimated) %d 条", countRule(stk.Findings, "stack-frame", Estimated)))
	check("优化建议每条都写了怎么复验，且没有一条署 measured",
		suggestions(stk.Findings) > 0 && allVerified(stk.Findings) && countBasis(stk.Findings, Measured) < len(stk.Findings),
		fmt.Sprintf("带修法的建议 %d 条", suggestions(stk.Findings)))
	check("没给栈：记 absent 带理由，不许读成「没有 bug」",
		hasUnknown(clean.Unknowns, "报错/栈 → 行号") && hasUnknown(py.Unknowns, "报错/栈 → 行号"), "")

	// W6：第 ⑧ 步的三态 —— 没打 / 打了且是演示件 / 打了但连不上（第三态由针 18 演，不在这里拨端口）。
	// 这一路只打 127.0.0.1 的随机端口；8797/8799 由 guardURL 挡死，本件从来不往那两本账上打。
	if os.Getenv("PGAGENT_BASE_URL") == "" {
		gwOff := runLoop(fixtureDirty, "x", "go", "selfcheck-gw", 6, func(Step) {}, nil, "")
		check("没配端点也没开 -fake-endpoint：第 ⑧ 步 NOT_RUN，且不印 gateway 读数（不写 0）",
			gwOff.Gateway == nil && !ranStep(gwOff, "gateway") &&
				strings.Contains(lastLine(gwOff.Trace, "gateway"), "NOT_RUN"),
			lastLine(gwOff.Trace, "gateway"))

		gatewayFake = true
		gwOn := runLoop(fixtureDirty, "解释一下", "go", "selfcheck-gw", 7, func(Step) {}, nil, "")
		gatewayFake = false
		ghosts := pipeGhosts(gwOn.Unknowns)
		still := pipeFlipped(gwOn)
		check("假端点一发：管路七格翻档（帧/时延/字节/usage 都不再是 absent）",
			gwOn.Gateway != nil && gwOn.Gateway.Chunks >= 4 && len(ghosts) == 0 && len(still) == 0,
			fmt.Sprintf("帧=%d 读回=%d 字节 送出=%d 字节 剩下的「账上那一格」=%v 账上还是缺席/没声明的=%v",
				gwOn.Gateway.Chunks, gwOn.Gateway.BytesIn, gwOn.Gateway.BytesOut, ghosts, still))
		check("端点的话署 model_says，且读数里写明是演示件",
			countRule(gwOn.Findings, "gateway-text", ModelSays) == 1 &&
				strings.Contains(lastLine(gwOn.Trace, "gateway"), "演示件"),
			fmt.Sprintf("gateway-text(model_says)=%d 条", countRule(gwOn.Findings, "gateway-text", ModelSays)))
		check("usage 全 0 停在 relayed（流式端点的老坑，不许升 measured）",
			gwOn.Gateway.UsageSaid && gwOn.Gateway.UsageIn == 0 &&
				strings.Contains(lastLine(gwOn.Trace, "gateway"), "relayed"),
			dumpDecision(gwOn, "usage_in"))
		check("翻档之后五档恒等仍然成立", gwOn.MixOK && gwOn.Mix.ModelSays >= 1, fmt.Sprintf("%+v", gwOn.Mix))
	}

	// W7：多语言降档一整份。命中的族数、档名、以及"哨兵值不许被抄进读数"各有一条自己的判据。
	py7 := analyze(fixturePyRich, "auto")
	pyFams := countAny(py7.Findings, "bare-except", "except-pass", "mutable-default-arg", "none-compare", "print-as-log", "unused-import(maybe)")
	check("Python 考卷六族文本判据全咬住（少一把尺子就是漏判，不许说成够用）", pyFams == 6,
		fmt.Sprintf("命中 %d/6 族｜lang=%s LangHow=%s", pyFams, py7.Metrics.Lang, py7.Metrics.LangHow))
	check("Python 那一份一个 measured 都不许有（文本匹配不是解析）",
		countBasis(py7.Findings, Measured) == 0 && len(py7.Findings) > 0,
		fmt.Sprintf("measured=%d 共 %d 条", countBasis(py7.Findings, Measured), len(py7.Findings)))
	js7 := analyze(fixtureJSRich, "auto")
	jsFams := countAny(js7.Findings, "loose-equality", "empty-catch", "eval-or-new-function", "debugger-left", "console-log", "var-left")
	check("JavaScript 考卷六族全咬住", jsFams == 6, fmt.Sprintf("命中 %d/6 族｜lang=%s", jsFams, js7.Metrics.Lang))
	check("合规写法不许被命中（=== / !== 那一族假红过，所以钉成判据）",
		!hasRule(analyze("function f(r){ return r.id === 3 && r.k !== 4; }", "javascript").Findings, "loose-equality"),
		"负对照")
	pyC := analyze(fixturePyClean, "auto")
	check("干净的 Python 样本不许被编出 critical（反臂：尺子不能凭空红）",
		countSeverity(pyC.Findings, "critical") == 0, fmt.Sprintf("findings=%d 条", len(pyC.Findings)))
	sec := analyze(fixtureSecret, "python")
	sb, _ := json.Marshal(sec)
	check("硬编码判据命中，且命中的字面量没被抄进任何读数",
		hasRule(sec.Findings, "hardcoded-secret(maybe)") && !strings.Contains(string(sb), "SENTINEL-VALUE-DO-NOT-USE-0123456789"),
		fmt.Sprintf("命中=%v 读数长度=%d 字节", hasRule(sec.Findings, "hardcoded-secret(maybe)"), len(sb)))
	check("语言判定说得出处：嗅探给依据、显式选定不冒充解析",
		strings.Contains(py7.Metrics.LangWhy, "命中") && analyze(fixtureJSRich, "python").Metrics.LangHow == "用户显式选定",
		fmt.Sprintf("嗅探依据=%s", firstLine(py7.Metrics.LangWhy)))

	// W12：问题必须真的动这一发。换问题输出不变 ⇒ 那个输入框是装饰，而"看起来在工作"最难发现。
	iOpt := runLoop(fixtureDirty, "这段能怎么优化？", "go", "selfcheck-intent", 1, func(Step) {}, nil, "")
	iDbg := runLoop(fixtureDirty, "为什么偶尔返回空？", "go", "selfcheck-intent", 2, func(Step) {}, nil, fixtureStack)
	check("问题路由三种问题三种结论带（换问题输出不变=那个框是装饰）",
		iOpt.Intent == "优化" && iDbg.Intent == "调试" && iOpt.AnswerSummary != iDbg.AnswerSummary,
		fmt.Sprintf("路由=%s/%s｜两条结论带一样=%v", iOpt.Intent, iDbg.Intent, iOpt.AnswerSummary == iDbg.AnswerSummary))
	check("路由那句自带分母与边界（词表条数 + 明说不是模型理解）",
		strings.Contains(iOpt.IntentWhy, "词表") && strings.Contains(iOpt.AnswerSummary, "问题路由=优化") &&
			strings.Contains(iOpt.IntentWhy, "不是模型理解"),
		firstLine(iOpt.IntentWhy))
	check("优化意图那一发的第一张卡属于建议族（只改文案不改顺序不算路由）",
		len(iOpt.Findings) > 0 && inRules(optimizeRules, iOpt.Findings[0].Rule),
		fmt.Sprintf("第一张=%q（建议族 %d 条：%v）", ruleNameAt(iOpt.Findings, 0), len(optimizeRules), strings.Join(optimizeRules, ",")))

	fmt.Printf("\n读数自印：dirty=%d clean=%d py=%d 条；未决项 %d/%d/%d；失败项 %d\n",
		len(dirty.Findings), len(clean.Findings), len(py.Findings),
		len(dirty.Unknowns), len(clean.Unknowns), len(py.Unknowns), rp.Fails)
	if rp.Fails > 0 {
		return 1
	}
	return 0
}

func hasRule(fs []Finding, rule string) bool {
	for _, f := range fs {
		if f.Rule == rule {
			return true
		}
	}
	return false
}

// ruleNameAt 只是给读数用的安全取法：越界时印"（没有卡）"，不让判据的 detail 自己 panic。
func ruleNameAt(fs []Finding, i int) string {
	if i < 0 || i >= len(fs) {
		return "（没有卡）"
	}
	return fs[i].Rule
}

func absentSteps(ts []Step) int {
	n := 0
	for _, s := range ts {
		if !s.Run && s.Basis == Absent {
			n++
		}
	}
	return n
}

func ranStep(r Result, name string) bool {
	for _, s := range r.Trace {
		if s.Name == name {
			return s.Run
		}
	}
	return false
}

// dumpDecision 把某一格的账面读数原样打出来 —— 考卷红的时候，得看得见它为什么红。
func dumpDecision(r Result, key string) string {
	for _, d := range r.Decisions {
		if d.Key == key {
			return fmt.Sprintf("[%s/%s] %s", d.Side, d.Basis, d.Claim)
		}
	}
	return "（这一格根本没读回来）"
}

func countSeverity(fs []Finding, sev string) int {
	n := 0
	for _, f := range fs {
		if f.Severity == sev {
			n++
		}
	}
	return n
}

func lastLine(ts []Step, name string) string {
	for i := len(ts) - 1; i >= 0; i-- {
		if ts[i].Name == name {
			return ts[i].Summary
		}
	}
	return ""
}

func countRule(fs []Finding, rule string, b Basis) int {
	n := 0
	for _, f := range fs {
		if f.Rule == rule && f.Basis == b {
			n++
		}
	}
	return n
}

// suggestions 数的是"带修法且署了判断档"的建议条数 —— 建议一律 estimated，
// 把建议署成 measured 就是拿量的口气说判断的话。
func suggestions(fs []Finding) int {
	n := 0
	for _, f := range fs {
		if f.Fix != nil && f.Basis == Estimated {
			n++
		}
	}
	return n
}

func allVerified(fs []Finding) bool {
	for _, f := range fs {
		if strings.TrimSpace(f.Verify) == "" {
			return false
		}
	}
	return len(fs) > 0
}

// pipeGhosts 数"账上那一格…"的未决项还剩几条：管路已经有真值时它必须是 0，
// 否则就是"翻档只翻了一半，未决项还在替旧状态说话"。
func pipeGhosts(us []Unknown) []string {
	var out []string
	for _, u := range us {
		if strings.HasPrefix(u.What, "账上那一格") {
			out = append(out, u.What)
		}
	}
	return out
}

// pipeFlipped 查的是**账上那七格自己翻没翻档**（从 Decisions 里读出处档），
// 不是"Gateway 那个结构体里有没有数"。10-21 的 G6 臂就是这么把自己骗过去的：
// 把 pipeInt 改坏成恒 absent，`Gateway.Chunks` 仍然是 4、判据照样绿 —— 那是代理读数。
// 返回还留在缺席/压根没出现状态的格名；空 = 七格全翻档。
func pipeFlipped(res Result) []string {
	want := []string{"chunks", "first_byte_ms", "max_gap_ms", "wire_bytes_in", "wire_bytes_out", "usage_in", "usage_out"}
	got := map[string]string{}
	for _, d := range res.Decisions {
		if d.Side == "output" {
			got[d.Key] = d.Basis
		}
	}
	var still []string
	for _, k := range want {
		b, ok := got[k]
		if !ok {
			still = append(still, k+"=账上没这条决定")
		} else if b == "" || b == "absent" {
			still = append(still, k+"="+b+"(还是缺席)")
		}
	}
	return still
}

// countAny 数的是"命中了几族"，不是"命中了几条"：
// 同一族打中十行只算一把尺子；拿条数充族数会把一份漏判的尺子说得像十项全能。
func countAny(fs []Finding, rules ...string) int {
	seen := map[string]bool{}
	for _, f := range fs {
		for _, r := range rules {
			if f.Rule == r {
				seen[r] = true
			}
		}
	}
	return len(seen)
}

func hasUnknown(us []Unknown, what string) bool {
	for _, u := range us {
		if u.What == what && strings.TrimSpace(u.WhyAbsent) != "" {
			return true
		}
	}
	return false
}
