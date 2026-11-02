package main

import (
	"fmt"
	"strings"
)

// 结构化结果的形状。这里刻意把「出处档」做成必填枚举：
// 少一档就编译不过，比在运行时靠人记得填要可靠。

type Basis string

const (
	Measured  Basis = "measured"   // 我们自己数出来的（字节、行、AST 节点、真 socket 上的分帧）
	Estimated Basis = "estimated"  // 文本级保守扫描，没真解析过
	ModelSays Basis = "model_says" // 模型自报，未经复核
	Relayed   Basis = "relayed"    // 转述别人的数（fixture、上游字段）
	Absent    Basis = "absent"     // 没量到 —— 必须带理由，绝不写成 0
)

var basisOrder = []Basis{Measured, Estimated, ModelSays, Relayed, Absent}

func validBasis(b Basis) bool {
	for _, x := range basisOrder {
		if x == b {
			return true
		}
	}
	return false
}

type Where struct {
	Lines  [2]int `json:"lines"`
	Symbol string `json:"symbol,omitempty"`
}

type Fix struct {
	Patch     string `json:"patch"`
	Rationale string `json:"rationale"`
	Risk      string `json:"risk"`
}

type Finding struct {
	ID       string `json:"id"`
	Rule     string `json:"rule"`
	Severity string `json:"severity"`
	Where    Where  `json:"where"`
	Evidence string `json:"evidence"`
	Basis    Basis  `json:"basis"`
	Claim    string `json:"claim"`
	Fix      *Fix   `json:"fix,omitempty"`
	Verify   string `json:"verify"`
}

type Metrics struct {
	Bytes int    `json:"bytes"`
	Lines int    `json:"lines"`
	Lang  string `json:"lang"`
	// 语言是怎么定的，本身要能追溯：显式选定 = 数出来的；嗅探 = 推断的（不许与前者混说）。
	LangHow string `json:"lang_how"`
	LangWhy string `json:"lang_why"`
	Parsed  bool   `json:"parsed"`
	Funcs   int    `json:"funcs"`
	MaxFunc int    `json:"max_func_lines"`
	Imports int    `json:"imports"`
	// 与 imports 分列：一个是"有几条导入"，一个是"其中几条疑似没用到"（文本级，没建作用域信息）。
	UnusedImports int    `json:"unused_imports"`
	BlankErrs     int    `json:"ignored_error_sites"`
	PrintCalls    int    `json:"print_calls"`
	SHA256        string `json:"sha256_of_code"`
	TokensBasis   string `json:"tokens_basis_from_ledger,omitempty"`
	BytesSource   string `json:"bytes_source,omitempty"`
	// 账上的 content_bytes 是「这一发送出去的整块内容」（系统件+工具清单+问题+代码），
	// 不是"贴进来的代码有多少字节"。混成同一格就是把两个不同的量当同一个 —— 单独立一格。
	LedgerContentBytes int `json:"ledger_content_bytes,omitempty"`
}

type Unknown struct {
	What      string `json:"what"`
	WhyAbsent string `json:"why_absent"`
	HowToGet  string `json:"how_to_get"`
	Basis     Basis  `json:"basis"`
}

type Step struct {
	No      int    `json:"step"`
	Name    string `json:"name"`
	Summary string `json:"out"`
	Ms      int64  `json:"ms"`
	Basis   Basis  `json:"basis"`
	Run     bool   `json:"ran"` // ran=false 时界面上必须是灰徽章，不许长得像绿
}

type Mix struct {
	Measured  int `json:"measured"`
	Estimated int `json:"estimated"`
	ModelSays int `json:"model_says"`
	Relayed   int `json:"relayed"`
	Absent    int `json:"absent"`
	Total     int `json:"total"`
}

type Result struct {
	Session       string        `json:"session"`
	Turn          int           `json:"turn"`
	Question      string        `json:"question"`
	Intent        string        `json:"intent,omitempty"`
	IntentWhy     string        `json:"intent_why,omitempty"`
	AnswerSummary string        `json:"answer_summary"`
	Findings      []Finding     `json:"findings"`
	Metrics       Metrics       `json:"metrics"`
	Trace         []Step        `json:"trace"`
	Unknowns      []Unknown     `json:"unknowns"`
	Mix           Mix           `json:"provenance_mix"`
	MixOK         bool          `json:"mix_identity_ok"`
	MixWhy        string        `json:"mix_identity_why"`
	Executed      bool          `json:"code_executed"`
	KPI           int           `json:"kpi_ledger_decided"`
	KPIWhy        string        `json:"kpi_why"`
	StopReason    string        `json:"stop_reason"`
	StopAt        string        `json:"-"`
	StopWhy       string        `json:"stop_why"`
	Decisions     []Decision    `json:"ledger_decisions,omitempty"`
	Debug         *DebugReadout `json:"debug,omitempty"`
	// Gateway 是第 ⑧ 步的读数。**没跑就没有这一格**（不印零值）——
	// 一行 bytes_in:0 会被读成"打出去了但一个字节没回来"，那是把没跑写成跑过。
	Gateway *pipeReadout `json:"gateway,omitempty"`
}

// mixOf 数五档并当场核恒等式：每条 findings/unknowns 必须落进恰好一档。
// 不等就不是"数错了"，是有一档塌了 —— 这套件最致命的假绿。
// 非法档名不许被归进某一档（那等于"不知道出处"读成"有出处"），它只进 Total，于是加总必然对不上、MixOK 红。
func mixOf(r *Result) {
	m := Mix{}
	total := 0
	var bad []string
	for _, f := range r.Findings {
		total++
		if !validBasis(f.Basis) {
			bad = append(bad, f.Rule+" 的档名 "+string(f.Basis))
			continue
		}
		add(&m, f.Basis)
	}
	for _, u := range r.Unknowns {
		total++
		if !validBasis(u.Basis) {
			bad = append(bad, u.What+" 的档名 "+string(u.Basis))
			continue
		}
		add(&m, u.Basis)
	}
	m.Total = total
	r.Mix = m
	sum := m.Measured + m.Estimated + m.ModelSays + m.Relayed + m.Absent
	r.MixOK = sum == total
	if !r.MixOK {
		r.MixWhy = fmt.Sprintf("有条目没落进五档（%s）—— 加总 %d ≠ 条数 %d，这是塌档不是数错",
			strings.Join(bad, "; "), sum, total)
	} else {
		r.MixWhy = fmt.Sprintf("五档加总 %d = findings + unknowns 条数，当场核过", sum)
	}
}

func add(m *Mix, b Basis) {
	switch b {
	case Measured:
		m.Measured++
	case Estimated:
		m.Estimated++
	case ModelSays:
		m.ModelSays++
	case Relayed:
		m.Relayed++
	case Absent:
		m.Absent++
	}
}

// DebugReadout 是"这一发到底有没有栈可看"的读数。
// 没给栈与给了栈但认不出帧是两件事，分开记才不会都被读成"没有 bug"。
type DebugReadout struct {
	StackBytes int `json:"stack_bytes"`
	Frames     int `json:"frames_parsed"`
	InRange    int `json:"frames_pointing_into_snippet"`
}
