package main

// Agent 调度循环：一句话 → 规划 → 选件 → 真跑 → 观察 → 再规划 → 收口。
// 三件纪律写在这里：
//   ① 每一步都发事件（tool_call / tool_status / tool_result），看得见不是装饰，是让人能指着某一步说它没跑；
//   ② 出处两轴分开：这一步是谁选的（estimated=本机规则 / model_says=端点）、这一格读数从哪来
//      （measured=本机真量到 / relayed=外部正文转述 / absent=没量到，必带理由）；
//   ③ 收口前整列过一遍自洽判据（turnSane），红就把红写在结果里 —— 判据自己也要有名字，
//      没在名册里的规则一律判红，免得"写了分支没人调用"这种死路被当成通过。

import (
	"context"
	"encoding/json"
	"fmt"
	"sort"
	"strings"
	"time"
)

const (
	EvMeasured = "measured"
	EvRelayed  = "relayed"
	EvAbsent   = "absent"
)

type Finding struct {
	Text string `json:"text"`
	Tier string `json:"tier"` // measured / estimated / model_says / relayed / absent
	Why  string `json:"why,omitempty"`
	Step int    `json:"step,omitempty"`
}

type Turn struct {
	Turn         int `json:"turn"`
	utterance    string
	Answer       string         `json:"answer"`
	AnswerTier   string         `json:"answer_tier"` // model_says=模型收口自己写的 / measured=本机按工具读数抄的
	AnswerWhy    string         `json:"answer_why,omitempty"`
	Findings     []Finding      `json:"findings"`
	Steps        []Observation  `json:"steps"`
	Stop         string         `json:"stop"` // 跑完 / 要补参数 / 步数上限 / 规划器全不可用 / 内部错 / 重复失败即停 / 没放行 / 被打断
	StopWhy      string         `json:"stop_why"`
	Plan         string         `json:"plan"`
	Fallbacks    []string       `json:"fallbacks,omitempty"` // 端点→本机规则这类"规划器降级"的逐条原因
	Retries      int            `json:"retries"`
	WaitedMs     int64          `json:"waited_ms"`
	Degrades     int            `json:"degrades"`
	Mix          map[string]int `json:"mix"`
	MixOK        bool           `json:"mix_ok"`
	Sane         *bool          `json:"sane,omitempty"`
	SaneWhy      string         `json:"sane_why,omitempty"`
	MS           int64          `json:"ms"`
	MemoryLen    int            `json:"memory_msgs"`
	Dropped      int            `json:"dropped_from_window"`
	ContextChars int            `json:"context_chars_used"`
}

type Agent struct {
	env *Env
	cfg Config
	mem *Memory
	reg *Registry
}

func NewAgent(env *Env, cfg Config) *Agent {
	return &Agent{env: env, cfg: cfg, mem: env.mem, reg: env.reg}
}

func (a *Agent) 规划器() []Planner {
	var 列 []Planner
	if a.cfg.ModelEndpoint != "" {
		列 = append(列, modelPlanner{cfg: a.cfg})
	}
	列 = append(列, localPlanner{})
	return 列
}

// RunTurn 跑一圈。emit 每步都调（SSE 往前端推），nil 时用哑函数。
func (a *Agent) RunTurn(ctx context.Context, utterance string, emit Emit) Turn {
	if emit == nil {
		emit = func(string, any) {}
	}
	start := time.Now()
	turn := a.mem.NextTurn()
	a.mem.SetNextTurn(turn + 1)
	a.mem.Append(Msg{Turn: turn, Role: "user", Text: utterance, At: start})
	res := Turn{Turn: turn, utterance: utterance, Stop: "跑完", Mix: map[string]int{}}
	pc := PlanCtx{Turn: turn, Utterance: utterance}

	emit("meta", map[string]any{"turn": turn, "plan": a.plannerNames(), "tools": a.reg.Count(),
		"max_steps": a.cfg.MaxSteps, "memory_msgs": a.mem.Count()})

	// 停：ctx 被取消（/api/stop 或连接断开）时也照样收口 —— 已经亮出来的步留在账上，
	// 没走到的语义步不补。把"没跑完"写成一条读数，而不是让页面停在半截。
	停 := func(步 int) Turn {
		res.Stop = "被打断"
		res.StopWhy = fmt.Sprintf("停止指令到了（/api/stop 或连接断开）⇒ 这一发停在步 %d；已经亮出来的 %d 步留在账上，没走到的不补",
			步, len(res.Steps))
		收口(a, &res, 步)
		return 收尾(a, &res, start, emit)
	}

	for 步 := 1; 步 <= a.cfg.MaxSteps; 步++ {
		if ctx.Err() != nil {
			return 停(步)
		}
		act, 用哪个, 降级话 := a.选一步(ctx, pc, emit, 步)
		res.Plan = 用哪个
		if 降级话 != "" {
			res.Fallbacks = append(res.Fallbacks, 降级话)
		}
		if ctx.Err() != nil {
			return 停(步)
		}
		switch act.Kind {
		case "ask":
			res.Stop = "要补参数"
			res.StopWhy = act.Why
			emit("plan", map[string]any{"step": 步, "kind": "ask", "why": act.Why, "plan": 用哪个})
			收口(a, &res, 步)
			return 收尾(a, &res, start, emit)
		case "done":
			res.Stop = "跑完"
			res.StopWhy = act.Why
			if 话 := strings.TrimSpace(act.Answer); 话 != "" {
				res.Answer = 话
				res.AnswerTier = "model_says"
				res.AnswerWhy = "模型端点收口时自己写的回答，原样收下；里面的事实仍要回看上面的步"
			}
			emit("plan", map[string]any{"step": 步, "kind": "done", "why": act.Why, "plan": 用哪个})
			收口(a, &res, 步)
			return 收尾(a, &res, start, emit)
		case "tool":
			// 落在这里
		default:
			res.Stop = "内部错"
			res.StopWhy = fmt.Sprintf("规划器交了不认识的 kind=%q", act.Kind)
			收口(a, &res, 步)
			return 收尾(a, &res, start, emit)
		}

		工, 认识 := a.reg.Get(act.Tool)

		// 同形失败不重撞：同一发里同样的工具+同样的参数已经没成过一次，就停下来。
		// 这条检查必须排在"没注册 / 门口挡 / 出网预检"之前：那几支以前都是 continue，
		// 下一轮会拿同一件再撞一次，白吃步数（T11 实测 6 步全是同一个被挡的 exec.run，自洽判据判红）。
		键 := 调用键(act.Tool, act.Args)
		for _, 旧 := range res.Steps {
			if 旧.Class != ClassOK && 旧.Tool != "" && 调用键(旧.Tool, 旧.Args) == 键 {
				res.Stop = "重复失败即停"
				res.StopWhy = fmt.Sprintf("第 %d 步已经用同样的参数撞过 %s 一次（类别 %s）⇒ 不再重撞，停下来问：%s",
					旧.Step, 旧.Tool, 旧.Class, 旧.Text)
				收口(a, &res, 步)
				return 收尾(a, &res, start, emit)
			}
		}

		if !认识 {
			o := Observation{Step: 步, Tool: act.Tool, Args: act.Args, ArgsFrom: act.From, Class: ClassUnsupported, Risk: "没注册",
				Text: fmt.Sprintf("这台机器上没注册过 %q（现有 %d 个：%s）", act.Tool, a.reg.Count(),
					截(strings.Join(a.reg.Names(), "、"), 160)),
				Attempts: 0, Why: act.Why, Provenance: act.Proven, Plan: 用哪个,
				Evidence: EvAbsent, AbsentWhy: "没有这个工具，所以这一格没有读数（不是它回了空）"}
			res.Steps = append(res.Steps, o)
			pc.Obs = append(pc.Obs, o)
			a.mem.Append(Msg{Turn: turn, Role: "tool", Tool: act.Tool, Class: ClassUnsupported, Text: o.Text, At: time.Now()})
			emit("tool_result", o)
			continue
		}
		spec := 工.Spec()
		if spec.RequiresFlag != "" && !a.cfg.旗标开了(spec.RequiresFlag) {
			o := Observation{Step: 步, Tool: spec.Name, Args: act.Args, ArgsFrom: act.From, Class: ClassRefused,
				Text:     fmt.Sprintf("没放行：%s 要 -%s 开着才允许跑（风险档 %s）", spec.Name, spec.RequiresFlag, spec.Risk),
				Attempts: 0, Why: act.Why, Provenance: act.Proven, Plan: 用哪个,
				Evidence: EvAbsent, AbsentWhy: "门口挡下，工具一次也没被调起"}
			a.mem.Append(Msg{Turn: turn, Role: "tool", Tool: spec.Name, Class: ClassRefused, Text: o.Text, Args: act.Args, At: time.Now()})
			// 门口挡这一形不许顺手降级到"别的能干同一件事的工具"：那是绕过用户的同意。
			// 也不许 continue 重撞：放行与否是用户的决定，再撞几次答案不会变。
			res.Steps = append(res.Steps, o)
			pc.Obs = append(pc.Obs, o)
			emit("tool_result", o)
			res.Stop = "没放行"
			res.StopWhy = fmt.Sprintf("%s 要 -%s 才允许跑 ⇒ 这一发停在这里，等用户决定放不放行", spec.Name, spec.RequiresFlag)
			收口(a, &res, 步)
			return 收尾(a, &res, start, emit)
		}

		// 出网预检：主机不在清单里 ⇒ 一次也没打出去（Attempts=0），与"打了但失败"分账。
		// manifest 里声明的 http_get 工具风险档也是 net_*，所以按档判而不是按名字判。
		if spec.Risk == RiskNetLocal || spec.Risk == RiskNetRemote {
			if u, _ := act.Args["url"].(string); u != "" {
				话, 放 := a.env.net.预检(u)
				if !放 {
					o := Observation{Step: 步, Tool: spec.Name, Args: act.Args, ArgsFrom: act.From, Class: ClassRefused, Risk: string(spec.Risk),
						Text: 话, Attempts: 0, Why: act.Why, Provenance: act.Proven, Plan: 用哪个,
						Evidence: EvAbsent, AbsentWhy: "出网门口挡下，一个包也没发出去"}
					res.Steps = append(res.Steps, o)
					pc.Obs = append(pc.Obs, o)
					a.mem.Append(Msg{Turn: turn, Role: "tool", Tool: spec.Name, Class: ClassRefused, Text: 话, Args: act.Args, At: time.Now()})
					emit("tool_result", o)
					continue
				}
			}
		}

		if ctx.Err() != nil {
			return 停(步)
		}
		out := 调一次(ctx, 工, act.Args, emit, 步, act.From)
		证据, 缺话 := 读数档(spec, out.Res)
		o := Observation{Step: 步, Tool: spec.Name, Args: act.Args, ArgsFrom: act.From, Class: out.Res.Class, Risk: string(spec.Risk),
			Text: out.Res.Text, Data: mapAny(out.Res.Data), MS: time.Now().Sub(start).Milliseconds(),
			Attempts: out.Attempts, Why: act.Why, Provenance: act.Proven, Plan: 用哪个,
			Evidence: 证据, AbsentWhy: 缺话}
		res.Retries += out.Attempts - 1
		res.WaitedMs += out.WaitedMs

		if out.Res.Class != ClassOK && spec.Fallback != "" {
			if 备, ok := a.reg.Get(spec.Fallback); ok && !被挡(备.Spec(), a.cfg) {
				新参, 能递 := 降级参数(备.Spec(), act.Args)
				if 能递 {
					o2 := 调一次(ctx, 备, 新参, emit, 步, "降级来的参数")
					证据2, 缺2 := 读数档(备.Spec(), o2.Res)
					o.DegradedFrom = spec.Name
					o.Text = fmt.Sprintf("原工具 %s 没成（%s）⇒ 降级用 %s：%s",
						spec.Name, 截(out.Res.Text, 120), 备.Spec().Name, o2.Res.Text)
					o.Class = o2.Res.Class
					o.Attempts += o2.Attempts
					o.Data = mapAny(o2.Res.Data)
					o.Evidence = 证据2
					o.AbsentWhy = 缺2
					o.Args = 新参
					o.ArgsFrom = fmt.Sprintf("从 %s 的降级参数映射来的", spec.Name)
					res.WaitedMs += o2.WaitedMs
					res.Degrades++
				}
			}
		}
		res.Steps = append(res.Steps, o)
		pc.Obs = append(pc.Obs, o)
		a.mem.Append(Msg{Turn: turn, Role: "tool", Tool: o.Tool, Class: o.Class, Text: o.Text,
			Args: o.Args, Data: o.Data, MS: o.MS, At: time.Now()})
		emit("tool_result", o)

		// 停止指令可能是在工具调用中间到的：调一次已经把这一格记成"被打断"，
		// 这里补上收口（步已进列，读数不丢），结束原因写明是被打断，不演成"跑完"。
		if out.Cancelled || ctx.Err() != nil {
			return 停(步)
		}

		if 步 == a.cfg.MaxSteps {
			res.Stop = "步数上限"
			res.StopWhy = fmt.Sprintf("跑到第 %d 步还没收口 ⇒ 停了（剩下的目标：%s）", a.cfg.MaxSteps, 没做完的(pc, a.reg))
		}
	}
	收口(a, &res, len(res.Steps)+1)
	return 收尾(a, &res, start, emit)
}

func 被挡(spec ToolSpec, cfg Config) bool {
	return spec.RequiresFlag != "" && !cfg.旗标开了(spec.RequiresFlag)
}

func mapAny(v any) map[string]any {
	if m, ok := v.(map[string]any); ok {
		return m
	}
	return nil
}

// 读数档：这一格到底是量到的、转述的、还是压根没量到。
// http.get 的正文是别人的话 ⇒ relayed；其余成功的读数是本机算出来的 ⇒ measured；
// 失败/被挡 ⇒ absent 并且必须带一句为什么。
func 读数档(spec ToolSpec, r Result) (string, string) {
	if r.Class != ClassOK {
		return EvAbsent, fmt.Sprintf("%s 这一发没成（类别 %s）：%s", spec.Name, r.Class, 截(r.Text, 160))
	}
	if spec.Name == "http.get" || strings.HasPrefix(spec.Source, "manifest:") && spec.Risk == RiskNetLocal {
		return EvRelayed, ""
	}
	return EvMeasured, ""
}

func (a *Agent) plannerNames() string {
	var 名 []string
	for _, p := range a.规划器() {
		名 = append(名, p.Name())
	}
	return strings.Join(名, "→")
}

// 选一步：按顺序问规划器；前一个交错误 ⇒ 记下"为什么降级"，再用下一个。
func (a *Agent) 选一步(ctx context.Context, pc PlanCtx, emit Emit, 步 int) (Action, string, string) {
	列 := a.规划器()
	var 降级话 string
	for i, p := range 列 {
		emit("plan", map[string]any{"step": 步, "ask": p.Name()})
		act, err := p.Propose(ctx, pc, a.mem, a.reg)
		if err == nil {
			act.Proven = p.Provenance()
			return act, p.Name(), 降级话
		}
		if i+1 < len(列) {
			降级话 = fmt.Sprintf("规划器 %s 没接上（%v）⇒ 这一步改由 %s 决定（本机规则选的件不许说成模型选的）",
				p.Name(), err, 列[i+1].Name())
		}
	}
	return Action{Kind: "done", Why: "没有可用的规划器"}, "无", 降级话
}

func 没做完的(pc PlanCtx, reg *Registry) string {
	var 名 []string
	做了 := map[string]bool{}
	for _, o := range pc.Obs {
		if o.Class == ClassOK {
			做了[o.Tool] = true
		}
	}
	for _, g := range 抽目标(pc.Utterance, 挂载目标(reg)) {
		if !做了[g.工具] {
			名 = append(名, g.ID)
		}
	}
	if len(名) == 0 {
		return "看着都做过了"
	}
	return strings.Join(名, "、")
}

// 收口：把每一步的读数汇成结论行，每条带档与理由；量不到的显式写 absent，不折成 0。
func 收口(a *Agent, res *Turn, 步 int) {
	var 成, 败, 挡 = 0, 0, 0
	for _, o := range res.Steps {
		switch o.Class {
		case ClassOK:
			成++
		case ClassRefused:
			挡++
		default:
			败++
		}
	}
	res.Findings = append(res.Findings, Finding{
		Text: fmt.Sprintf("这一发第 %d 轮：走 %d 步（成功 %d、失败 %d、门口挡 %d），重试多花了 %d 次尝试、等 %d ms，降级 %d 次",
			res.Turn, len(res.Steps), 成, 败, 挡, res.Retries, res.WaitedMs, res.Degrades),
		Tier: "measured", Step: 步})
	for _, o := range res.Steps {
		档 := "measured"
		switch {
		case o.Evidence == EvAbsent:
			档 = "absent"
		case o.Evidence == EvRelayed:
			档 = "relayed"
		case o.Provenance == "model_says":
			档 = "model_says"
		}
		话 := 截(o.Text, 300)
		if o.DegradedFrom != "" {
			话 += fmt.Sprintf("（这一步是从 %s 降级来的，参数也跟着换了：%s）", o.DegradedFrom, o.ArgsFrom)
		}
		if o.Evidence == EvAbsent && o.AbsentWhy == "" {
			话 += "（这一格没理由就空着 —— 不许）"
		}
		res.Findings = append(res.Findings, Finding{Text: fmt.Sprintf("%s ｜ 步 %d ｜ 谁选的：%s ｜ 参数：%s（%s）｜ %s",
			o.Tool, o.Step, 谁的名(o.Provenance), 小JSON(o.Args), o.ArgsFrom, 话), Tier: 档, Step: o.Step, Why: o.AbsentWhy})
	}
	摘要, n := a.mem.摘要(res.Turn)
	res.Findings = append(res.Findings, Finding{Text: 摘要, Tier: "estimated", Why: "本机摘要规则写的，不是模型写的"})
	res.MemoryLen = n
	窗口, 用了, 挤掉 := a.mem.窗口(res.Turn, a.cfg.ContextChars)
	res.ContextChars = 用了
	res.Dropped = 挤掉
	res.Findings = append(res.Findings, Finding{
		Text: fmt.Sprintf("上下文：这轮一共 %d 条记忆，喂进去 %d 条 / %d 码元，窗口外挤掉 %d 条",
			a.mem.Count(), len(窗口), 用了, 挤掉),
		Tier: "measured"})
	if a.cfg.ModelEndpoint == "" {
		res.Findings = append(res.Findings, Finding{
			Text: "模型端点这一路：NOT_RUN（没配 -model-endpoint，本机也没有口令环境变量）⇒ 这一发的选件全是本机规则定的",
			Tier: "absent", Why: "端点没配，不是端点回了空"})
	}

	// 模型的收口话只许在这里兜底时被本机话顶掉：模型自己写了什么就原样留什么，
	// 否则「answer」永远只是工具回显，模型说了什么在盘上一点痕迹都没有（10-23 业务 26 发实测）。
	if strings.TrimSpace(res.Answer) == "" {
		var 话 []string
		for _, o := range res.Steps {
			if o.Class == ClassOK {
				话 = append(话, fmt.Sprintf("%s：%s", o.Tool, 截(第一行(o.Text), 200)))
			}
		}
		if len(话) == 0 {
			话 = append(话, "这一发没有任何成功读数")
		}
		res.Answer = strings.Join(话, "；")
		res.AnswerTier = "measured"
		res.AnswerWhy = "模型收口没写 answer（或这一发不是模型收的）⇒ 这一格是本机按工具读数抄的，不是模型的话"
	} else {
		res.Findings = append(res.Findings, Finding{
			Text: "模型端点写的收口话（原样收下、不核事实）：" + 截(res.Answer, 400),
			Tier: "model_says"})
	}
	switch res.Stop {
	case "跑完":
		// 不把结论再抄进 stop_why：answer 自己就是一格，收口那句结论里也有一份。
		// 抄进来的那一发把结论带撑到 404 字 12 行（浏览器量的），而它本来就是"账"不是"话"。
	case "要补参数":
		res.StopWhy = "这一发停在这里等用户补一句：" + res.StopWhy
	case "步数上限":
		res.StopWhy = "步数上限：" + res.StopWhy
	}
}

func 谁的名(p string) string {
	switch p {
	case "model_says":
		return "模型端点"
	case "relayed":
		return "外部正文"
	default:
		return "本机规则"
	}
}

func 第一行(s string) string {
	if i := strings.IndexByte(s, '\n'); i >= 0 {
		return s[:i]
	}
	return s
}

// 收尾：算五档、跑自洽判据、把这一发的 agent 回话落进记忆，再把整份结果推给前端。
func 收尾(a *Agent, res *Turn, start time.Time, emit Emit) Turn {
	for _, f := range res.Findings {
		res.Mix[f.Tier]++
	}
	总 := 0
	for _, v := range res.Mix {
		总 += v
	}
	res.MixOK = 总 == len(res.Findings)
	res.Mix["total"] = 总
	判, _ := a.自洽判(*res)
	res.Sane = &判
	res.SaneWhy = a.自洽话(*res)
	res.MS = time.Since(start).Milliseconds()
	a.mem.Append(Msg{Turn: res.Turn, Role: "agent", Class: res.Stop,
		Text: fmt.Sprintf("%s ｜ 结束=%s：%s ｜ 整列自洽=%v", res.Answer, res.Stop, res.StopWhy, *res.Sane),
		Data: map[string]any{"steps": len(res.Steps), "stop": res.Stop, "sane": *res.Sane,
			"ms": res.MS, "kpi_ok": 成功步数(*res)}, At: time.Now()})
	emit("result", *res)
	return *res
}

func 成功步数(t Turn) int {
	n := 0
	for _, o := range t.Steps {
		if o.Class == ClassOK {
			n++
		}
	}
	return n
}

// 调用键：工具名 + 按名字排好的参数，用来认出"同一发里的第二次同样撞法"。
func 调用键(名 string, args map[string]any) string {
	ks := make([]string, 0, len(args))
	for k := range args {
		ks = append(ks, k)
	}
	sort.Strings(ks)
	var b strings.Builder
	b.WriteString(名)
	for _, k := range ks {
		fmt.Fprintf(&b, "|%s=%v", k, args[k])
	}
	return b.String()
}

// 小JSON：参数进结论句必须是 JSON —— Go 的 %v 会把 map[string]any 打成 map[a:1 b:2]，
// 那不是给前端吃的东西，也是"页面出现没人接的字段"这一族的老形状。
func 小JSON(v any) string {
	b, err := json.Marshal(v)
	if err != nil {
		return fmt.Sprintf("{序列化失败:%v}", err)
	}
	return string(b)
}
