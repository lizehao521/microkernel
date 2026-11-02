package main

import (
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
)

// E7：三行界面（现在 / 已经 / 接下来）。这一组针要证的是「页面只投影、不算口径」，
// 以及「后端没交的那一格在屏上写没量过」——后者光看源码不算数，所以把页面里的 JS
// 拿到 node 里用桩 DOM 真跑一遍，喂三种帧，看渲染出来的字。
// 后端全绿 ≠ 页面活：node --check 与这三行读数都在同一条测试命令里。

func servePage(t *testing.T) (string, func()) {
	t.Helper()
	path := filepath.Join(t.TempDir(), "page.events.jsonl")
	r := newRun(t, "happy", true, "included", 20)
	r.events = newEventBus(path)
	r.loop()
	r.closeOut()
	addr, stop, err := serveEvents(path)
	if err != nil {
		t.Fatalf("起投送：%v", err)
	}
	return addr, stop
}

// 1) 路由与三行：/ 出页面，标签齐，订阅的是 /events，日志列有界。
func TestPageServesThreeRows(t *testing.T) {
	addr, stop := servePage(t)
	defer stop()
	code, body := httpGet(t, "http://"+addr+"/", "")
	if code != http.StatusOK {
		t.Fatalf("/ 给了 %d（三行页没接上路由）：%s", code, body[:120])
	}
	for _, want := range []string{"现在", "已经", "接下来", "EventSource('/events')", "没量过", "KEEP = 12"} {
		if !strings.Contains(body, want) {
			t.Errorf("页面上找不到 %q", want)
		}
	}
	// 结构配平：三行各一个 span，标签开闭数对得上（几何与结构同源那一条）
	if n := strings.Count(body, `<div class="row">`); n != 3 {
		t.Errorf("行容器 %d 个，应为 3（现在/已经/接下来）", n)
	}
	if strings.Count(body, "<script>") != strings.Count(body, "</scr"+"ipt>") {
		t.Error("script 标签不配平")
	}
}

// 2) 前端不许算口径：这些原语一出现就是页面自己开始加总/换算了。
func TestPageDoesNotComputeAnything(t *testing.T) {
	js := pageScript()
	if js == "" {
		t.Fatal("抠不出 <script> 那一段 —— 上一支针看到的页是从哪儿来的？")
	}
	for _, bad := range []string{"reduce(", "Math.", "parseInt(", "parseFloat(", "+=", "eval(", ".toFixed("} {
		if strings.Contains(js, bad) {
			t.Errorf("前端出现了 %q：口径只能由后端交，页面不许自己算（E7 的反臂就是插一个这个）", bad)
		}
	}
	// 屏上每一个值都要过 txt()：直接 put 后端字段就是把 undefined 交给浏览器显示。
	for _, line := range strings.Split(js, "\n") {
		s := strings.TrimSpace(line)
		if strings.HasPrefix(s, "put(") && strings.Contains(s, "d.") && !strings.Contains(s, "txt(") &&
			!strings.Contains(s, "head") && !strings.Contains(s, "nxt") && !strings.Contains(s, "doneBits") {
			t.Errorf("put() 里直接递了后端字段，没走「没量过」那道闸：%s", s)
		}
	}
}

// 3) node --check：语法不过，页面就是一张白纸，后端再绿也不作数。
func TestPageScriptParsesInNode(t *testing.T) {
	if _, err := exec.LookPath("node"); err != nil {
		t.Fatalf("这台机器上没有 node ⇒ 这一支没法跑（不写成过）：%v", err)
	}
	f := filepath.Join(t.TempDir(), "page.js")
	if err := os.WriteFile(f, []byte(pageScript()), 0o644); err != nil {
		t.Fatalf("写临时 js：%v", err)
	}
	out, err := exec.Command("node", "--check", f).CombinedOutput()
	if err != nil {
		t.Fatalf("node --check 红了：%v\n%s", err, string(out))
	}
}

// 4) 桩 DOM 真跑：三种帧各喂一发，看屏上那三行显示什么字。
func TestPageRendersWithStubDOM(t *testing.T) {
	if _, err := exec.LookPath("node"); err != nil {
		t.Fatalf("这台机器上没有 node ⇒ 这一支没法跑（不写成过）：%v", err)
	}
	harness := `
var els = {};
function El(id) { this.id = id; this.textContent = ''; this.children = []; }
Object.defineProperty(El.prototype, 'firstChild', { get: function () { return this.children[0] || null; } });
Object.defineProperty(El.prototype, 'lastChild', { get: function () { return this.children[this.children.length - 1] || null; } });
El.prototype.insertBefore = function (n) { this.children.unshift(n); };
El.prototype.removeChild = function () { this.children.pop(); };
global.document = {
  getElementById: function (id) { if (!els[id]) els[id] = new El(id); return els[id]; },
  createElement: function () { return new El('li'); }
};
function RealES(url) { this.url = url; this.onopen = null; this.onerror = null; this._h = {}; }
RealES.prototype.addEventListener = function (k, f) { this._h[k] = f; };
var inst = null;
global.EventSource = function (url) { inst = new RealES(url); return inst; };
` + "var PAGE = " + "`" + strings.ReplaceAll(pageScript(), "`", "") + "`" + `
eval(PAGE);
function fire(frame) { inst.onmessage({ data: JSON.stringify(frame) }); }
function read() {
  return [els['now'].textContent, els['done'].textContent, els['next'].textContent].join('\u0001');
}
var out = [];
fire(` + fmt.Sprintf("%s", frameJSON(t, map[string]any{
		"kind": "turn_accepted", "state": "running", "evidence": "measured", "turn": 1, "seq": 1, "ts": "T",
		"accept": map[string]any{"planned_shots": 0, "turn_limit": 2, "resumable": true},
	})) + `);
out.push(read());
fire(` + fmt.Sprintf("%s", frameJSON(t, map[string]any{
		"kind": "turn_settled", "state": "settled", "evidence": "measured", "turn": 1, "seq": 9, "ts": "T",
		"progress": map[string]any{"done": 1, "total": 2, "limit": 2},
		"settle": map[string]any{"kind": "completed", "phase": "record_call", "counts": map[string]int{"ok": 3, "running": 5}, "not_reached": []string{}},
	})) + `);
out.push(read());
fire(` + fmt.Sprintf("%s", frameJSON(t, map[string]any{
		"kind": "precheck", "state": "refused", "evidence": "absent", "turn": 2, "seq": 3, "ts": "T",
		"why": "账上没有这一格",
		"settle": map[string]any{"not_reached": []string{"check_call", "record_call"}},
	})) + `);
out.push(read());
for (var q = 0; q < 20; q++) {
  fire({"kind":"recorded","state":"ok","evidence":"measured","turn":9,"seq":q,"ts":"T"});
}
inst.onerror();
out.push(read());
fire({"kind":"recorded","state":"ok","evidence":"measured","turn":9,"seq":99,"ts":"T"});
out.push(read());
console.log(out.join('\u0002') + '\u0003' + els['log'].children.length);
`
	f := filepath.Join(t.TempDir(), "render.js")
	if err := os.WriteFile(f, []byte(harness), 0o644); err != nil {
		t.Fatalf("写 harness：%v", err)
	}
	cmd := exec.Command("node", f)
	out, err := cmd.CombinedOutput()
	if err != nil {
		t.Fatalf("页面 JS 在 node 里跑不起来：%v\n%s", err, string(out))
	}
	raw := strings.TrimSpace(string(out))
	tail := ""
	if i := strings.LastIndex(raw, "\u0003"); i >= 0 {
		tail = raw[i+len("\u0003"):]
		raw = raw[:i]
	} else {
		t.Fatal("node 没回日志列的行数 —— 有界性这一维没读到")
	}
	rows := strings.Split(raw, "\u0002")
	if len(rows) != 5 {
		t.Fatalf("喂了五组现场（三帧 + 断流 + 断流后又进一帧），拿回 %d 行", len(rows))
	}
	held := -1
	if _, err := fmt.Sscanf(tail, "%d", &held); err != nil {
		t.Fatalf("列长读不出：%q (%v)", tail, err)
	}
	for i, row := range rows {
		for _, dirty := range []string{"undefined", "NaN", "[object Object]", "null", "map["} {
			if strings.Contains(row, dirty) {
				t.Errorf("第 %d 帧的屏上有脏字 %q：%s", i+1, dirty, row)
			}
		}
	}
	cols := strings.Split(rows[0], "\u0001")
	if !strings.Contains(cols[0], "turn_accepted") || !strings.Contains(cols[2], "剧本已尽") {
		t.Errorf("planned_shots=0 那一帧没把「剧本已尽」投影出来：%s", rows[0])
	}
	if !strings.Contains(cols[1], "done=没量过") {
		t.Errorf("帧里没交 progress，「已经」行却不是没量过：%s", cols[1])
	}
	cols = strings.Split(rows[1], "\u0001")
	if !strings.Contains(cols[1], "done=1") || !strings.Contains(cols[1], "total=2") ||
		!strings.Contains(cols[1], "limit=2") || !strings.Contains(cols[1], "ok=3") || !strings.Contains(cols[1], "running=5") {
		t.Errorf("结算帧的「已经」行没把后端给的数原样投影：%s", cols[1])
	}
	if !strings.Contains(cols[2], "四相都走完了") {
		t.Errorf("not_reached 为空却说不出「四相都走完了」：%s", cols[2])
	}
	cols = strings.Split(rows[2], "\u0001")
	// 后端交过的数不能因为「这一帧没带」就被抹成没量过 —— 那是把有数读成没数（另一种塌三态）。
	if !strings.Contains(cols[1], "done=1") || !strings.Contains(cols[1], "total=2") {
		t.Errorf("后一帧没带 progress，屏上把上一帧交过的数丢了：%s", cols[1])
	}
	if !strings.Contains(cols[2], "check_call / record_call") {
		t.Errorf("not_reached 没被投影成接下来：%s", cols[2])
	}
	// 断流不能把「现在」那一行改成只剩一句断线：帧还在进的时候，那句是错的。
	cols = strings.Split(rows[3], "\u0001")
	if !strings.Contains(cols[0], "recorded") || !strings.Contains(cols[0], "断了") {
		t.Errorf("断流后「现在」行丢了最后一帧（应同时留 recorded 与断流状态）：%s", cols[0])
	}
	// 帧重新进来了，屏上却还挂着「断了」—— 浏览器实测真抓到过这一句假话
	cols = strings.Split(rows[4], "\u0001")
	if !strings.Contains(cols[0], "在进") || strings.Contains(cols[0], "断了") {
		t.Errorf("断流后又收到帧，「现在」的流状态没被更正：%s", cols[0])
	}
	// 会增长的容器一律有界：喂了 23 帧，屏上只许留 KEEP=12 行
	if held < 0 {
		t.Fatalf("列长没读到：%q", tail)
	}
	if held > 12 {
		t.Errorf("日志列留了 %d 行（应 ≤12）—— 不设界的列表在长会话里会把页面拖死", held)
	}
	if held != 12 {
		t.Errorf("日志列只留了 %d 行，喂了 23 帧 ⇒ 截断逻辑没走到 12 这个数", held)
	}
}

func frameJSON(t *testing.T, v any) string {
	t.Helper()
	b, err := json.Marshal(v)
	if err != nil {
		t.Fatalf("造帧：%v", err)
	}
	return string(b)
}

var _ = http.StatusOK
