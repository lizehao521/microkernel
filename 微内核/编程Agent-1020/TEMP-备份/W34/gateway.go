package main

// 第 ⑧ 步「模型网关」。两条路，一条今天要能真跑，一条如实挂着：
//
//   - **本机假端点**（`-fake-endpoint`）：进程内起一个只听 127.0.0.1:随机端口 的 SSE 端点，
//     把管路那七格（帧数 / 首帧 / 最大间隔 / 进出字节 / usage 两格）变成**有出处的读数**。
//     它说的是脚本写好的话，所以文本那一格署 model_says 并且带着"假端点·演示件"字样 ——
//     真实模型调用在这一条路上发生 **0 次**，界面与账本都不许把它读成"模型答对了"。
//   - **真端点**：只有当环境变量 `PGAGENT_BASE_URL`（+ `PGAGENT_MODEL`、`PGAGENT_KEY`）在本机存在时才走。
//     口令只进请求头，不进文件、不进账本、不进读数件。没设 ⇒ 这一步是 NOT_RUN，**不写 0**。
//
// 一条硬守卫：不管哪条路，**目标端口是 8797/8799 一律拒** —— 那两本是内核自己的账本实例，
// 把用户贴进来的代码发过去等于未经批准打真流量（见长期目标里的硬约束）。

import (
	"bufio"
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"os"
	"strings"
	"sync"
	"time"
)

const fakeModelName = "假端点·演示件（脚本回帧，不是真模型；真实模型调用 0 次）"

var forbiddenPorts = map[string]string{
	"8797": "内核 MCP 实例（未批准不许打流量）",
	"8799": "内核 MCP 实例（未批准不许打流量）",
}

// pipe 是这一发的通道读数。nil = 这一发根本没开通道 ⇒ 那七格只能记 absent。
var pipe *pipeReadout

type pipeReadout struct {
	Fake        bool   `json:"fake"`
	Loopback    bool   `json:"loopback"` // 地址是本机回环 ⇒ 贴进来的代码没出这台机
	BaseURL     string `json:"base_url"`
	Model       string `json:"model"`
	Chunks      int64  `json:"chunks"`
	FirstByteMs int64  `json:"first_byte_ms"`
	MaxGapMs    int64  `json:"max_gap_ms"`
	BytesIn     int64  `json:"bytes_in"`  // 我从 socket 上真读到的字节 ⇒ measured
	BytesOut    int64  `json:"bytes_out"` // 我交给 http.Client 的负载字节，不含 TLS/HTTP 头帧 ⇒ estimated
	UsageIn     int64  `json:"usage_in"`
	UsageOut    int64  `json:"usage_out"`
	UsageSaid   bool   `json:"usage_said"` // 端点自报过 usage（哪怕报 0）—— 那是转述档，不是测量
	Text        string `json:"text"`
	Finish      string `json:"finish"`
	Kind        string `json:"fail_kind"`   // 空 = 这一发正常回来；transport / http / protocol 是三种失败形状
	Detail      string `json:"fail_detail"` // 擦过口令的原话（口令绝不进读数、不进账）
	Status      int    `json:"http_status"` // 0 = 根本没收到响应 ⇒ 账上那一格记缺席，不是 measured(0)
	Received    bool   `json:"received"`    // 真收到过响应头没（区分"连不上"与"连上了但回错"）
	// BodyRead = 正文**真的一行行读过**。回了非 200 那一形我们刻意不读错误体（里面常带着请求回显，
	// 那是最容易把口令抄进读数/账本的一条路），于是帧数/首帧/帧间/入线字节这四格是"没量"，不是"量到 0"。
	BodyRead bool `json:"body_read"`
	// 流式回帧的"收完没"：OpenAI 兼容流以 data: [DONE] 收尾，或至少给一个 finish_reason。
	// 两个都没等到就是**半路断了** —— 那一形以前会被记成"正常回完"（fail_kind 空、KPI 照算）。
	Done       bool   `json:"done"`
	FinishSeen bool   `json:"finish_seen"`
	WireObject string `json:"wire_object"` // 对端自己说它按什么格式回的（顶层 object）；没带就是没说
	Malformed  int64  `json:"malformed"`   // 我扫过但解不出 JSON 的行数（数出来的 0 才是读数）
	ElapsedMs  int64  `json:"elapsed_ms"`
}

var (
	fakeOnce   sync.Once
	fakeURL    string
	fakeErr    error
	fakeServer *http.Server
)

// guardURL 拒掉两类目标：指向内核账本实例的端口，和不是 http(s) 的怪串。
func guardURL(raw string) error {
	u, err := url.Parse(raw)
	if err != nil {
		return fmt.Errorf("网关地址解不开：%w", err)
	}
	if u.Scheme != "http" && u.Scheme != "https" {
		return fmt.Errorf("网关只认 http/https，现在是 %q", u.Scheme)
	}
	port := u.Port()
	if port == "" {
		if u.Scheme == "https" {
			port = "443"
		} else {
			port = "80"
		}
	}
	if why, bad := forbiddenPorts[port]; bad {
		return fmt.Errorf("拒发往 %s：%s", raw, why)
	}
	return nil
}

// startFake 在 127.0.0.1 的随机端口上起一个假端点。回帧形状刻意复刻本机量到的那条已知坑：
// **流式时 usage 三个数全 0**（而非流式才给真数）—— 这样"0 不许升 measured"这一族才有实物可打。
func startFake() (string, error) {
	fakeOnce.Do(func() {
		var ln net.Listener
		ln, fakeErr = net.Listen("tcp", "127.0.0.1:0")
		if fakeErr != nil {
			return
		}
		mux := http.NewServeMux()
		mux.HandleFunc("/v1/chat/completions", func(w http.ResponseWriter, r *http.Request) {
			_, _ = io.Copy(io.Discard, r.Body) // 读完，别让 client 那边卡住
			w.Header().Set("Content-Type", "text/event-stream")
			fl, ok := w.(http.Flusher)
			if !ok {
				http.Error(w, "不支持流式", http.StatusInternalServerError)
				return
			}
			lines := []string{
				`data: {"object":"chat.completion.chunk","choices":[{"delta":{"content":"这台机不执行你的代码。"}}]}`,
				`data: {"object":"chat.completion.chunk","choices":[{"delta":{"content":"上面的行号来自语法树与栈文本的对位，"}}]}`,
				`data: {"object":"chat.completion.chunk","choices":[{"delta":{"content":"是定位线索，不是诊断。"}}]}`,
				`data: {"object":"chat.completion.chunk","choices":[{"delta":{},"finish_reason":"stop"}],"usage":{"prompt_tokens":0,"completion_tokens":0,"total_tokens":0}}`,
				`data: [DONE]`,
			}
			for _, l := range lines {
				fmt.Fprintln(w, l)
				fl.Flush()
				time.Sleep(6 * time.Millisecond)
			}
		})
		fakeServer = &http.Server{Handler: mux}
		fakeURL = "http://" + ln.Addr().String() + "/v1"
		go func() { _ = fakeServer.Serve(ln) }()
	})
	return fakeURL, fakeErr
}

// detectGateway 决定这一发走哪条路。返回空串 = 不走（NOT_RUN），并给一句能写进读数的理由。
func detectGateway(useFakeFlag bool) (gwConfig, string) {
	base := strings.TrimSpace(os.Getenv("PGAGENT_BASE_URL"))
	if base != "" {
		if err := guardURL(base); err != nil {
			return gwConfig{}, err.Error()
		}
		return gwConfig{BaseURL: strings.TrimSuffix(base, "/"), Model: envOr("PGAGENT_MODEL", "未命名模型"),
			Key: os.Getenv("PGAGENT_KEY"), Real: true}, ""
	}
	if useFakeFlag {
		base, err := startFake()
		if err != nil {
			return gwConfig{}, "本机假端点起不来：" + err.Error()
		}
		return gwConfig{BaseURL: base, Model: fakeModelName}, ""
	}
	return gwConfig{}, "PGAGENT_BASE_URL 未设 ⇒ 真端点 NOT_RUN；假端点没开（要 -fake-endpoint）"
}

type gwConfig struct {
	BaseURL string
	Model   string
	Key     string
	Real    bool
}

func envOr(k, def string) string {
	if v := strings.TrimSpace(os.Getenv(k)); v != "" {
		return v
	}
	return def
}

// callGateway 打一发并**自己数**：写了多少字节出去、读回来多少、几帧、首帧多久、最大间隔多久。
// usage 只从端点自报里取，取到就是 relayed；一个字节都不许拿它冒充 measured。
func callGateway(cfg gwConfig, prompt string, timeout time.Duration) (*pipeReadout, error) {
	if err := guardURL(cfg.BaseURL); err != nil {
		return nil, err
	}
	payload, err := json.Marshal(map[string]any{
		"model":    cfg.Model,
		"messages": []map[string]string{{"role": "user", "content": prompt}},
		"stream":   true,
	})
	if err != nil {
		return nil, err
	}
	req, err := http.NewRequest("POST", cfg.BaseURL+"/chat/completions", bytes.NewReader(payload))
	if err != nil {
		return nil, err
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Accept", "text/event-stream")
	if cfg.Key != "" {
		req.Header.Set("Authorization", "Bearer "+cfg.Key) // 只进头，不进日志、不进账
	}
	t0 := time.Now()
	p := &pipeReadout{Fake: !cfg.Real, Loopback: isLoopback(cfg.BaseURL), BaseURL: cfg.BaseURL,
		Model: cfg.Model, BytesOut: int64(len(payload))}
	cl := &http.Client{Timeout: timeout}
	resp, err := cl.Do(req)
	if err != nil {
		// 连不上 / 超时 / 断了：这一发**打了**，只是没成功。记 transport 与擦过口令的原因，
		// 不许塌成 NOT_RUN（那是"没打"），也不许塌成"端点说没有"。
		p.Kind, p.Detail = "transport", scrub(err.Error(), cfg.Key)
		return p, fmt.Errorf("打不出去：%s", p.Detail)
	}
	defer resp.Body.Close()
	p.Received = true
	p.Status = resp.StatusCode
	if resp.StatusCode != http.StatusOK {
		// 只数状态码，不读它的正文 —— 错误体里常带着请求回显，那是最容易把口令抄进读数的一条路。
		p.Kind, p.Detail = "http", fmt.Sprintf("端点回了 %d（正文没读）", resp.StatusCode)
		return p, fmt.Errorf("%s", p.Detail)
	}
	sc := bufio.NewScanner(resp.Body)
	sc.Buffer(make([]byte, 0, 64*1024), 1024*1024)
	p.BodyRead = true // 从这里往下才是"真的一行行读过"
	var last time.Time
	var got []byte
	for sc.Scan() {
		line := sc.Bytes()
		p.BytesIn += int64(len(line) + 1) // +1：行尾那个换行也是从 socket 上来的
		now := time.Now()
		if p.FirstByteMs == 0 {
			p.FirstByteMs = now.Sub(t0).Milliseconds()
		}
		if !last.IsZero() {
			if g := now.Sub(last).Milliseconds(); g > p.MaxGapMs {
				p.MaxGapMs = g
			}
		}
		last = now
		s := strings.TrimSpace(string(line))
		if !strings.HasPrefix(s, "data:") {
			continue
		}
		body := strings.TrimSpace(strings.TrimPrefix(s, "data:"))
		if body == "[DONE]" {
			p.Done = true
			continue
		}
		p.Chunks++
		var frame struct {
			Object  string `json:"object"` // 对端自报的格式；没带就是"它没说"，不许由我们替它填
			Choices []struct {
				Delta struct {
					Content          string `json:"content"`
					ReasoningContent string `json:"reasoning_content"`
				} `json:"delta"`
				FinishReason string `json:"finish_reason"`
			} `json:"choices"`
			Usage *struct {
				PromptTokens     int64 `json:"prompt_tokens"`
				CompletionTokens int64 `json:"completion_tokens"`
			} `json:"usage"`
		}
		if err := json.Unmarshal([]byte(body), &frame); err != nil {
			p.Malformed++ // 数到的畸形帧：这一格是"我扫过、它解不开"，不是"没有畸形帧"
			continue
		}
		if frame.Object != "" {
			p.WireObject = frame.Object
		}
		for _, ch := range frame.Choices {
			got = append(got, ch.Delta.Content...)
			if ch.FinishReason != "" {
				p.Finish = ch.FinishReason
				p.FinishSeen = true
			}
			if ch.Delta.ReasoningContent != "" && ch.Delta.Content == "" {
				// 本机量过的形状：token 花在 reasoning 上、content 是空的、finish=length。
				// 只读 content 的驱动会把"没回话"记成正常收尾 —— 这里不许。
				p.Finish = strings.TrimSpace(p.Finish)
				if p.Finish == "" {
					p.Finish = "只有 reasoning、正文为空"
				}
			}
		}
		if frame.Usage != nil {
			p.UsageSaid = true
			p.UsageIn = frame.Usage.PromptTokens
			p.UsageOut = frame.Usage.CompletionTokens
		}
	}
	if err := sc.Err(); err != nil {
		p.Kind, p.Detail = "protocol", scrub(err.Error(), cfg.Key)
		return p, fmt.Errorf("回帧读到一半断了：%s", p.Detail)
	}
	if !p.Done && !p.FinishSeen {
		// 连接安安静静结束，但既没等到 [DONE] 也没收到 finish_reason ⇒ 这一发**没收完**。
		// 这一形以前会被记成正常回帧（fail_kind 空、KPI 照算），于是"端点话说了一半"在账上等于"说完了"。
		p.Kind, p.Detail = "protocol", fmt.Sprintf("回帧没收完：读到 %d 帧（其中 %d 帧解不开），既没等到 [DONE] 也没收到 finish_reason",
			p.Chunks, p.Malformed)
		return p, fmt.Errorf("%s", p.Detail)
	}
	p.Text = strings.TrimSpace(string(got))
	p.ElapsedMs = time.Since(t0).Milliseconds()
	return p, nil
}

// isLoopback 只看地址：这决定"贴进来的代码出不出这台机"，比"哪个旗标开的"更实在。
func isLoopback(raw string) bool {
	u, err := url.Parse(raw)
	if err != nil {
		return false
	}
	h := strings.ToLower(u.Hostname())
	return h == "localhost" || h == "127.0.0.1" || h == "::1" || strings.HasPrefix(h, "127.")
}

// gatewayLine 是第 ⑧ 步那句读数：全部是这一发自己数出来的，不带任何"应该有多少"的假设。
func (p *pipeReadout) gatewayLine() string {
	who := "非本机端点（贴进来的代码出这台机了 —— 只在你显式给了 PGAGENT_BASE_URL 时才走到这）"
	if p.Loopback {
		who = "本机端点（127.0.0.1，出不了这台机）"
	}
	if p.Fake {
		who += "·演示件：脚本写的回帧，真实模型调用 0 次"
	}
	usage := "端点没带 usage 字段（没说 ≠ 报了 0）"
	if p.UsageSaid {
		usage = fmt.Sprintf("端点自报 usage=%d/%d（relayed 档）", p.UsageIn, p.UsageOut)
		if p.UsageIn == 0 && p.UsageOut == 0 {
			usage += "：全 0 —— 这台机量过，流式的推理型端点就这样，所以停在 relayed，不许升 measured"
		}
	}
	head := ""
	if p.Kind != "" {
		head = "【打了但失败·归因 " + p.Kind + "：" + p.Detail + "】"
		if !p.Received {
			head += "（一个字节都没收到 ⇒ 下面的帧数/时延是 0 读数，不是量到 0）"
		} else if !p.BodyRead {
			// 回了非 200：错误体刻意不读（里面常回显请求，那是最容易把口令抄进读数的一条路），
			// 所以这一形下面的 0 帧/0ms 与"连不上"那一形是两种没量，都得在屏幕上说清，不许看着像量到的。
			head += "（回了非 200 ⇒ 错误体刻意没读：下面的帧数/时延是「没读」，不是「量到 0」）"
			if p.Status == 429 || p.Status >= 500 {
				// 降不降档重试是**人**的决定，而且这一发没真收到过流式帧 ⇒ 账上那一格记的是"不降"（见 failureOf 的注释）。
				// 但这一发请求里确实写着 stream=true，所以这句话得留在屏幕上，不能因为账上没记就不说。
				head += fmt.Sprintf("（这一发请求要的是流式、被 %d 挡回：要不要改非流式重试由你定，账上「降档」那一格这次记不降）", p.Status)
			}
		}
	}
	return fmt.Sprintf("%s｜%s｜读回 %d 字节、送出负载 %d 字节（不含 TLS/HTTP 头帧，估）、%d 帧、首帧 %dms、最大间隔 %dms、畸形帧 %d、收尾=%s｜%s",
		who+head, p.Model, p.BytesIn, p.BytesOut, p.Chunks, p.FirstByteMs, p.MaxGapMs, p.Malformed, orDash(p.Finish), usage)
}

func orDash(s string) string {
	if strings.TrimSpace(s) == "" {
		return "—"
	}
	return s
}

// scrub 把口令从要外泄到读数/账本的那句话里擦掉。
// 内核的契约写着"Detail 由调用方先擦过"（output.go:70），所以这一支必须在落Detail之前跑。
func scrub(s, key string) string {
	if k := strings.TrimSpace(key); k != "" {
		s = strings.ReplaceAll(s, k, "‹口令已擦〉")
	}
	return clipOne(s, 240)
}
