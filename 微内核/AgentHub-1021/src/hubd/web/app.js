// 前端只做三件事：把 SSE 事件原样画出来、把三态分清楚（量到 / 没量到 / 被挡）、
// 以及绝不把「后端没交的数」写成 0。数字与判据都由后端交，这里不自己算口径。
//
// 界面做法参考了同类控制台（trace 行 = 名称 + 右对齐元数字 + 耗时条；状态不只靠颜色；
// 折叠条在收起态也要带信息）。一处刻意不跟：参考产品把零值元数据直接不渲染（LangSmith 藏 $0.00），
// 而这台机器上 retries=0 / degrades=0 是**量出来的 0**，藏掉等于删证据 ⇒ 保留，只降视觉权重。
'use strict';

const $ = (id) => document.getElementById(id);
const el = (tag, cls, text) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== null && text !== undefined) n.textContent = String(text);
  return n;
};

let 在跑 = null;    // AbortController
let 当前 = null;    // 这一发的步表：步号 -> DOM 节点
let 脏字 = 0;
let 最长ms = 1;

// 动作短语：折叠条标题要能读懂"在干什么"；真工具名必须同时在场（那是契约里的一栏）。
const 动作 = {
  'fs.list': '列目录', 'fs.read': '读文件', 'text.stats': '数文本', 'calc.eval': '算算式',
  'time.now': '看时间', 'http.get': '取地址', 'tools.list': '报工具', 'memory.recall': '忆旧话',
  'notes.write': '写笔记', 'exec.run': '跑命令', 'demo.flaky': '演重试',
};
const 状态字 = { queued: '○', attempt: '◐', retrying: '↻', backoff: '⏱', ok: '✓', failed: '✕' };
const 档字 = { measured: '▣', estimated: '◐', model_says: '✦', relayed: '❝', absent: '∅' };

function 档徽(档) {
  const 名 = { measured: '量到', estimated: '本机推的', model_says: '端点说的', relayed: '外部正文', absent: '没量到' };
  const 认 = 名[档];
  return el('b', 'b ' + (档 || 'absent'), 认 ? 档字[档] + ' ' + 认 : '不认识档:' + 档);
}

function 状态徽(s) {
  const 认 = { queued: '排队', attempt: '试第', retrying: '重试', backoff: '等', ok: '成功', failed: '失败' };
  if (!(s in 认)) return el('b', 'b bad', '不认识状态:' + s);
  return el('b', 'b ' + s, 状态字[s] + ' ' + 认[s]);
}

function 摘要(o) {
  const 件 = [];
  for (const k of Object.keys(o.args || {})) 件.push(k + '=' + JSON.stringify(o.args[k]));
  const 文 = 件.join(' ') || '（无参）';
  return 文.length > 46 ? 文.slice(0, 46) + '…' : 文;
}

function 清一列() {
  当前 = new Map();
  最长ms = 1;
  $('calls').textContent = '';
  $('answer').textContent = '';
  $('findings').textContent = '';
  $('unknowns').textContent = '';
  $('fold').hidden = true;
  脏字 = 0;
}

function 步节点(p) {
  const li = el('li', 'call');
  const 头 = el('div', 'hd');
  头.append(el('b', 'step', '步 ' + p.step));
  头.append(el('span', 'tool', (动作[p.tool] || p.tool) + (动作[p.tool] ? ' ' + p.tool : '')));
  const 状 = el('span', 'st');
  const 条 = el('span', 'dur');
  条.append(el('i'));
  const 元 = el('span', 'meta');
  头.append(状);
  li.append(头);
  // 表头只留三格：步号 / 工具名 / 状态徽。毫秒与重试旁白同住下一行 ——
  // 实测：表头带第四格（右对齐元数字）时，1100 与 700 两档把工具名挤到 45px、60px，
  // 而名字要 102~162px 才不截断；名字是这一行最不能少的东西。
  const 旁 = el('div', 'sub');
  const 话 = el('span', 'dim');
  旁.append(条, 话, 元);
  li.append(旁);

  const 参 = document.createElement('details');
  参.className = 'fold args';
  参.append(el('summary', null, '参数 ' + 摘要(p) + '（' + (p.args_from || '没交代来处') + '）'));
  参.append(el('pre', null, JSON.stringify(p.args || {}, null, 1)));
  li.append(参);

  li.append(el('div', 'why', '为什么走这步：' + (p.why || '（后端没交这句）')));

  const 出 = document.createElement('details');
  出.className = 'fold out';
  出.append(el('summary', null, '返回正文'));
  const 结果 = el('pre', 'result');
  出.append(结果);
  li.append(出);

  li.dataset.state = 'run';
  $('calls').append(li);
  return { li, 结果, 状, 元, 条, 话, 出 };
}

function 上状态(节, d) {
  if (!节 || !节.状) return;
  节.状.textContent = '';
  节.状.append(状态徽(d.status));
  // 旁白走表头下面那一行，不挤表头：先前把「第 N 次 / 类别 / 等 Nms」塞进状态格里，
  // 表头最宽的一格成了它，被压成两个字的却是工具名。
  节.话.textContent = '';
  if (d.第几次 > 1) 节.话.append(el('span', null, '第 ' + d.第几次 + ' 次'));
  if (d.class) 节.话.append(el('span', null, ' 类别 ' + d.class));
  if (d.等_ms) 节.话.append(el('span', null, ' ↻ 等 ' + d.等_ms + 'ms（' + (d.为什么 || '') + '）'));
  if (d.ms) 节.元.textContent = d.ms + 'ms';
  if (d.text) {
    节.结果.textContent = d.text;
    节.出.querySelector('summary').textContent = '返回正文 · ' + d.text.length + ' 字';
  }
}

function 收结果(o) {
  let 节 = 当前.get(o.step);
  if (!节) {
    节 = 步节点(o);
    当前.set(o.step, 节);
  }
  填(节, o);
}

function 填(节, o) {
  节.li.dataset.state = o.class === 'ok' ? 'ok' : 'bad';
  节.结果.textContent = o.text || '';
  节.出.querySelector('summary').textContent = '返回正文 · ' + (o.text || '').length + ' 字';
  // 失败留开、成功收起：要看的是坏那一格的原文
  节.出.open = o.class !== 'ok';
  if (o.ms > 最长ms) 最长ms = o.ms;
  节.元.textContent = (o.ms === undefined ? '' : o.ms + 'ms') + (o.attempts ? ' · 试 ' + o.attempts + ' 次' : '');
  let 尾 = 节.li.querySelector('.tag');
  if (!尾) { 尾 = el('span', 'tag'); 节.li.append(尾); }
  尾.textContent = '';
  尾.append(档徽(o.evidence));
  尾.append(el('span', 'dim', ' 谁选的：' + (o.provenance === 'model_says' ? '模型端点' : '本机规则') +
    ' ｜ 风险档 ' + (o.risk || '没交') + (o.attempts ? ' ｜ 试了 ' + o.attempts + ' 次' : '') +
    (o.waited_ms ? ' ｜ 等 ' + o.waited_ms + 'ms' : '')));
  if (o.degraded_from) 尾.append(el('span', 'warn', ' ↧ 从 ' + o.degraded_from + ' 降级来'));
  if (o.absent_why) 节.li.append(el('div', 'red', '∅ 没量到：' + o.absent_why));
  画条();
  $('fold').hidden = 当前.size < 2;
}

// 耗时条：按这一发里最慢的一步归一化；不足 2% 也给一点宽度，别让 1ms 的步看着像没跑。
function 画条() {
  当前.forEach((节) => {
    if (!节.条 || !节.条.firstElementChild) return;
    const m = (节.元.textContent || '').match(/^(\d+)ms/);
    const i = 节.条.firstElementChild;
    if (!m) { i.style.width = '0'; return; }
    const 占 = Math.max(2, Math.round((Number(m[1]) / 最长ms) * 100));
    i.style.width = 占 + '%';
    节.条.title = m[1] + 'ms ｜ 占这一发最慢一步的 ' + 占 + '%';
  });
}

// 带的第一行就是那本账：三处地方要往这一行上续字，没有就建一个。
function 带一行() {
  const band = $('band');
  let 一 = band.querySelector('.带一');
  if (!一) { 一 = el('div', '带一'); band.append(一); }
  return 一;
}

function 填band(res) {
  const band = $('band');
  band.textContent = '';
  const 成 = (res.steps || []).filter((s) => s.class === 'ok').length;
  const 一 = el('div', '带一');
  // 这里不写"跑完"：那一格归后面的「结束=」说。先前写死了，于是一发撞在步数上限上，
  // 带首仍印"第 N 发跑完"—— 自己跟自己打架。
  一.append(el('b', null, '第 ' + res.turn + ' 发'));
  // 带里不重述答案：全文已经落在左栏，抄一遍会把这一格撑成十行散文（截图量过）。
  // 只留"没结论"这一种情况 —— 那是要在账上看得见的坏。
  if (!res.answer) 一.append(el('span', 'red', ' （这一发没结论）'));
  一.append(el('span', 'dim 统计', ' ｜ 走 ' + (res.steps || []).length + ' 步（成功 ' + 成 + '）· 规划器 ' +
    (res.plan || '—') + ' · 多试 ' + res.retries + ' 次 · 等 ' + res.waited_ms + 'ms · 降级 ' + res.degrades + ' 次'));
  const mix = res.mix || {};
  const 分档 = ['measured', 'estimated', 'model_says', 'relayed', 'absent'];
  const 加总 = 分档.reduce((a, k) => a + (mix[k] || 0), 0);
  一.append(el('span', 'dim 统计', ' ｜ 出处档 ' + 分档.map((k) => 档字[k] + (mix[k] || 0)).join(' ') +
    ' · 加总 ' + 加总 + '/' + (mix.total === undefined ? '没交' : mix.total) +
    ' ' + (mix.total === undefined ? '（没量过）' : (加总 === mix.total ? '对得上' : '对不上'))));
  一.append(el('span', res.sane === true ? 'dim' : 'red', ' · 自洽=' + 三态(res.sane) +
    (res.sane === true ? ' ✓' : res.sane === false ? ' ✕' : '')));
  一.append(el('span', res.stop === '跑完' ? 'dim' : 'red', ' · 结束=' + res.stop));
  band.append(一);
  // 两句"为什么"折起来：账要一眼看完，理由点开才看。坏的那一发不许折 ——
  // 藏进 details 里的红等于没有红（和"失败那格的返回正文留开"是同一条规矩）。
  const 折 = document.createElement('details');
  折.className = 'fold 带折';
  折.append(el('summary', null, '展开：这一行的完整账 + 为什么'));
  const 内 = el('div', '带故');
  // 窄屏把上面那行夹成一行（CSS），所以这里必须带一份全文 —— 夹掉不等于没有。
  内.append(el('div', 'dim 账全', '账：' + 一.innerText));
  内.append(el('div', res.sane === true ? 'dim' : 'red', '整列自洽：' + (res.sane_why || '（这条读数没交来）')));
  内.append(el('div', res.stop === '跑完' ? 'dim' : 'red', '结束=' + res.stop + '：' + res.stop_why));
  折.append(内);
  折.open = !(res.sane === true && res.stop === '跑完');
  band.append(折);
  画条();
}

function 三态(v) {
  if (v === true) return '过';
  if (v === false) return '红';
  return '没量过';
}

async function 发(text) {
  if (在跑) { 在跑.abort(); }
  在跑 = new AbortController();
  清一列();
  $('go').disabled = true;
  document.body.classList.add('streaming-on');
  const me = el('div', 'msg user');
  me.append(el('b', null, '你说'));
  me.append(el('span', null, text));
  $('msgs').append(me);
  const 回 = el('div', 'msg agent');
  回.append(el('b', null, 'Agent'));
  const 正文 = el('span', 'streaming', '');
  回.append(正文);
  $('msgs').append(回);
  滚到底();

  let 事件数 = 0, 帧 = '';
  const t0 = performance.now();
  try {
    const r = await fetch('/api/chat', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text }), signal: 在跑.signal });
    if (!r.ok || !r.body) { 正文.textContent = '取回 HTTP ' + r.status + ' ⇒ 这一发没流式'; return; }
    const rd = r.body.getReader();
    const 码 = new TextDecoder();
    for (;;) {
      const { value, done } = await rd.read();
      if (done) break;
      帧 += 码.decode(value, { stream: true });
      let 切;
      while ((切 = 帧.indexOf('\n\n')) >= 0) {
        const 块 = 帧.slice(0, 切);
        帧 = 帧.slice(切 + 2);
        处理(块, 正文);
        事件数++;
      }
    }
  } catch (e) {
    if (e.name !== 'AbortError') 正文.append(el('span', 'red', ' ✕ 断了：' + e.message));
    else 正文.append(el('span', 'warn', ' ⊘ 你打断了这一发'));
  } finally {
    $('go').disabled = false;
    document.body.classList.remove('streaming-on');
    在跑 = null;
    $('budget').textContent = '这一发收了 ' + 事件数 + ' 帧 · ' + Math.round(performance.now() - t0) + 'ms';
    读记忆();
  }
}

function 处理(块, 正文) {
  let kind = '', data = '';
  for (const l of 块.split('\n')) {
    if (l.startsWith('event: ')) kind = l.slice(7).trim();
    else if (l.startsWith('data: ')) data = l.slice(6);
  }
  if (!kind) return;
  let p;
  try { p = JSON.parse(data); } catch (e) { p = { 解析失败: String(data).slice(0, 120) }; }
  switch (kind) {
    case 'meta':
      $('band').textContent = '';
      带一行().append(el('b', null, '第 ' + p.turn + ' 发开跑'));
      带一行().append(el('span', 'dim 统计', ' ｜ 规划顺序 ' + p.plan + ' · 认识 ' + p.tools + ' 个工具 · 步数上限 ' +
        p.max_steps + ' · 记忆里 ' + p.memory_msgs + ' 条'));
      break;
    case 'plan':
      if (p.kind === 'ask' || p.kind === 'done') {
        const li = el('li', 'call plan');
        li.dataset.state = p.kind === 'ask' ? 'bad' : 'ok';
        const 头 = el('div', 'hd');
        头.append(el('b', 'step', '步 ' + p.step));
        头.append(el('span', 'tool', p.kind === 'ask' ? '⊘ 要你再补一句' : '✓ 可以收口了'));
        li.append(头);
        li.append(el('div', 'why', p.why || '（后端没交理由）'));
        li.append(el('div', 'dim', '这一步由 ' + p.plan + ' 决定'));
        $('calls').append(li);
        当前.set(p.step, { li });
        $('fold').hidden = 当前.size < 2;
      } else if (p.ask) {
        带一行().append(el('span', 'dim', ' · 问 ' + p.ask));
      }
      break;
    case 'tool_status': {
      let 节 = 当前.get(p.step);
      if (!节) {
        节 = 步节点({ step: p.step, tool: p.tool, args: p.args, args_from: p.args_from,
          why: '（这一步由状态事件先带出来，参数见下）' });
        当前.set(p.step, 节);
      }
      if (p.risk) 节.li.dataset.risk = p.risk;
      上状态(节, p);
      break;
    }
    case 'tool_result':
      收结果(p);
      break;
    case 'answer_delta':
      正文.append(document.createTextNode(p.text));
      滚到底();
      break;
    case 'result':
      填band(p);
      for (const f of p.findings || []) {
        const li = el('li');
        li.append(档徽(f.tier));
        li.append(el('span', null, ' ' + f.text));
        if (f.why) li.append(el('div', 'dim', '为什么：' + f.why));
        if (f.tier === 'absent') {
          const u = el('li');
          u.append(el('span', 'red', '∅ 没量到：' + f.text));
          u.append(el('div', 'dim', '理由：' + (f.why || '后端没交理由 —— 这本身就是问题')));
          $('unknowns').append(u);
        }
        $('findings').append(li);
      }
      检脏字();
      break;
    case 'done':
      带一行().append(el('span', 'dim', ' · 共 ' + p.events + ' 帧'));
      读健康();
      break;
    default:
      带一行().append(el('span', 'red', ' · 不认识的事件 ' + kind));
  }
}

function 检脏字() {
  const t = document.body.innerText;
  for (const w of ['undefined', 'NaN', '[object Object]', 'null', 'map[', '%!']) {
    const n = t.split(w).length - 1;
    if (n > 0) 脏字 += n;
  }
  if (脏字 > 0) {
    $('band').append(el('div', 'red', '✕ 屏幕上有 ' + 脏字 + ' 处 undefined/NaN/[object Object]/null ⇒ 后端交了没人接的字段'));
  }
}

function 滚到底() { const m = $('msgs'); m.scrollTop = m.scrollHeight; }

async function 读健康() {
  try {
    const h = await (await fetch('/api/health')).json();
    $('health').textContent = '本机认识 ' + h.tools + ' 个工具 ｜ 记忆 ' + h.memory + ' 条 ｜ 下一发是第 ' +
      h.next_turn + ' 发 ｜ 模型端点 ' + h.model_endpoint + ' ｜ 写文件=' + (h.allow_write ? '放行' : '关') +
      ' 执行=' + (h.allow_exec ? '放行' : '关');
  } catch (e) {
    $('health').textContent = '读不到 /api/health：' + e.message;
  }
}

async function 读注册表() {
  try {
    const t = await (await fetch('/api/tools')).json();
    const ul = $('registry');
    ul.textContent = '';
    for (const s of t.specs || []) {
      const li = el('li');
      li.append(el('b', null, (动作[s.name] ? 动作[s.name] + ' ' : '') + s.name));
      li.append(el('span', 'dim', ' [' + s.risk + ']（' + s.source + '，超时 ' + s.timeout_ms + 'ms，试 ' + s.retry.attempts + ' 次）'));
      li.append(el('div', null, s.summary));
      li.append(el('div', 'dim', '参数：' + (s.params || []).map((p) => p.name + (p.required ? '*' : '') + ':' + p.type).join('、') +
        (s.fallback ? ' ｜ 降级备选：' + s.fallback : '') + (s.requires_flag ? ' ｜ 要 -' + s.requires_flag : '') +
        (s.triggers && s.triggers.length ? ' ｜ 触发词：' + s.triggers.join('、') : '')));
      ul.append(li);
    }
    for (const r of t.rejected || []) ul.append(el('li', 'red', '✕ 被拒的注册：' + r));
    for (const r of t.shadow || []) ul.append(el('li', 'red', '✕ 影子注册被挡：' + r));
    ul.append(el('li', 'dim', '文件根：' + (t.fs_roots || []).join('、') + ' ｜ 出网白名单：' + (t.net_allow || []).join('、') +
      ' ｜ 清单目录：' + t.tools_dir + '（放一个 .json 就多一个工具）'));
    $('tab-reg').textContent = '工具注册表 ' + (t.specs || []).length;
  } catch (e) {
    $('registry').append(el('li', 'red', '✕ 读不到 /api/tools：' + e.message));
  }
}

async function 读记忆() {
  try {
    const m = await (await fetch('/api/turns?limit=40')).json();
    const ul = $('hist');
    ul.textContent = '';
    for (const t of m.msgs || []) {
      const li = el('li');
      li.append(el('b', null, '第 ' + t.turn + ' 发'));
      li.append(el('span', null, ' ' + (t.user || '（没有用户话）') + ' → ' + (t.agent || '（没回话）')));
      li.append(el('div', 'dim', '工具：' + ((t.tools || []).map((x) => 动作[x] || x).join('、') || '这发没走工具') +
        ' ｜ 结束=' + (t.stop || '—')));
      ul.append(li);
    }
    if (!(m.msgs || []).length) ul.append(el('li', 'dim', '这本会话还没有发'));
    $('tab-hist').textContent = '会话记忆 ' + (m.msgs || []).length;
  } catch (e) {
    $('hist').append(el('li', 'red', '✕ 读不到 /api/turns：' + e.message));
  }
}

// —— 交互：Enter 发、Shift+Enter 换行、Esc 打断、全部展开/收起、右栏两个低频页签 ——
// 叫停走两端：先让后端取消（它才会把「被打断」的收口交回来），再给本地流一个兜底 abort。
// 只 abort 本地流的话，服务端那一发会照跑到底 —— 以前它根本不看 ctx。
function 叫停(话) {
  if (!在跑) return;
  const ctl = 在跑;
  $('budget').textContent = 话 || '正在叫停…';
  fetch('/api/stop', { method: 'POST' }).catch(() => {});
  setTimeout(() => { if (在跑 === ctl) ctl.abort(); }, 2000);
}
$('say').addEventListener('submit', (ev) => {
  ev.preventDefault();
  const v = $('input').value.trim();
  if (!v) { $('budget').textContent = '空的 ⇒ 这一发没话可规划，前端就没发请求'; return; }
  $('input').value = '';
  发(v);
});
$('input').addEventListener('keydown', (ev) => {
  if (ev.key === 'Enter' && !ev.shiftKey) { ev.preventDefault(); $('say').requestSubmit(); }
  else if (ev.key === 'Escape' && 在跑) { 叫停('已叫停这一发：等它交出被打断的收口'); }
});
$('stop').addEventListener('click', () => { 叫停(); });
// 开一本新账：后端早就有 /api/session/new，前端一直没接 —— 于是"换一本账"只能在页外做。
$('new').addEventListener('click', async () => {
  if (在跑) 叫停('先叫停这一发，再换账…');
  $('new').disabled = true;
  try {
    const r = await (await fetch('/api/session/new', { method: 'POST' })).json();
    if (r.ok !== true) { $('budget').textContent = '没开成新账：' + (r.why || '后端没交理由'); return; }
    $('msgs').textContent = '';
    清一列();
    $('band').textContent = '';
    $('budget').textContent = '换了一本账：上一本 ' + r['上一本几条'] + ' 条 · 新文件 ' + r['新文件'] +
      ' · 读回 ' + r['读回行'] + ' 行（坏行 ' + r['坏行'] + '）';
    读健康(); 读记忆();
  } catch (e) {
    $('budget').textContent = '开新账没成：' + e.message;
  } finally {
    $('new').disabled = false;
  }
});
$('fold').addEventListener('click', () => {
  const 要开 = $('fold').dataset.on !== '1';
  document.querySelectorAll('#calls details.fold').forEach((d) => { d.open = 要开; });
  $('fold').dataset.on = 要开 ? '1' : '0';
  $('fold').textContent = 要开 ? '全部收起' : '全部展开';
});
document.querySelectorAll('.tab').forEach((钮) => {
  钮.addEventListener('click', () => {
    document.querySelectorAll('.tab').forEach((x) => {
      x.setAttribute('aria-selected', x === 钮 ? 'true' : 'false');
      $(x.dataset.for).hidden = x !== 钮;
    });
  });
});

读健康();
读注册表();
读记忆();

// ?run=N：连着跑 N 发样例（截图与浏览器实测要用）。
// 以前只认 run=1，run=2 会一发出都不发 —— 页面看着"空"却没人报错，那是把旗标写死成 1 的代价。
const 参 = new URLSearchParams(location.search);
const 要跑 = parseInt(参.get('run') || '0', 10);
if (要跑 > 0) {
  const 例 = [
    '列一下当前目录，按大小排，再统计最大的那个文件有多少行',
    '用 flaky 演重试，前 2 次要失败',
    '取一下 https://example.com/robots.txt',
    '把结论存成笔记「今天.md」',
    '现在几点了',
  ];
  let i = 0;
  const 接 = () => {
    if (i >= Math.min(要跑, 例.length)) return;
    const t = 例[i++];
    发(t).then(() => setTimeout(接, 320));
  };
  接();
}
