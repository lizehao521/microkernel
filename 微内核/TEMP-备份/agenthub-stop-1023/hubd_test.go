package main

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net"
	"net/http"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
	"testing"
	"time"
)

// 搭 一台干净的机器：临时根、自己的端口、自己的 tools/数据目录。
// 不共用 自检机 的目录 —— 上一子测试留在共享 tools/ 里的清单会把下一子测试拖红（这类污染在本项目记过名）。
func 搭(t *testing.T, 改 func(*Config)) (*EnvX, *Agent, Config) {
	t.Helper()
	根 := filepath.Join(t.TempDir(), "根")
	if err := os.MkdirAll(根, 0o755); err != nil {
		t.Fatal(err)
	}
	c := 默认配置()
	c.Port = 8900 + int(time.Now().UnixNano()%370)
	c.DataDir = filepath.Join(根, "数据")
	c.ToolsDir = filepath.Join(根, "tools")
	c.NotesDir = filepath.Join(根, "笔记")
	c.FsRoots = []string{根, c.NotesDir}
	c.NetAllow = []string{"127.0.0.1", "localhost"}
	c.MaxSteps = 4
	c.StepDelay = 0
	c.安静 = true
	if 改 != nil {
		改(&c)
	}
	x, err := 装配(c)
	if err != nil {
		t.Fatal(err)
	}
	return x, NewAgent(x.Env, c), c
}

func 步(t *testing.T, 名 string, res Turn) Observation {
	t.Helper()
	for _, o := range res.Steps {
		if o.Tool == 名 {
			return o
		}
	}
	t.Fatalf("这一发没走 %s（步：%v，结束=%s：%s）⇒ 想验的形压根没出现，不许算过",
		名, 步名(res), res.Stop, res.StopWhy)
	return Observation{}
}

// 起监听 现挑一个真空闲端口：固定端口会被上一子测试的 TIME_WAIT 卡住，
// 而卡住之后 t.Skip 会把"没量到"演成"没问题"。
func 起监听(t *testing.T, c Config, x *EnvX) (string, func()) {
	t.Helper()
	srv := 起服务(c, x)
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatalf("连本地端口都起不来：%v", err)
	}
	go func() { _ = srv.Serve(ln) }()
	return ln.Addr().String(), func() {
		ctx, cancel := context.WithTimeout(context.Background(), 300*time.Millisecond)
		defer cancel()
		srv.Shutdown(ctx)
	}
}

func 读完(t *testing.T, rc io.Reader) []byte {
	t.Helper()
	b, err := io.ReadAll(rc)
	if err != nil {
		t.Fatalf("读流断了：%v", err)
	}
	return b
}

func TestRegistryRejectsDuplicateAndBadSpec(t *testing.T) {
	x, _, c := 搭(t, nil)
	先 := x.reg.Count()
	写文件(c.ToolsDir, "撞名.json", `{"name":"fs.list","summary":"顶","risk":"local_read","timeout_ms":500,"retry":{"attempts":1},"invoke":{"kind":"fs_read","root":"."}}`)
	装, 拒 := LoadManifests(c.ToolsDir, x.reg, x.net)
	if len(装) != 0 || len(拒) == 0 || !strings.Contains(拒[0], "重名") {
		t.Fatalf("撞名清单 loaded=%v rejected=%v", 装, 拒)
	}
	if x.reg.Count() != 先 {
		t.Fatalf("工具数从 %d 涨到 %d ⇒ 覆盖是静默的", 先, x.reg.Count())
	}
	if len(x.reg.shadow) == 0 {
		t.Fatal("影子注册没留痕 ⇒ /api/tools 上看不见这件事")
	}
	哑 := func(context.Context, map[string]any) (Result, error) { return Result{Class: ClassOK}, nil }
	// 直接搭 funcTool 而不是走 quick()：quick 会把没给的超时/重试补成默认值，
	// 那正好把"注册表该拒掉 0 超时"这一形演成合法 —— 测的是注册表的门，不是 quick 的Defaults。
	裸 := func(s ToolSpec) Tool { return &funcTool{spec: s, fn: 哑} }
	if err := x.reg.Add(裸(ToolSpec{Name: "没超时", Risk: RiskCompute, Retry: RetryPolicy{Attempts: 1}})); err == nil {
		t.Fatal("超时没给的工具被注册上了（0 秒＝可以挂到永远）")
	}
	if err := x.reg.Add(裸(ToolSpec{Name: "没重试档", Risk: RiskCompute, TimeoutMs: 500})); err == nil {
		t.Fatal("重试次数为 0 的工具被注册上了 ⇒ 一次也不试却算注册过")
	}
	if err := x.reg.Add(裸(ToolSpec{Name: "", Risk: RiskCompute, TimeoutMs: 500, Retry: RetryPolicy{Attempts: 1}})); err == nil {
		t.Fatal("没名字的工具被注册上了")
	}
	快明 := quick(ToolSpec{Name: "参数没名字", Params: []ParamSpec{{Type: "string"}}, Risk: RiskCompute}, 哑)
	if err := x.reg.Add(快明); err == nil {
		t.Fatal("参数没名字的工具被注册上了")
	}
}

func TestParamValidationUnknownKeyAndType(t *testing.T) {
	x, _, _ := 搭(t, nil)
	工, _ := x.reg.Get("text.stats")
	res, err := 工.Run(context.Background(), map[string]any{"tex": "x"})
	if err != nil {
		t.Fatalf("工具抛了错 %v（这形该走 bad_args 的读数，不该抛栈）", err)
	}
	if res.Class != ClassBadArgs {
		t.Fatalf("未知键被判成 %s（应当 bad_args 并点名可用参数）：%s", res.Class, res.Text)
	}
	if !strings.Contains(res.Text, "text") {
		t.Fatalf("拒收句没列出可用参数名 ⇒ 调用方只能瞎猜：%s", res.Text)
	}
	res2, _ := 工.Run(context.Background(), map[string]any{"text": 3})
	if res2.Class != ClassBadArgs || !strings.Contains(res2.Text, "要 string") {
		t.Fatalf("类型错判成 %s ｜ %s", res2.Class, res2.Text)
	}
	res3, _ := 工.Run(context.Background(), map[string]any{})
	if res3.Class != ClassBadArgs {
		t.Fatalf("两个参数都不给应当 bad_args，给了 %s：%s", res3.Class, res3.Text)
	}
}

func TestGatesRefuseBeforeCalling(t *testing.T) {
	_, a, c := 搭(t, nil)
	if c.AllowWrite || c.AllowExec {
		t.Fatal("默认必须都关着")
	}
	res := a.RunTurn(context.Background(), "把结论存成笔记「x.md」", nil)
	看 := 步(t, "notes.write", res)
	if 看.Class != ClassRefused || 看.Attempts != 0 {
		t.Fatalf("notes.write 类别=%s 试了 %d 次", 看.Class, 看.Attempts)
	}
	if 看.Evidence != EvAbsent || 看.AbsentWhy == "" {
		t.Fatalf("被挡这一格没记 absent 或没带理由：%+v", 看)
	}
	if 看.DegradedFrom != "" {
		t.Fatalf("被门口挡下却被降级（degraded_from=%s）⇒ 那等于绕过用户的同意找替身", 看.DegradedFrom)
	}
}

func TestNetPrecheckCountsZeroAttempts(t *testing.T) {
	_, a, _ := 搭(t, nil)
	res := a.RunTurn(context.Background(), "取一下 https://example.com/robots.txt", nil)
	看 := 步(t, "http.get", res)
	if 看.Attempts != 0 {
		t.Fatalf("出网门口挡下却记了 %d 次尝试 ⇒ 白名单是在工具内部判的，账上分不开「没打」与「打了失败」", 看.Attempts)
	}
	if !strings.Contains(看.Text, "没打到外面") {
		t.Fatalf("拒收句没写清是没打出去：%s", 看.Text)
	}
}

func TestRetryBackoffAndNoRetryClasses(t *testing.T) {
	x, a, _ := 搭(t, nil)
	x.resetFlaky()
	res := a.RunTurn(context.Background(), "用 flaky 演示重试，前 2 次要失败", nil)
	看 := 步(t, "demo.flaky", res)
	if 看.Attempts != 3 || 看.Class != ClassOK {
		t.Fatalf("试了 %d 次、类别 %s（要 3 次且成功）", 看.Attempts, 看.Class)
	}
	if res.WaitedMs <= 0 {
		t.Fatalf("重用了却没等（WaitedMs=%d）⇒ 退避那条分支没跑过", res.WaitedMs)
	}
	工, _ := x.reg.Get("calc.eval")
	out := 调一次(context.Background(), 工, map[string]any{"expr": "1/0"}, nil, 1, "测试")
	if out.Res.Class != ClassBadArgs {
		t.Fatalf("除以 0 判成 %s：%s", out.Res.Class, out.Res.Text)
	}
	if out.Attempts != 1 {
		t.Fatalf("算式错重试了 %d 次 ⇒ 拿同一个错再撞一次墙还把耗时记进账", out.Attempts)
	}
}

func TestDegradeMarksItsSource(t *testing.T) {
	x, a, _ := 搭(t, nil)
	x.resetFlaky()
	res := a.RunTurn(context.Background(), "用 flaky 演示降级，前 9 次都要失败", nil)
	var 看 *Observation
	for i := range res.Steps {
		if res.Steps[i].DegradedFrom == "demo.flaky" {
			看 = &res.Steps[i]
		}
	}
	if 看 == nil {
		t.Fatalf("没有一步标着从 demo.flaky 降级来（步：%v）⇒ 读起来就像 flaky 自己成功了", 步名(res))
	}
	if res.Degrades != 1 {
		t.Fatalf("降级计数=%d，要正好 1", res.Degrades)
	}
	if 看.Class != ClassOK || !strings.Contains(看.Text, "降级用 time.now") {
		t.Fatalf("降级后没跑成或结论句里看不见：%s", 截(看.Text, 140))
	}
}

func TestMemoryAcrossProcessAndReference(t *testing.T) {
	x, a, c := 搭(t, nil)
	写文件(c.FsRoots[0], "大的一个.txt", strings.Repeat("行\n", 4))
	头 := a.RunTurn(context.Background(), "列一下 "+c.FsRoots[0]+" 目录", nil)
	第二 := a.RunTurn(context.Background(), "再统计最大的那个文件有多少行", nil)
	看 := 步(t, "text.stats", 第二)
	if 看.Class != ClassOK {
		t.Fatalf("绑定后没跑成：%s ｜ %s（第一发步：%v）", 看.Class, 截(看.Text, 120), 步名(头))
	}
	if !strings.Contains(看.ArgsFrom, "top+dir") {
		t.Fatalf("参数来处=%q ⇒ 不像从上一发读数拼出来的", 看.ArgsFrom)
	}
	另 := NewMemory(x.会话文件)
	行, 坏, err := 另.Load()
	if err != nil {
		t.Fatal(err)
	}
	if 坏 != 0 {
		t.Fatalf("会话文件有 %d 行读不回来 ⇒ 写与读不一致", 坏)
	}
	if 另.NextTurn() != x.mem.NextTurn() {
		t.Fatalf("重开进程后发号 %d ≠ %d ⇒ 会撞号", 另.NextTurn(), x.mem.NextTurn())
	}
	if 行 < 4 {
		t.Fatalf("盘上才 %d 行 ⇒ 两发没写够", 行)
	}
}

func TestAskInsteadOfInventingArgs(t *testing.T) {
	_, a, _ := 搭(t, nil)
	res := a.RunTurn(context.Background(), "读一下那个文件", nil)
	if res.Stop != "要补参数" {
		t.Fatalf("没路径时这一发结束了=%s：%s ⇒ 该停下来问，不该编一个", res.Stop, res.StopWhy)
	}
	if len(res.Steps) != 0 {
		t.Fatalf("既然要问，就不该有步（实际 %v）", 步名(res))
	}
	统计 := a.RunTurn(context.Background(), "统计一下最大的那个文件", nil)
	if 统计.Stop != "要补参数" {
		t.Fatalf("记忆里没文件时统计结束了=%s ⇒ 拿用户这句话自己当统计对象是换对象", 统计.Stop)
	}
}

func TestWindowDropIsVisible(t *testing.T) {
	_, a, _ := 搭(t, func(c *Config) { c.ContextChars = 30 })
	for _, 话 := range []string{"列一下 .", "算一下 2+3", "现在几点了", "有哪些工具"} {
		a.RunTurn(context.Background(), 话, nil)
	}
	res := a.RunTurn(context.Background(), "现在几点了", nil)
	见 := false
	for _, f := range res.Findings {
		if strings.Contains(f.Text, "窗口外挤掉") && res.Dropped > 0 {
			见 = true
		}
	}
	if !见 {
		t.Fatalf("窗口被裁却看不见挤掉了几条（Dropped=%d）⇒ 裁剪被藏起来了", res.Dropped)
	}
}

func TestSaneJudgeBitesEachLie(t *testing.T) {
	形 := []struct {
		名  string
		改  func(*Turn)
		期望 string
	}{
		{"成功却一次也没试", func(r *Turn) {
			for i := range r.Steps {
				if r.Steps[i].Class == ClassOK {
					r.Steps[i].Attempts = 0
				}
			}
		}, "成功了却一次也没试"},
		{"absent没理由", func(r *Turn) {
			for i := range r.Steps {
				r.Steps[i].Class = ClassRefused
				r.Steps[i].Evidence = EvAbsent
				r.Steps[i].AbsentWhy = ""
			}
		}, "absent没理由"},
		{"没成却署了measured", func(r *Turn) {
			for i := range r.Steps {
				r.Steps[i].Class = ClassRefused
				r.Steps[i].Evidence = EvMeasured
			}
		}, "没成却署了measured"},
		{"成了却没读数", func(r *Turn) {
			for i := range r.Steps {
				r.Steps[i].Evidence = EvAbsent
				if r.Steps[i].AbsentWhy == "" {
					r.Steps[i].AbsentWhy = "这里是谎"
				}
			}
		}, "成了却没读数"},
		{"端点没配却说模型说的", func(r *Turn) {
			if len(r.Steps) > 0 {
				r.Steps[0].Provenance = "model_says"
			}
		}, "端点没配却有model_says"},
		{"署名不认识", func(r *Turn) {
			if len(r.Steps) > 0 {
				r.Steps[0].Provenance = "猜的"
			}
		}, "署名不在名册里"},
		{"五档加总不等", func(r *Turn) { r.Mix["measured"] += 2 }, "五档加总不等"},
		{"空收口", func(r *Turn) {
			for i := range r.Steps {
				r.Steps[i].Class = ClassUpstream
				r.Steps[i].Evidence = EvAbsent
				if r.Steps[i].AbsentWhy == "" {
					r.Steps[i].AbsentWhy = "上游没回"
				}
			}
			r.Stop = "跑完"
		}, "空收口"},
		{"降级没写来处", func(r *Turn) {
			r.Steps[0].DegradedFrom = "某个没在结论里出现过的工具"
		}, "降级却没写从谁降级来"},
	}
	for _, 条 := range 形 {
		t.Run(条.名, func(t *testing.T) {
			_, a, _ := 搭(t, nil)
			res := a.RunTurn(context.Background(), "现在几点了", nil)
			if len(res.Steps) == 0 {
				t.Fatal("这一发没步子 ⇒ 针是空的")
			}
			条.改(&res)
			过, 红 := a.自洽判(res)
			if 过 {
				t.Fatal("谎发过了判据")
			}
			找到 := false
			for _, h := range 红 {
				if strings.Contains(h, 条.期望) {
					找到 = true
				}
			}
			if !找到 {
				t.Fatalf("红了但没点名该点的 %q：%v", 条.期望, 红)
			}
		})
	}
}

func TestJudgeNameMustBeInRoster(t *testing.T) {
	_, a, _ := 搭(t, nil)
	res := a.RunTurn(context.Background(), "现在几点了", nil)
	改 := append([]Observation(nil), res.Steps...)
	造了 := false
	for i := range 改 {
		if 改[i].Class == ClassOK {
			改[i].Attempts = 0
			造了 = true
		}
	}
	if !造了 {
		t.Fatal("没有成功步可供造假 ⇒ 这条臂什么都没量")
	}
	res.Steps = 改
	存 := append([]string(nil), 自洽名册...)
	自洽名册 = []string{"别的名字"}
	defer func() { 自洽名册 = 存 }()
	过, 红 := a.自洽判(res)
	认出来 := false
	for _, h := range 红 {
		if strings.Contains(h, "不在名册里") {
			认出来 = true
		}
	}
	if 过 || !认出来 {
		t.Fatalf("规则咬了但名册不认这个名字，判据却没点名（过=%v 红=%v）", 过, 红)
	}
}

func TestRealTurnsStaySelfConsistent(t *testing.T) {
	_, a, _ := 搭(t, nil)
	各 := []string{"列一下 .", "算一下 (2+3)*4**2", "现在几点了", "有哪些工具", "还记得 文件", "取一下 http://127.0.0.1:1/x"}
	var 列 []Turn
	for _, 话 := range 各 {
		res := a.RunTurn(context.Background(), 话, nil)
		if res.Sane == nil {
			t.Fatalf("话 %q 没交自洽读数（三态里的「没量过」）", 话)
		}
		if !*res.Sane {
			t.Fatalf("话 %q 整列自洽是红的：%s", 话, res.SaneWhy)
		}
		if !res.MixOK {
			t.Fatalf("话 %q 五档加总不等：%+v", 话, res.Mix)
		}
		if res.Turn != len(列)+1 {
			t.Fatalf("发号 %d ≠ %d ⇒ 会话内没接续", res.Turn, len(列)+1)
		}
		列 = append(列, res)
	}
	过, 话 := 跨发判据(列)
	if !过 {
		t.Fatalf("跨发不自洽：%s", 话)
	}
}

func TestCrossTurnJudgeCatchesBrokenChain(t *testing.T) {
	_, a, _ := 搭(t, nil)
	var 列 []Turn
	for _, 话 := range []string{"现在几点了", "算一下 1+1"} {
		列 = append(列, a.RunTurn(context.Background(), 话, nil))
	}
	过, 话 := 跨发判据(列)
	if !过 {
		t.Fatalf("两发真话被判红：%s", 话)
	}
	跳号 := append([]Turn(nil), 列...)
	跳号[1].Turn = 9
	if 过, 话 = 跨发判据(跳号); 过 || !strings.Contains(话, "发号") {
		t.Fatalf("发号跳了却没判红（过=%v 话=%s）", 过, 话)
	}
	没交 := append([]Turn(nil), 列...)
	没交[0].Sane = nil
	if 过, 话 = 跨发判据(没交); 过 || !strings.Contains(话, "没交自洽读数") {
		t.Fatalf("旧发没交判据读数却被当过了（过=%v 话=%s）⇒ 三态塌成担保", 过, 话)
	}
}

func TestManifestToolRunsForReal(t *testing.T) {
	f, err := 起假端点(false)
	if err != nil {
		t.Fatal(err)
	}
	defer f.收()
	x, _, c := 搭(t, nil)
	先 := x.reg.Count()
	写文件(c.ToolsDir, "本机取.json", fmt.Sprintf(
		`{"name":"local.ping","summary":"取本机一下","risk":"net_local","timeout_ms":2000,"retry":{"attempts":2,"backoff_ms":10,"backoff_max_ms":50},"invoke":{"kind":"http_get","url":"%s"}}`, f.地址))
	装, 拒 := LoadManifests(c.ToolsDir, x.reg, x.net)
	if len(装) != 1 || len(拒) != 0 {
		t.Fatalf("loaded=%v rejected=%v", 装, 拒)
	}
	if x.reg.Count() != 先+1 {
		t.Fatalf("工具数 %d → %d", 先, x.reg.Count())
	}
	工, _ := x.reg.Get("local.ping")
	out := 调一次(context.Background(), 工, map[string]any{}, nil, 1, "测试")
	if out.Res.Class != ClassOK {
		t.Fatalf("清单工具跑不起来：%s ｜ %s", out.Res.Class, out.Res.Text)
	}
	if !strings.HasPrefix(工.Spec().Source, "manifest:") {
		t.Fatalf("来源没标清单：%q ⇒ 分不清内置与挂载", 工.Spec().Source)
	}
	if !strings.Contains(工.Spec().Summary, "取本机") {
		t.Fatalf("清单里的 summary 没进说明书：%q", 工.Spec().Summary)
	}
}

func TestBadManifestIsRejectedNotSilent(t *testing.T) {
	x, _, c := 搭(t, nil)
	写文件(c.ToolsDir, "坏清单.json", `{"name":`)
	写文件(c.ToolsDir, "没人认的kind.json", `{"name":"k","summary":"s","risk":"compute","timeout_ms":500,"retry":{"attempts":1},"invoke":{"kind":"magic"}}`)
	装, 拒 := LoadManifests(c.ToolsDir, x.reg, x.net)
	if len(装) != 1 {
		t.Fatalf("loaded=%v（坏清单不该拖垮整批，格式合法的那个要装上）", 装)
	}
	if len(拒) != 1 || !strings.Contains(拒[0], "不是合法清单") {
		t.Fatalf("rejected=%v ⇒ 坏清单被静默跳过了", 拒)
	}
	工, _ := x.reg.Get("k")
	res, _ := 工.Run(context.Background(), map[string]any{})
	if res.Class != ClassUnsupported || !strings.Contains(res.Text, "magic") {
		t.Fatalf("没人解释的 kind 回了 %s ｜ %s", res.Class, res.Text)
	}
}

func TestSSEEndToEndEventsAndToolVisualization(t *testing.T) {
	x, _, c := 搭(t, nil)
	地址, 停 := 起监听(t, c, x)
	defer 停()
	resp, err := http.Post("http://"+地址+"/api/chat", "application/json", strings.NewReader(`{"text":"算一下 6*7"}`))
	if err != nil {
		t.Fatalf("连不上：%v", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != 200 {
		t.Fatalf("HTTP %d ⇒ 404 的正文里也有关键词，别拿正文当跑过了", resp.StatusCode)
	}
	总 := string(读完(t, resp.Body))
	for _, 件 := range []string{"event: meta", "event: plan", "event: tool_status", "event: tool_result", "event: answer_delta", "event: result", "event: done"} {
		if !strings.Contains(总, 件) {
			t.Fatalf("少了一类事件 %s（收了 %d 字节）⇒ 前端就看不见这一维", 件, len(总))
		}
	}
	for _, 格 := range []string{`"args"`, `"attempts"`, `"evidence"`, `"provenance"`, `"sane"`, `"mix"`, `"stop_why"`} {
		if !strings.Contains(总, 格) {
			t.Fatalf("读数里缺 %s ⇒ 工具调用可视化少一栏", 格)
		}
	}
	for _, 脏 := range []string{"undefined", "NaN", "[object Object]", "map[", "%!"} {
		if strings.Contains(总, 脏) {
			t.Fatalf("读数里带了 %q ⇒ 后端交了没人接的字段（map[ 就是拿 Go 的 %%v 打 map 的那一族）", 脏)
		}
	}
	if !strings.Contains(总, "\"risk\"") {
		t.Fatal("tool_result 里没有 risk ⇒ 前端的风险档徽章只能空着")
	}
	if !strings.Contains(总, "\"args_from\"") {
		t.Fatal("没交代参数来处 ⇒ 看不出这个 path 是话里抽的还是记忆里绑的")
	}
	h, err := http.Get("http://" + 地址 + "/api/health")
	if err != nil {
		t.Fatal(err)
	}
	hb := 读完(t, h.Body)
	h.Body.Close()
	if !strings.Contains(string(hb), `"tools"`) {
		t.Fatalf("health 没交工具数：%s", 截(string(hb), 120))
	}
	tj, err := http.Get("http://" + 地址 + "/api/tools")
	if err != nil {
		t.Fatal(err)
	}
	tjb := 读完(t, tj.Body)
	tj.Body.Close()
	var 面 struct {
		Count int        `json:"count"`
		Specs []ToolSpec `json:"specs"`
	}
	if err := json.Unmarshal(tjb, &面); err != nil {
		t.Fatalf("/api/tools 不是合法 JSON：%v（正文 %s）", err, 截(string(tjb), 120))
	}
	if 面.Count != len(面.Specs) || 面.Count < 11 {
		t.Fatalf("count=%d specs=%d ⇒ 自述端点与注册表对不上", 面.Count, len(面.Specs))
	}
}

func TestExecRunAcceptsBothSlicesAndRefusesEmpty(t *testing.T) {
	x, _, _ := 搭(t, func(cc *Config) { cc.AllowExec = true })
	工, _ := x.reg.Get("exec.run")
	res, _ := 工.Run(context.Background(), map[string]any{"argv": []string{"cmd", "/c", "echo", "hi"}})
	if res.Class != ClassOK || !strings.Contains(res.Text, "hi") {
		t.Fatalf("[]string 那条路没跑通：%s ｜ %s", res.Class, 截(res.Text, 140))
	}
	res2, _ := 工.Run(context.Background(), map[string]any{"argv": []any{}})
	if res2.Class != ClassBadArgs {
		t.Fatalf("空 argv 判成 %s（应当 bad_args 并说清是没给参数，不是执行失败）：%s", res2.Class, res2.Text)
	}
}

func TestConcurrentTurnIsRefusedNotInterleaved(t *testing.T) {
	x, _, c := 搭(t, func(cc *Config) { cc.StepDelay = 40 * time.Millisecond })
	地址, 停 := 起监听(t, c, x)
	defer 停()
	端 := "http://" + 地址 + "/api/chat"
	第完 := make(chan struct{})
	go func() {
		defer close(第完)
		r, err := http.Post(端, "application/json", strings.NewReader(`{"text":"现在几点了"}`))
		if err == nil {
			io.ReadAll(r.Body)
			r.Body.Close()
		}
	}()
	time.Sleep(30 * time.Millisecond)
	r2, err := http.Post(端, "application/json", strings.NewReader(`{"text":"算一下 1+1"}`))
	if err != nil {
		t.Fatalf("第二发连不上：%v", err)
	}
	b := 读完(t, r2.Body)
	r2.Body.Close()
	if !strings.Contains(string(b), "上一发还在跑") {
		t.Fatalf("第二发没被重入保护挡下（回了 %s）⇒ 两发的步骤会混进同一列", 截(string(b), 140))
	}
	<-第完
}

func TestEvalExprShapes(t *testing.T) {
	对 := map[string]float64{
		"1+2*3":     7,
		"(2+3)*4":   20,
		"2**3**2":   512, // 右结合：左结合会算成 64
		"-4+2":      -2,
		"7%3":       1,
		"10/4":      2.5,
		"(1)":       1,
		"2 * (3+4)": 14,
	}
	for 式, 值 := range 对 {
		got, err := evalExpr(式)
		if err != nil {
			t.Fatalf("%q 没过：%v", 式, err)
		}
		if got != 值 {
			t.Fatalf("%q = %v，要 %v", 式, got, 值)
		}
	}
	坏 := []string{"1/0", "(1+2", "1..2", "abc", "2+*3", ""}
	for _, 式 := range 坏 {
		if _, err := evalExpr(式); err == nil {
			t.Fatalf("%q 本该报错却出了数", 式)
		}
	}
}

func TestFsGuardBlocksEscape(t *testing.T) {
	x, _, c := 搭(t, nil)
	工, _ := x.reg.Get("fs.read")
	for _, 越 := range []string{"..\\..\\Windows\\win.ini", "../../etc/passwd", filepath.Join(c.FsRoots[0], "..", "..", "x.txt")} {
		res, _ := 工.Run(context.Background(), map[string]any{"path": 越})
		if res.Class != ClassRefused {
			t.Fatalf("路径 %q 被判成 %s ⇒ 文件根没拦住（%s）", 越, res.Class, 截(res.Text, 100))
		}
	}
	res, _ := 工.Run(context.Background(), map[string]any{"path": filepath.Join(c.FsRoots[0], "在根里的.txt")})
	if res.Class == ClassRefused {
		t.Fatalf("根内的路径被挡了：%s", res.Text)
	}
}
func TestManifestWithTriggersIsPickedByLocalPlanner(t *testing.T) {
	f, err := 起假端点(false)
	if err != nil {
		t.Fatal(err)
	}
	defer f.收()
	x, a, c := 搭(t, nil)
	写文件(c.ToolsDir, "带触发词.json", fmt.Sprintf(
		`{"name":"本机探针","summary":"取本机一下看管路","risk":"net_local","timeout_ms":2000,"retry":{"attempts":1,"backoff_ms":10,"backoff_max_ms":50},"triggers":["探一下本机"],"invoke":{"kind":"http_get","url":"%s"}}`, f.地址))
	装, 拒 := LoadManifests(c.ToolsDir, x.reg, x.net)
	if len(装) != 1 || len(拒) != 0 {
		t.Fatalf("loaded=%v rejected=%v", 装, 拒)
	}
	res := a.RunTurn(context.Background(), "探一下本机", nil)
	看 := 步(t, "本机探针", res)
	if 看.Class != ClassOK {
		t.Fatalf("挂载工具被选中但没跑成：%s ｜ %s", 看.Class, 截(看.Text, 140))
	}
	if 看.Provenance != "estimated" {
		t.Fatalf("这一步署了 %s ⇒ 是本机规则选的就别写成别人选的", 看.Provenance)
	}
	if 看.Evidence != EvRelayed {
		t.Fatalf("外部正文却署成 %s ⇒ 转述与量到的分不开", 看.Evidence)
	}
	_, 红 := a.自洽判(res)
	if len(红) > 0 {
		t.Fatalf("挂载工具这一形把判据撞红：%v", 红)
	}
}

func TestAnaphoraBeatsRawPathToken(t *testing.T) {
	// 部署侧第一跑的真实形状：一句话里既有裸目录路径又有"最大的那个文件"，
	// 顺序写反了就会拿目录当统计对象，撞两次上游错再吃掉步数上限。
	_, a, c := 搭(t, nil)
	写文件(c.FsRoots[0], "最大的一份.txt", strings.Repeat("三段内容一字一行 ", 3))
	写文件(c.FsRoots[0], "小的一份.txt", "一行")
	res := a.RunTurn(context.Background(), "列一下 "+c.FsRoots[0]+" 目录，按大小排，再统计最大的那个文件有多少行", nil)
	统 := 步(t, "text.stats", res)
	if !strings.Contains(统.ArgsFrom, "top+dir") {
		t.Fatalf("统计对象来处=%q args=%v ⇒ 指代没赢过话里的裸路径", 统.ArgsFrom, 统.Args)
	}
	if 统.Class != ClassOK {
		t.Fatalf("绑定后没跑成：%s ｜ %s", 统.Class, 截(统.Text, 140))
	}
	if res.Stop == "步数上限" {
		t.Fatalf("两goal一句话却走到步数上限：%s", res.StopWhy)
	}
	_, 红 := a.自洽判(res)
	if len(红) > 0 {
		t.Fatalf("这一形把判据撞红：%v", 红)
	}
}

func TestSameShapeFailureStopsInsteadOfRebumbling(t *testing.T) {
	x, a, c := 搭(t, nil)
	res := a.RunTurn(context.Background(), "统计一下 "+c.FsRoots[0]+" 有多少行", nil)
	if len(res.Steps) != 1 {
		t.Fatalf("同一套参数的失败撞了 %d 次（步：%v）⇒ 该撞一次就停", len(res.Steps), 步名(res))
	}
	看 := res.Steps[0]
	if 看.Class != ClassBadArgs || !strings.Contains(看.Text, "是个目录") {
		t.Fatalf("目录当统计对象判成 %s ｜ %s（要说清是参数给错对象，不是读失败）", 看.Class, 截(看.Text, 120))
	}
	if res.Stop != "重复失败即停" {
		t.Fatalf("结束原因=%s：%s", res.Stop, res.StopWhy)
	}
	// 判据半边：手工造两次同样的重撞，必须点名"同形失败重撞"
	撞 := res
	撞.Steps = append([]Observation(nil), 看, 看)
	过, 红 := a.自洽判(撞)
	认出来 := false
	for _, h := range 红 {
		if strings.Contains(h, "同形失败重撞") {
			认出来 = true
		}
	}
	if 过 || !认出来 {
		t.Fatalf("重撞两次却没判红（过=%v 红=%v）", 过, 红)
	}
	_ = x
}

// TestWebContractHolds 是改样式时的结构针：CSS/HTML 重写最容易坏的不是好看，是 JS 找不到的那个 id。
// 所以这里机械对三遍：app.js 要的每个 id 都在 index.html 里；app.js 会造的每个类名都在 style.css 里有规则；
// 会增长的容器都限了高（无界撑栏是这类面板的老病）。
func TestWebContractHolds(t *testing.T) {
	js := 读进来(t, filepath.Join("web", "app.js"))
	页 := 读进来(t, filepath.Join("web", "index.html"))
	样 := 读进来(t, filepath.Join("web", "style.css"))

	要 := map[string]bool{}
	for _, m := range regexp.MustCompile(`\$\('([a-z0-9-]+)'\)`).FindAllStringSubmatch(js, -1) {
		要[m[1]] = true
	}
	for _, m := range regexp.MustCompile(`getElementById\('([a-z0-9-]+)'\)`).FindAllStringSubmatch(js, -1) {
		要[m[1]] = true
	}
	if len(要) < 10 {
		t.Fatalf("只从 app.js 认出 %d 个 id ⇒ 针本身失效了（正则没匹配上就别测）", len(要))
	}
	for id := range 要 {
		if !strings.Contains(页, `id="`+id+`"`) {
			t.Fatalf("app.js 要找 #%s，index.html 里没有 ⇒ 那一栏永远空白", id)
		}
	}
	类 := []string{"msg", "streaming", "call", "step", "tool", "args", "why", "result", "st", "tag", "plan",
		"answer", "dim", "red", "warn", "b", "measured", "estimated", "model_says", "relayed", "absent",
		"ok", "failed", "retrying", "backoff", "queued", "attempt", "ghost", "row", "legend", "streaming-on",
		// 纸面第二版加的：trace 行的网格头、耗时条、右对齐元数字、折叠、页签、快捷键提示、统计段
		"hd", "dur", "meta", "fold", "out", "tabs", "tab", "小钮", "统计", "sub",
		// 结论带折起来那一版：账一行、为什么折、折里的正文、窄屏夹一行时折里带的全文
		"带一", "带折", "带故", "账全"}
	页签 := []string{"fold", "new", "tab-reg", "tab-hist", "registry", "hist", "msgs", "calls", "band",
		"findings", "unknowns", "answer", "health", "input", "go", "stop", "budget", "say"}
	for _, id := range 页签 {
		if !strings.Contains(页, `id="`+id+`"`) {
			t.Fatalf("index.html 里没有 #%s ⇒ app.js 会拿到 null 并在第一发就崩", id)
		}
	}
	for _, c := range 类 {
		if !regexp.MustCompile(`\.` + regexp.QuoteMeta(c) + `([^A-Za-z0-9_-]|$)`).MatchString(样) {
			t.Fatalf("style.css 里没有 .%s 的规则 ⇒ 这个类名的元素会掉回浏览器默认样式", c)
		}
	}
	for _, 容器 := range []string{"#msgs", "#calls", "#hist", "#registry", "#findings", "#unknowns"} {
		块 := regexp.MustCompile(regexp.QuoteMeta(容器) + `[^}]*max-height:\s*(\d+)vh`).FindStringSubmatch(样)
		if 块 == nil {
			t.Fatalf("%s 没限高 ⇒ 会无界撑整栏", 容器)
		}
	}
	if !strings.Contains(样, "prefers-reduced-motion") || !strings.Contains(样, "focus-visible") {
		t.Fatal("少了 reduced-motion 或 focus-visible 之一 ⇒ 动效与键盘这两条被样式重写弄丢了")
	}
	后 := 读进来(t, "httpapi.go")
	全, 缺 := 端点接线(后, js)
	if len(全) < 5 {
		t.Fatalf("只从 httpapi.go 认出 %d 个 /api 端点 ⇒ 这根针自己失效了（正则没匹配上就别测）", len(全))
	}
	if len(缺) > 0 {
		t.Fatalf("后端注册了这些端点，前端一处都没调用：%s ⇒ 页面上根本做不到这件事", strings.Join(缺, "、"))
	}
}

// 端点接线 对"后端注册了 /api/* 却没人接"这一形。
// 起因是真的漏过一次：/api/session/new 后端早写好了，app.js 里 0 处调用 ⇒ 页面上换不了账，
// 而当时 24 个 Test、全部闸都绿 —— 没有任何一根针管"注册了却没人接"。
func 端点接线(后端 string, js string) ([]string, []string) {
	见 := map[string]bool{}
	for _, m := range regexp.MustCompile(`mux\.HandleFunc\("(/api/[a-z0-9/-]+)"`).FindAllStringSubmatch(后端, -1) {
		见[m[1]] = true
	}
	var 全, 缺 []string
	for 路 := range 见 {
		全 = append(全, 路)
		// 路径后面允许引号或查询串：app.js 里写的是 fetch('/api/turns?limit=40')，
		// 只认"紧跟引号"会把这条真调用判成没接（针第一跑就误报过一次）。
		if !regexp.MustCompile(regexp.QuoteMeta(路) + `["'?]`).MatchString(js) {
			缺 = append(缺, 路)
		}
	}
	sort.Strings(全)
	sort.Strings(缺)
	return 全, 缺
}

// TestApiRoutePinBites 是那根针自己的臂：造一个"注册了没人接"的端点，针必须点名它；
// 全接上时必须数出 0 缺 —— 两头都咬，它才不是恒绿。
func TestApiRoutePinBites(t *testing.T) {
	后 := `mux.HandleFunc("/api/chat", h.chat)
mux.HandleFunc("/api/orphan", h.orphan)`
	全, 缺 := 端点接线(后, "fetch('/api/chat')")
	if len(全) != 2 {
		t.Fatalf("认出 %d 个端点，该是 2 ⇒ %v", len(全), 全)
	}
	if len(缺) != 1 || 缺[0] != "/api/orphan" {
		t.Fatalf("注册了没人接却没点名（缺=%v）⇒ 这根针恒绿，别拿它当证据", 缺)
	}
	if _, 缺2 := 端点接线(后, "fetch('/api/chat')；fetch('/api/orphan')"); len(缺2) != 0 {
		t.Fatalf("两头都接了还报缺：%v ⇒ 匹配面太窄", 缺2)
	}
}

func 读进来(t *testing.T, 路 string) string {
	t.Helper()
	b, err := os.ReadFile(路)
	if err != nil {
		t.Fatalf("读 %s 失败：%v", 路, err)
	}
	return string(b)
}

// TestFakeEndpointReadsWholeBody 是假端点自己的臂：正文分两块写，中间停一下。
// 一次 Read 只拿到第一块 ⇒ Unmarshal 静默失败 ⇒ 它回默认分支 time.now，
// 看上去"端点在选件"，其实一个字都没读到（真服务器上 12 个工具说明书 + 历史就是几 KB，正是这一形）。
// ReadAll 才吃得下整包 ⇒ 必须回 fs.list。
func TestFakeEndpointReadsWholeBody(t *testing.T) {
	f, err := 起假端点(false)
	if err != nil {
		t.Fatal(err)
	}
	defer f.收()
	地址 := strings.TrimPrefix(f.地址, "http://")
	if i := strings.Index(地址, "/"); i > 0 {
		地址 = 地址[:i] // 拨号只要 host:port，路径写在进行中的请求行里
	}
	c, err := net.Dial("tcp", 地址)
	if err != nil {
		t.Fatal(err)
	}
	defer c.Close()
	体 := `{"messages":[{"role":"user","content":"列一下当前目录"}],"tools":[{"name":"calc.eval","description":"算一个算式"}]}`
	半 := len(体) / 2
	if _, err = fmt.Fprintf(c, "POST /v1/chat HTTP/1.1\r\nHost: x\r\nContent-Type: application/json\r\nContent-Length: %d\r\n\r\n%s",
		len(体), 体[:半]); err != nil {
		t.Fatal(err)
	}
	time.Sleep(260 * time.Millisecond) // 让第一块先落地
	if _, err = c.Write([]byte(体[半:])); err != nil {
		t.Fatal(err)
	}
	if tc, ok := c.(*net.TCPConn); ok {
		_ = tc.CloseWrite()
	}
	_ = c.SetReadDeadline(time.Now().Add(3 * time.Second))
	回, _ := io.ReadAll(c)
	话 := string(回)
	if !strings.Contains(话, `"tool":"fs.list"`) {
		t.Fatalf("分两块发的正文没被读全（回：%s）⇒ 端点漏读时谁都在选件，其实它没听见", 截(话, 160))
	}
}

// TestModelPlannerPicksAndRuns 量的是"端点选的那一步真跑得成"。
// 这一形原先没人管：假端点拿整包请求找关键词，而请求里永远带着工具说明书（"算一个算式…"），
// 于是它逢问就选 calc.eval 却只带 path ⇒ 每步 bad_args，可 provenance 照样署 model_says、
// 13 条判据全绿 —— "谁选的"署对了，没人问"选完跑没跑成"。
func TestModelPlannerPicksAndRuns(t *testing.T) {
	f, err := 起假端点(false)
	if err != nil {
		t.Fatal(err)
	}
	defer f.收()
	活, _ := os.Getwd()
	x, a, _ := 搭(t, func(c *Config) {
		c.ModelEndpoint = f.地址
		c.ModelKeyEnv = "" // 假端点不查凭据
		// 假端点交的是 path="."（= 当前目录）。不把它列进根，这一步会被守卫挡下 ——
		// 挡得对（第一跑就是 refused，根只有临时目录），这一发要量的是"端点选的件跑不跑得成"。
		c.FsRoots = append(c.FsRoots, 活)
	})
	// 塞满历史再跑：空记忆时请求只有一小块，端点漏读正文也看不出来；
	// 带上历史（12 个工具的说明书 + 若干条长文本）正文才跨块 —— 那一形就是这么炸的。
	for i := 0; i < 8; i++ {
		x.mem.Append(Msg{Turn: 900 + i, Role: "user", Text: strings.Repeat("上一发说过的那句话，带上目录与参数口径的长文本", 8)})
		x.mem.Append(Msg{Turn: 900 + i, Role: "agent", Text: strings.Repeat("上一发的回话，长文本长文本长文本", 8)})
	}
	res := a.RunTurn(context.Background(), "列一下当前目录", nil)
	看 := 步(t, "fs.list", res)
	if 看.Provenance != "model_says" {
		t.Fatalf("这一步署了 %s ⇒ 端点选的却写成本机选的", 看.Provenance)
	}
	if 看.Class != ClassOK {
		t.Fatalf("端点选的这一步没跑成：%s ｜ %s", 看.Class, 截(看.Text, 140))
	}
	for _, o := range res.Steps {
		if o.Class == "bad_args" {
			t.Fatalf("端点交的参数本机不认（步 %d %s：%s）⇒ 管路没通，光看 model_says 会以为通了",
				o.Step, o.Tool, 截(o.Text, 120))
		}
	}
	if !strings.Contains(res.Plan, "模型端点") {
		t.Fatalf("规划器那格写的是 %q ⇒ 端点起了却没走它，这一发的出处要重看", res.Plan)
	}
	// 端点自己收口那一形。注意"跑完"有两种来处：端点说 done，或本机目标表判满 ——
	// 只断言 Stop=="跑完"是空的（把端点改成永不收口，这一发照样"跑完"），必须点名是谁收的口。
	if !strings.Contains(res.StopWhy, "端点说可以收口") {
		t.Fatalf("结束=%s：%s ⇒ 这一发的口不是端点收的（它没读「已做过：N 步」？），别把本机判满说成端点收口",
			res.Stop, 截(res.StopWhy, 120))
	}
}
