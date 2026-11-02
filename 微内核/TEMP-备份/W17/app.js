'use strict';

const $ = (id) => document.getElementById(id);
const SAMPLE = `package main

import (
	"fmt"
	"os"
	"strings"
)

func load(p string) string {
	data, _ := os.ReadFile(p)
	seed := len(data)
	seed := seed + 1
	if strings.Contains(string(data), "x") {
		for i := 0; i < 3; i++ {
			switch i {
			case 0:
				fmt.Println("a")
			case 1:
				fmt.Printf("b%d", i)
			}
		}
	}
	return string(data)
}

func helper() int { return 1 }

func helper() int { return 2 }

func main() {
	err := fmt.Errorf("boom")
	if err != nil {
	}
	fmt.Print(load("a.txt"))
}
`;

// 配上面那份样例的报错：两帧指得回 SAMPLE 的行号（16 / 31）。
// 栈只用来定位，不用来下结论 —— 这台机不执行代码，帧行号对不上文件名是常态。
const SAMPLE_STACK = "panic: runtime error: invalid memory address or nil pointer dereference\n" +
  "[signal SIGSEGV: segmentation violation code=0x1 addr=0x0 pc=0x47e07f]\n\n" +
  "goroutine 1 [running]:\nmain.load({0x4a1b20, 0x7})\n\t/tmp/demo/main.go:16 +0x42\n" +
  "main.main()\n\t/tmp/demo/main.go:31 +0x1f\nexit status 2\n";

const session = (() => {
  const k = 'pgagent-session';
  let v = localStorage.getItem(k);
  if (!v) { v = 'web-' + Math.random().toString(36).slice(2, 8); localStorage.setItem(k, v); }
  return v;
})();

const BADGE = { measured: 'm', estimated: 'e', model_says: 's', relayed: 'r', absent: 'a' };
let curTurn = null;

function el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined) n.textContent = text;   // 一律 textContent：贴进来的代码不许变成 HTML
  return n;
}

function syncGutter() {
  const t = $('code');
  const n = t.value.split('\n').length;
  const lines = [];
  for (let i = 1; i <= n; i++) lines.push(i);
  $('gutter').textContent = lines.join('\n');
  $('gutter').style.transform = `translateY(${-t.scrollTop}px)`;
}

async function loadHistory() {
  const r = await fetch(`/api/history?session=${encodeURIComponent(session)}`);
  const j = await r.json();
  const ol = $('hist');
  ol.textContent = '';
  (j.turns || []).forEach((t) => {
    const li = el('li');
    li.append(el('b', null, `第 ${t.turn} 发`));
    li.append(el('span', 'dim', ` · 跑了 ${t.steps_ran}/${t.steps_total} 步 · findings ${t.findings} · 未决 ${t.unknowns} · 指纹 ${t.sha256_of_code} · 结束=${t.stop_reason}`));
    li.append(el('div', 'sum', t.answer_summary));
    if (t.stop_reason !== '跑完') li.append(el('div', 'dim', '停在哪：' + t.stop_why));
    if (!t.mix_identity_ok) li.append(el('div', 'red', '五档加总对不上 —— 这一发的出处有塌档'));
    ol.append(li);
  });
  $('hist-note').textContent = `本会话 ${j.count} 发（数据/会话-${session}.jsonl）`;
}

function renderStep(s) {
  const li = el('li');
  li.className = s.ran ? 'ran' : 'notran';
  li.append(el('span', 'no', `${s.step}`));
  li.append(el('b', 'tool', s.name));
  li.append(el('span', 'b ' + (BADGE[s.basis] || 'a'), s.basis + (s.ran ? '' : ' · 没跑')));
  li.append(el('div', 'out', s.out));
  $('trace').append(li);
}

function renderResult(res) {
  const findings = res.findings || [];
  const unknowns = res.unknowns || [];
  const dec = res.ledger_decisions || [];
  const f = $('findings');
  f.textContent = '';
  if (!findings.length) {
    f.append(el('p', 'dim', '结构类判据没命中。这不等于代码没问题 —— 只等于这几条尺子量不到（看下面未决项）。'));
  }
  findings.slice(0, 15).forEach((x, i) => {
    const card = el('article', 'card ' + x.severity);
    const head = el('div', 'head');
    head.append(el('span', 'sev', x.severity));
    head.append(el('b', 'rule', x.rule));
    head.append(el('span', 'b ' + BADGE[x.basis], x.basis));
    if (x.where && x.where.lines && x.where.lines[1]) head.append(el('span', 'dim', ` L${x.where.lines[0]}-${x.where.lines[1]}${x.where.symbol ? ' ' + x.where.symbol : ''}`));
    card.append(head);
    card.append(el('p', 'ev', '证据：' + x.evidence));
    card.append(el('p', 'claim', x.claim));
    if (x.fix) card.append(el('p', 'fix', '修法：' + x.fix.rationale + '（风险：' + x.fix.risk + '）'));
    card.append(el('p', 'ver', '怎么验：' + x.verify));
    f.append(card);
    if (i === 14 && findings.length > 15) f.append(el('p', 'dim', `本页只渲前 15 条，共 ${findings.length} 条（其余条数看加总）`));
  });

  const dp = $('debug');
  dp.textContent = '';
  const dbg = res.debug;
  if (dbg) {
    dp.append(el('b', null, '栈读数：'));
    dp.append(el('span', null, `贴入 ${dbg.stack_bytes} 字节 · 认出 ${dbg.frames_parsed} 帧 · 行号落进上面代码 ${dbg.frames_pointing_into_snippet} 帧（栈只定位、不下结论；文件名对不上就不许升 measured）`));
  } else {
    dp.append(el('span', null, '栈读数：这一发没给栈 ⇒ 调试路径没跑。这不是「没有 bug」，理由在下面的未决项里。'));
  }

  const gp = $('gwline');
  gp.textContent = '';
  const gwv = res.gateway;
  if (gwv) {
    gp.append(el('b', null, '通道读数：'));
    let who = '非本机端点（贴进来的代码出了这台机）';
    if (gwv.loopback) who = '本机端点（127.0.0.1，出不了这台机）';
    if (gwv.fake) who += '·演示件：真实模型 0 次';
    if (gwv.fail_kind) who += `｜失败归因 ${gwv.fail_kind}：${gwv.fail_detail}`;
    const usage = gwv.usage_said ? `${gwv.usage_in}/${gwv.usage_out}（relayed，端点自报）` : '端点没说（没说 ≠ 0）';
    gp.append(el('span', null, `${who}｜读回 ${gwv.bytes_in} 字节、送出 ${gwv.bytes_out} 字节（估）、` +
      `${gwv.chunks} 帧、首帧 ${gwv.first_byte_ms}ms、最大间隔 ${gwv.max_gap_ms}ms、畸形帧 ${gwv.malformed}、` +
      `收尾=${gwv.finish || '—'}｜usage ${usage}｜格式=${gwv.wire_object || '对端没说'}`));
  } else {
    gp.append(el('span', null, '通道读数：这一发没打端点 ⇒ 第 ⑧ 步是 NOT_RUN，管路那几格记 absent 带理由（不写 0）。'));
  }

  const u = $('unknowns');
  u.textContent = '';
  unknowns.forEach((x) => {
    const li = el('li');
    li.append(el('b', null, x.what));
    li.append(el('span', 'b ' + BADGE[x.basis], x.basis));
    li.append(el('div', 'dim', '为什么没量到：' + x.why_absent));
    li.append(el('div', 'get', '怎么才量得到：' + x.how_to_get));
    u.append(li);
  });

  const d = $('decisions');
  d.textContent = '';
  if (!dec.length) {
    d.append(el('li', 'dim', '这一发没有任何一格是从账上读回来再改写结果的（接缝没装或被关掉）—— 不是 0 次决定，是没问账'));
  }
  dec.forEach((x) => {
    const li = el('li');
    li.append(el('b', 'key', `${x.side} / ${x.key}`));
    li.append(el('span', 'b ' + (BADGE[x.basis] || 'a'), x.basis || '没这一格'));
    li.append(el('div', 'dim', '账上原话：' + (x.claim || '（回帧里没有这一格）')));
    li.append(el('div', 'get', '所以这一步这么走：' + x.effect));
    d.append(li);
  });
  $('kpi-why').textContent = res.kpi_why || '';

  const m = res.provenance_mix;
  const mix = $('mix');
  mix.textContent = `measured ${m.measured} / estimated ${m.estimated} / model_says ${m.model_says} / relayed ${m.relayed} / absent ${m.absent} = ${m.total}　加总核对：${res.mix_identity_ok ? '对得上' : '对不上'}`;
  mix.className = 'mix ' + (res.mix_identity_ok ? 'ok' : 'bad');

  const ran = res.trace.filter((s) => s.ran).length;
  const kpi = res.trace.find((s) => s.name === 'kernel.read_back');
  const band = $('band');
  band.textContent = '';
  band.append(el('b', null, `第 ${res.turn} 发跑完：`));
  band.append(el('span', null, ` ${res.answer_summary} · 真跑了 ${ran}/${res.trace.length} 步 · `));
  band.append(el('span', kpi && kpi.ran ? 'ok' : 'red',
    kpi && kpi.ran
      ? `账本触发过 ${res.kpi_ledger_decided} 次决定（读回 ${dec.length} 格，只有真改写了结果的才计入）· ${res.kpi_why}`
      : (kpi
        ? `账本触发 ${res.kpi_ledger_decided} 次决定 · 读回这一步的原话：${kpi.out}`
        : '这一发没走到读回那步 ⇒ 「账触发过几次决定」量不到，记 absent，不写 0')));
  band.append(el('span', 'dim', ` · 代码执行=${res.code_executed ? '是' : '否'}`));
  band.append(el('span', res.stop_reason === '跑完' ? 'dim' : 'red',
    ` · 结束=${res.stop_reason}：${res.stop_why}`));
}

async function submit() {
  const code = $('code').value;
  if (!code.trim()) { $('state').textContent = '代码是空的：不发空输入（发了也只会被后端拒）'; return; }
  $('trace').textContent = '';
  $('findings').textContent = '';
  $('unknowns').textContent = '';
  $('decisions').textContent = '';
  $('debug').textContent = '';
  $('gwline').textContent = '';
  $('state').textContent = '跑动中……';
  curTurn = null;
  $('stop').disabled = true;
  const t0 = performance.now();
  try {
    const resp = await fetch('/api/turn', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session, code, question: $('q').value, lang: $('lang').value, stack: $('stack').value }),
    });
    if (!resp.ok) { $('state').textContent = '服务端拒了：' + (await resp.text()); return; }
    const reader = resp.body.getReader();
    const dec = new TextDecoder();
    let buf = '';
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let i;
      while ((i = buf.indexOf('\n\n')) >= 0) {
        const frame = buf.slice(0, i);
        buf = buf.slice(i + 2);
        let ev = 'message', data = '';
        frame.split('\n').forEach((ln) => {
          if (ln.startsWith('event: ')) ev = ln.slice(7).trim();
          else if (ln.startsWith('data: ')) data += ln.slice(6);
        });
        if (!data) continue;
        const obj = JSON.parse(data);
        if (ev === 'meta') { curTurn = obj.turn; $('stop').disabled = false; }
        else if (ev === 'step') renderStep(obj);
        else if (ev === 'result') { renderResult(obj); }
      }
    }
    $('state').textContent = `这一发用了 ${Math.round(performance.now() - t0)} ms`;
    await loadHistory();
  } catch (e) {
    $('state').textContent = '出错：' + e.message;
  } finally {
    $('stop').disabled = true;
  }
}

async function stopTurn() {
  if (curTurn == null) return;
  $('stop').disabled = true;
  $('state').textContent = '已点停，等这一发把已跑的部分收口……';
  await fetch('/api/stop', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session, turn: curTurn }),
  });
}

$('go').addEventListener('click', submit);
$('stop').addEventListener('click', stopTurn);
$('load').addEventListener('click', () => { $('code').value = SAMPLE; syncGutter(); });
$('loadstack').addEventListener('click', () => { $('stack').value = SAMPLE_STACK; });
$('code').addEventListener('input', syncGutter);
$('code').addEventListener('scroll', syncGutter);
$('code').addEventListener('keydown', (e) => {
  if (e.key === 'Tab') {
    e.preventDefault();
    const t = e.target, s = t.selectionStart, en = t.selectionEnd;
    t.value = t.value.slice(0, s) + '\t' + t.value.slice(en);
    t.selectionStart = t.selectionEnd = s + 1;
    syncGutter();
  }
});
document.addEventListener('keydown', (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') { e.preventDefault(); submit(); }
});

syncGutter();
loadHistory();

// ?run=1 —— 给"打开链接就自己跑一圈"的场合（无头渲染出截图 / 试读的人不必先研究按钮）。
// 它走的是与点【发起一发】完全同一条 /api/turn，数据不是造的；但**触发者不是人**，
// 所以页面必须把这件事写在脸上，免得日后这张图被读成"真人点出来的一发"。
const params = new URLSearchParams(location.search);
if (params.get('run') === '1') {
  const a = $('autorun');
  a.textContent = '这一发由 URL 参数 ?run=1 自动触发（不是人点出来的；代码与栈用的是页内置样例）。';
  a.hidden = false;
  $('code').value = SAMPLE;
  $('stack').value = SAMPLE_STACK;
  const q = params.get('q');
  if (q) $('q').value = q;
  syncGutter();
  submit();
}
