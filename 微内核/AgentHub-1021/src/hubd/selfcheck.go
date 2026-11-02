package main

// 自检：一条命令把"这台机器到底做没做到它承诺的那些事"跑一遍。
// 分两类：正臂（该过的必须过）与臂·会红（该被抓住的谎必须被抓住）。
// 任何一条不合期望就 [RED] 并让退出码非 0 —— 退出码是契约，不是装饰。

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"
)

type 自检机 struct {
	底  string
	台次 int
	跑过 int
	红  []string
}

func 自检(cfg Config) int {
	底 := filepath.Join(os.TempDir(), "hubd-自检")
	os.RemoveAll(底)
	if err := os.MkdirAll(底, 0o755); err != nil {
		fmt.Fprintf(os.Stderr, "自检连临时目录都建不起来：%v\n", err)
		return 2
	}
	s := &自检机{底: 底}
	fmt.Printf("hubd 自检 · 临时根 %s\n", 底)

	s.条("装配·内置工具都注册上了并且数得出来", func(z *自检机) (string, error) {
		x, _ := z.新台(cfg)
		名 := x.reg.Names()
		if len(名) < 11 {
			return "", fmt.Errorf("内置工具只注册了 %d 个（预期至少 11：列/读/统计/算/时间/取/清单/记忆/笔记/执行/自检）", len(名))
		}
		if x.reg.Count() != len(名) {
			return "", fmt.Errorf("Count=%d 与 Names=%d 不一致 ⇒ 有一面在撒谎", x.reg.Count(), len(名))
		}
		return fmt.Sprintf("%d 个：%s", len(名), strings.Join(名, "、")), nil
	})

	s.条("注册表·重名不许影子覆盖", func(z *自检机) (string, error) {
		x, _ := z.新台(cfg)
		先 := x.reg.Count()
		写文件(x.cfg.ToolsDir, "撞名.json", `{"name":"fs.list","summary":"顶掉内置的","risk":"local_read","timeout_ms":500,"retry":{"attempts":1},"invoke":{"kind":"fs_read","root":"."}}`)
		装, 拒 := LoadManifests(x.cfg.ToolsDir, x.reg, x.net)
		if len(拒) == 0 {
			return "", fmt.Errorf("撞名清单被装上了（loaded=%v）⇒ 覆盖是静默的，工具总数再也没法自印", 装)
		}
		if !strings.Contains(拒[0], "重名") {
			return "", fmt.Errorf("拒了但不是因为重名：%s", 拒[0])
		}
		if x.reg.Count() != 先 {
			return "", fmt.Errorf("数量从 %d 涨到 %d ⇒ 还是被装进去了", 先, x.reg.Count())
		}
		if len(x.reg.shadow) == 0 {
			return "", fmt.Errorf("被拒的影子注册没留痕 ⇒ /api/tools 上看不见这件事")
		}
		return fmt.Sprintf("拒了：%s ｜ 影子留痕 %d 条", 拒[0], len(x.reg.shadow)), nil
	})

	s.条("扩展·放一个清单就多一个真能跑的工具", func(z *自检机) (string, error) {
		f, err := 起假端点(false)
		if err != nil {
			return "", err
		}
		defer f.收()
		x, _ := z.新台(cfg)
		先 := x.reg.Count()
		写文件(x.cfg.ToolsDir, "本机取.json", fmt.Sprintf(
			`{"name":"local.ping","summary":"取本机假端点一下","risk":"net_local","timeout_ms":2500,"retry":{"attempts":2,"backoff_ms":20,"backoff_max_ms":100},"params":[{"name":"url","type":"string","desc":"地址","required":false}],"invoke":{"kind":"http_get","url":"%s"}}`, f.地址))
		装, 拒 := LoadManifests(x.cfg.ToolsDir, x.reg, x.net)
		if len(装) != 1 || len(拒) != 0 {
			return "", fmt.Errorf("清单没装上（loaded=%v rejected=%v）", 装, 拒)
		}
		if x.reg.Count() != 先+1 {
			return "", fmt.Errorf("工具数 %d → %d，不是 +1", 先, x.reg.Count())
		}
		工, _ := x.reg.Get("local.ping")
		if 工.Spec().Source == "" || !strings.HasPrefix(工.Spec().Source, "manifest:") {
			return "", fmt.Errorf("来源没写清：%q ⇒ 分不清这个是内置还是挂载的", 工.Spec().Source)
		}
		out := 调一次(context.Background(), 工, map[string]any{}, func(string, any) {}, 1, "自检")
		if out.Res.Class != ClassOK {
			return "", fmt.Errorf("清单工具跑不起来：%s（%s）", out.Res.Class, out.Res.Text)
		}
		return fmt.Sprintf("装 %v ｜ 真跑到 %s ｜ %s", 装, f.地址, 第一行(out.Res.Text)), nil
	})

	s.条("门口·默认关掉写文件与执行时绝不真调起", func(z *自检机) (string, error) {
		x, a := z.新台(cfg)
		res := a.RunTurn(context.Background(), "把结论存成笔记「今天.md」", nil)
		var 挡 *Observation
		for i := range res.Steps {
			if res.Steps[i].Tool == "notes.write" {
				挡 = &res.Steps[i]
			}
		}
		if 挡 == nil {
			return "", fmt.Errorf("这一发压根没走到 notes.write（规划器没把「存成笔记」认出来）⇒ 这一条等于没量")
		}
		if 挡.Class != ClassRefused || 挡.Attempts != 0 {
			return "", fmt.Errorf("notes.write 类别=%s 试了 %d 次 ⇒ 没放行也被调起了", 挡.Class, 挡.Attempts)
		}
		if 挡.Evidence != EvAbsent || strings.TrimSpace(挡.AbsentWhy) == "" {
			return "", fmt.Errorf("被挡这一格没记 absent 或没带理由：%+v", 挡)
		}
		_, 红 := a.自洽判(res)
		for _, h := range 红 {
			if strings.Contains(h, "没放行却跑成了读数") {
				return "", fmt.Errorf("自洽判据里已经看见越界跑了：%s", h)
			}
		}
		if x.cfg.AllowWrite {
			return "", fmt.Errorf("自检这台默认就该关着写文件")
		}
		return 第一行(挡.Text), nil
	})

	s.条("门口·放行之后同一条真能跑（临时目录 + 超时）", func(z *自检机) (string, error) {
		c := cfg
		c.AllowExec = true
		_, a := z.新台(c)
		res := a.RunTurn(context.Background(), `跑一下命令「cmd /c echo hi」`, nil)
		var 跑 *Observation
		for i := range res.Steps {
			if res.Steps[i].Tool == "exec.run" {
				跑 = &res.Steps[i]
			}
		}
		if 跑 == nil {
			return "", fmt.Errorf("放行了却没走 exec.run ⇒ 规划器不认识这一形")
		}
		if 跑.Class != ClassOK {
			return "", fmt.Errorf("放行后没跑成：%s ｜ %s", 跑.Class, 跑.Text)
		}
		if !strings.Contains(跑.Text, "hi") {
			return "", fmt.Errorf("跑了但输出里没有 hi：%s", 截(跑.Text, 120))
		}
		return 第一行(跑.Text), nil
	})

	s.条("出网·清单外主机是没打出去，不是打失败", func(z *自检机) (string, error) {
		_, a := z.新台(cfg)
		res := a.RunTurn(context.Background(), "取一下 https://example.com/robots.txt 这个接口", nil)
		var 挡 *Observation
		for i := range res.Steps {
			if res.Steps[i].Tool == "http.get" {
				挡 = &res.Steps[i]
			}
		}
		if 挡 == nil {
			return "", fmt.Errorf("这一发没走 http.get ⇒ 没量到")
		}
		if 挡.Class != ClassRefused || !strings.Contains(挡.Text, "没打到外面") {
			return "", fmt.Errorf("类别=%s 话=%s ⇒ 拒收没被说成「压根没打出去」这一形", 挡.Class, 截(挡.Text, 120))
		}
		if 挡.Attempts != 0 {
			return "", fmt.Errorf("被门口挡下却还是试了 %d 次（那说明白名单只在事后判）", 挡.Attempts)
		}
		return 第一行(挡.Text), nil
	})

	s.条("重试·上游回坏要真再来一次并等", func(z *自检机) (string, error) {
		c := cfg
		c.MaxSteps = 2
		x, a := z.新台(c)
		x.resetFlaky()
		res := a.RunTurn(context.Background(), "用 flaky 演示重试，前 2 次要失败", nil)
		var 看 *Observation
		for i := range res.Steps {
			if res.Steps[i].Tool == "demo.flaky" {
				看 = &res.Steps[i]
			}
		}
		if 看 == nil {
			return "", fmt.Errorf("没走 demo.flaky ⇒ 规划器不认识「重试」这一形")
		}
		if 看.Class != ClassOK || 看.Attempts != 3 {
			return "", fmt.Errorf("试了 %d 次、类别 %s（前 2 次坏 + 第 3 次成 ⇒ 要正好 3）", 看.Attempts, 看.Class)
		}
		if res.WaitedMs <= 0 {
			return "", fmt.Errorf("重用了但没等（WaitedMs=%d）⇒ 退避是没跑的那条分支", res.WaitedMs)
		}
		return fmt.Sprintf("试 %d 次、等 %d ms ｜ %s", 看.Attempts, res.WaitedMs, 第一行(看.Text)), nil
	})

	s.条("重试·参数错不许再撞一次", func(z *自检机) (string, error) {
		c := cfg
		c.MaxSteps = 2
		x, a := z.新台(c)
		工, _ := x.reg.Get("text.stats")
		呼 := 0
		out := 调一次(context.Background(), 工, map[string]any{"text": 3}, func(k string, p any) {
			if k == "tool_status" {
				呼++
			}
		}, 1, "自检")
		_ = a
		if out.Res.Class != ClassBadArgs {
			return "", fmt.Errorf("类型不对却回了 %s（说明书说这形该是 bad_args）", out.Res.Class)
		}
		if out.Attempts != 1 {
			return "", fmt.Errorf("参数错重试了 %d 次 ⇒ 用同一个错参数再撞墙还把耗时记进账", out.Attempts)
		}
		return fmt.Sprintf("bad_args ｜ 只试 1 次 ｜ 状态事件 %d 条 ｜ %s", 呼, 第一行(out.Res.Text)), nil
	})

	s.条("降级·重试用尽走备选并把来处留下", func(z *自检机) (string, error) {
		c := cfg
		c.MaxSteps = 2
		x, a := z.新台(c)
		x.resetFlaky()
		res := a.RunTurn(context.Background(), "用 flaky 演示降级，前 9 次都要失败", nil)
		var 看 *Observation
		for i := range res.Steps {
			if res.Steps[i].Tool == "demo.flaky" || res.Steps[i].DegradedFrom != "" {
				看 = &res.Steps[i]
			}
		}
		if 看 == nil {
			return "", fmt.Errorf("没走 flaky ⇒ 没量到")
		}
		if 看.DegradedFrom != "demo.flaky" {
			return "", fmt.Errorf("degraded_from=%q ⇒ 降级没被标出来（读起来就像 flaky 自己成功了）", 看.DegradedFrom)
		}
		if res.Degrades != 1 {
			return "", fmt.Errorf("计数降级 %d 次（要正好 1）", res.Degrades)
		}
		if !strings.Contains(看.Text, "降级用 time.now") {
			return "", fmt.Errorf("结论句里看不见降级这件事：%s", 截(看.Text, 120))
		}
		return 第一行(看.Text), nil
	})

	s.条("臂·谎发「成功却一次也没试」必须被自洽判据点名", func(z *自检机) (string, error) {
		_, a := z.新台(cfg)
		res := a.RunTurn(context.Background(), "现在几点了", nil)
		原 := res.Steps
		改 := append([]Observation(nil), 原...)
		for i := range 改 {
			if 改[i].Class == ClassOK {
				改[i].Attempts = 0
			}
		}
		if len(改) == 0 {
			return "", fmt.Errorf("这一发没有任何步 ⇒ 这条臂是空臂，什么都没量")
		}
		res.Steps = 改
		过, 红 := a.自洽判(res)
		res.Steps = 原
		if 过 {
			return "", fmt.Errorf("谎发过了判据（把成功步的 attempts 改成 0 它都不响）")
		}
		if !strings.Contains(strings.Join(红, "；"), "成功了却一次也没试") {
			return "", fmt.Errorf("红了但没点名该点的那条：%v", 红)
		}
		return fmt.Sprintf("抓住：%s", 红[0]), nil
	})

	s.条("臂·谎发「absent 没理由」必须红", func(z *自检机) (string, error) {
		_, a := z.新台(cfg)
		res := a.RunTurn(context.Background(), "现在几点了", nil)
		改 := append([]Observation(nil), res.Steps...)
		动过 := false
		for i := range 改 {
			if 改[i].Class != ClassOK {
				改[i].Evidence = EvAbsent
				改[i].AbsentWhy = ""
				动过 = true
			}
		}
		if !动过 {
			改[0].Class = ClassRefused
			改[0].Evidence = EvAbsent
			改[0].AbsentWhy = ""
		}
		res.Steps = 改
		过, 红 := a.自洽判(res)
		if 过 || !strings.Contains(strings.Join(红, "；"), "absent没理由") {
			return "", fmt.Errorf("absent 不带理由这一形没被抓住（过=%v 红=%v）", 过, 红)
		}
		return fmt.Sprintf("抓住：%s", 红[0]), nil
	})

	s.条("臂·谎发「端点没配却署 model_says」必须红", func(z *自检机) (string, error) {
		_, a := z.新台(cfg)
		res := a.RunTurn(context.Background(), "现在几点了", nil)
		改 := append([]Observation(nil), res.Steps...)
		改[0].Provenance = "model_says"
		res.Steps = 改
		过, 红 := a.自洽判(res)
		if 过 || !strings.Contains(strings.Join(红, "；"), "端点没配却有model_says") {
			return "", fmt.Errorf("把规则选的件改署成模型说的，判据没响（过=%v 红=%v）", 过, 红)
		}
		return fmt.Sprintf("抓住：%s", 红[0]), nil
	})

	s.条("臂·谎发「五档加总不等」必须红", func(z *自检机) (string, error) {
		_, a := z.新台(cfg)
		res := a.RunTurn(context.Background(), "现在几点了", nil)
		res.Mix["measured"] += 3
		过, 红 := a.自洽判(res)
		if 过 || !strings.Contains(strings.Join(红, "；"), "五档加总不等") {
			return "", fmt.Errorf("五档加总被改乱了却不红（过=%v）", 过)
		}
		return fmt.Sprintf("抓住：%s", 红[0]), nil
	})

	s.条("臂·判据名不在名册里必须红（写了分支没人认得）", func(z *自检机) (string, error) {
		_, a := z.新台(cfg)
		res := a.RunTurn(context.Background(), "现在几点了", nil)
		// 光把名册换掉不会有任何规则咬 —— 那这条臂就成了空臂（什么都没量却报过）。
		// 所以要先造一个"必然会咬"的谎，再看名册认不认这个名字。
		改 := append([]Observation(nil), res.Steps...)
		造了谎 := false
		for i := range 改 {
			if 改[i].Class == ClassOK {
				改[i].Attempts = 0
				造了谎 = true
			}
		}
		if !造了谎 {
			return "", fmt.Errorf("这一发没有一个成功步可供造假 ⇒ 这条臂什么都没量")
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
			return "", fmt.Errorf("规则咬了但名册不认这个名字，判据却没点名（过=%v 红=%v）⇒ 名册这道闸形同虚设", 过, 红)
		}
		return 红[0], nil
	})

	s.条("扩展·清单带触发词就被本机规则自主选起并真跑", func(z *自检机) (string, error) {
		f, err := 起假端点(false)
		if err != nil {
			return "", err
		}
		defer f.收()
		x, a := z.新台(cfg)
		写文件(x.cfg.ToolsDir, "带触发词.json", fmt.Sprintf(
			`{"name":"自检探针","summary":"取本机假端点","risk":"net_local","timeout_ms":2000,"retry":{"attempts":1,"backoff_ms":10,"backoff_max_ms":50},"triggers":["探一下自检"],"invoke":{"kind":"http_get","url":"%s"}}`, f.地址))
		装, 拒 := LoadManifests(x.cfg.ToolsDir, x.reg, x.net)
		if len(装) != 1 || len(拒) != 0 {
			return "", fmt.Errorf("loaded=%v rejected=%v", 装, 拒)
		}
		res := a.RunTurn(context.Background(), "探一下自检", nil)
		走 := false
		for _, o := range res.Steps {
			if o.Tool == "自检探针" {
				走 = true
				if o.Class != ClassOK {
					return "", fmt.Errorf("挂载工具被选中却没跑成：%s ｜ %s", o.Class, 截(o.Text, 120))
				}
				if o.Evidence != EvRelayed {
					return "", fmt.Errorf("外部正文署成了 %s ⇒ 出处档在挂载工具这条路上塌了", o.Evidence)
				}
			}
		}
		if !走 {
			return "", fmt.Errorf("挂了触发词的清单没被本机规则选起（步：%v，结束=%s）⇒ 「放一个 JSON 就多一个工具」只对模型端点成立", 步名(res), res.Stop)
		}
		_, 红 := a.自洽判(res)
		if len(红) > 0 {
			return "", fmt.Errorf("挂载工具这一形把判据撞红：%v", 红)
		}
		return fmt.Sprintf("挂载 %d 个、真跑起 1 个（出处档 relayed）｜ %s", len(装), 第一行(res.Answer)), nil
	})

	s.条("指代优先·一句话里既有裸目录又有点「那个文件」", func(z *自检机) (string, error) {
		_, a := z.新台(cfg)
		写文件(z.底, "最大的一份.txt", strings.Repeat("三段内容一字一行 ", 3))
		res := a.RunTurn(context.Background(), "列一下 "+z.底+" 目录，按大小排，再统计最大的那个文件有多少行", nil)
		var 统 *Observation
		for i := range res.Steps {
			if res.Steps[i].Tool == "text.stats" {
				统 = &res.Steps[i]
			}
		}
		if 统 == nil {
			return "", fmt.Errorf("这一发没走 text.stats（步：%v，结束=%s）", 步名(res), res.Stop)
		}
		if !strings.Contains(统.ArgsFrom, "top+dir") {
			return "", fmt.Errorf("统计对象来处=%q args=%v ⇒ 指代没赢过话里的裸路径，拿目录当统计对象", 统.ArgsFrom, 统.Args)
		}
		if 统.Class != ClassOK {
			return "", fmt.Errorf("绑定后没跑成：%s ｜ %s", 统.Class, 截(统.Text, 120))
		}
		if res.Stop == "步数上限" {
			return "", fmt.Errorf("两个目标一句话却走到步数上限：%s", res.StopWhy)
		}
		_, 红 := a.自洽判(res)
		if len(红) > 0 {
			return "", fmt.Errorf("这一形把判据撞红：%v", 红)
		}
		return fmt.Sprintf("%d 步、结束=%s ｜ %s", len(res.Steps), res.Stop, 第一行(统.Text)), nil
	})

	s.条("同形失败只撞一次就停下来问", func(z *自检机) (string, error) {
		_, a := z.新台(cfg)
		res := a.RunTurn(context.Background(), "统计一下 "+z.底+" 有多少行", nil)
		if len(res.Steps) != 1 {
			return "", fmt.Errorf("同一套参数撞了 %d 次（步：%v）⇒ 该撞一次就停，不该吃掉步数上限", len(res.Steps), 步名(res))
		}
		看 := res.Steps[0]
		if 看.Class != ClassBadArgs || !strings.Contains(看.Text, "是个目录") {
			return "", fmt.Errorf("目录当统计对象判成 %s ｜ %s（要说清是参数给错对象，不是读失败）", 看.Class, 截(看.Text, 120))
		}
		if res.Stop != "重复失败即停" {
			return "", fmt.Errorf("结束原因=%s：%s", res.Stop, res.StopWhy)
		}
		撞 := res
		撞.Steps = append([]Observation(nil), 看, 看)
		过, 红 := a.自洽判(撞)
		认出来 := ""
		for _, h := range 红 {
			if strings.Contains(h, "同形失败重撞") {
				认出来 = h
			}
		}
		if 过 || 认出来 == "" {
			return "", fmt.Errorf("手工造两次重撞却没点名这条规则（过=%v 红=%v）⇒ 这条判据是恒绿的", 过, 红)
		}
		return fmt.Sprintf("撞一次就停：%s ｜ 判据点名的就是这条：%s", 截(看.Text, 60), 截(认出来, 110)), nil
	})

	s.条("正臂·真发三圈：自洽、五档对得上、结束原因有来历", func(z *自检机) (string, error) {
		x, a := z.新台(cfg)
		三 := []string{"列一下当前目录", "算一下 (2+3)*4", "现在几点了"}
		var 列 []Turn
		for _, 话 := range 三 {
			res := a.RunTurn(context.Background(), 话, nil)
			列 = append(列, res)
			if res.Sane == nil || !*res.Sane {
				return "", fmt.Errorf("发 %d 整列自洽是红/没量过：%s", res.Turn, res.SaneWhy)
			}
			if !res.MixOK {
				return "", fmt.Errorf("发 %d 五档加总不等：%+v", res.Turn, res.Mix)
			}
			if res.Stop == "内部错" {
				return "", fmt.Errorf("发 %d 内部错：%s", res.Turn, res.StopWhy)
			}
			if len(res.Steps) == 0 {
				return "", fmt.Errorf("发 %d 一步也没走（话=%q）⇒ 规划器没接住", res.Turn, 话)
			}
		}
		过, 话 := 跨发判据(列)
		if !过 {
			return "", fmt.Errorf("跨发不自洽：%s", 话)
		}
		if x.mem.Count() < 6 {
			return "", fmt.Errorf("三发之后记忆里才 %d 条 ⇒ 落盘没在写", x.mem.Count())
		}
		return fmt.Sprintf("三发各 %d 步、结束=%s ｜ %s", len(列[0].Steps), 列[0].Stop, 话), nil
	})

	s.条("记忆·上一发的读数绑到这一发（指代不用重说路径）", func(z *自检机) (string, error) {
		_, a := z.新台(cfg)
		// 现场里得真有一个文件：临时根里全是目录时，"最大的那个文件"压根不存在，
		// 那这条臂量的就不是"指代"，而是"没指代可绑"（那种情况产品现在会停下来问，也是对的）。
		写文件(z.底, "给自检读的文件.txt", strings.Repeat("这是一行给自检数着玩的\n", 9))
		头 := a.RunTurn(context.Background(), "列一下 "+z.底+" 目录，按大小排", nil)
		var 有文件 bool
		for _, o := range 头.Steps {
			if o.Tool == "fs.list" && o.Class == ClassOK {
				if s, _ := o.Data["top"].(string); s != "" {
					有文件 = true
				}
			}
		}
		if !有文件 {
			return "", fmt.Errorf("第一发的 fs.list 没留下任何文件读数（步：%v）⇒ 现场里没有文件，第二发的指代无从谈起", 步名(头))
		}
		res := a.RunTurn(context.Background(), "再统计最大的那个文件有多少行", nil)
		var 看 *Observation
		for i := range res.Steps {
			if res.Steps[i].Tool == "text.stats" {
				看 = &res.Steps[i]
			}
		}
		if 看 == nil {
			return "", fmt.Errorf("第二发没走 text.stats ⇒ 指代没接上（步：%v）", 步名(res))
		}
		if !strings.Contains(看.ArgsFrom, "绑的") && !strings.Contains(看.ArgsFrom, "记忆里") {
			return "", fmt.Errorf("参数来处写的是 %q ⇒ 看着不像从上一发读数来的", 看.ArgsFrom)
		}
		if 看.Class != ClassOK {
			return "", fmt.Errorf("绑上了但没跑成：%s ｜ %s", 看.Class, 截(看.Text, 120))
		}
		return fmt.Sprintf("%s ← %s", 第一行(看.Text), 看.ArgsFrom), nil
	})

	s.条("记忆·跨进程续（同一本文件重开，发号接着走）", func(z *自检机) (string, error) {
		c := cfg
		c.Port = 8792
		x, a := z.新台(c)
		res := a.RunTurn(context.Background(), "现在几点了", nil)
		文件 := x.会话文件
		前 := x.mem.NextTurn()
		二 := NewMemory(文件)
		行, 坏, err := 二.Load()
		if err != nil {
			return "", err
		}
		if 坏 != 0 {
			return "", fmt.Errorf("会话文件里有 %d 行读不回来 ⇒ 落盘格式与读法不一致", 坏)
		}
		if 二.NextTurn() != 前 {
			return "", fmt.Errorf("重开进程后发号从 %d 变成 %d ⇒ 会撞号", 前, 二.NextTurn())
		}
		if 行 < 2 {
			return "", fmt.Errorf("盘上才 %d 行 ⇒ 这一发没落够（用户话 + 工具 + 回话）", 行)
		}
		return fmt.Sprintf("第一发=%d ｜ 重开读回 %d 行 ｜ 下一发是 %d", res.Turn, 行, 二.NextTurn()), nil
	})

	s.条("窗口·挤掉了多少条要写在结论里", func(z *自检机) (string, error) {
		c := cfg
		c.ContextChars = 40
		_, a := z.新台(c)
		for _, 话 := range []string{"列一下当前目录", "算一下 6*7", "现在几点了"} {
			a.RunTurn(context.Background(), 话, nil)
		}
		res := a.RunTurn(context.Background(), "现在几点了", nil)
		找 := ""
		for _, f := range res.Findings {
			if strings.Contains(f.Text, "窗口外挤掉") {
				找 = f.Text
			}
		}
		if 找 == "" {
			return "", fmt.Errorf("结论里没有「窗口外挤掉 N 条」这一句 ⇒ 裁剪被藏起来了")
		}
		return 第一行(找), nil
	})

	s.条("模型路径·假端点驱动的步要署 model_says", func(z *自检机) (string, error) {
		f, err := 起假端点(false)
		if err != nil {
			return "", err
		}
		defer f.收()
		c := cfg
		c.ModelEndpoint = f.地址
		c.ModelKeyEnv = ""
		_, a := z.新台(c)
		res := a.RunTurn(context.Background(), "现在几点了", nil)
		var 署 string
		for _, o := range res.Steps {
			署 += o.Provenance + ","
		}
		if !strings.Contains(署, "model_says") {
			return "", fmt.Errorf("端点配了却没一步署 model_says（%s）⇒ 模型这一路其实没接上", 署)
		}
		if f.收到 == 0 {
			return "", fmt.Errorf("假端点一次也没被问 ⇒ 步是本机规则补的，署错了档")
		}
		过, 红 := a.自洽判(res)
		if !过 {
			return "", fmt.Errorf("端点驱动这一形把判据撞红了：%v", 红)
		}
		return fmt.Sprintf("端点被问 %d 次 ｜ 出处档 %s", f.收到, 截(署, 60)), nil
	})

	s.条("降级·端点回坏形状要回落本机规则并留下为什么", func(z *自检机) (string, error) {
		f, err := 起假端点(true)
		if err != nil {
			return "", err
		}
		defer f.收()
		c := cfg
		c.ModelEndpoint = f.地址
		c.ModelKeyEnv = ""
		_, a := z.新台(c)
		res := a.RunTurn(context.Background(), "现在几点了", nil)
		if len(res.Fallbacks) == 0 {
			return "", fmt.Errorf("端点回坏却没有一条降级记录 ⇒ 悄悄换成规则选的，屏幕上看不出来")
		}
		if !strings.Contains(res.Fallbacks[0], "本机规则") {
			return "", fmt.Errorf("降级话没写清退到谁：%s", res.Fallbacks[0])
		}
		for _, o := range res.Steps {
			if o.Provenance == "model_says" {
				return "", fmt.Errorf("端点明明回坏了，步 %d 还署 model_says：%v", o.Step, o.Provenance)
			}
		}
		过, 红 := a.自洽判(res)
		if !过 {
			return "", fmt.Errorf("降级这一形把判据撞红了：%v", 红)
		}
		return res.Fallbacks[0], nil
	})

	s.条("端口·8797/8799 是内核交付件的，装配必须拒", func(z *自检机) (string, error) {
		c := cfg
		c.Port = 8797
		_, err := 装配(c)
		if err == nil || !strings.Contains(err.Error(), "内核交付件") {
			return "", fmt.Errorf("占 8797 装配没拒（err=%v）", err)
		}
		地址, err := 端口可占(0)
		if err != nil {
			return "", err
		}
		return fmt.Sprintf("拒了：%v ｜ 随机端口自检走 %s", err, 地址), nil
	})

	s.条("不执行用户代码·默认那一路连调起都没有", func(z *自检机) (string, error) {
		x, a := z.新台(cfg)
		res := a.RunTurn(context.Background(), "帮我看看这段代码有什么问题：package main\nfunc main(){ println(1) }", nil)
		for _, o := range res.Steps {
			if o.Tool == "exec.run" && o.Attempts > 0 {
				return "", fmt.Errorf("没放行却调起了 exec.run（%d 次）", o.Attempts)
			}
		}
		名 := strings.Join(步名(res), "、")
		if res.Turn == 0 {
			return "", fmt.Errorf("发号是 0 ⇒ 这一发没进记忆")
		}
		if x.mem.Count() == 0 {
			return "", fmt.Errorf("没落盘")
		}
		return fmt.Sprintf("走了 %d 步（%s）｜ 结束=%s", len(res.Steps), 截(名, 80), res.Stop), nil
	})

	fmt.Printf("\n合计 %d 条 ｜ [RED] %d 条\n", s.跑过, len(s.红))
	for _, h := range s.红 {
		fmt.Printf("  RED %s\n", h)
	}
	if len(s.红) > 0 {
		return 1
	}
	return 0
}

func 写文件(dir, 名, 正文 string) {
	os.MkdirAll(dir, 0o755)
	os.WriteFile(filepath.Join(dir, 名), []byte(正文), 0o644)
}

func (z *自检机) 新台(cfg Config) (*EnvX, *Agent) {
	z.台次++
	c := cfg
	c.Port = 8800 + z.台次
	c.DataDir = filepath.Join(z.底, fmt.Sprintf("数据-%d", z.台次))
	c.ToolsDir = filepath.Join(z.底, fmt.Sprintf("tools-%d", z.台次))
	os.MkdirAll(c.ToolsDir, 0o755)
	c.NotesDir = filepath.Join(z.底, "笔记")
	c.FsRoots = []string{z.底, c.DataDir}
	c.NetAllow = []string{"127.0.0.1", "localhost"}
	c.MaxSteps = 4
	c.安静 = true
	x, err := 装配(c)
	if err != nil {
		panic(err)
	}
	return x, NewAgent(x.Env, c)
}

func (s *自检机) 条(名 string, f func(*自检机) (string, error)) {
	s.跑过++
	话, err := f(s)
	if err != nil {
		s.红 = append(s.红, 名)
		fmt.Printf("[RED] %s —— %v\n", 名, err)
		return
	}
	fmt.Printf("[OK ] %s —— %s\n", 名, 截(话, 190))
}

func 步名(t Turn) []string {
	var 列 []string
	for _, o := range t.Steps {
		列 = append(列, fmt.Sprintf("%s%s", o.Tool, map[bool]string{true: "", false: "(没成)"}[o.Class == ClassOK]))
	}
	return 列
}

var _ = json.Marshal
var _ = sort.Strings
var _ = time.Now
