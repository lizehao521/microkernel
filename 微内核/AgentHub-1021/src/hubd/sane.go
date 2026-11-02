package main

// 整列自洽判据：每一发收口前把整列过一遍。每条规则都有名字，名字要写在名册里 ——
// 写了分支却没进名册的规则等于没跑过，名册里没有的规则撞上时要自己判红。
// 这套判据只管"同一发内部自相矛盾"，管不了"每发内部自洽但连起来骗人"（那要跨发判据）。

import (
	"fmt"
	"regexp"
	"strings"
)

var 自洽名册 = []string{
	"没成却署了measured", "成了却没读数", "absent没理由", "五档加总不等", "步数句自己数错了",
	"不认识的工具没标类别", "端点没配却有model_says", "成功了却一次也没试", "同形失败重撞",
	"降级却没写从谁降级来", "没放行却跑成了读数", "空收口", "署名不在名册里",
}

var re步数 = regexp.MustCompile(`走 (\d+) 步`)

func (a *Agent) 自洽判(res Turn) (bool, []string) {
	var 红 []string
	在册 := map[string]bool{}
	for _, n := range 自洽名册 {
		在册[n] = true
	}
	咬 := func(名, 话 string) {
		if !在册[名] {
			红 = append(红, fmt.Sprintf("判据名 %q 不在名册里（这条规则写了但没人认得它）", 名))
			return
		}
		红 = append(红, 名+"："+话)
	}
	成 := 0
	for _, o := range res.Steps {
		switch {
		case o.Class == ClassOK && o.Evidence == EvAbsent:
			咬("成了却没读数", fmt.Sprintf("步 %d %s 类别=%s 却把读数档写成 absent ⇒ 跑成功了却说没量到", o.Step, o.Tool, o.Class))
		case o.Class != ClassOK && o.Evidence != EvAbsent:
			咬("没成却署了measured", fmt.Sprintf("步 %d %s 类别=%s（没跑成）却把读数档署成 %s ⇒ 这是把没量到写成有东西",
				o.Step, o.Tool, o.Class, o.Evidence))
		case o.Class == ClassOK && o.Attempts < 1:
			咬("成功了却一次也没试", fmt.Sprintf("步 %d %s 报成功但 attempts=%d ⇒ 这个读数不是调出来的", o.Step, o.Tool, o.Attempts))
		}
		if o.Evidence == EvAbsent && strings.TrimSpace(o.AbsentWhy) == "" {
			咬("absent没理由", fmt.Sprintf("步 %d %s 是 absent 却没交代为什么", o.Step, o.Tool))
		}
		if o.Class == ClassUnsupported {
			继续 := true
			for _, 名 := range a.reg.Names() {
				if 名 == o.Tool {
					继续 = false
					break
				}
			}
			if !继续 {
				咬("不认识的工具没标类别", fmt.Sprintf("步 %d %s 其实注册过，却被标成 unsupported", o.Step, o.Tool))
			}
		}
		if o.DegradedFrom != "" {
			// 只扫"结论里有没有『降级』两个字"是恒过的：收口那句汇总永远写着"降级 N 次"，
			// 哪怕 N=0。要判的是**这一步**的结论里带没带它是从谁降级来的。
			写了这一步 := false
			for _, f := range res.Findings {
				if f.Step == o.Step && strings.Contains(f.Text, "从 "+o.DegradedFrom+" 降级来") {
					写了这一步 = true
				}
			}
			if !写了这一步 {
				咬("降级却没写从谁降级来", fmt.Sprintf("步 %d 标了 degraded_from=%s，可这一步的结论里看不见降级这件事（读起来就像原工具自己成功了）",
					o.Step, o.DegradedFrom))
			}
		}
		工, ok := a.reg.Get(o.Tool)
		if ok {
			sp := 工.Spec()
			if sp.RequiresFlag != "" && !a.cfg.旗标开了(sp.RequiresFlag) && o.Class == ClassOK {
				咬("没放行却跑成了读数", fmt.Sprintf("步 %d %s 要 -%s 才允许，却报了成功", o.Step, o.Tool, sp.RequiresFlag))
			}
		}
		if o.Provenance == "model_says" && a.cfg.ModelEndpoint == "" {
			咬("端点没配却有model_says", fmt.Sprintf("步 %d 署了模型说的，可这台机器没配 -model-endpoint", o.Step))
		}
		if o.Provenance != "model_says" && o.Provenance != "estimated" {
			咬("署名不在名册里", fmt.Sprintf("步 %d 的出处档 %q 这台机器不认（只认 estimated / model_says）", o.Step, o.Provenance))
		}
		if o.Class == ClassOK {
			成++
		}
	}
	总 := 0
	for k, v := range res.Mix {
		if k == "total" {
			continue
		}
		总 += v
	}
	if res.Mix["total"] != len(res.Findings) || 总 != len(res.Findings) {
		咬("五档加总不等", fmt.Sprintf("结论 %d 条，五档加总 %d（total 格写的是 %d）", len(res.Findings), 总, res.Mix["total"]))
	}
	for _, f := range res.Findings {
		if m := re步数.FindStringSubmatch(f.Text); m != nil {
			if n, _ := atoiSafe(m[1]); n != len(res.Steps) {
				咬("步数句自己数错了", fmt.Sprintf("结论里写「走 %d 步」，可这一发列出来 %d 步", n, len(res.Steps)))
			}
		}
	}
	if res.Stop == "跑完" && 成 == 0 && len(res.Steps) > 0 {
		咬("空收口", fmt.Sprintf("说是跑完，可 %d 步里没有一个成功读数 ⇒ 该说成要补参数或失败", len(res.Steps)))
	}
	// 同形失败重撞：同一发里同样的工具+参数没成过两次 ⇒ 循环没守住"停下来问"。
	撞计 := map[string]int{}
	for _, o := range res.Steps {
		if o.Class != ClassOK && o.Tool != "" {
			撞计[调用键(o.Tool, o.Args)]++
		}
	}
	for 键, n := range 撞计 {
		if n > 1 {
			咬("同形失败重撞", fmt.Sprintf("%s 用同一套参数失败了 %d 次 ⇒ 该停下来问，不该吃掉步数上限", 键, n))
		}
	}

	return len(红) == 0, 红
}

func (a *Agent) 自洽话(res Turn) string {
	过, 红 := a.自洽判(res)
	if 过 {
		return fmt.Sprintf("整列 %d 步 / %d 条结论自洽（判据 %d 条全过）", len(res.Steps), len(res.Findings), len(自洽名册))
	}
	return fmt.Sprintf("红了 %d 条：%s", len(红), strings.Join(红, " ｜ "))
}

func atoiSafe(s string) (int, bool) {
	n := 0
	if s == "" {
		return 0, false
	}
	for _, r := range s {
		if r < '0' || r > '9' {
			return 0, false
		}
		n = n*10 + int(r-'0')
	}
	return n, true
}

// 跨发判据：一列发连起来看是否自洽（记忆在长、发号在续、同一句话不许两头发不同的数）。
func 跨发判据(列 []Turn) (bool, string) {
	var 红 []string
	上发 := 0
	for _, t := range 列 {
		if t.Turn != 上发+1 {
			红 = append(红, fmt.Sprintf("第 %d 发的发号不是接着走的（上一发是 %d）", t.Turn, 上发))
		}
		上发 = t.Turn
		if t.Sane == nil {
			红 = append(红, fmt.Sprintf("第 %d 发没交自洽读数（旧记录=没量过，不许替它担保）", t.Turn))
		} else if !*t.Sane {
			红 = append(红, fmt.Sprintf("第 %d 发当时整列自洽就是红的：%s", t.Turn, t.SaneWhy))
		}
		if t.MemoryLen > 0 && t.MemoryLen < 上发 {
			红 = append(红, fmt.Sprintf("第 %d 发摘要说只有 %d 条记忆，可前面已经走到第 %d 发", t.Turn, t.MemoryLen, 上发))
		}
	}
	if len(红) > 0 {
		return false, strings.Join(红, " ｜ ")
	}
	return true, fmt.Sprintf("共 %d 发：发号逐发接续、每发都交了自洽读数、记忆条数不倒退", len(列))
}
