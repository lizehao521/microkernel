package main

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"strconv"
	"strings"
	"sync"

	kernel "agentkernel"
	"agentkernel/mcpsrv"
)

// 内核接缝（W4）。姿势与 cmd/agentd 一模一样：同进程 mcpsrv.New() + Serialize(line)，
// 不重写 Check、不起子进程、不开端口。48 键/49 格是内核的，这一层只往里填真值。
//
// KPI「账本触发过几次决定」在这里的定义是**能被指认的动作**：
// 某一格的值或出处档是从 read_back 的回帧里读出来、并且真的改写了这一发的结果
// （拿账上的数覆盖内存里的数 / 把一处声明降成 absent 并引用账上原话 / 不许升档）。
// 数不到动作就不计入 —— 与 agentd 那条「依据写『本地』的不计」同一个口径。

const (
	pgCeiling = int64(16384) // 贴进来的代码会比剧本长；这是预算上限，不是"允许截断"的额度
	pgSlack   = 10
	pgReader  = "pgagent-web"
)

// declaredCells 记「这个读者已经声明过读哪一格」（键 = side/key）。
// 声明说的是代码读哪格，是一码事、不是"每一发都要喊一遍"；内核明确拒收同一个读者第二次声明
// （那句原话是"同一个读者声明两遍会把分母数大"）—— 10-21 那张截图就是第二发被全数拒收时拍下来的。
// 服务是并发的（一发一个 goroutine），所以这张表带锁。
var (
	declMu        sync.Mutex
	declaredCells = map[string]bool{}
)

// procLanded 记"这个进程落了几发"。内核接缝是**进程内**的一本账（换进程从 0 重新起算），
// 而会话文件是跨进程追加的 —— 两个数不写在一起，"账 147 条"就会被读成整本会话的账（W28 实测过这一形）。
var (
	landedMu   sync.Mutex
	procLanded int
)

func landedCount() int {
	landedMu.Lock()
	defer landedMu.Unlock()
	return procLanded
}

var pgShares = map[kernel.PartKind]int{kernel.KindSystem: 10,
	kernel.KindToolSpec: 20,
	kernel.KindHistory:  10,
	kernel.KindUser:     30,
	kernel.KindObserved: 20,
	kernel.KindNotice:   10,
}

// pgSystem 里写的就是这台机器的规矩：不执行、只读、出处五档。
// 它进账本，所以"这条约束是有的"这件事也在账上，不只在 README 里。
const pgSystem = "编程 Agent：只读字节与解析语法树，不执行任何用户代码；" +
	"每一条结论必须带出处档（measured/estimated/model_says/relayed/absent），量不到就记 absent 并写理由，绝不写成 0。"

const pgToolSpec = "analyzer(go:ast 结构判据) / text(保守扫描) / store(会话 JSONL) / gateway(未配置 ⇒ NOT_RUN)"

type pgRPC struct {
	srv *mcpsrv.Server
	n   int
}

func newPgRPC(entryCap int, appendOnly bool) *pgRPC {
	s := mcpsrv.New()
	s.SetEntryCap(entryCap)
	s.SetAppendOnly(appendOnly)
	return &pgRPC{srv: s}
}

type pgReply struct {
	Text  string
	IsErr bool
}

// seamCaller 是"能调用一个内核工具"这件最小接口。见 runSeam 的注释。
type seamCaller interface {
	call(tool string, args map[string]any) (pgReply, error)
}

func (k *pgRPC) call(tool string, args map[string]any) (pgReply, error) {
	k.n++
	raw, err := json.Marshal(map[string]any{
		"jsonrpc": "2.0", "id": k.n, "method": "tools/call",
		"params": map[string]any{"name": tool, "arguments": args},
	})
	if err != nil {
		return pgReply{}, fmt.Errorf("拼 %s 的请求帧就散了：%w", tool, err)
	}
	out := k.srv.Serialize(append(raw, '\n'))
	if len(out) == 0 {
		return pgReply{}, fmt.Errorf("%s 没有回帧（第 %d 次调用）", tool, k.n)
	}
	var msg struct {
		Result *struct {
			Content []struct {
				Type string `json:"type"`
				Text string `json:"text"`
			} `json:"content"`
			IsError bool `json:"isError"`
		} `json:"result"`
		Error *struct {
			Code    int    `json:"code"`
			Message string `json:"message"`
		} `json:"error"`
	}
	if err := json.Unmarshal(out, &msg); err != nil {
		return pgReply{}, fmt.Errorf("%s 的回帧解不开（%v）：%s", tool, err, string(out))
	}
	if msg.Error != nil {
		return pgReply{Text: msg.Error.Message, IsErr: true}, nil
	}
	if msg.Result == nil || len(msg.Result.Content) == 0 {
		return pgReply{}, fmt.Errorf("%s 回了但正文一格都没有：%s", tool, string(out))
	}
	return pgReply{Text: msg.Result.Content[0].Text, IsErr: msg.Result.IsError}, nil
}

// cellFromReadBack：值只能从回帧字节里读。读不到就回 false ——
// 不许拿内存里那份结构冒充"账上有"。（与 agentd 同一姿势，抄的是形状不是结论。）
func cellFromReadBack(text, key string) (basis, claim string, ok bool) {
	for _, line := range strings.Split(text, "\n") {
		t := strings.TrimLeft(line, " \t")
		if !strings.HasPrefix(t, key) {
			continue
		}
		rest := t[len(key):]
		if rest != "" && !strings.HasPrefix(rest, " ") && !strings.HasPrefix(rest, "\t") {
			continue // 前缀撞车：fail_kind 不许命中 fail_status 那族
		}
		f := strings.Fields(rest)
		if len(f) == 0 {
			return "", "", false
		}
		i := strings.Index(rest, f[0])
		claim = ""
		if i >= 0 {
			claim = strings.TrimSpace(rest[i+len(f[0]):])
		}
		return f[0], claim, true
	}
	return "", "", false
}

func pgSha(s string) string {
	h := sha256.Sum256([]byte(s))
	return hex.EncodeToString(h[:])
}

// pgBudget 把内核那把尺子拿出来给第 ① 步做预告。
// 这不是抄判据：公式的唯一 owner 在内核包里（DeriveBudget），我们只是拿它算出来的数
// 与自己数出来的 parts 字节比一次 —— 而且只敢做**单向**断言（说超就一定不落账；
// 说不超仍可能被按段的回夹拒掉，那一刀只有内核知道）。
func pgBudget() (kernel.Budget, error) {
	return kernel.DeriveBudget(pgCeiling, pgSlack, pgShares,
		kernel.EstimatedOf(96, "pgagent 本地估的系统开销（说明件 + 工具清单的固定头），不是测量"))
}

// pgPartsBytes 数这一发真要送进账的字节：系统件 + 工具清单 + (问题 + 空两行 + 代码)。
// 与 buildPair 里那份 segs 必须是同一份算法 —— 两处各数一遍就会数出两个数（本项目点过名）。
func pgPartsBytes(question, code string) int64 {
	return int64(len(pgSystem) + len(pgToolSpec) + len(question) + 2 + len(code))
}

// buildPair 把这一发装成内核要的两侧。每一格的出处按"我们到底怎么知道的"来署：
// 自己数的 = measured；本地粗算 = estimated；没有对端 = absent + 理由（不写 0）。
func buildPair(session string, call int, code, question, answer string) (map[string]any, error) {
	segs := []struct {
		kind kernel.PartKind
		body string
	}{
		{kernel.KindSystem, pgSystem},
		{kernel.KindToolSpec, pgToolSpec},
		{kernel.KindUser, question + "\n\n" + code},
	}
	var content int64
	order := make([]kernel.PartKind, 0, len(segs))
	parts := make([]kernel.PartCount, 0, len(segs))
	for _, s := range segs {
		content += int64(len(s.body))
		order = append(order, s.kind)
		parts = append(parts, kernel.PartCount{Kind: s.kind, Parts: 1, Bytes: int64(len(s.body))})
	}
	budget, err := pgBudget()
	if err != nil {
		return nil, err
	}
	// 两读对账：① 步预告用的是 pgPartsBytes，落账用的是这里逐段加的 content —— 同一发不许数出两个字节。
	if pb := pgPartsBytes(question, code); pb != content {
		return nil, fmt.Errorf("pgagent 自己数出两个字节：逐段加=%d ① 步口径=%d", content, pb)
	}
	in := kernel.InputMeta{
		Call:         call,
		Order:        order,
		Parts:        parts,
		ContentBytes: content,
		Tokens: kernel.EstimatedOf(content/4+int64(len(order)),
			"pgagent 本地粗算（字节/4+段数）；分词器不在本机，这不是测量"),
		Budget: budget,
	}
	out := kernel.OutputMeta{
		Call:      call,
		Streaming: pipe != nil && pipe.BodyRead,
		// ^ 这一格署的是"**这一发真按流式收到过东西**"，不是"我们请求了流式"。
		// W33 实测：连不上/超时那一形里 pipe 不是 nil（打了、有读数对象），但一个字节没回来，
		// 当时写成 Streaming=true + 分帧数=缺席 ⇒ 内核整发拒收（原话："这一发是流式的，分帧数却报缺席 ——
		// 流式就该量得到它"）⇒ 失败那一发**根本进不了账**，账上只剩一个拒收计数。
		// 请求是不是要流式，第 ⑧ 步那句与 fail_kind 那一格都写着，不必由这一格冒充。
		Chunks: pipeInt(pipe, func(p *pipeReadout) int64 { return p.Chunks }, "这台机没开通道：这一发不分帧，帧数无从数起"),
		// 三个时间格与两个过网线字节格：没开通道时只能是缺席 + 理由。
		// 署成 measured(0) 就是把「没量到」写成「量到是 0」—— 内核那侧专门有针盯这一族。
		FirstByteMs:  pipeInt(pipe, func(p *pipeReadout) int64 { return p.FirstByteMs }, "非流式：没有首帧这回事"),
		MaxGapMs:     pipeInt(pipe, func(p *pipeReadout) int64 { return p.MaxGapMs }, "非流式：没有帧间这回事"),
		WireBytesIn:  pipeIn(pipe),
		WireBytesOut: pipeOut(pipe),
		ToolCalls:    0,
		Malformed:    0, // 这一格数的是"提议了但执行不了的工具调用"：本件不发工具调用，所以是真的 0，不是"没数"
		Says:         kernel.Says{Bytes: int64(len(answer)), Kept: int64(len(answer)), SHA256: pgSha(answer)},
		// 没有对端报 token：两格一律缺席 + 理由。**不许写 0**。
		// 有对端自报时是 relayed：那个数是端点**说**的，不是我量的（本机量过：流式端点这三个数常是 0）。
		UsageIn:  pipeUsage(pipe, true),
		UsageOut: pipeUsage(pipe, false),
		Finish:   kernel.Finish{Reason: finishOf(pipe), Said: pipe == nil || pipe.Finish != ""},
		Failure:  failureOf(pipe),
		// "model" 这一格署的是**对端自报的身份**，转述档：假端点那一份要自带"演示件"字样，
		// 免得日后有人把它的回帧读成一次真模型调用。
		Model:          modelOf(pipe),
		ModelSaid:      true,
		WireFormat:     wireFormatOf(pipe),
		WireFormatSaid: pipe == nil || pipe.WireObject != "",
	}
	return map[string]any{"session": session, "actor": pgReader, "input": in, "output": out}, nil
}

// installSeam 把接缝装进 loop.go 的插槽。readBack=false 就是那条反臂：
// 不读回 ⇒ 没有任何一格是被账决定的 ⇒ KPI 必须掉回 0。
func installSeam(entryCap int, readBack bool) {
	rpc := newPgRPC(entryCap, false)
	seam = func(code, question, session string, turn int) (SeamReply, error) {
		pair, err := buildPair(session, turn, code, question, "本地分析件的一发结论")
		if err != nil {
			return SeamReply{}, err
		}
		return runSeam(rpc, pair, session, turn, readBack)
	}
	seamReadBack = readBack
}

var seamReadBack bool

// runSeam 走预检→落账→读回→声明读者→收口数。返回的 Decisions 就是 KPI 的分子。
// 参数收的是"能 call 一个内核工具"这件最小接口（不是 *pgRPC 本身）：
// 不为好看，是为了让"声明被拒"这条失败路**能被真走一遍** —— 走不了的失败路等于没测的失败路。
func runSeam(rpc seamCaller, pair map[string]any, session string, turn int, readBack bool) (SeamReply, error) {
	var rep SeamReply
	pre, err := rpc.call("kernel.check_call", pair)
	rep.Checked = err == nil && !pre.IsErr
	if err != nil {
		// 通道本身断了也要落 Reason：第 ⑦ 步那句"没读回："跟的就是这个字段，
		// 空着上屏就是「没读回：」后面一片白 —— 判据第 2 条（缺席必带理由）在针 41 的
		// 「接缝报散」那一形上当场抓到过（W38）。
		rep.Reason = "预检这一发没打出去，调用就失败了：" + err.Error()
		return rep, err
	}
	rep.Verdict = firstLine(pre.Text)
	if pre.IsErr {
		// 预检红的时候**不许只给第一行**：内核那句回话是三行的（第一行往往是"输入侧：自洽"），
		// 只截第一行 ⇒ 页面上印出「预检被内核判据拒：输入侧：自洽」这种自相矛盾的一句话，
		// 真正那行（输出侧哪一格不合格）被切掉了（W33 实测：连不上/超时那一形就走到这里）。
		rep.Verdict = strings.ReplaceAll(strings.TrimSpace(pre.Text), "\n", " ｜ ")
		// Reason 也要落字：页面上那句"没读回："后面跟着空，等于把原因咽了回去（absent 必带理由）。
		rep.Reason = "预检被拒，根本没走到读回那一步：" + rep.Verdict
		收口数(rpc, &rep) // 账没进，但那本账还在 ⇒ 第 ⑨ 步照样要交内核原话（见 收口数 的注释）
		return rep, fmt.Errorf("预检被内核判据拒：%s", rep.Verdict)
	}

	rec, err := rpc.call("kernel.record_call", pair)
	if err != nil {
		rep.Reason = "落账这一发没打出去，调用就失败了：" + err.Error()
		return rep, err
	}
	rep.RecordLine = firstLine(rec.Text)
	rep.Recorded = !rec.IsErr
	if !rec.IsErr {
		landedMu.Lock()
		procLanded++
		landedMu.Unlock()
	}
	if rec.IsErr {
		// 走到这里预检是**过了**的：挡下这一发的不是内核判据，是门口那道门（账本到上限、整块没给、参数解不开）。
		// Reason 必须落字：第 ⑦ 步那句"没读回："跟的就是这个字段，空着等于把原因咽回去（W32 实测到这一形）。
		// 内核那句原话由第 ⑥ 步说（RecordLine），这里只指路 —— 同一句话在一列里写三遍就会被读出三个版本。
		rep.Reason = "落账那一步被门口挡下（第 ⑤ 步预检是过了的）⇒ 账上没有这一发，三轴读回无从谈起；内核原话在第 ⑥ 步"
		收口数(rpc, &rep) // 被挡这一发也要交第 ⑨ 步：链上没长、被拒计数 +1，跨发判据量的就是这两格
		return rep, fmt.Errorf("落账被拒：%s", rep.RecordLine)
	}
	if !readBack {
		// 反臂走的就是这一条：不读回，后面一格都不许算"账决定的"。
		rep.Reason = "read_back 被关掉了（反臂）：值没从账上回来过，所以没有任何声明被账本改写过"
		收口数(rpc, &rep) // 反臂关的是"读回"，不是"收口"：账落了，第 ⑨ 步照样要交内核原话
		return rep, nil
	}

	outRB, err := rpc.call("kernel.read_back", map[string]any{"session": session, "call": turn, "side": "output"})
	if err != nil {
		rep.Reason = "读回（输出侧）这一发没打出去，调用就失败了：" + err.Error()
		return rep, err
	}
	inRB, err := rpc.call("kernel.read_back", map[string]any{"session": session, "call": turn, "side": "input"})
	if err != nil {
		rep.Reason = "读回（输入侧）这一发没打出去，调用就失败了：" + err.Error()
		return rep, err
	}
	rep.ReadBack = !outRB.IsErr && !inRB.IsErr
	if !rep.ReadBack {
		rep.Reason = "读回报错：" + firstLine(outRB.Text)
		收口数(rpc, &rep)
		return rep, nil
	}

	// 从账上取值/取档，并**真的改写结果**：改一次计一次。没改写的不计 —— 否则数的是"我读了"。
	consume := func(side, text, key string) {
		basis, claim, ok := cellFromReadBack(text, key)
		if !ok {
			rep.Decisions = append(rep.Decisions, Decision{
				Key: key, Side: side, Effect: "read_back 的回帧里没有这一格 ⇒ 这一发不许引用它",
			})
			return
		}
		switch basis {
		case "absent":
			rep.Decisions = append(rep.Decisions, Decision{
				Key: key, Side: side, Basis: basis, Claim: claim,
				Effect: "账上记的是缺席 ⇒ 结果区这一处跟着记 absent，理由引用账上原话（不写 0）",
			})
		case "measured":
			rep.Decisions = append(rep.Decisions, Decision{
				Key: key, Side: side, Basis: basis, Claim: claim,
				Effect: "整块送出量落成独立一格 metrics.ledger_content_bytes（不覆盖代码字节数 —— 两个量不能并成一行）",
			})
		default:
			rep.Decisions = append(rep.Decisions, Decision{
				Key: key, Side: side, Basis: basis, Claim: claim,
				Effect: fmt.Sprintf("出处按账上写的 %s 档，不许升成 measured", basis),
			})
		}
		// 声明读者：这一格真被人读了（内核自己核不到的那一半，S7 同族）。
		// **失败不许吞**：声明没落账 ⇒ readers_report 会把这格报成"没人声明读过"，
		// 而我们还在喊"读了 12 格"。那种两边各说各话正是这一族项目点过名的假账。
		// 另一条（10-21 截图当场暴露的）：声明说的是"这个读者读这一格"，那是**代码的属性**，不是一发的属性；
		// 内核明确拒收同一个读者第二次声明（"两遍会把分母数大"）⇒ 每格只声明一次，第二发不再喊。
		dk := side + "/" + key
		declMu.Lock()
		already := declaredCells[dk]
		declMu.Unlock()
		if !already {
			d, derr := rpc.call("kernel.declare_reader", map[string]any{"reader": pgReader, "key": key, "side": side})
			switch {
			case derr != nil:
				rep.DeclFail = append(rep.DeclFail, fmt.Sprintf("%s：调用就失败了（%v）", dk, derr))
			case d.IsErr:
				rep.DeclFail = append(rep.DeclFail, fmt.Sprintf("%s：内核拒收（%s）", dk, firstLine(d.Text)))
			default:
				declMu.Lock()
				declaredCells[dk] = true
				declMu.Unlock()
			}
		}
	}
	for _, k := range []string{"content_bytes", "tokens", "parts"} {
		consume("input", inRB.Text, k)
	}
	outCells := []string{"usage_in", "usage_out", "wire_bytes_in", "wire_bytes_out", "chunks",
		"first_byte_ms", "max_gap_ms", "fail_kind", "model_says_sha256",
		// W34 起多读一格 finish：它是**端点说的**收尾原因（我们以前只往账里写、从不读回来，
		// 于是"我们填的话"与"端点说的话"没有一道闸能分开）。
		"finish"}
	// retry_after_ms 只在"这一发要么失败了、要么端点真给了等待话"的时候才读：
	// 正常回完那一发里它天然是缺席，把这种缺席挂成一条未决，就是把"没有这回事"演成"我们还欠一个答案"
	// （W6 那根针 TestFakeEndpointFlipsThePipeCells 盯的正是这一族）。
	if pipe != nil && (pipe.Kind != "" || pipe.RetrySaid || pipe.RetryRaw != "") {
		outCells = append(outCells, "retry_after_ms")
	}
	for _, k := range outCells {
		consume("output", outRB.Text, k)
	}
	rep.KPI = len(rep.Decisions)

	收口数(rpc, &rep)
	return rep, nil
}

// 收口数 打第 ⑨ 步那三个只读件：tally（五档）、verify（链自洽）、readers_report（谁声明读过）。
// 为什么每条早退路都要先打它们：这三件数的是**那本账**，不是"这一发进没进账"——
// 预检被拒、被门口挡下、反臂关掉读回，账都还在原地，内核照样答得出。
// 以前这些形状直接早退 ⇒ 页面上第 ⑩ 步只能记"没东西可印"，而跨发判据也就永远量不到被挡那一发的链上读数
// （W37 那两条守卫臂就是这么个死臂）。目标里 ⑨ 是每一发都要走的一步，不是落了账才走的一步。
// 唯一不打的形状：连 check_call 都没回话（通道本身死了）—— 那时这三个调用也一样死，编不出数。
func 收口数(rpc seamCaller, rep *SeamReply) {
	if rep.Tally == "" {
		if tally, err := rpc.call("kernel.tally", nil); err == nil {
			rep.Tally = firstLine(tally.Text)
		}
	}
	if rep.Verify == "" {
		if ver, err := rpc.call("kernel.verify", nil); err == nil {
			rep.Verify = firstLine(ver.Text)
		}
	}
	if rep.Readers == "" {
		if rep2, err := rpc.call("kernel.readers_report", nil); err == nil {
			rep.Readers = firstLine(rep2.Text)
		}
	}
}

func firstLine(s string) string {
	s = strings.TrimSpace(s)
	if i := strings.IndexByte(s, '\n'); i >= 0 {
		return s[:i] + " …（共 " + strconv.Itoa(strings.Count(s, "\n")+1) + " 行）"
	}
	return s
}

// 下面这一族把"第 ⑧ 步跑没跑"翻译成账上那几格的出处档。
// 口径只有一条：**跑过才有数，没跑过就还是缺席 + 理由，一格都不许写成 0**。

func pipeInt(p *pipeReadout, get func(*pipeReadout) int64, whyAbsent string) kernel.Measure {
	if p == nil {
		return kernel.AbsentBecause(whyAbsent)
	}
	if !p.Received {
		// 打了、但一个字节都没回来：0 是"没量到"，不是"量到 0"。
		// 恒为 0 的分帧数会被下一个人读成"一帧都没收到"（那恰好是协议错的判据），所以这里记缺席。
		return kernel.AbsentBecause("这一发打出去了但没收到响应（失败归因在 fail_kind 那一格）—— 分帧与时序的 0 是没量到")
	}
	if !p.BodyRead {
		// 回了非 200：错误体刻意不读（那里面常回显请求，是最容易把口令抄进读数/账本的一条路）。
		// 于是这四格是"没读"，署成 measured(0) 就是把没量写成量到 —— W33 实测到这一形一路是 measured。
		return kernel.AbsentBecause("端点回了非 200（状态码在 fail_status 那一格）⇒ 错误体刻意没读 ⇒ 分帧与时序没量过，这不是量到 0")
	}
	return kernel.MeasuredOf(get(p))
}

func pipeIn(p *pipeReadout) kernel.Measure {
	if p == nil {
		return kernel.AbsentBecause("这一发没开 socket：结论是本地分析件给的字符串，不在任何通道上")
	}
	if !p.Received {
		return kernel.AbsentBecause("连的是 transport 那一类：没收到响应 ⇒ 通道上一个字节都没读到，这不是量到 0")
	}
	if !p.BodyRead {
		// 状态行与头是收到了，但**正文刻意没读** ⇒ "过网线的字节"这一格没量过。
		// 署成 measured(0) 会被读成"这一发的响应是空的"，而它其实可能是 429 带着一段回显错误的正文。
		return kernel.AbsentBecause("端点回了非 200：状态行收到了，正文刻意没读 ⇒ 入线字节没量过，这不是量到 0")
	}
	return kernel.MeasuredOf(p.BytesIn) // 从我自己那个 reader 上逐行加出来的
}

func pipeOut(p *pipeReadout) kernel.Measure {
	if p == nil {
		return kernel.AbsentBecause("这一发没开 socket：一个字节都没过网线")
	}
	// 数得出的是**交给 http.Client 的负载**；TLS/HTTP 头帧与分帧开销在这一台上看不见 ⇒ estimated。
	return kernel.EstimatedOf(p.BytesOut, "请求体字节数（我自己编出来的 JSON），不含 TLS/HTTP 头帧与分帧开销")
}

func pipeUsage(p *pipeReadout, in bool) kernel.Measure {
	if p == nil {
		return kernel.AbsentBecause("本地分析件不报 token；这台机也没有模型端点可问")
	}
	if !p.UsageSaid {
		return kernel.AbsentBecause("端点这轮回帧里没有 usage 字段 —— 没说 ≠ 报了 0，两个是不同事实")
	}
	n, which := p.UsageOut, "completion_tokens"
	if in {
		n, which = p.UsageIn, "prompt_tokens"
	}
	src := "端点自报的 " + which + "（转述档：分词器在对端，我数不出来）"
	if n == 0 {
		src += "；本机量过的坑：流式的推理型端点这几个数恒为 0 ⇒ 停在 relayed，不许升 measured"
	}
	return kernel.RelayedOf(n, src)
}

func finishOf(p *pipeReadout) string {
	if p == nil {
		return "stop" // 本地分析件自己收尾，它说得出"这一发结束了"
	}
	return p.Finish
}

func modelOf(p *pipeReadout) string {
	if p == nil {
		return "pgagent-offline-analyzer（本地分析件，不是模型端点）"
	}
	return p.Model
}

func wireFormatOf(p *pipeReadout) string {
	if p == nil {
		return "pgagent.local.turn"
	}
	return p.WireObject // 空串 = 对端没自报；配 WireFormatSaid=false，不拿我们自己的常量冒充
}

// retryOf 把 Retry-After 头翻成那一格，三种事实分开：没这个头（对端没说）、有头但这一版读不懂
// （原话照抄进理由，不猜）、读出了秒数（measured —— 我是从响应头读的，不是端点自报 token 那种转述档）。
// 以前这一格永远是 absent + "这一版没解析"，于是"对端明明说了要等 7 秒"在账上长成"没说"。
func retryOf(p *pipeReadout) kernel.Measure {
	if p == nil {
		return kernel.AbsentBecause("这一发没打端点：没有响应头可读")
	}
	if p.RetrySaid {
		return kernel.MeasuredOf(p.RetryAfter)
	}
	if p.RetryRaw != "" {
		return kernel.AbsentBecause("响应头里有 Retry-After 但这一版读不懂（原话：" + p.RetryRaw + "）⇒ 没说 ≠ 说了 0，不猜")
	}
	return kernel.AbsentBecause("这一发的响应头里没有 Retry-After：对端没说 ≠ 说了 0")
}

// failureOf 把第 ⑧ 步那一发分三种形状：
// 没打（pipe=nil）／打了正常回（Kind 空）／打了没回或回错（transport / http / protocol）。
// "没收到响应"时状态码那一格必须是缺席 —— 内核注释里写过这一格曾被写死成 measured(0)，
// 于是每一发没故障的往来都在账上说"我们量到状态码是 0"。
func failureOf(p *pipeReadout) kernel.Failure {
	if p == nil || p.Kind == "" {
		return kernel.Failure{
			Status:       kernel.AbsentBecause("正常收尾，没有故障状态码可记（没收到错误 ≠ 收到 0）"),
			RetryAfterMs: kernel.AbsentBecause("没故障就不该有「等多久」"),
		}
	}
	st := kernel.AbsentBecause("连的是 " + p.Kind + " 那一类：根本没收到响应，所以没有状态码 —— 不许记成 measured(0)")
	if p.Received {
		st = kernel.MeasuredOf(int64(p.Status))
	}
	return kernel.Failure{
		Kind:         kernel.FailKind(p.Kind),
		Detail:       p.Detail, // 进账之前已在 callGateway 里擦过口令
		Status:       st,
		RetryAfterMs: retryOf(p),
		// 「降档重试」这一格只能给**真按流式收到过**那一发：内核有一条自洽判据
		// （原话："这一发本来就不是流式的，却建议「换成非流式再发一次」" ⇒ 整发拒收）。
		// 429 且正文刻意没读那一形里，我们请求的是流式、但一个正文帧都没收着 ⇒ Streaming=false，
		// 于是这一格只能跟着不降；那句"要不要改非流式重试"是本件自己的话，写在第 ⑧ 步里，不冒充账上那一格。
		Downgrade: p.Kind == "http" && p.BodyRead && (p.Status == 429 || p.Status >= 500),
	}
}
