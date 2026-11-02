package main

// 工具注册与管理：一个 Tool = 一份可机读的说明书（ToolSpec）+ 一个真执行的 Run。
// 加新工具不需要改调度循环：要么在 builtin 表里加一项，要么往 tools/*.json 放一个清单
// （清单里声明的 http/fs 工具由 ManifestTool 统一解释执行）。
// 这里刻意把"重名"与"影子注册"判成错误而不是静默覆盖 —— 覆盖会让"这台机器上到底有几个工具"
// 这个数没法自印，而调度循环下一步就是拿这个名字去选件。

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
)

type RiskTier string

const (
	RiskLocalRead RiskTier = "local_read"
	RiskCompute   RiskTier = "compute"
	RiskNetLocal  RiskTier = "net_local"
	RiskNetRemote RiskTier = "net_remote"
	RiskFsWrite   RiskTier = "fs_write"
	RiskExec      RiskTier = "exec"
)

type ParamSpec struct {
	Name     string `json:"name"`
	Type     string `json:"type"` // string int number bool strings
	Desc     string `json:"desc"`
	Required bool   `json:"required"`
	Example  string `json:"example,omitempty"`
}

type RetryPolicy struct {
	Attempts       int      `json:"attempts"` // 含第一次，>=1
	BackoffMs      int      `json:"backoff_ms"`
	BackoffMaxMs   int      `json:"backoff_max_ms"`
	NoRetryClasses []string `json:"no_retry_classes,omitempty"`
}

type ToolSpec struct {
	Name         string      `json:"name"`
	Summary      string      `json:"summary"`
	Params       []ParamSpec `json:"params"`
	Risk         RiskTier    `json:"risk"`
	TimeoutMs    int         `json:"timeout_ms"`
	Retry        RetryPolicy `json:"retry"`
	Fallback     string      `json:"fallback,omitempty"`
	RequiresFlag string      `json:"requires_flag,omitempty"`
	Triggers     []string    `json:"triggers,omitempty"`
	Source       string      `json:"source"` // builtin | manifest:<文件名>
}

type Result struct {
	Text         string `json:"text"`
	Data         any    `json:"data,omitempty"`
	Class        string `json:"class"`
	RetryAfterMs int    `json:"retry_after_ms,omitempty"`
}

type Tool interface {
	Spec() ToolSpec
	Run(ctx context.Context, args map[string]any) (Result, error)
}

// 错误类别：调度循环、重试策略与降级都按这个分类决定"要不要再来一次"。
// 分类不是装饰 —— 把 bad_args 拿去重试，等于用同一个错参数再撞一次墙并把耗时记进账。
const (
	ClassOK          = "ok"
	ClassBadArgs     = "bad_args"
	ClassRefused     = "refused"  // 门口挡：风险档没开、主机不在允许清单、路径越界
	ClassUpstream    = "upstream" // 工具背后的东西回了坏（非 2xx、5xx、连不上）
	ClassTimeout     = "timeout"
	ClassInternal    = "internal"
	ClassUnsupported = "unsupported"
)

type Registry struct {
	tools  map[string]Tool
	order  []string
	shadow []string // 想影子注册却被拒的（清单撞了内置名），要让 /api/tools 看得见
}

func NewRegistry() *Registry {
	return &Registry{tools: map[string]Tool{}}
}

func (r *Registry) Add(t Tool) error {
	spec := t.Spec()
	if strings.TrimSpace(spec.Name) == "" {
		return fmt.Errorf("工具没名字")
	}
	if spec.TimeoutMs <= 0 {
		return fmt.Errorf("工具 %s 的超时没给（0 秒＝可以挂到永远，不许注册）", spec.Name)
	}
	if spec.Retry.Attempts < 1 {
		return fmt.Errorf("工具 %s 的重试次数=%d，至少要 1 次", spec.Name, spec.Retry.Attempts)
	}
	if old, dup := r.tools[spec.Name]; dup {
		r.shadow = append(r.shadow, fmt.Sprintf("%s（%s 想顶掉 %s）", spec.Name, spec.Source, old.Spec().Source))
		return fmt.Errorf("重名：工具 %s 已由 %s 注册", spec.Name, old.Spec().Source)
	}
	for _, p := range spec.Params {
		if strings.TrimSpace(p.Name) == "" {
			return fmt.Errorf("工具 %s 有一个参数没名字", spec.Name)
		}
	}
	r.tools[spec.Name] = t
	r.order = append(r.order, spec.Name)
	return nil
}

func (r *Registry) Get(name string) (Tool, bool) {
	t, ok := r.tools[name]
	return t, ok
}

func (r *Registry) Names() []string {
	out := append([]string(nil), r.order...)
	sort.Strings(out)
	return out
}

func (r *Registry) Count() int { return len(r.tools) }

func (r *Registry) Specs() []ToolSpec {
	var out []ToolSpec
	for _, n := range r.Names() {
		out = append(out, r.tools[n].Spec())
	}
	return out
}

// 校验参数：多余的键、缺的必填、类型不对，一律 bad_args 并说清是哪一条。
// 未知键不许忽略 —— 把 path 写成 Path 时，忽略未知键的工具会拿着空路径去读根目录。
func 校验参数(spec ToolSpec, args map[string]any) error {
	known := map[string]bool{}
	for _, p := range spec.Params {
		known[p.Name] = true
	}
	for k := range args {
		if !known[k] {
			return fmt.Errorf("参数 %q 不在 %s 的说明书里（这台机器上有这些参数可用：%s）",
				k, spec.Name, strings.Join(paramNames(spec.Params), "、"))
		}
	}
	for _, p := range spec.Params {
		v, has := args[p.Name]
		if !has || v == nil {
			if p.Required {
				return fmt.Errorf("缺必填参数 %q（%s）", p.Name, p.Desc)
			}
			continue
		}
		if err := 类型对(p, v); err != nil {
			return err
		}
	}
	return nil
}

func 类型对(p ParamSpec, v any) error {
	switch p.Type {
	case "string":
		if _, ok := v.(string); !ok {
			return fmt.Errorf("参数 %q 要 string，给的是 %T", p.Name, v)
		}
	case "int":
		if _, ok := asInt(v); !ok {
			return fmt.Errorf("参数 %q 要整数，给的是 %T（%v）", p.Name, v, v)
		}
	case "number":
		if _, ok := asNumber(v); !ok {
			return fmt.Errorf("参数 %q 要数字，给的是 %T", p.Name, v)
		}
	case "bool":
		if _, ok := v.(bool); !ok {
			return fmt.Errorf("参数 %q 要 true/false，给的是 %T", p.Name, v)
		}
	case "strings":
		switch x := v.(type) {
		case []string: // 本机规划器直接给切片；JSON 那条路只会给 []any，两种都得认，否则内部调用被自己的校验拒了
			return nil
		case []any:
			for i, item := range x {
				if _, ok := item.(string); !ok {
					return fmt.Errorf("参数 %q 的第 %d 项不是字符串（%T）", p.Name, i, item)
				}
			}
			return nil
		}
		return fmt.Errorf("参数 %q 要字符串数组，给的是 %T", p.Name, v)
	default:
		return fmt.Errorf("参数 %q 声明了没人认识类型 %q", p.Name, p.Type)
	}
	return nil
}

func paramNames(ps []ParamSpec) []string {
	var out []string
	for _, p := range ps {
		out = append(out, p.Name)
	}
	return out
}

func asInt(v any) (int, bool) {
	n, ok := asNumber(v)
	if !ok {
		return 0, false
	}
	if n != float64(int(n)) {
		return 0, false
	}
	return int(n), true
}

func asNumber(v any) (float64, bool) {
	switch x := v.(type) {
	case float64:
		return x, true
	case int:
		return float64(x), true
	case string:
		var f float64
		if _, err := fmt.Sscanf(x, "%g", &f); err == nil {
			return f, true
		}
	}
	return 0, false
}

func getString(args map[string]any, key, def string) string {
	if v, ok := args[key].(string); ok && v != "" {
		return v
	}
	return def
}

func getInt(args map[string]any, key string, def int) int {
	if n, ok := asInt(args[key]); ok {
		return n
	}
	return def
}

func getBool(args map[string]any, key string, def bool) bool {
	if v, ok := args[key].(bool); ok {
		return v
	}
	return def
}

// —— 清单式扩展：tools/*.json 放一个文件就多一个工具，不用动循环 ——

type Manifest struct {
	Name         string      `json:"name"`
	Summary      string      `json:"summary"`
	Params       []ParamSpec `json:"params"`
	Risk         RiskTier    `json:"risk"`
	TimeoutMs    int         `json:"timeout_ms"`
	Retry        RetryPolicy `json:"retry"`
	Fallback     string      `json:"fallback,omitempty"`
	RequiresFlag string      `json:"requires_flag,omitempty"`
	Triggers     []string    `json:"triggers,omitempty"`
	Invoke       struct {
		Kind     string `json:"kind"` // http_get | fs_read
		URL      string `json:"url,omitempty"`
		Root     string `json:"root,omitempty"`
		MaxBytes int    `json:"max_bytes,omitempty"`
	} `json:"invoke"`
}

type manifestTool struct {
	spec  ToolSpec
	m     Manifest
	net   *NetGuard
	allow []string
}

func (t *manifestTool) Spec() ToolSpec { return t.spec }

func (t *manifestTool) Run(ctx context.Context, args map[string]any) (Result, error) {
	switch t.m.Invoke.Kind {
	case "http_get":
		url := getString(args, "url", t.m.Invoke.URL)
		if url == "" {
			return Result{Class: ClassBadArgs, Text: "清单没写 url，参数也没给 url"}, nil
		}
		return t.net.Get(ctx, url)
	case "fs_read":
		rel := getString(args, "path", "")
		if rel == "" {
			return Result{Class: ClassBadArgs, Text: "缺参数 path"}, nil
		}
		return readWithin(t.m.Invoke.Root, rel, t.m.Invoke.MaxBytes)
	default:
		return Result{Class: ClassUnsupported,
			Text: fmt.Sprintf("清单里的 invoke.kind=%q 这台机器上没人解释（认得 http_get / fs_read）", t.m.Invoke.Kind)}, nil
	}
}

// LoadManifests 返回（装了几个、拒了几个与被拒原因）。
// 一个坏清单不许拖垮启动：它被记进 rejected 并让 /api/tools 显示出来，别静默跳过。
func LoadManifests(dir string, reg *Registry, net *NetGuard) (loaded, rejected []string) {
	ents, err := os.ReadDir(dir)
	if os.IsNotExist(err) {
		return nil, nil
	}
	if err != nil {
		return nil, []string{fmt.Sprintf("%s：%v", dir, err)}
	}
	for _, e := range ents {
		if e.IsDir() || !strings.HasSuffix(e.Name(), ".json") {
			continue
		}
		path := filepath.Join(dir, e.Name())
		b, err := os.ReadFile(path)
		if err != nil {
			rejected = append(rejected, fmt.Sprintf("%s：读不进来 %v", e.Name(), err))
			continue
		}
		var m Manifest
		if err := json.Unmarshal(b, &m); err != nil {
			rejected = append(rejected, fmt.Sprintf("%s：不是合法清单 %v", e.Name(), err))
			continue
		}
		if m.Invoke.MaxBytes <= 0 {
			m.Invoke.MaxBytes = 256 * 1024
		}
		spec := ToolSpec{
			Name: m.Name, Summary: m.Summary, Params: m.Params, Risk: m.Risk,
			TimeoutMs: m.TimeoutMs, Retry: m.Retry, Fallback: m.Fallback,
			RequiresFlag: m.RequiresFlag, Triggers: m.Triggers, Source: "manifest:" + e.Name(),
		}
		if spec.TimeoutMs <= 0 {
			spec.TimeoutMs = 4000
		}
		if spec.Retry.Attempts <= 0 {
			spec.Retry.Attempts = 2
		}
		if spec.Risk == "" {
			spec.Risk = RiskNetLocal
		}
		if m.Invoke.Kind == "http_get" && len(spec.Params) == 0 {
			spec.Params = []ParamSpec{{Name: "url", Type: "string", Desc: "要取的本机地址（只允许 127.0.0.1/localhost）", Required: false, Example: m.Invoke.URL}}
		}
		if m.Invoke.Kind == "fs_read" && len(spec.Params) == 0 {
			spec.Params = []ParamSpec{{Name: "path", Type: "string", Desc: "相对清单 root 的路径", Required: true}}
		}
		t := &manifestTool{spec: spec, m: m, net: net}
		if err := reg.Add(t); err != nil {
			rejected = append(rejected, fmt.Sprintf("%s：%v", e.Name(), err))
			continue
		}
		loaded = append(loaded, spec.Name)
	}
	return loaded, rejected
}
