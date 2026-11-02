package main

import (
	"fmt"
	"regexp"
	"strings"
	"time"
)

// 一发一循环。界面上亮的就是这九步。
//
// 关键纪律：没跑的步骤记 ran=false + basis=absent + 理由，**绝不因为"这一步在代码里存在"就标成跑过**。
// 内核那三步（预检/落账/读回）在 W4 才接；模型那一步在没有凭据的机器上是 NOT_RUN。
// 今天把它们标成 absent 而不是删掉，是为了让"缺口"在页面上看得见 —— 缺口看不见就是假绿。

type Emitter func(Step)

type Decision struct {
	Key    string `json:"key"`
	Side   string `json:"side"`
	Basis  string `json:"basis,omitempty"`
	Claim  string `json:"claim,omitempty"`
	Effect string `json:"effect"`
}

type SeamReply struct {
	Checked  bool
	Recorded bool
	ReadBack bool
	Verdict  string
	// RecordLine 是内核 record_call 那句**原话**（成功是"整发落账 49 条（输入侧 20 格 + 输出侧 29 格）…"，
	// 被挡是"写入被挡：这本账已到上限…"）。为什么单开一格、不并进 Verdict：W32 实测到并进去之后
	// 第 ⑤ 步替第 ⑥ 步说了话，同一列里于是出现两个数 —— 内核说"49 条"、我们自己写死"49 格"。
	// 一句话只归一个步说，数字才不会各写一遍。
	RecordLine string
	Reason     string
	Tally      string
	Verify     string
	Readers    string
	KPI        int
	Decisions  []Decision
	// DeclFail 记的是"这一格谁在读"那句声明**没落进账**的格（side/key：原因）。
	// 声明失败不能静默：账上没这条声明，readers_report 就会把那一格报成"没人声明读过"，
	// 而我们这边还喊着"读了 12 格" —— 两边各说各话就是假账。
	DeclFail []string
}

// seam 是内核接缝的插槽。W1 传 nil ⇒ 那三步如实记 absent。
var seam func(code, question, session string, turn int) (SeamReply, error)

// stepDelay 是"每步之间等多久"。它不是妆：这台机一圈跑完只要几十毫秒，
// 不留窗口就没人能真的打断 —— agentd 的 --shot-delay 同一课（没延时时的"能中断"是散文）。
var stepDelay time.Duration

// gatewayFake / gatewayTimeout 由 main.go 的旗标设定。
// 默认 false ⇒ 第 ⑧ 步是 NOT_RUN（不写 0）；开了也只打本机 127.0.0.1 的假端点，出不了这台机。
var (
	gatewayFake    bool
	gatewayTimeout = 4 * time.Second
)

// gatewayPrompt 是要发出去的那句话。贴进来的代码剪到 4000 字节：
// 不剪就等于把用户整份文件默认送出本机，而"发多少"这件事应该是显式的。
func gatewayPrompt(code, question string) string {
	return question + "\n\n```\n" + clipOne(code, 4000) + "\n```"
}

func aborted(ch <-chan struct{}) bool {
	select {
	case <-ch:
		return true
	default:
		return false
	}
}

// beat 在一步之后等一拍；期间 abort 关了就算被打断（返回 true）。nil 通道永不就绪 ⇒ 测试传 nil 就是"不可中断"。
// 先看一眼再等：中断必须立刻生效，不能让人最多再等一整拍（stepDelay 调到秒级时那会很蠢）。
func beat(abort <-chan struct{}) bool {
	if aborted(abort) {
		return true
	}
	if stepDelay <= 0 {
		return false
	}
	t := time.NewTimer(stepDelay)
	defer t.Stop()
	select {
	case <-t.C:
		return false
	case <-abort:
		return true
	}
}

// ledgerScope 给第 ⑩ 步那句"账 N 条"标清是哪一本账。W28 实测：换一次进程，内核账是新的、会话文件是旧的。
// 两个数**口径不同**（一个按进程数、一个按会话数），所以句子必须各自带标签，不能写成一句可以被相减的话；
// 会话文件里没有往轮时也不许说"那 0 发不在"（那是把空集说成有东西）。读不到盘时明说不知道，不写 0。
func ledgerScope(session string) string {
	s := fmt.Sprintf(" ｜ 这本账是本进程的（不分会话）：本进程至今落了 %d 发", landedCount())
	if storeRef == nil {
		return s + "；这一本会话文件没接上（store 未装）⇒ 此前有几发不知道，这里不写 0"
	}
	_, rows, _, err := storeRef.turnFloor(session)
	if err != nil {
		return s + fmt.Sprintf("；这一本会话文件读不回来（%v）⇒ 此前有几发不知道，这里不写 0", err)
	}
	if rows == 0 {
		return s + "；这一本会话文件此前没有往轮（新开张的一本）"
	}
	return s + fmt.Sprintf("；这一本会话文件此前有 %d 发 ⇒ 换过一次进程，账本从 0 重新起算，那 %d 发的账不在这个进程里", rows, rows)
}

var reZeroSet = regexp.MustCompile(`[那有记着共]\s*0\s*发`)

// clauseOf 从第 ⑩ 步那句长文里切出"这本账是本进程的…"那一段 —— 只审我自己写的那句。
// 内核那句"被内核判据拒 0 发"是**量到的零**，不是空集，不许拿来自拍子误伤（所以不扫全文）。
func clauseOf(tally string) string {
	i := strings.Index(tally, "这本账是本进程的")
	if i < 0 {
		return ""
	}
	return tally[i:]
}

// scopeSane 是"口径句"的机械判据。W29 那条教训：这句话逻辑全对、针也全绿，
// 第一次上屏却印出「此前记着 0 发 ⇒ 那 0 发不在这本账上」—— 进程数与会话数混在一句里等于邀请相减，
// 还把空集说成有东西。判据只认形状，不认我当时的自信。
func scopeSane(clause string) (bool, string) {
	if clause == "" {
		return false, "第 ⑩ 步里没有口径句 —— 装了接缝就该说清这是哪一本账"
	}
	if !strings.Contains(clause, "（不分会话）") || !strings.Contains(clause, "这一本会话文件") {
		return false, "两个数没各带口径标签（一个按进程数、一个按会话数，混在一句里会被相减）：" + clause
	}
	if z := reZeroSet.FindString(clause); z != "" {
		return false, "把空集说成了有东西（「" + z + "」）：" + clause
	}
	return true, clause
}

// traceSane 是"整列自洽"的机械判据。W32/W33/W34 三波各自修过一句假话，形状全都一样：
// 同一发里两句话对同一个事实说法不一，或者把"没量／没读／没收到"演成"量到／答了／收完"。
// 靠记性守一定复发（W30 那条口径句就是这么教训我的），所以做成一条能跑的判据 —— 每一发过它。
// 它只看**上屏的那句话**，不看我以为写了什么：读数与打印件不一致时，红的是打印件。
func traceSane(res Result) (bool, []string) {
	找 := func(名 string) (Step, bool) {
		for _, s := range res.Trace {
			if s.Name == 名 {
				return s, true
			}
		}
		return Step{}, false
	}
	五, 有五 := 找("kernel.check_call")
	六, 有六 := 找("kernel.record_call")
	七, 有七 := 找("kernel.read_back")
	八, 有八 := 找("gateway")
	十, 有十 := 找("kernel.tally")
	红 := []string{}
	在册 := map[string]bool{}
	for _, 名 := range traceSane规则 {
		在册[名] = true
	}
	// 每条规则带一个名：判据一次跑十一条，红了却不说是哪条咬的，等于把"哪一处骗人"又变回手感。
	// 名字还得落在 traceSane规则 上 —— 夹带一个没列的名，这条判据自己就是假账。
	咬 := func(名, 话 string) {
		if !在册[名] {
			红 = append(红, "规则名没在册｜判据咬了「"+名+"」，可规则清单里没有这一条："+话)
			return
		}
		红 = append(红, 名+"｜"+话)
	}

	// 1 谁拒的：预检过了 ⇒ 落账那句不许甩锅给预检（W32 实测到的第一句假话）
	if 有五 && 六.Name != "" && !六.Run && 五.Run && strings.Contains(六.Summary, "预检就拒了") {
		咬("谁拒的没对上", "第 ⑤ 步 ran=true（预检过了），第 ⑥ 步却说「预检就拒了」⇒ 同一列里两句话打脸："+六.Summary)
	}
	// 2 缺席必须带理由：⑥ 没跑时那句冒号后面不许是空的（W32 第二句、W26 同族）
	for _, s := range []Step{六, 七} {
		if s.Name == "" || s.Run {
			continue
		}
		剩 := strings.TrimSpace(s.Summary)
		for _, 前 := range []string{"没读回：", "没落账（", "这一步没东西可印："} {
			if strings.HasPrefix(剩, 前) {
				剩 = strings.TrimSpace(strings.TrimPrefix(剩, 前))
			}
		}
		if 剩 == "" || strings.HasSuffix(剩, "：") {
			咬("缺席没理由", s.Name+" 记的是缺席，但那句话没带理由（absent 必带理由）："+s.Summary)
		}
	}
	// 3 第 ⑧ 步：报了失败归因又报 0 帧 ⇒ 必须自带"没读／没收到"那类免责，否则 0 看着像量到的。
	// 只在**正文没读**时管：正文读过而帧数是 0，那是真数出来的 0（畸形帧那一形），不该被逼着写免责。
	if 有八 && res.Gateway != nil && !res.Gateway.BodyRead &&
		strings.Contains(八.Summary, "归因") && strings.Contains(八.Summary, "0 帧") &&
		!strings.Contains(八.Summary, "没读") && !strings.Contains(八.Summary, "没收到") {
		咬("0帧没来历", "第 ⑧ 步把「0 帧」光秃秃地报出来却没说为什么没量到："+八.Summary)
	}
	// 4 第 ⑧ 步：一个字的正文都没回，就不许只报"读回 N 字节"（那是过网线的字节，W34 那一形）
	if 有八 && res.Gateway != nil && strings.TrimSpace(res.Gateway.Text) == "" &&
		!strings.Contains(八.Summary, "正文 0 字") {
		咬("空正文装答了", "端点没回正文，第 ⑧ 步却没写「正文 0 字」⇒ 屏幕上像它答了："+八.Summary)
	}
	// 5 一格两数：第 ⑦ 步喊的两个数必须与打印件同源（读回格数 = decisions 长度，改写数 = KPI）
	if 有七 && 七.Run {
		数 := reReadBack.FindStringSubmatch(七.Summary)
		if 数 == nil {
			咬("一格两数", "第 ⑦ 步没按「读回 N 格，其中 M 格…」的形状说话："+七.Summary)
		} else if 数[1] != fmt.Sprint(len(res.Decisions)) || 数[2] != fmt.Sprint(res.KPI) {
			咬("一格两数", fmt.Sprintf("第 ⑦ 步喊的数与打印件不一致（它说读回 %s／改写 %s，实际 %d／%d）",
				数[1], 数[2], len(res.Decisions), res.KPI))
		}
	}
	// 6 落了账那一发里，收口那三步的缺席句也不许说"这一发没进账"（与规则 9 同族：一处盯步、一处盯未决）。
	// 原本这里写的是「⑥ ran 必须等于 ⑩ ran」—— 那是错的口径：tally 数的是整本账，反臂里
	// 落账成功而收口三步没打是**设计如此**，两个 ran 本来就可以不一样。针 41 甲半边一跑就撞出来，
	// 于是改成量话不量旗标（判据自己也在这一针里被红过一遍，不是只红别人）。
	if 有六 && 六.Run && 有十 && !十.Run && strings.Contains(十.Summary, "没进账") &&
		!strings.Contains(十.Summary, "落了账") {
		咬("落了账收口却说没进账", fmt.Sprintf("第 ⑥ 步 ran=true（账落了），第 ⑩ 步那句缺席的理由却说「没进账」：%s", 十.Summary))
	}
	// 7 被拒那一发：LedgerReject 有话时第 ⑥ 步必须没跑（否则"落账成功"与"被拒"并存）
	if res.LedgerReject != "" && 六.Name != "" && 六.Run {
		咬("拒了又说落了", "带着 ledger_reject 却说这一发落了账："+六.Summary)
	}
	// 8 measured(0) 的白名单：正文没读的时候那四格的 0 是"没量"，署成 measured 就是编数
	if res.Gateway != nil && !res.Gateway.BodyRead {
		for _, d := range res.Decisions {
			if d.Basis == "measured" && strings.HasPrefix(strings.TrimSpace(d.Claim), "0") &&
				(d.Key == "chunks" || d.Key == "first_byte_ms" || d.Key == "max_gap_ms" || d.Key == "wire_bytes_in") {
				咬("没量写成measured", "正文没读那一形里 "+d.Key+" 署成了 measured(0) ⇒ 把没量写成量到")
			}
		}
	}
	// 9 未决那栏也在同一列里说话：第 ⑥ 步 ran=true（账落了）时，任何一条"为什么没量到"
	// 都不许写"这一发压根没落账"。针 41 甲半边先在收口三步那句上抓到，回头发现未决栏是同一族的第二处。
	if 有六 && 六.Run {
		for _, u := range res.Unknowns {
			if strings.Contains(u.WhyAbsent, "压根没落账") {
				咬("落了账却说没落", "第 ⑥ 步 ran=true（账落了），未决那栏却写着「压根没落账」："+u.What+"｜"+u.WhyAbsent)
			}
		}
	}
	// 11 「整列 N 步自洽」这句自己也得对得上列里的步数 —— 判据喊的是整列，数错了就是"一格两数"同族。
	// 这一条是 W35 的浏览器读数抓的：判据先在 12 步那一刻算完，stop 那步是算完之后才补的，
	// 于是屏幕上「真跑了 13/13 步」与「整列 12 步自洽」并排亮着。修法有两半：判据挪到 stop 之后算，
	// 再加这一条把"喊的步数 ≠ 列里的步数"钉住 —— 只修文案不钉判据，下次换个地方一样复发。
	if res.TraceSane {
		n := reTraceCount.FindStringSubmatch(res.TraceSaneWhy)
		if n == nil {
			咬("自洽句自己数错了步", "过了判据却没写「整列 N 步自洽」这种可核对的形状："+res.TraceSaneWhy)
		} else if n[1] != fmt.Sprint(len(res.Trace)) {
			咬("自洽句自己数错了步", fmt.Sprintf("那句喊整列 %s 步自洽，列里现在有 %d 步 ⇒ 两个数并排上屏", n[1], len(res.Trace)))
		}
	}
	// 12 硬约束：这一发有没有执行用户代码，必须写在脸上且为否
	if res.Executed {
		咬("执行了用户代码", "这一发执行了用户代码 ⇒ 目标的第一条硬约束破了")
	}
	return len(红) == 0, 红
}

var reReadBack = regexp.MustCompile(`读回 (\d+) 格，其中 (\d+) 格`)

// traceSane规则 是上面那条判据的规则名清单。为什么要单独列出来：判据里每咬一条就得上一次屏，
// 而"清单有几条"必须是数出来的 —— 夹带一条没列的名、或列了却从不咬，都让"每条规则配一臂"变成空话。
// 这与内核那面「目录 26 条 vs 分支 20 条」的数法是一族：声明与实现对账，不靠印象。
var traceSane规则 = []string{
	"谁拒的没对上", "缺席没理由", "0帧没来历", "空正文装答了", "一格两数",
	"落了账收口却说没进账", "拒了又说落了", "没量写成measured", "落了账却说没落",
	"自洽句自己数错了步", "执行了用户代码",
}

var reTraceCount = regexp.MustCompile(`整列 (\d+) 步自洽`)

// runLoop 走那一圈。abort 被关掉 ⇒ 立刻收口，但**收口照做**：
// 已经亮出来的步数、已经落进账的格子、五档读数都得留下，并写明"这一发是怎么结束的"。
// 打断了就不交账（agentd 的六态退出码同族），交出去的只是"没跑完"这三个字。
func runLoop(code, question, lang, session string, turn int, emit Emitter, abort <-chan struct{}, stack string) Result {
	var res Result
	var pend []Step
	res.Session = session
	res.Turn = turn
	res.Question = question
	res.Executed = false
	res.StopReason = "跑完"
	res.Findings = []Finding{}
	res.Unknowns = []Unknown{}

	t0 := time.Now()
	st := func(no int, name, out string, basis Basis, ran bool) {
		s := Step{No: no, Name: name, Summary: out, Basis: basis, Run: ran, Ms: time.Since(t0).Milliseconds()}
		res.Trace = append(res.Trace, s)
		emit(s)
	}
	finish := func() Result {
		// 打断那一跳最容易塌成一态的地方：五档全 0 会被读成"量到 0 条"。
		// 所以没走到的语义步要逐条记 absent + 理由，让"这一发停在哪"成为账上的一条读数。
		if res.StopReason != "跑完" {
			seen := map[string]bool{}
			for _, s := range res.Trace {
				seen[s.Name] = true
			}
			var skipped []string
			for _, want := range []string{"intake", "shape", "select-analyzers", "analyze",
				"kernel.check_call", "kernel.record_call", "kernel.read_back", "gateway", "fold"} {
				if !seen[want] {
					skipped = append(skipped, want)
				}
			}
			if len(skipped) > 0 {
				res.Unknowns = append(res.Unknowns, Unknown{
					What:      "被打断后没走到的步骤：" + strings.Join(skipped, "、"),
					WhyAbsent: fmt.Sprintf("这一发停在%s；这些步骤根本没执行，不是执行了且没结果", res.StopWhy),
					HowToGet:  "再发一发（页面点发起，或 curl 走 /api/turn）；带 -step-delay 时可以停在任意一步之后",
					Basis:     Absent,
				})
			}
		}
		if res.Intent == "" {
			// 早停那一发根本没走到 ④ ⇒ 没做路由。这里不补一个"看起来像路由过"的说法。
			res.AnswerSummary = answerLine(res.Findings, len(res.Unknowns))
		} else {
			res.AnswerSummary = answerFor(Intent{Kind: res.Intent, Why: res.IntentWhy},
				res.Findings, len(res.Unknowns), res.Metrics, res.Debug != nil)
		}
		mixOf(&res)
		st(9, "fold", fmt.Sprintf("五档 %d/%d/%d/%d/%d，加总 %d 条（恒等式 %v）",
			res.Mix.Measured, res.Mix.Estimated, res.Mix.ModelSays, res.Mix.Relayed, res.Mix.Absent, res.Mix.Total, res.MixOK), Measured, true)
		// 内核的补账放在收口之后按顺序发：步骤号 1-9 是目标里那九步的编号，不许被打乱。
		for _, s := range pend {
			st(len(res.Trace)+1, s.Name, s.Summary, s.Basis, s.Run)
		}
		// 整列自洽判据：stop 那一步也发完了才审 —— 「整列」得是页面上真正亮出来的那一整列。
		// W35 的浏览器读数抓到过 12 与 13 两个版本并排上屏（判据先算、stop 后补），判据第 11 条现在钉着这件事。
		// 红不红都要落进读数并上屏 —— 判据只活在返回值里，等于没有判据。
		res.StopWhy = stopLine(res, res.StopAt)
		st(len(res.Trace)+1, "stop", res.StopWhy, Measured, true)
		var 自洽红 []string
		res.TraceSane, 自洽红 = traceSane(res)
		if res.TraceSane {
			res.TraceSaneWhy = fmt.Sprintf("整列 %d 步自洽（过了 %d 条判据：谁拒的、缺席的理由、0 的来历、读回的数、落了账不许说没落）",
				len(res.Trace), len(traceSane规则))
		} else {
			res.TraceSaneWhy = strings.Join(自洽红, "；")
		}
		return res
	}

	// ①②：先算一次，两步都用同一份数（同一发里两个步骤各数一遍会数出两个不同的数，那是假账）
	an := analyze(code, lang)
	res.Metrics = an.Metrics
	// ① 就把"这一发会不会落得了账"预告出来 —— 边界读数抓到过：贴 200KB 或写 50KB 的问题时，
	// 用户要点完发才知道账没落。预告用内核自己算出来的生效额度（DeriveBudget 是公式的唯一 owner），
	// 且只敢做**单向**断言：说超 ⇒ ⑤ 必须拒；说不超 ⇒ 仍可能被按段的回夹拒掉，那一刀只有内核知道。
	res.PartsBytes = pgPartsBytes(question, code)
	preLine := "预算算不出来（不猜）："
	if b, berr := pgBudget(); berr != nil {
		preLine += berr.Error()
	} else {
		res.EffectiveCeil = b.EffectiveCeiling
		res.BudgetOver = res.PartsBytes > b.EffectiveCeiling
		verdict := "不超（仍可能被按段回夹拒掉，那一刀只有内核知道）"
		if res.BudgetOver {
			verdict = "超了 ⇒ 这一发不会落账（把代码或问题分开发，或只贴关键那段）"
		}
		preLine = fmt.Sprintf("｜要进账的 parts=%d 字节、本机生效额度 %d 字节 ⇒ %s", res.PartsBytes, b.EffectiveCeiling, verdict)
	}
	st(1, "intake", fmt.Sprintf("%d 字节 / %d 行 / 指纹 %s%s", an.Metrics.Bytes, an.Metrics.Lines, an.Metrics.SHA256, preLine), Measured, true)
	if hit := beat(abort); hit {
		res.StopReason, res.StopAt = "被打断", "第 1 步之后"
		return finish()
	}

	shape := fmt.Sprintf("判为 %s（%s）；真解析%s；函数 %d 个、import %d 条（其中 %d 条疑似没用到）｜凭什么：%s",
		an.Metrics.Lang, orDash(an.Metrics.LangHow), map[bool]string{true: "过了", false: "没过"}[an.Metrics.Parsed],
		an.Metrics.Funcs, an.Metrics.Imports, an.Metrics.UnusedImports, an.Metrics.LangWhy)
	if !an.Metrics.Parsed && an.Metrics.LangHow != "用户显式选定" {
		shape += "｜注意：语言这一格是推断出来的，函数/import 两个数是文本匹配数出来的"
	}
	st(2, "shape", shape, Measured, true)
	if hit := beat(abort); hit {
		res.StopReason, res.StopAt = "被打断", "第 2 步之后"
		return finish()
	}

	// ③ 选件：武装了什么要说得出理由，没武装的也要说出来（缺口不看见就是假绿）
	rules, howMany := familiesFor(an.Metrics.Lang, an.Metrics.Parsed)
	rules += " +通用(todo,hardcoded-secret(maybe))"
	howMany += 2
	if stack != "" {
		rules += " + debug(栈→行)"
		howMany++
	} else {
		rules += "（没给报错/栈 ⇒ debug 不武装）"
	}
	rules += " + optimize(度量→建议)"
	howMany++
	st(3, "select-analyzers", fmt.Sprintf("%s｜共 %d 族", rules, howMany), Measured, true)
	if beat(abort) {
		res.StopReason, res.StopAt = "被打断", "第 3 步之后"
		return finish()
	}

	// ④ 实算
	res.Findings = an.Findings
	res.Unknowns = an.Unknowns
	if stack != "" {
		fs, un, inRange, total := debugFindings(stack, strings.Split(code, "\n"))
		res.Findings = append(res.Findings, fs...)
		res.Unknowns = append(res.Unknowns, un...)
		res.Debug = &DebugReadout{StackBytes: len([]byte(stack)), Frames: total, InRange: inRange}
	} else {
		res.Unknowns = append(res.Unknowns, Unknown{
			What: "报错/栈 → 行号", WhyAbsent: "这一发没给栈文本（代码框里那段只当代码分析）",
			HowToGet: "把终端输出原样贴进「报错/栈」那一栏再发一发", Basis: Absent,
		})
	}
	os2, ou2 := optimize(an.Metrics)
	res.Findings = append(res.Findings, os2...)
	res.Unknowns = append(res.Unknowns, ou2...)
	// 问题路由：让"提的问题"真的动这一发的顺序与结论（关键词表，不是模型理解；见 intent.go）。
	it := intentOf(question)
	res.Intent = it.Kind
	res.IntentWhy = it.Why
	res.Findings = prioritize(res.Findings, it.Kind)
	st(4, "analyze", fmt.Sprintf("findings %d 条（measured %d / estimated %d）；栈帧 %d 个、落进贴入范围 %d 个；问题路由=%s（%s）",
		len(res.Findings), countBasis(res.Findings, Measured), countBasis(res.Findings, Estimated),
		frameCount(res), inRangeCount(res), it.Kind, it.Why), Measured, true)
	if beat(abort) {
		res.StopReason, res.StopAt = "被打断", "第 4 步之后（实算已完成，还没进账）"
		return finish()
	}

	// ⑧ 的那一次调用要**在这里**发生：账要先带上通道读数，否则那七格只能记 absent。
	// 界面上它仍然作为第 8 步亮出来（下面 st(8, ...) 用的是同一份读数，不是第二次调用）——
	// 顺序与编号不一致这件事我在第 ⑧ 步那句话里写死，免得下一个人以为有两发。
	var gw *pipeReadout
	var gwWhy string
	if cfg, why := detectGateway(gatewayFake); why == "" {
		p, err := callGateway(cfg, gatewayPrompt(code, question), gatewayTimeout)
		if p != nil {
			// 失败那一发也带读数：打了没打通 ≠ 没打。账要能分出这两种，才谈得上失败归因。
			gw = p
			pipe = p
			defer func() { pipe = nil }() // 下一发不许继承上一发的通道读数
		}
		if err != nil {
			gwWhy = err.Error()
		}
	} else {
		gwWhy = why
	}

	// ⑤⑥⑦ 内核三步
	if seam == nil {
		why := "内核接缝未装（W4 段接：同进程 mcpsrv + check_call/record_call/read_back，只消费格）"
		st(5, "kernel.check_call", why, Absent, false)
		st(6, "kernel.record_call", why, Absent, false)
		st(7, "kernel.read_back", why, Absent, false)
		res.Unknowns = append(res.Unknowns, Unknown{
			What: "这一发有没有真的进账、账上触发过几次决定", WhyAbsent: why,
			HowToGet: "W4 装上接缝；KPI 与反臂同 agentd 那条（不读回 ⇒ 掉回 0）", Basis: Absent,
		})
	} else {
		reply, err := seam(code, question, session, turn)
		if err != nil && !res.BudgetOver {
			res.LedgerReject = err.Error()
		}
		// ① 的预告与第 ⑤ 步必须对得上（单向）：说"超了不会落账"却照样落了账 ⇒ 那句预告在骗人。
		{
			ok := !(res.BudgetOver && reply.Checked)
			res.BudgetPreOK = &ok
		}
		res.Decisions = reply.Decisions
		// 先把账上的决定落到结果里，再发这三步的事件 —— 不然步骤⑦喊的数与结果里的数会是两个数
		// （刚才就喊出了 12 与 9 两个版本；一格两数是假绿的入口）。
		res.KPI = applyDecisions(&res, reply)
		// 每一步自己说自己跑没跑：不能因为"接缝装了"就三步全绿 ——
		// 预检红 ⇒ 后面根本不该有落账；反臂（不读回）⇒ 读回这步如实记没跑。
		// 第 ⑤ 步的话只能由第 ⑤ 步自己说：`orLine` 一见到 err 就把整句换成「接缝报错：…」，
		// 而账满那一形的 err 是**第 ⑥ 步**报的 ⇒ 页面上第 ⑤ 步看着像是被拒的那个地方，
		// 内核预检那句原话（"输入侧：自洽"）整条被盖掉。针 38 实测到这一形。
		五话 := reply.Verdict
		if !reply.Checked || 五话 == "" {
			五话 = orLine(reply.Verdict, err)
		}
		st(5, "kernel.check_call", 五话, stepBasis(reply.Checked), reply.Checked)
		// 第 ⑥ 步那句"没落账"到底是谁拒的，只能按第 ⑤ 步的实际读数分岔：W32 实测 —— 账到上限那一形里
		// 预检是过的（内核原话："这是外壳按部署方给的容量挡的，不是内核判据拒的"），
		// 而这句写死了"预检就拒了"，跟同一列里亮着"预检过了"的第 ⑤ 步当场打脸。
		recNo := "没落账（第 ⑤ 步预检就拒了 ⇒ 一条都不该写）"
		if reply.Checked {
			谁 := reply.RecordLine
			if 谁 == "" {
				谁 = reply.Reason
			}
			if 谁 == "" {
				谁 = "接缝没交原因 ⇒ 这里不替它圆，去内核那侧找这一笔"
			}
			// 内核那句原话里指的路是它自己那面的旗标名（mcpsrv 的 -max-entries）。照抄不改是规矩，
			// 但抄完得说清"这一台该敲哪个" —— 否则人照着屏幕去敲 -max-entries，这台服只回一句 flag not defined。
			if strings.Contains(谁, "-max-entries") {
				谁 += "（上面是内核原话，里面的 -max-entries 是内核那面 mcpsrv 的旗标；这一台服的是 -entry-cap）"
			}
			recNo = "没落账（第 ⑤ 步预检是过了的 ⇒ 挡下这一发的是门口那道门，不是内核判据）：" + 谁
		}
		yesNo := "整发落账（这一句是内核 record_call 的原话，不是我按 48 键/49 格算出来的）：" + reply.RecordLine
		if reply.Recorded && reply.RecordLine == "" {
			// 桩接缝（单测里那些）不给原话：这格就老实说"内核点了头、但没交来那句话"，
			// 不许把"落账成功"这句话由我们自己补全 —— 那等于把没量到的写成量到的。
			yesNo = "整发落账（接缝点了头，但没带回内核那句原话 ⇒ 这里不替它补）"
		}
		st(6, "kernel.record_call", stepNote(reply.Recorded, yesNo, recNo),
			stepBasis(reply.Recorded), reply.Recorded)
		rbNote := fmt.Sprintf("三轴读回（session/发号/侧）；读回 %d 格，其中 %d 格真的改写了这一发的结果",
			len(reply.Decisions), res.KPI)
		if len(reply.DeclFail) > 0 {
			rbNote += fmt.Sprintf("｜读者声明有 %d 格没落账：%s", len(reply.DeclFail), strings.Join(reply.DeclFail, "；"))
			res.Unknowns = append(res.Unknowns, Unknown{
				What: "这几格「谁在读」没进账",
				WhyAbsent: fmt.Sprintf("declare_reader 失败/被拒 %d 格：%s ⇒ readers_report 会把它们报成没人声明读过，本件不替它们圆",
					len(reply.DeclFail), strings.Join(reply.DeclFail, "；")),
				HowToGet: "看内核那句拒收原话（多半是 key/side 不在表上）；改调用方，不动判据表",
				Basis:    Absent,
			})
		}
		st(7, "kernel.read_back", stepNote(reply.ReadBack, rbNote, "没读回："+reply.Reason),
			stepBasis(reply.ReadBack), reply.ReadBack)
		// 收口那三步：内核没回话时**不许整块缺席**。边界读数抓到过这一形 —— 贴进 200KB 时预检被拒，
		// 页面上只剩 ①-④⑧⑨，"账没落成"这件事发生在哪一步看不出来；缺席与"跑了但没东西可印"长一个样。
		// 所以照⑤⑥⑦那条口径来：如实记成没跑 + 一句为什么，别把它省成"看不见就等于没发生"。
		// 那句"为什么"必须按这一发的实际读数分岔：针 41 的整列判据抓到第四句假话 —— 反臂那一形里
		// 账是落了的（第 ⑥ 步喊"整发落账"），这三步却没写死一句"这一发没进账"，同一列当场打脸。
		没进账 := "这一发没进账：" + orLine(reply.Verdict, err)
		if reply.Recorded {
			原 := reply.Reason
			if 原 == "" {
				原 = orLine(reply.Verdict, err) + "（接缝没交原因，这里不替它圆）"
			}
			没进账 = "这一发落了账，可收口那三步没打：" + 原
		}
		noClose := func(name string) Step {
			return Step{Name: name, Summary: "这一步没东西可印：" + 没进账,
				Basis: Absent, Run: false}
		}
		if reply.Tally != "" {
			pend = append(pend, Step{Name: "kernel.tally", Summary: reply.Tally + ledgerScope(session), Basis: Measured, Run: true})
		} else {
			pend = append(pend, noClose("kernel.tally"))
		}
		if reply.Verify != "" {
			pend = append(pend, Step{Name: "kernel.verify", Summary: reply.Verify, Basis: Measured, Run: true})
		} else {
			pend = append(pend, noClose("kernel.verify"))
		}
		if reply.Readers != "" {
			// 「49 格里有几格没人声明读过」—— 内核自己核不到的那一半，声明了才有人证。
			pend = append(pend, Step{Name: "kernel.readers_report", Summary: reply.Readers, Basis: Measured, Run: true})
		} else {
			pend = append(pend, noClose("kernel.readers_report"))
			未决 := "这一发压根没落账 ⇒ 内核那边没有五档、没有 verify 结论、也没有读者报告可取；" +
				"被拦的原因：" + orLine(reply.Verdict, err) +
				fmt.Sprintf("（本机预算上限 %d 字节，贴进来的代码字节算进 parts）", pgCeiling)
			拿 := "把字节降到预算内，或分批发；这是调用侧的额度问题，不是判据表的问题 —— 表一个字不动"
			if reply.Recorded {
				// 同一族第二处：账落了、只是这三步没打（反臂与读回报错走的就是这一条）。
				// 写"压根没落账"会和第 ⑥ 步那句"整发落账"当场打脸 —— 判据的第十条就是量这一处。
				// 原因直接引上面那句 没进账：一处事实只在一个地方算，两处各算一遍就会有两个版本。
				未决 = "这一发落了账，可内核侧的收口读数（tally / verify / readers_report）没打；原因：" +
					"见第 ⑩ 步那三格 —— " + 没进账
				拿 = "把 read_back 打开再发一发（-read-back=false 是反臂，关掉它会把这三步一起省掉）；" +
					"或看第 ⑩ 步那句缺席的理由里指的是哪一步"
			}
			res.Unknowns = append(res.Unknowns, Unknown{
				What:      "内核侧的收口读数（tally / verify / readers_report）",
				WhyAbsent: 未决,
				HowToGet:  拿,
				Basis:     Absent,
			})
		}
		res.KPIWhy = fmt.Sprintf("KPI = 账上读回来的值/出处档真的改写了结果的那几格（%d 格，读回共 %d 格）；"+
			"反臂：不 read_back ⇒ 0 格", res.KPI, len(reply.Decisions))
	}
	if beat(abort) {
		res.StopReason, res.StopAt = "被打断", "第 7 步之后（账已落，读回已完成）"
		return finish()
	}

	// ⑧ 模型补充（三态：没打 / 打了但失败 / 打了且回了帧 —— 三件事，不许塌成一件事）
	if gw != nil && gw.Kind == "" {
		res.Gateway = gw
		st(8, "gateway", gw.gatewayLine()+
			"｜调用发生在第 5-7 步之前（账要带读数），本步只是把那一次读数亮出来，没有第二次", Measured, true)
		if txt := strings.TrimSpace(gw.Text); txt != "" {
			res.Findings = append(res.Findings, Finding{
				ID: "G1", Rule: "gateway-text", Severity: "minor",
				Evidence: fmt.Sprintf("从通道上收到的正文 %d 字节（我自己数的），端点收尾=%s，帧数=%d",
					len(txt), orDash(gw.Finish), gw.Chunks),
				Basis:  ModelSays,
				Claim:  "端点原话（照抄，不解读）：" + clipOne(txt, 200),
				Verify: "同一句话再问一遍，比对是不是同一份回帧；对不上就别写「它一直这么说」",
			})
		} else {
			// 本机量过的形状：token 花在 reasoning 上、content 是空的。
			// 这记的是"通道上没带回正文"，不许塌成"它说了空话"。
			res.Unknowns = append(res.Unknowns, Unknown{
				What: "端点给的正文",
				WhyAbsent: fmt.Sprintf("通道是通的（收了 %d 字节、%d 帧）但一个正文字节都没带回来；收尾=%s —— 这是「没收到」，不是「它说没有」",
					gw.BytesIn, gw.Chunks, orDash(gw.Finish)),
				HowToGet: "看第 ⑧ 步那句的收尾字段；或换非流式再发一发（本机量过：非流式才给 usage 真数）",
				Basis:    Absent,
			})
		}
	} else if gw != nil {
		// 打了、但没打通或回错：这一步**跑过**（ran=true），只是结果是一条失败归因。
		// 记 ran=false 就是把"打失败了"擦成"没打"，而这两种形状在账上长得不一样。
		res.Gateway = gw
		st(8, "gateway", gw.gatewayLine()+
			"｜调用发生在第 5-7 步之前，失败归因已经跟着那一发进账（fail_kind 那一格）", Measured, true)
		res.Unknowns = append(res.Unknowns, Unknown{
			What: "模型给的额外解释与优化建议",
			WhyAbsent: fmt.Sprintf("第 ⑧ 步真打了，但没拿到回帧正文（归因 %s：%s）—— 这是「打失败了」，"+
				"跟「根本没打」和「打了且它说没有」是三种形状，都不许写成「模型没话」", gw.Kind, gw.Detail),
			HowToGet: "读数在 gateway 那一步与账上 fail_kind / fail_status 两格；要重试就把 PGAGENT_BASE_URL 指回可用端点再发一发",
			Basis:    Absent,
		})
	} else {
		st(8, "gateway", "NOT_RUN（根本没打）："+gwWhy, Absent, false)
		res.Unknowns = append(res.Unknowns, Unknown{
			What:      "模型给的额外解释与优化建议",
			WhyAbsent: "第 ⑧ 步根本没跑（" + gwWhy + "）；这一格不许写成「没有建议」，那是把没跑读成跑过",
			HowToGet: "本机零成本：起服务时加 -fake-endpoint（打的是本机假端点，演示件，真实模型 0 次）；" +
				"真端点要先你批准，并把 PGAGENT_BASE_URL/PGAGENT_MODEL/PGAGENT_KEY 只走环境变量给我 —— 口令不进文件、不进账本、不进日志",
			Basis: Absent,
		})
	}
	if beat(abort) {
		res.StopReason, res.StopAt = "被打断", "第 8 步之后"
		return finish()
	}

	// ⑨ 收口
	res.StopReason, res.StopAt = "跑完", "九步走完"
	return finish()
}

// stopLine 是"这一发怎么结束的"那句读数：亮了几步、真跑了几步、账触发过几次、几条未决。
// 打断那一跳不许只留一个"停了"字 —— 已经落下来的东西要能点出来数。
// 计数把 stop 这一步自己也算进去（它马上就要被 append），否则页面上会出现两句对不上的"跑了 N 步"。
func stopLine(res Result, where string) string {
	ran := 0
	for _, s := range res.Trace {
		if s.Run {
			ran++
		}
	}
	return fmt.Sprintf("%s：到这里已亮 %d 步（真跑了 %d 步）、账本触发 %d 次决定、findings %d 条、未决 %d 条",
		where, len(res.Trace)+1, ran+1, res.KPI, len(res.Findings), len(res.Unknowns))
}

func answerLine(f []Finding, unknowns int) string {
	if len(f) == 0 {
		return fmt.Sprintf("结构类判据没命中（%d 条未决项都写了理由）；这不等于代码没问题 —— 只等于这几条尺子量不到", unknowns)
	}
	crit := 0
	for _, x := range f {
		if x.Severity == "critical" {
			crit++
		}
	}
	return fmt.Sprintf("命中 %d 条，其中 critical %d 条；每条带出处档与自己数出来的分母", len(f), crit)
}

func countBasis(fs []Finding, b Basis) int {
	n := 0
	for _, f := range fs {
		if f.Basis == b {
			n++
		}
	}
	return n
}

// stepBasis 是 ⑤⑥⑦ 那三步的出处档：跑了 = 值从账上回来过（measured），没跑 = 缺席（absent）。
// 为什么这一格不落"理由"参数：W32 检查时发现这里曾带一个 `why string` 参数、三处调用各塞了一句
// 理由（"落账由内核点头""值来自账上回帧"），而函数体一个字没读它 —— 写了等于没写，
// 那三句好话从没上过屏。缺席的真正理由由 ⑤⑥⑦ 各自的 summary（接缝报错 / 没落账 / 没读回：+ Reason）交，
// 那些才是人看得见的。参数删掉，别留一个"看起来会显示、其实不会"的口子。
func stepBasis(ran bool) Basis {
	if ran {
		return Measured
	}
	return Absent
}

func stepNote(ran bool, yes, no string) string {
	if ran {
		return yes
	}
	return no
}

// applyDecisions 把账上读回来的东西**真的落到结果里**，并数出落了几次。
// 数的是动作不是意图：没改写任何字段的一格不计 —— 否则 KPI 数的是"我们打算读"。
func applyDecisions(res *Result, rep SeamReply) int {
	decided := 0
	for _, d := range rep.Decisions {
		switch {
		case d.Basis == "absent":
			res.Unknowns = append(res.Unknowns, Unknown{
				What:      fmt.Sprintf("账上那一格「%s」（%s 侧）", d.Key, d.Side),
				WhyAbsent: "内核读回来的原话记的是缺席：" + d.Claim,
				HowToGet:  "只有真在通道上打到对端才量得到；这台机没开 socket 也没凭据",
				Basis:     Absent,
			})
			decided++
		case d.Basis == "measured" && d.Key == "content_bytes":
			if n, ok := firstInt(d.Claim); ok && n > 0 {
				// 账上的 content_bytes 是「这一发送出去的整块内容」，不是"贴进来的代码字节"。
				// 单独立一格，不覆盖 Metrics.Bytes —— 把两个量并成一格就是假绿。
				res.Metrics.LedgerContentBytes = n
				res.Metrics.BytesSource = "账上读回来的 content_bytes（整块送出量），与 metrics.bytes（贴进来的代码量）分列两格"
				decided++
			}
		case d.Key == "tokens" || d.Key == "usage_in" || d.Key == "usage_out":
			res.Metrics.TokensBasis = fmt.Sprintf("%s ← 账上 %s 侧 %s 档：%s",
				d.Key, d.Side, d.Basis, firstChunk(d.Claim))
			decided++
		case d.Basis == "measured" && d.Key == "retry_after_ms":
			// 端点在响应头里说了要等多久：这个数从账上读回来、落成独立一格（不并进第 ⑧ 步那句散文里）。
			if n, ok := firstInt(d.Claim); ok && n > 0 {
				res.Metrics.LedgerRetryAfterMs = n
				res.Metrics.RetryAfterSource = "账上读回来的 retry_after_ms（值来自响应头，不是我们估的）"
				decided++
			}
		}
	}
	return decided
}

func firstInt(s string) (int, bool) {
	neg := false
	i := 0
	for i < len(s) && !isdigit(s[i]) {
		if s[i] == '-' {
			neg = true
		}
		i++
	}
	j := i
	for j < len(s) && isdigit(s[j]) {
		j++
	}
	if j == i {
		return 0, false
	}
	n := 0
	for _, c := range s[i:j] {
		n = n*10 + int(c-'0')
	}
	if neg {
		return -n, true
	}
	return n, true
}

func isdigit(c byte) bool { return c >= '0' && c <= '9' }

func firstChunk(s string) string {
	if len(s) > 48 {
		return s[:48] + "…"
	}
	return s
}

func orLine(v string, err error) string {
	if err != nil {
		return "接缝报错：" + err.Error()
	}
	if v == "" {
		return "接缝回了空话（空话不算放行）"
	}
	return v
}

func frameCount(res Result) int {
	if res.Debug == nil {
		return 0
	}
	return res.Debug.Frames
}

func inRangeCount(res Result) int {
	if res.Debug == nil {
		return 0
	}
	return res.Debug.InRange
}
