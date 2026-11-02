package main

import (
	"bufio"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"time"
)

// 轨迹落盘：一发一行 JSONL，append-only。
// 这一份不是账本（账本在 W4 接内核），它只保证"刷新页面历史还在"与"事后能复核当时的读数"。

type Record struct {
	TS       string `json:"ts"`
	Session  string `json:"session"`
	Turn     int    `json:"turn"`
	Question string `json:"question"`
	Summary  string `json:"answer_summary"`
	Findings int    `json:"findings"`
	Unknowns int    `json:"unknowns"`
	Mix      Mix    `json:"provenance_mix"`
	MixOK    bool   `json:"mix_identity_ok"`
	Sha      string `json:"sha256_of_code"`
	StepsRan int    `json:"steps_ran"`
	Stop     string `json:"stop_reason"`
	StopWhy  string `json:"stop_why"`
	StepsAll int    `json:"steps_total"`
	// 额度那三件也要跨落盘活着：不然翻往轮轨迹时只看到"findings 6 条、KPI 0"，
	// 说不出**当年那一发为什么没落账**（第 ① 步当场说了，落盘之后却丢了 = 半程诚实）。
	PartsBytes int64 `json:"parts_bytes"`
	Effective  int64 `json:"budget_effective_ceiling,omitempty"`
	BudgetOver bool  `json:"budget_over"`
	// 与 Result.LedgerReject 同一口径：拒收原话要能翻回来，不能只在当场那一发里活过。
	LedgerReject string `json:"ledger_reject,omitempty"`
	// 整列自洽判据的读数也要跨落盘活着：往轮轨迹里那一发当时判据是红的，刷新之后必须还看得到。
	// 指针不是省事：判据上线（W35）之前跑的那些发**根本没有这一格** —— 那是"没量过"。
	// 塌成 false 就把旧账全说成骗人，塌成 true 就是替它们作保；两个方向都是假账。
	TraceSane    *bool  `json:"trace_sane,omitempty"`
	TraceSaneWhy string `json:"trace_sane_why,omitempty"`
	// 核心 KPI 也要跨落盘活着：以前往轮轨迹只翻得回 findings/未决/步数，
	// 「这一发账本改写了几个决定」当场说过就没了 —— 而那正是本件唯一的核心 KPI。
	// 全用指针：没接缝、没读回、没落账的那些发是「没量过」，写成 0 就是把没量演成量到。
	KPI         *int  `json:"kpi_ledger_decided,omitempty"`
	LedgerCells *int  `json:"ledger_cells,omitempty"`
	Recorded    *bool `json:"recorded,omitempty"`
	// 链上条数与被拒写入是从第 ⑩ 步那句内核原话里数出来的两格。跨发判据只吃这两格与上面那三格，
	// 不吃"我们自己记得刚才落了几个"—— 同一件事有两个来源就会有两个版本。
	ChainEntries *int `json:"chain_entries,omitempty"`
	// 跨发判据的读数也落盘：它是"到这一发为止"那一列的读数，只活在当场横幅里的话，
	// 刷新之后历史页就查不到哪一发被它点过名（与 trace_sane 同一族半程诚实）。
	ChainSane *bool  `json:"chain_sane,omitempty"`
	ChainWhy  string `json:"chain_why,omitempty"`
	// TurnCells 是这一发自己交来的格数（内核 record_call 那句「整发落账 49 条」）。
	// 跨发判据拿它对**增量**，不拿绝对值 —— tally 那句「账 N 条」数的是整个进程那本账，跨会话共用。
	TurnCells    *int `json:"turn_cells,omitempty"`
	RejectWrites *int `json:"reject_writes,omitempty"`
}

type Store struct {
	dir string
}

func newStore(dir string) *Store { return &Store{dir: dir} }

func (s *Store) path(session string) string {
	clean := strings.Map(func(r rune) rune {
		if r >= 'a' && r <= 'z' || r >= '0' && r <= '9' || r == '-' || r >= 0x4e00 {
			return r
		}
		return '_'
	}, session)
	if clean == "" {
		clean = "default"
	}
	return filepath.Join(s.dir, "会话-"+clean+".jsonl")
}

func (s *Store) append(r Record) error {
	if err := os.MkdirAll(s.dir, 0o755); err != nil {
		return err
	}
	f, err := os.OpenFile(s.path(r.Session), os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0o644)
	if err != nil {
		return err
	}
	defer f.Close()
	line, err := json.Marshal(r)
	if err != nil {
		return err
	}
	_, err = f.Write(append(line, '\n'))
	return err
}

// turnFloor 数这本会话文件：行数、解析得到的最大发号、解析不开的行数。
// 返回的地板取两者较大 —— 行解析不开（进程被掐在写一半）时那些行仍占着号，
// 让下一发从 1 重新起号就是把两个身份写进同一本账（10-21 W28 实测到的那一形）。
func (s *Store) turnFloor(session string) (floor int, rows int, bad int, err error) {
	b, err := os.ReadFile(s.path(session))
	if err != nil {
		if os.IsNotExist(err) {
			return 0, 0, 0, nil
		}
		return 0, 0, 0, err
	}
	for _, ln := range strings.Split(string(b), "\n") {
		ln = strings.TrimSpace(ln)
		if ln == "" {
			continue
		}
		rows++
		var r struct {
			Turn int `json:"turn"`
		}
		if json.Unmarshal([]byte(ln), &r) != nil || r.Turn <= 0 {
			bad++
			continue
		}
		if r.Turn > floor {
			floor = r.Turn
		}
	}
	if rows > floor {
		floor = rows
	}
	return floor, rows, bad, nil
}

func (s *Store) history(session string) ([]Record, error) {
	f, err := os.Open(s.path(session))
	if err != nil {
		if os.IsNotExist(err) {
			return nil, nil
		}
		return nil, err
	}
	defer f.Close()
	var out []Record
	sc := bufio.NewScanner(f)
	sc.Buffer(make([]byte, 1<<20), 1<<22)
	for sc.Scan() {
		var r Record
		if err := json.Unmarshal(sc.Bytes(), &r); err != nil {
			return out, fmt.Errorf("第 %d 行解不开（这一份文件已经被改坏过？）: %w", len(out)+1, err)
		}
		out = append(out, r)
	}
	return out, sc.Err()
}

// recordOf 从结果里数出落盘那几格。steps 的 ran 计数是"真跑了几步"的读数 —— 不是步数上限。
func recordOf(res Result, code string) Record {
	ran := 0
	for _, s := range res.Trace {
		if s.Run {
			ran++
		}
	}
	自洽 := res.TraceSane
	记 := Record{
		TS: time.Now().Format(time.RFC3339), Session: res.Session, Turn: res.Turn,
		Question: res.Question, Summary: res.AnswerSummary,
		Findings: len(res.Findings), Unknowns: len(res.Unknowns),
		Mix: res.Mix, MixOK: res.MixOK, Sha: res.Metrics.SHA256,
		StepsRan: ran, StepsAll: len(res.Trace),
		Stop: res.StopReason, StopWhy: res.StopWhy,
		PartsBytes: res.PartsBytes, Effective: res.EffectiveCeil, BudgetOver: res.BudgetOver,
		LedgerReject: res.LedgerReject,
		TraceSane:    &自洽, TraceSaneWhy: res.TraceSaneWhy,
	}
	// 落了账没有：只认第 ⑥ 步自己的 ran，不认"接缝装了"（装了也可能被门口挡下）。
	if s, 有 := stepOf(res.Trace, "kernel.record_call"); 有 {
		落 := s.Run
		记.Recorded = &落
	}
	// KPI 与读回格数：只有第 ⑦ 步真跑了才有这两个数。反臂那一发是"落了账、没读回"⇒ 两格都不许写，
	// 写了就等于替它作保"账上没改写任何东西"（那是量不到的）。
	if s, 有 := stepOf(res.Trace, "kernel.read_back"); 有 && s.Run {
		改, 格 := res.KPI, len(res.Decisions)
		记.KPI, 记.LedgerCells = &改, &格
	}
	// 链上条数与被拒写入：从第 ⑩ 步那句内核原话里数，不从我们自己的记忆里取。
	if s, 有 := stepOf(res.Trace, "kernel.tally"); 有 && s.Run {
		记.ChainEntries, 记.RejectWrites = 数链上(s.Summary)
	}
	if s, 有 := stepOf(res.Trace, "kernel.record_call"); 有 && s.Run {
		if m := re格数.FindStringSubmatch(s.Summary); m != nil {
			if n, err := strconv.Atoi(m[1]); err == nil {
				记.TurnCells = &n
			}
		}
	}
	return 记
}

func stepOf(ts []Step, 名 string) (Step, bool) {
	for _, s := range ts {
		if s.Name == 名 {
			return s, true
		}
	}
	return Step{}, false
}

var re链上 = regexp.MustCompile(`账 (\d+) 条`)
var re被拒 = regexp.MustCompile(`被拒的写入 (\d+) 次`)
var re格数 = regexp.MustCompile(`整发落账 (\d+) 条`)

// 数链上 把第 ⑩ 步那句内核原话里的两个数抠出来。抠不到就返回 nil —— 那是"没量到"，
// 拿 0 冒充"链上是空的"会让下面每一发的对账全跟着错。
func 数链上(话 string) (*int, *int) {
	取 := func(re *regexp.Regexp) *int {
		m := re.FindStringSubmatch(话)
		if m == nil {
			return nil
		}
		n, err := strconv.Atoi(m[1])
		if err != nil {
			return nil
		}
		return &n
	}
	return 取(re链上), 取(re被拒)
}

// chainSane规则 是跨发判据的名字清单。为什么要列出来：判据一次跑六条，红了不说是哪条咬的，
// 就等于把"哪一处骗人"又变回手感；而清单里有名却没配臂 = 那条从没被证明会红。
var chainSane规则 = []string{
	"链上条数与这一发的格数对不上", "没落账那一发却让链上长了", "被拒写入与这一发对不上",
	"没落账那一发却有读数", "改写了结果却没有读回格数", "同码同问两发结论数不一样",
}

// chainSane 数的是"同一本会话文件里前后两发的读数互相对不对"。
// 单发判据（traceSane）管不了这一族：每一发内部都自洽，连起来看仍在骗。
//
// 全部按**增量**对，不按绝对值对 —— 这是部署侧探针第一跑教我的：内核 tally 那句「账 N 条」数的是
// **这一本账（整个进程那本）**，不是本会话。同一台服上先跑了别的会话，本会话第一发就带着 441 条进场，
// 拿"链上 == 49 × 本会话落账发数"去判，判的是我编的口径而不是产品（针 43 甲半边当场把它撞红）。
// 增量还顺手管住接缝重启：换进程 / 重装接缝会让链上掉回去，那一发只记"换段"，不记假账。
func chainSane(列 []Record) (bool, string) {
	红 := []string{}
	在册 := map[string]bool{}
	for _, 名 := range chainSane规则 {
		在册[名] = true
	}
	咬 := func(名, 话 string) {
		if !在册[名] {
			红 = append(红, "规则名没在册｜判据咬了「"+名+"」，可清单里没这条："+话)
			return
		}
		红 = append(红, 名+"｜"+话)
	}
	上一链, 上一拒, 重启, 长过 := -1, -1, 0, 0
	同码 := map[string]int{}
	for _, r := range 列 {
		if r.ChainEntries != nil {
			链 := *r.ChainEntries
			if 上一链 >= 0 {
				Δ := 链 - 上一链
				switch {
				case Δ < 0:
					重启++ // 换了一次接缝/进程：这本账是新的，上一发的数不作数
				case r.Recorded != nil && *r.Recorded && r.TurnCells != nil:
					if Δ != *r.TurnCells {
						咬("链上条数与这一发的格数对不上", fmt.Sprintf(
							"第 %d 发落了账，链上却长了 %d 条，而这一发自己交来的格数是 %d", r.Turn, Δ, *r.TurnCells))
					} else {
						长过++
					}
				case r.Recorded != nil && !*r.Recorded && Δ != 0:
					咬("没落账那一发却让链上长了", fmt.Sprintf(
						"第 %d 发被挡下（%s），链上却从 %d 条长到 %d 条 ⇒ 要么那句拒收在骗，要么账上多写了一次",
						r.Turn, clipOne(r.LedgerReject, 60), 上一链, 链))
				}
			}
			上一链 = 链
		}
		if r.RejectWrites != nil {
			// 内核那句「被拒的写入 N 次」数的是**内核判据**挡下的写入；外壳按部署方容量挡下的那类
			// （-entry-cap 到上限）不走这个计数 —— W38 第一版拿"被挡一次 ⇒ 该 +1"去判，
			// 账满那一形当场被它判红（内核计数是 0→0，可那句拒收原话明明写着"不是内核判据拒的"）。
			// 所以这里只判两个方向：一发最多让计数走 1 步，且走了一步的那发必须真是一次拒收。
			拒 := *r.RejectWrites
			if 上一拒 >= 0 && 拒 >= 上一拒 { // 掉回去 = 换了接缝，这一发只当没有前情
				Δ := 拒 - 上一拒
				if Δ > 1 {
					咬("被拒写入与这一发对不上", fmt.Sprintf(
						"第 %d 发一发就让内核的写入被拒计数走了 %d 步（一发最多一次）", r.Turn, Δ))
				} else if Δ == 1 && r.Recorded != nil && *r.Recorded && r.LedgerReject == "" {
					咬("被拒写入与这一发对不上", fmt.Sprintf(
						"第 %d 发落了账、也没带任何拒收原话，内核的被拒计数却 +1 ⇒ 有一发拒收没记在列里", r.Turn))
				}
			}
			上一拒 = 拒
		}
		if r.Recorded != nil && !*r.Recorded &&
			((r.KPI != nil && *r.KPI > 0) || (r.LedgerCells != nil && *r.LedgerCells > 0)) {
			咬("没落账那一发却有读数", fmt.Sprintf("第 %d 发没进账（拒收：%s），却记着 KPI=%s、读回 %s 格 ⇒ 账上没这一发，值从哪来",
				r.Turn, clipOne(r.LedgerReject, 60), 指(r.KPI), 指(r.LedgerCells)))
		}
		if r.KPI != nil && *r.KPI > 0 && (r.LedgerCells == nil || *r.LedgerCells == 0) {
			咬("改写了结果却没有读回格数", fmt.Sprintf("第 %d 发喊 KPI=%d，读回格数却是 %s ⇒ 数了没发生过的改写",
				r.Turn, *r.KPI, 指(r.LedgerCells)))
		}
		if r.Stop == "跑完" && r.Recorded != nil && *r.Recorded {
			键 := r.Sha + "｜" + r.Question
			if 前, 有 := 同码[键]; 有 && 前 != r.Findings {
				咬("同码同问两发结论数不一样", fmt.Sprintf("同一份代码同一个问题连发两回，findings 一次 %d 一次 %d ⇒ 有东西从上一发漏过来了",
					前, r.Findings))
			}
			同码[键] = r.Findings
		}
	}
	if len(红) > 0 {
		return false, strings.Join(红, "；")
	}
	return true, fmt.Sprintf("跨发 %d 发对得上（链上按每发自己交来的格数往上涨、被拒计数逐发对得上；这一列里换过 %d 次接缝、逐段数过来 %d 次涨）",
		len(列), 重启, 长过)
}

// 补跨发 把这一发接回它所在那一列的末尾数一遍跨发判据，读数写进这一格。
// 为什么单独成一个函数：判据只算一次，算完同时交给落盘那一格与交回前端那一格 ——
// 两处各算一遍就会有两个版本（W32 那一族"一格两数"就是这么冒出来的）。
func 补跨发(st *Store, 记 Record) Record {
	前列, err := st.history(记.Session)
	if err != nil {
		记.ChainWhy = "跨发判据没量过：读不回这本会话文件（" + err.Error() + "）"
		return 记
	}
	合, 话 := chainSane(append(append([]Record{}, 前列...), 记))
	记.ChainSane, 记.ChainWhy = &合, 话
	return 记
}

func 指(p *int) any {
	if p == nil {
		return "没量过"
	}
	return *p
}
