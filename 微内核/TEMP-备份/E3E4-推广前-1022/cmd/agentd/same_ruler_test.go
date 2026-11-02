package main

import (
	"bufio"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"reflect"
	"strings"
	"testing"
	"time"
)

// 「与 mcpkernel 同一份判据」这句现在只是代码读起来像：宿主走 mcpsrv.New()+Serialize，
// mcpkernel 也走那一份。这一根针把它换成读数 —— 同一发喂两边（进程内 / 交付件里那枚 exe 走 stdio），
// 四句回话必须逐字一样。不一样就只有两种解释：宿主自己漂了一套，或者交付件落后于树。
// 两边都是各自新建的空账，也不碰 8797/8799（stdio 面不开端口）。
func TestSameRulerAsShippedKernel(t *testing.T) {
	exe := os.Getenv("AGENTKERNEL_SHIPPED_MCPKERNEL")
	if exe == "" {
		exe = findShippedKernel(t)
	}
	st, err := os.Stat(exe)
	if err != nil {
		t.Fatalf("交付件里的 mcpkernel 找不到（%s）：%v —— 这一根针就没跑，别当成过了", exe, err)
	}
	t.Logf("对账的两把尺子：进程内 mcpsrv  vs  %s（%d 字节，%s）",
		exe, st.Size(), st.ModTime().Format("2006-01-02 15:04"))

	in, body, err := (&assembly{
		system: systemPrompt, toolspec: toolSpec, user: userAsk,
	}).buildInput(1)
	if err != nil {
		t.Fatalf("装配：%v", err)
	}
	out := buildOutput(1, proposal{
		Text: "27 + 15 = 42", UsageIn: 40, UsageOut: 6, FinishSaid: true, FinishReason: "stop", ReportsModel: true,
	}, body)
	good := sides("同一把尺子", in, out)

	badIn := in
	badIn.Call = 0
	bad := sides("同一把尺子", badIn, out)

	local := newKernelRPC(0, false)
	remote := startShipped(t, exe)
	defer remote.close()

	cases := []struct {
		tool    string
		args    map[string]any
		wantErr bool
		journal bool // encode_journal 走"逐行比字段"，理由见 compareJournal
	}{
		{"kernel.celltable", nil, false, false},
		{"kernel.check_call", good, false, false},
		{"kernel.record_call", good, false, false},
		{"kernel.check_call", bad, true, false},
		{"kernel.read_back", map[string]any{"session": "同一把尺子", "call": 1, "side": "output"}, false, false},
		{"kernel.declare_reader", map[string]any{"reader": "同一把尺子", "key": "content_bytes", "side": "input"}, false, false},
		{"kernel.readers_report", nil, false, false},
		{"kernel.encode_journal", map[string]any{"payload": "included"}, false, true},
		// load_journal 这一发故意喂进不去的文本：两边都必须**拒**且拒得逐字一样。
		// 不拿成功路径比是因为换账会把两边的账换成同一份文件，比出来的"一致"就没意义了。
		{"kernel.load_journal", map[string]any{"text": "这不是 JSONL，一行都不是"}, true, false},
		{"kernel.tally", nil, false, false},
		{"kernel.verify", nil, false, false},
	}
	for i, c := range cases {
		l, lerr := local.call(c.tool, c.args)
		r, rerr := remote.call(c.tool, c.args)
		if lerr != nil || rerr != nil {
			t.Fatalf("第 %d 项 %s：本地 %v / 交付件 %v", i+1, c.tool, lerr, rerr)
		}
		if strings.TrimSpace(l.Text) == "" || strings.TrimSpace(r.Text) == "" {
			t.Fatalf("第 %d 项 %s：有一侧回的是空话（本地 %q / 交付件 %q）—— 两句空话相等不算「逐字一样」",
				i+1, c.tool, l.Text, r.Text)
		}
		// 逐字一样只证明"两边说同一句话"，不证明那句话会挑出错的：第 3 项（发号写 0）两边都必须拒、
		// 其余必须放行。少了这一条，把交付件换成一枚永远放行的 exe、或两边一起报空，针照样绿。
		want := "放行"
		if c.wantErr {
			want = "拒"
		}
		if l.IsErr != c.wantErr {
			t.Fatalf("第 %d 项 %s：这一发本该%s，却判成 isError=%v\n本地   ：%s",
				i+1, c.tool, want, l.IsErr, firstLine(l.Text))
		}
		if l.IsErr != r.IsErr {
			t.Fatalf("第 %d 项 %s：isError 不一样（本地 %v / 交付件 %v）\n本地：%s\n交付件：%s",
				i+1, c.tool, l.IsErr, r.IsErr, firstLine(l.Text), firstLine(r.Text))
		}
		if c.journal {
			compareJournal(t, i+1, l.Text, r.Text)
		} else if l.Text != r.Text {
			t.Fatalf("第 %d 项 %s：同一发判出了两句话\n本地   ：%s\n交付件：%s", i+1, c.tool, clip(l.Text), clip(r.Text))
		}
		t.Logf("%d/%d %-18s isError=%-5v %s", i+1, len(cases), c.tool, l.IsErr, firstLine(l.Text))
	}
}

// journalDerived 是"时间戳的下游"。机制是量出来的，不是编的：这台机（Win 10）的墙钟刻度粗，
// 两个进程落在同一个刻度里时整串 ts 完全相同（实测见 0 行不同那几次），跨一个刻度就整串不同；
// 而 ts 喂进 hash ⇒ prev_hash / chain_head / gate_sha256 / seal 跟着不同，头行那句"多少个字节"也跟着不同。
// 除这五格与头行的字节数之外，任何一格不同都是判据真的不一样，红。
//
// 8 次连跑的分布：5 次 50 行原始字节不同、3 次全同 —— 两种都判绿，因为比的是内容字段。
// 这条一开始写成"逐字一样"，于是**同一份代码**跑出 3 红 3 绿的抖动针；抖动针比没针更糟（教人重跑到绿为止）。
var journalDerived = map[string]bool{"ts": true, "hash": true, "prev_hash": true, "chain_head": true, "gate_sha256": true, "seal": true}

var headBytes = regexp.MustCompile(`^\d+ 字节`)

// compareJournal 不比整段字节 —— 上面那串倒影让它注定不同，硬要比就只能加掩码，
// 而掩码是藏差异的地方。改成两件事：① 头行把"字节数"那一格让开，其余逐字一样；
// ② 每一行把五格倒影让开，其余字段（kind/claim/basis/source/refused/payload…）必须全等。
// 让开了什么都让开了，逐名打印出来 —— 缺口必须看得见。
func compareJournal(t *testing.T, idx int, a, b string) {
	t.Helper()
	la := strings.Split(strings.TrimRight(a, "\n"), "\n")
	lb := strings.Split(strings.TrimRight(b, "\n"), "\n")
	if len(la) != len(lb) {
		t.Fatalf("第 %d 项 encode_journal：行数不一样（本地 %d 行 / 交付件 %d 行）", idx, len(la), len(lb))
	}
	ha := headBytes.ReplaceAllString(la[0], "N 字节")
	hb := headBytes.ReplaceAllString(lb[0], "N 字节")
	if ha != hb {
		t.Fatalf("第 %d 项 encode_journal：头行除了字节数还有别的东西不一样\n本地   ：%s\n交付件：%s", idx, la[0], lb[0])
	}
	differing := 0
	allowed := map[string]int{}
	var tsSample [2]string
	if len(la) > 1 {
		var e1, e2 map[string]any
		_ = json.Unmarshal([]byte(la[1]), &e1)
		_ = json.Unmarshal([]byte(lb[1]), &e2)
		tsSample[0], tsSample[1] = fmt.Sprint(e1["ts"]), fmt.Sprint(e2["ts"])
	}
	for i := 1; i < len(la); i++ {
		if la[i] == lb[i] {
			continue
		}
		differing++
		var ma, mb map[string]any
		if err := json.Unmarshal([]byte(la[i]), &ma); err != nil {
			t.Fatalf("第 %d 项：本地第 %d 行不是 JSON：%v", idx, i, err)
		}
		if err := json.Unmarshal([]byte(lb[i]), &mb); err != nil {
			t.Fatalf("第 %d 项：交付件第 %d 行不是 JSON：%v", idx, i, err)
		}
		keys := map[string]bool{}
		for k := range ma {
			keys[k] = true
		}
		for k := range mb {
			keys[k] = true
		}
		for k := range keys {
			if journalDerived[k] {
				if !reflect.DeepEqual(ma[k], mb[k]) {
					allowed[k]++
				}
				continue
			}
			if !reflect.DeepEqual(ma[k], mb[k]) {
				t.Fatalf("第 %d 项：第 %d 行的 %q 真的不一样（%v vs %v）—— 这一格不在时间戳的下游，掩码不许盖它",
					idx, i, k, ma[k], mb[k])
			}
		}
	}
	t.Logf("第 %d 项 encode_journal：%d 行逐行比过，%d 行原始字节不同；头行（去字节数）与所有非倒影字段全等；"+
		"让开的倒影逐名：%v｜两边的 ts 样本：%s vs %s",
		idx, len(la)-1, differing, allowed, tsSample[0], tsSample[1])
}

func clip(s string) string {
	if len(s) > 400 {
		return s[:400] + " …（截到这里，全长远在这之外）"
	}
	return s
}

type shipped struct {
	cmd  *exec.Cmd
	in   io.WriteCloser
	out  *bufio.Reader
	id   int
	t    *testing.T
	done chan struct{}
}

func startShipped(t *testing.T, exe string) *shipped {
	t.Helper()
	cmd := exec.Command(exe)
	stdin, err := cmd.StdinPipe()
	if err != nil {
		t.Fatalf("交给付件接 stdin：%v", err)
	}
	stdout, err := cmd.StdoutPipe()
	if err != nil {
		t.Fatalf("交给付件接 stdout：%v", err)
	}
	cmd.Stderr = io.Discard // 横幅走 stderr，与本测试无关
	if err := cmd.Start(); err != nil {
		t.Fatalf("起交付件：%v", err)
	}
	return &shipped{cmd: cmd, in: stdin, out: bufio.NewReader(stdout), t: t, done: make(chan struct{})}
}

func (s *shipped) call(tool string, args map[string]any) (reply, error) {
	s.id++
	if args == nil {
		args = map[string]any{}
	}
	raw, err := json.Marshal(map[string]any{
		"jsonrpc": "2.0", "id": s.id, "method": "tools/call",
		"params": map[string]any{"name": tool, "arguments": args},
	})
	if err != nil {
		return reply{}, err
	}
	if _, err := s.in.Write(append(raw, '\n')); err != nil {
		return reply{}, fmt.Errorf("写不进交付件那侧：%v", err)
	}
	line := make(chan string, 1)
	go func() {
		l, err := s.out.ReadString('\n')
		if err != nil {
			line <- ""
			return
		}
		line <- l
	}()
	select {
	case l := <-line:
		if l == "" {
			return reply{}, fmt.Errorf("交付件没回帧（%s）", tool)
		}
		var msg struct {
			Result *struct {
				Content []struct {
					Text string `json:"text"`
				} `json:"content"`
				IsError bool `json:"isError"`
			} `json:"result"`
			Error *struct{ Message string } `json:"error"`
		}
		if err := json.Unmarshal([]byte(l), &msg); err != nil {
			return reply{}, fmt.Errorf("%s 的回帧解不开：%v", tool, err)
		}
		if msg.Error != nil {
			return reply{Text: msg.Error.Message, IsErr: true}, nil
		}
		if msg.Result == nil || len(msg.Result.Content) == 0 {
			return reply{}, fmt.Errorf("%s 回了但没正文：%s", tool, l)
		}
		return reply{Text: msg.Result.Content[0].Text, IsErr: msg.Result.IsError}, nil
	case <-time.After(10 * time.Second):
		return reply{}, fmt.Errorf("等 %s 回帧超时（交付件那侧卡住了？）", tool)
	}
}

func (s *shipped) close() {
	_ = s.in.Close()
	done := make(chan error, 1)
	go func() { done <- s.cmd.Wait() }()
	select {
	case <-done:
	case <-time.After(3 * time.Second):
		_ = s.cmd.Process.Kill()
	}
}

// findShippedKernel 往上找交付件里那枚 mcpkernel，不数 ../ 的层数：
// 数层数这件事本身就是个会随目录移动而说谎的常量。
func findShippedKernel(t *testing.T) string {
	t.Helper()
	dir, err := os.Getwd()
	if err != nil {
		t.Fatalf("拿当前目录：%v", err)
	}
	for i := 0; i < 7; i++ {
		p := filepath.Join(dir, "构建-1017", "agentkernel", "bin", "mcpkernel.exe")
		if _, err := os.Stat(p); err == nil {
			return p
		}
		parent := filepath.Dir(dir)
		if parent == dir {
			break
		}
		dir = parent
	}
	return filepath.Join("..", "构建-1017", "agentkernel", "bin", "mcpkernel.exe")
}
