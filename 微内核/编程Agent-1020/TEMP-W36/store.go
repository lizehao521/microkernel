package main

import (
	"bufio"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
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
	return Record{
		TS: time.Now().Format(time.RFC3339), Session: res.Session, Turn: res.Turn,
		Question: res.Question, Summary: res.AnswerSummary,
		Findings: len(res.Findings), Unknowns: len(res.Unknowns),
		Mix: res.Mix, MixOK: res.MixOK, Sha: res.Metrics.SHA256,
		StepsRan: ran, StepsAll: len(res.Trace),
		Stop: res.StopReason, StopWhy: res.StopWhy,
		PartsBytes: res.PartsBytes, Effective: res.EffectiveCeil, BudgetOver: res.BudgetOver,
		LedgerReject: res.LedgerReject,
	}
}
