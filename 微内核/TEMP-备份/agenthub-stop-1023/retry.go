package main

// 重试与降级：坏法不一样，处置就不一样。
//   bad_args / refused / unsupported —— 再来一次还是同一个错，重试只是把耗时记进账；
//   upstream / timeout —— 按 Attempts 重试，退避吃工具自己交的 RetryAfterMs（工具没说就指数退避）；
//   重试用尽还有 Fallback 工具 —— 走一次降级，并把"从谁降级来的"留在读数上；
//   没有降级可走 —— 这一格记 absent + 理由，绝不塌成"没有这件事"。

import (
	"context"
	"fmt"
	"time"
)

type Emit func(kind string, payload any)

type callOutcome struct {
	Res      Result
	Attempts int
	WaitedMs int64
	TimedOut bool
}

// 该不该再来一次：类别说了算，工具自己给的 RetryAfterMs 说了算，说明书里的次数上限也说了算。
func 该重试(p RetryPolicy, class string, 已经试过 int) bool {
	if 已经试过 >= p.Attempts || 已经试过 <= 0 {
		return false
	}
	for _, c := range p.NoRetryClasses {
		if c == class {
			return false
		}
	}
	return class == ClassUpstream || class == ClassTimeout
}

func 退避(p RetryPolicy, 第几次 int, 工具交来的 int) int {
	if 工具交来的 > 0 {
		上限 := 工具交来的
		if p.BackoffMaxMs > 0 && 上限 > p.BackoffMaxMs {
			上限 = p.BackoffMaxMs
		}
		return 上限
	}
	等 := p.BackoffMs
	for i := 1; i < 第几次; i++ {
		等 *= 2
		if p.BackoffMaxMs > 0 && 等 > p.BackoffMaxMs {
			等 = p.BackoffMaxMs
			break
		}
	}
	if 等 < 0 {
		等 = 0
	}
	if p.BackoffMaxMs > 0 && 等 > p.BackoffMaxMs {
		等 = p.BackoffMaxMs
	}
	return 等
}

// 调一次工具：包超时、包重试；emit 把每一次尝试都推给前端（queued/attempt/retrying/failed/ok）。
func 调一次(ctx context.Context, t Tool, args map[string]any, emit Emit, 步 int, 标签 string) callOutcome {
	if emit == nil {
		// 自检、测试与循环外的调用都可能不带事件汇；这里不吃 nil 就是一个空指针 panic，
		// 而 panic 会让"重试策略对不对"这件事根本没被量到。
		emit = func(string, any) {}
	}
	spec := t.Spec()
	emit("tool_status", map[string]any{"step": 步, "tool": spec.Name, "status": "queued",
		"risk": string(spec.Risk), "timeout_ms": spec.TimeoutMs, "attempts_allowed": spec.Retry.Attempts,
		"args": args, "args_from": 标签, "fallback": spec.Fallback})
	var out callOutcome
	var 最后 Result
	for n := 1; n <= spec.Retry.Attempts; n++ {
		cctx, cancel := context.WithTimeout(ctx, time.Duration(spec.TimeoutMs)*time.Millisecond)
		emit("tool_status", map[string]any{"step": 步, "tool": spec.Name, "status": "attempt", "第几次": n})
		start := time.Now()
		res, err := t.Run(cctx, args)
		耗时 := time.Since(start).Milliseconds()
		if err != nil {
			res = Result{Class: ClassInternal, Text: fmt.Sprintf("工具内部抛了：%v", err)}
		}
		if cctx.Err() == context.DeadlineExceeded && res.Class == ClassInternal {
			res.Class = ClassTimeout
			res.Text = fmt.Sprintf("到 %d ms 还没回：%s", spec.TimeoutMs, res.Text)
		}
		out.Attempts = n
		最后 = res
		if res.Class == ClassOK {
			cancel()
			emit("tool_status", map[string]any{"step": 步, "tool": spec.Name, "status": "ok",
				"第几次": n, "ms": 耗时})
			out.Res = res
			out.Res.Text = fmt.Sprintf("%s ｜ 试了 %d 次 ｜ %dms", res.Text, n, 耗时)
			return out
		}
		cancel()
		还要 := 该重试(spec.Retry, res.Class, n)
		st := "failed"
		if 还要 {
			st = "retrying"
		}
		emit("tool_status", map[string]any{"step": 步, "tool": spec.Name, "status": st,
			"第几次": n, "class": res.Class, "ms": 耗时, "text": 截(res.Text, 240)})
		if !还要 {
			break
		}
		等 := 退避(spec.Retry, n, res.RetryAfterMs)
		if 等 > 0 {
			sctx, scancel := context.WithTimeout(ctx, time.Duration(等)*time.Millisecond)
			emit("tool_status", map[string]any{"step": 步, "tool": spec.Name, "status": "backoff",
				"等_ms": 等, "为什么": "工具自己交了 Retry-After，按它给的等（超过 max 会被压回上限）"})
			<-sctx.Done()
			scancel()
			out.WaitedMs += int64(等)
		}
	}
	out.Res = 最后
	if out.Res.Text == "" {
		out.Res = Result{Class: ClassInternal, Text: "工具一次也没回过话（这条不是 0，是没量到）"}
	}
	return out
}

// 降级参数：从"要读的文件读不到"退到"先把目录列出来"，参数得重造 —— 直接把原参数递给备选工具
// 通常是不合法的（fs.list 要 path，而原来那是个文件路径），所以这里按对子显式映射。
func 降级参数(备选 ToolSpec, 原 map[string]any) (map[string]any, bool) {
	switch 备选.Name {
	case "fs.list":
		p, _ := 原["path"].(string)
		if p == "" {
			p = "."
		}
		return map[string]any{"path": 上级(p)}, true
	case "fs.read":
		if p, ok := 原["path"].(string); ok {
			return map[string]any{"path": p}, true
		}
		return nil, false
	case "time.now":
		return map[string]any{}, true
	}
	var out = map[string]any{}
	for _, ps := range 备选.Params {
		if v, ok := 原[ps.Name]; ok {
			out[ps.Name] = v
		}
	}
	if len(out) == 0 && len(备选.Params) > 0 {
		return nil, false // 一个参数都递不过去 ⇒ 别硬调
	}
	return out, true
}

func 上级(p string) string {
	for i := len(p) - 1; i >= 0; i-- {
		if p[i] == '/' || p[i] == '\\' {
			if i == 0 {
				return p[:1]
			}
			return p[:i]
		}
	}
	if p == "" {
		return "."
	}
	return "."
}
