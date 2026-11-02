(function () {
  'use strict';

  var $ = function (sel, root) { return (root || document).querySelector(sel); };
  var $$ = function (sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); };

  var DELIVERIES = [
    {
      id: 'DLV-1023-0042',
      key: 'real',
      title: '审查 6 行 Python 并给出修法',
      agent: 'pgagent',
      agentSub: 'MiniMax-M2.5 · 真端点',
      repo: 'PDF-1022 / 真端点-1023',
      at: '10-23 21:40',
      wait: '2 小时',
      status: 'warn',
      statusLabel: '核不了',
      statusCode: 'NOT-ACCEPTED-UNVERIFIED',
      rc: 3,
      why: '1 条声明无法回盘核：D3；证据源核不全：pgagent；8 条声明只有交付方自己的产物作证：D1, D2, D4–D9。',
      decidable: true,
      sources: { pgagent: 'warn', agentd: 'ok', journal: 'ok' },
      sourceNote: '3 源 · 1 缺',
      claims: [
        { id: 'D1', kind: 'json_value', cls: 'self', basis: 'relayed', verdict: 'ok', why: '这是本会话的第 1 发', target: 'pgagent-真端点.json#result.turn', expected: '1', actual: '1', detail: '' },
        { id: 'D2', kind: 'json_value', cls: 'self', basis: 'relayed', verdict: 'ok', why: '被审代码被数成 6 行', target: 'pgagent-真端点.json#result.metrics.lines', expected: '6', actual: '6', detail: '' },
        { id: 'D3', kind: 'file_sha256', cls: 'disk', basis: 'absent', verdict: 'absent', why: '交付报出的源码指纹（16 位前缀）', target: '源文件/待审.py', expected: '05bdf4a2f686c85b', actual: null, detail: '文件不存在，读不到内容：源文件/待审.py' },
        { id: 'D4', kind: 'json_len', cls: 'self', basis: 'relayed', verdict: 'ok', why: '找到 1 条问题', target: 'pgagent-真端点.json#result.findings', expected: '1', actual: '1', detail: '' },
        { id: 'D5', kind: 'json_len', cls: 'self', basis: 'relayed', verdict: 'ok', why: '另有 6 条未决', target: 'pgagent-真端点.json#result.unknowns', expected: '6', actual: '6', detail: '' },
        { id: 'D6', kind: 'json_value', cls: 'self', basis: 'relayed', verdict: 'ok', why: '账本有 4 格改写了这一发的结果', target: 'pgagent-真端点.json#result.kpi_ledger_decided', expected: '4', actual: '4', detail: '' },
        { id: 'D7', kind: 'json_value', cls: 'self', basis: 'relayed', verdict: 'ok', why: '13 步整列自洽', target: 'pgagent-真端点.json#result.trace_sane', expected: 'true', actual: 'true', detail: '' },
        { id: 'D8', kind: 'json_value', cls: 'self', basis: 'relayed', verdict: 'ok', why: '跨发账链对得上', target: 'pgagent-真端点.json#result.chain_sane', expected: 'true', actual: 'true', detail: '' },
        { id: 'D9', kind: 'json_value', cls: 'self', basis: 'relayed', verdict: 'ok', why: '五档加总 7 条', target: 'pgagent-真端点.json#result.provenance_mix.total', expected: '7', actual: '7', detail: '' }
      ],
      relayed: [
        { k: 'trace_sane', v: 'true' },
        { k: 'chain_sane', v: 'true' },
        { k: 'kpi_ledger_decided', v: '4' },
        { k: 'mix_identity_ok', v: 'true' }
      ],
      receipt: { generated: '2026-10-26 01:52', tool: '7994b666…', spec: 'e1fce41a…', landing: '9/9 rows OK', note: '源码未随交付提交' },
      decision: null
    },
    {
      id: 'DLV-1026-0007',
      key: 'good',
      title: '修复均值函数并补 3 条测试',
      agent: '示例 Agent',
      agentSub: '好交付样例',
      repo: '示例-编程 / 工作区',
      at: '01:52',
      wait: '18 分钟',
      status: 'ok',
      statusLabel: '可收',
      statusCode: 'ACCEPTED',
      rc: 0,
      why: '每条声明都由盘上证据复核通过，且没有仅凭自报的项。',
      decidable: true,
      sources: { pgagent: 'ok', agentd: 'ok', journal: 'ok' },
      sourceNote: '3 源全绿',
      claims: [
        { id: 'C1', kind: 'file_sha256', cls: 'disk', basis: 'measured', verdict: 'ok', why: '修好的文件指纹', target: '工作区/calc.py', expected: 'e5e1efde…4f640', actual: 'e5e1efde…4f640', detail: '64 位全量一致' },
        { id: 'C2', kind: 'file_contains', cls: 'disk', basis: 'measured', verdict: 'ok', why: '空列表分支已补上', target: '工作区/calc.py:3', expected: 'if not xs:', actual: '第 3 行命中', detail: '' },
        { id: 'C3', kind: 'log_exit', cls: 'disk', basis: 'measured', verdict: 'ok', why: '测试进程正常退出', target: '工作区/test.log', expected: '0', actual: 'exit_code=0', detail: '' },
        { id: 'C4', kind: 'log_contains', cls: 'disk', basis: 'measured', verdict: 'ok', why: '日志报告 1 件通过', target: '工作区/test.log', expected: 'OK · 1 件', actual: '末行命中', detail: '' },
        { id: 'C5', kind: 'file_absent', cls: 'disk', basis: 'measured', verdict: 'ok', why: '调试文件未残留', target: '工作区/debug.log', expected: '不存在', actual: '确认不存在', detail: '' },
        { id: 'C6', kind: 'file_bytes', cls: 'disk', basis: 'measured', verdict: 'ok', why: '输入文件字节数', target: '工作区/input.txt', expected: '99', actual: '99', detail: '' },
        { id: 'C7', kind: 'file_lines', cls: 'disk', basis: 'measured', verdict: 'ok', why: '输入文件行数', target: '工作区/input.txt', expected: '4', actual: '4', detail: '' },
        { id: 'C8', kind: 'log_contains', cls: 'disk', basis: 'measured', verdict: 'ok', why: '确实跑了 3 条测试', target: '工作区/test.log', expected: 'Ran 3 tests', actual: '命中', detail: '' }
      ],
      relayed: [],
      receipt: { generated: '2026-10-26 01:52', tool: '7994b666…', spec: '样例声明', landing: '8/8 rows OK', note: '示例工作区未交付源码审查' },
      decision: 'accepted'
    },
    {
      id: 'DLV-1026-0008',
      key: 'liar',
      title: '同一声明，盘上未改',
      agent: '示例 Agent',
      agentSub: '谎报样例',
      repo: '示例-编程-谎报 / 工作区',
      at: '01:52',
      wait: '16 分钟',
      status: 'bad',
      statusLabel: '需退',
      statusCode: 'NOT-ACCEPTED-MISMATCH',
      rc: 2,
      why: '5 条声明与盘上事实不符：C1, C2, C3, C4, C5。3 条真话仍绿。',
      decidable: true,
      sources: { pgagent: 'ok', agentd: 'ok', journal: 'ok' },
      sourceNote: '3 源全绿',
      claims: [
        { id: 'C1', kind: 'file_sha256', cls: 'disk', basis: 'measured', verdict: 'bad', why: '修好的文件指纹', target: '工作区/calc.py', expected: 'e5e1efde…4f640', actual: '13e046f5…463208', detail: '文件没有改' },
        { id: 'C2', kind: 'file_contains', cls: 'disk', basis: 'measured', verdict: 'bad', why: '空列表分支已补上', target: '工作区/calc.py:3', expected: 'if not xs:', actual: 'return sum(xs) / len(xs)', detail: '第 3 行仍是旧实现' },
        { id: 'C3', kind: 'log_exit', cls: 'disk', basis: 'measured', verdict: 'bad', why: '测试进程正常退出', target: '工作区/test.log', expected: '0', actual: 'exit_code=1', detail: '' },
        { id: 'C4', kind: 'log_contains', cls: 'disk', basis: 'measured', verdict: 'bad', why: '日志报告 1 件通过', target: '工作区/test.log', expected: 'OK · 1 件', actual: 'OK · 0 件', detail: '' },
        { id: 'C5', kind: 'file_absent', cls: 'disk', basis: 'measured', verdict: 'bad', why: '调试文件未残留', target: '工作区/debug.log', expected: '不存在', actual: '存在：27 字节', detail: '' },
        { id: 'C6', kind: 'file_bytes', cls: 'disk', basis: 'measured', verdict: 'ok', why: '输入文件字节数', target: '工作区/input.txt', expected: '43', actual: '43', detail: '' },
        { id: 'C7', kind: 'file_lines', cls: 'disk', basis: 'measured', verdict: 'ok', why: '输入文件行数', target: '工作区/input.txt', expected: '2', actual: '2', detail: '' },
        { id: 'C8', kind: 'log_contains', cls: 'disk', basis: 'measured', verdict: 'ok', why: '确实跑了 3 条测试', target: '工作区/test.log', expected: 'Ran 3 tests', actual: '命中', detail: '' }
      ],
      relayed: [],
      receipt: { generated: '2026-10-26 01:52', tool: '7994b666…', spec: '样例声明', landing: '8/8 rows OK', note: '同一份声明，盘上未改' },
      decision: 'returned',
      reason: '声明与盘上不符'
    },
    {
      id: 'DLV-1020-0113',
      key: 'hub',
      title: '13 题业务回归 · 第 41 发',
      agent: 'AgentHub',
      agentSub: 'hubd · 长窗',
      repo: 'AgentHub-1021 / 读数',
      at: '01:12 起',
      wait: '进行中',
      status: 'processing',
      statusLabel: '处理中',
      statusCode: 'RUNNING',
      rc: null,
      why: '正在只读核对 13 题的发位与判据；当前 7/13，尚未生成回执。',
      decidable: false,
      sources: { pgagent: 'warn', agentd: 'ok', journal: 'off' },
      sourceNote: '进行中 · 2 源',
      claims: [],
      relayed: [],
      receipt: { generated: '—', tool: '—', spec: '—', landing: '—', note: '尚未落回执' }
    },
    {
      id: 'DLV-1018-0294',
      key: 'journal',
      title: '客服靶场账本导出 · 2940 条',
      agent: 'agentd',
      agentSub: '事件层 · 形状样例',
      repo: '构建-1017 / 客服靶场',
      at: '10-23',
      wait: '3 天',
      status: 'ok',
      statusLabel: '可收',
      statusCode: 'ACCEPTED',
      rc: 0,
      why: 'seal 2940/2940 重算通过；60 组 × 49 格，20 入 / 29 出。',
      decidable: true,
      sources: { pgagent: 'off', agentd: 'ok', journal: 'ok' },
      sourceNote: '2 源 · 1 不涉及',
      claims: [
        { id: 'J2', kind: 'file_lines', cls: 'disk', basis: 'measured', verdict: 'ok', why: '账本记录条数', target: '账本-全量-1018.jsonl', expected: '2940', actual: '2940', detail: '表头行单独计' },
        { id: 'J4', kind: 'file_sha256', cls: 'disk', basis: 'measured', verdict: 'ok', why: 'seal 逐条重算', target: '账本-全量-1018.jsonl', expected: '2940/2940', actual: '2940/2940', detail: '' },
        { id: 'J8', kind: 'json_len', cls: 'disk', basis: 'measured', verdict: 'ok', why: '49 格分组', target: '账本-全量-1018.jsonl#groups', expected: '60 组 × 49 格', actual: '60 × 49', detail: '20 入 / 29 出' }
      ],
      relayed: [],
      receipt: { generated: '2026-10-23', tool: '对账单 1.0', spec: '形状样例', landing: '3/3 rows OK', note: '与本交付无因果关系' },
      decision: 'archived'
    },
    {
      id: 'DLV-1026-0009',
      key: 'pending',
      title: '新交付 · 声明尚未生成',
      agent: '未署名',
      agentSub: '等待导入',
      repo: '—',
      at: '刚刚',
      wait: '刚刚',
      status: 'warn',
      statusLabel: '待核',
      statusCode: 'NO-CLAIMS',
      rc: null,
      why: '交付方尚未生成机器可核的声明；没有可核对象，不能当作通过。',
      decidable: false,
      sources: { pgagent: 'off', agentd: 'off', journal: 'off' },
      sourceNote: '0 源 · 未导入',
      claims: [],
      relayed: [],
      receipt: { generated: '—', tool: '—', spec: '—', landing: '—', note: '没有声明可核' }
    }
  ];

  var state = {
    screen: 'queue',
    filter: 'all',
    q: '',
    demo: 'normal',
    current: null,
    modal: null
  };

  function statusClass(s) {
    if (s === 'ok') return 'ok';
    if (s === 'bad') return 'bad';
    if (s === 'processing') return 'unk';
    return 'warn';
  }

  function basisText(b) {
    return b === 'measured' ? '实量' : b === 'relayed' ? '转述' : '缺席';
  }

  function verdictText(v) {
    return v === 'ok' ? 'MATCH' : v === 'bad' ? 'MISMATCH' : v === 'absent' ? 'ABSENT' : '进行中';
  }

  function verdictClass(v) {
    return v === 'ok' ? 'ok' : v === 'bad' ? 'bad' : v === 'absent' ? 'absent' : 'unk';
  }

  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function counts() {
    var c = { ok: 0, bad: 0, warn: 0, processing: 0 };
    DELIVERIES.forEach(function (d) {
      if (d.status === 'processing') c.processing++;
      else if (d.status === 'ok') c.ok++;
      else if (d.status === 'bad') c.bad++;
      else c.warn++;
    });
    return c;
  }

  function refreshCounts() {
    var mode = state.demo;
    var c = counts();
    $$('[data-count]').forEach(function (el) {
      var k = el.getAttribute('data-count');
      el.textContent = mode === 'normal' ? (c[k] || 0) : mode === 'empty' ? '0' : '—';
    });
    $$('[data-chip-count]').forEach(function (el) {
      var k = el.getAttribute('data-chip-count');
      el.textContent = mode === 'normal' ? (k === 'all' ? DELIVERIES.length : (c[k] || 0)) : mode === 'empty' ? '0' : '—';
    });
    var nav = $('#navQueueCount');
    if (nav) nav.textContent = mode === 'normal' ? String(DELIVERIES.length) : mode === 'empty' ? '0' : '—';
    var sub = $('#queueSub');
    if (sub) {
      sub.textContent = mode === 'normal'
        ? DELIVERIES.length + ' 单 · ' + c.warn + ' 单核不了 · ' + c.bad + ' 单需退'
        : mode === 'empty' ? '0 单 · 队列已空'
        : mode === 'loading' ? '读取中…' : '读取失败 · 证据根不可读';
    }
    var hist = $('#navHistoryCount');
    if (hist) hist.textContent = String($$('.history-row[data-delivery]').length);
  }

  function syncHistory() {
    $$('.history-row[data-delivery]').forEach(function (row) {
      var key = row.getAttribute('data-delivery');
      var d = DELIVERIES.filter(function (x) { return x.key === key; })[0];
      var el = row.querySelector('.h-decision');
      if (!d || !el) return;
      if (d.decision === 'accepted') el.textContent = d.status === 'warn' ? '已收下 · 仍核不了' : '已收下';
      else if (d.decision === 'returned') el.textContent = '已退回';
      else if (d.decision === 'archived') el.textContent = '已归档';
      else el.textContent = '未决定';
    });
  }

  function barsHTML(d) {
    if (!d.claims.length) {
      return '<div class="mini-bars" aria-hidden="true"><i></i><i></i><i></i><i></i><i></i></div>';
    }
    return '<div class="mini-bars" aria-hidden="true">' + d.claims.map(function (c) {
      var cls = c.verdict === 'ok' ? 'ok' : c.verdict === 'bad' ? 'bad' : 'absent';
      return '<i class="' + cls + '"></i>';
    }).join('') + '</div>';
  }

  function sourcePips(d) {
    var map = { pgagent: 'P', agentd: 'E', journal: 'J' };
    return '<div class="source-pips" aria-hidden="true">' + Object.keys(map).map(function (k) {
      var s = d.sources[k];
      var cls = s === 'ok' ? 'ok' : s === 'bad' ? 'bad' : s === 'warn' ? 'warn' : '';
      return '<i class="' + cls + '" title="' + esc(k) + ': ' + esc(s) + '">' + map[k] + '</i>';
    }).join('') + '</div>';
  }

  function rowsForQueue() {
    var q = state.q.trim().toLowerCase();
    return DELIVERIES.filter(function (d) {
      var f = state.filter;
      var okFilter = f === 'all' ||
        (f === 'ok' && d.status === 'ok') ||
        (f === 'bad' && d.status === 'bad') ||
        (f === 'warn' && d.status === 'warn') ||
        (f === 'processing' && d.status === 'processing');
      if (!okFilter) return false;
      if (!q) return true;
      return (d.id + ' ' + d.title + ' ' + d.agent + ' ' + d.repo).toLowerCase().indexOf(q) >= 0;
    });
  }

  function rowHTML(d) {
    var counts = { ok: 0, bad: 0, absent: 0 };
    d.claims.forEach(function (c) {
      if (c.verdict === 'ok') counts.ok++;
      else if (c.verdict === 'bad') counts.bad++;
      else counts.absent++;
    });
    var claimsLine;
    if (!d.claims.length) {
      claimsLine = d.key === 'pending' ? '0 条 · 尚未生成' : '— · 核对中';
    } else {
      claimsLine = '<b>' + d.claims.length + '</b> 条 · ' + counts.ok + ' 过' +
        (counts.bad ? ' / ' + counts.bad + ' 不符' : '') +
        (counts.absent ? ' / ' + counts.absent + ' 缺席' : '');
    }
    return '' +
      '<tr data-open="' + esc(d.id) + '" tabindex="0">' +
        '<td class="d-main">' +
          '<div class="d-id"><span class="mono">' + esc(d.id) + '</span>' + (d.key === 'real' || d.key === 'good' || d.key === 'liar' ? '<span class="badge plain" style="font-size:8.5px;padding:0 4px">实测回执</span>' : '<span class="badge plain" style="font-size:8.5px;padding:0 4px">演示占位</span>') + '</div>' +
          '<div class="d-title">' + esc(d.title) + '</div>' +
          '<div class="d-sub">' + esc(d.repo) + '</div>' +
        '</td>' +
        '<td><div class="agent-cell"><div class="agent-mark">' + esc(d.agent.slice(0, 2)) + '</div><div><b>' + esc(d.agent) + '</b><small>' + esc(d.agentSub) + '</small></div></div></td>' +
        '<td class="claims-cell"><div class="c-line">' + claimsLine + '</div>' + barsHTML(d) + '</td>' +
        '<td><span class="badge ' + statusClass(d.status) + '"><span class="dot"></span>' + esc(d.statusLabel) + '</span></td>' +
        '<td class="sources-cell">' + sourcePips(d) + '<small>' + esc(d.sourceNote) + '</small></td>' +
        '<td class="wait-cell"><div class="w1">' + esc(d.wait) + '</div><div class="w2">' + esc(d.at) + '</div></td>' +
        '<td><span class="row-cta">' + (d.decidable ? '核对' : '查看') + ' <svg><use href="#i-arrow"/></svg></span></td>' +
      '</tr>';
  }

  function stateBox(kind) {
    if (kind === 'loading') {
      var rows = '';
      for (var i = 0; i < 5; i++) {
        rows += '<div class="skeleton-row"><span class="sk t1"></span><span class="sk t2"></span><span class="sk t3"></span><span class="sk t4"></span></div>';
      }
      return '<div aria-label="读取中">' + rows + '</div>';
    }
    if (kind === 'empty') {
      return '<div class="state-box"><div class="state-icon"><svg><use href="#i-queue"/></svg></div><h3>队列是空的</h3><p>没有待核对的交付。把 Agent 的交付声明拖进来，或让它按模板自动生成。</p><button class="btn primary" data-import>导入交付声明…</button></div>';
    }
    return '<div class="state-box error"><div class="state-icon"><svg><use href="#i-alert"/></svg></div><h3>读取失败</h3><p>证据根不可读：<span class="mono">~/Desktop/微内核</span>。检查路径后重试；本件不会联网寻找替代源。</p><button class="btn" data-retry>重试读取</button></div>';
  }

  function renderQueue() {
    var table = $('#queueBody');
    var stateEl = $('#queueState');
    var foot = $('#queueFootCount');
    if (state.demo !== 'normal') {
      table.hidden = true;
      stateEl.hidden = false;
      stateEl.innerHTML = stateBox(state.demo);
      foot.textContent = state.demo === 'empty' ? '0 / 0 单' : '—';
      refreshCounts();
      return;
    }
    table.hidden = false;
    stateEl.hidden = true;
    var rows = rowsForQueue();
    var tbody = $('#queueRows');
    if (!rows.length) {
      tbody.innerHTML = '<tr><td colspan="7"><div class="state-box" style="padding:36px"><div class="state-icon"><svg><use href="#i-search"/></svg></div><h3>没有符合条件的单</h3><p>换个筛选或清空搜索。</p></div></td></tr>';
    } else {
      tbody.innerHTML = rows.map(rowHTML).join('');
    }
    foot.textContent = rows.length + ' / ' + DELIVERIES.length + ' 单';
    refreshCounts();
  }

  function detailMetaHTML(d) {
    return '' +
      '<span><svg><use href="#i-link"/></svg><span class="mono">' + esc(d.id) + '</span></span>' +
      '<span><svg><use href="#i-terminal"/></svg>' + esc(d.agent) + '</span>' +
      '<span><svg><use href="#i-clock"/></svg>' + esc(d.at) + '</span>' +
      '<span><svg><use href="#i-file"/></svg>' + esc(d.repo) + '</span>';
  }

  function bannerFor(d) {
    var cls = d.status === 'ok' ? 'ok' : d.status === 'bad' ? 'bad' : '';
    var title = d.status === 'ok' ? '可收' : d.status === 'bad' ? '需退' : d.status === 'processing' ? '处理中' : d.statusLabel === '待核' ? '待核' : '核不了';
    return {
      cls: cls,
      title: title,
      code: d.statusCode,
      rc: d.rc == null ? '' : 'rc ' + d.rc,
      icon: d.status === 'ok' ? 'i-check' : d.status === 'processing' ? 'i-clock' : 'i-alert'
    };
  }

  function claimRowHTML(c, d) {
    var expected = c.expected == null ? '—' : String(c.expected);
    var actual = c.actual == null ? '—' : String(c.actual);
    var ev;
    if (c.verdict === 'absent') {
      ev = '<div class="ev-line bad"><span class="lbl">盘上</span><span class="val">读不到</span></div><div class="ev-note">' + esc(c.detail || '缺席，原因未写') + '</div>';
    } else if (c.verdict === 'bad') {
      ev = '<div class="ev-line"><span class="lbl">期望</span><span class="val">' + esc(expected) + '</span></div><div class="ev-line bad"><span class="lbl">盘上</span><span class="val">' + esc(actual) + '</span></div>';
    } else {
      ev = '<div class="ev-line"><span class="lbl">值</span><span class="val">' + esc(actual) + '</span></div>' + (c.detail ? '<div class="ev-note">' + esc(c.detail) + '</div>' : '');
    }
    return '' +
      '<tr data-claim="' + esc(c.id) + '" tabindex="0">' +
        '<td><div class="claim-id"><span>' + esc(c.id) + '</span><span class="kind-chip">' + esc(c.kind) + '</span></div></td>' +
        '<td><div class="claim-why">' + esc(c.why) + '</div><div class="claim-where">' + esc(c.target) + '</div></td>' +
        '<td><span class="verdict ' + verdictClass(c.verdict) + '"><span class="dot"></span>' + verdictText(c.verdict) + '</span></td>' +
        '<td><span class="basis-chip ' + esc(c.basis) + '">' + basisText(c.basis) + '</span></td>' +
        '<td class="evidence-cell">' + ev + '</td>' +
      '</tr>';
  }

  function sourceListHTML(d) {
    var meta = {
      pgagent: { name: 'pgagent 轨迹', note: d.key === 'real' ? 'P10 缺席：源码未随交付提交' : d.key === 'hub' ? '本单无关联轨迹' : 'P0–P10 已核' },
      agentd: { name: 'agentd 事件层', note: d.key === 'real' ? 'E1–E8 · 会话 real-agentd-1' : 'E1–E8 · 结构自洽' },
      journal: { name: '内核账本', note: d.key === 'journal' ? 'seal 2940/2940 · 60 × 49' : 'J0–J9 · 形状样例' }
    };
    return ['pgagent', 'agentd', 'journal'].map(function (k) {
      var s = d.sources[k];
      var cls = s === 'ok' ? 'ok' : s === 'bad' ? 'bad' : s === 'warn' ? 'warn' : 'off';
      var label = s === 'ok' ? 'GREEN' : s === 'bad' ? 'RED' : s === 'warn' ? 'ABSENT' : 'NOT-USED';
      return '<button class="evidence-item" data-src="' + k + '">' +
        '<span class="e-dot ' + cls + '"></span>' +
        '<span class="e-body"><b>' + meta[k].name + '</b><small>' + esc(meta[k].note) + '</small></span>' +
        '<span class="e-state ' + (cls === 'off' ? '' : cls) + '">' + label + '</span>' +
      '</button>';
    }).join('');
  }

  function renderDetail(d) {
    state.current = d;
    $('#crumbId').textContent = d.id;
    $('#detailTitle').textContent = d.title;
    $('#detailMeta').innerHTML = detailMetaHTML(d);
    var b = bannerFor(d);
    var banner = $('#statusBanner');
    banner.className = 'status-banner ' + b.cls;
    $('.s-icon svg use', banner).setAttribute('href', '#' + b.icon);
    $('#bannerTitle').textContent = b.title;
    $('#bannerCode').textContent = b.code;
    $('#bannerRc').textContent = b.rc;
    $('#bannerRc').style.display = b.rc ? '' : 'none';
    $('#bannerWhy').textContent = d.why;

    var disk = d.claims.filter(function (c) { return c.cls === 'disk'; }).length;
    var self = d.claims.length - disk;
    $('#claimCount').textContent = d.claims.length + ' 条';
    $('#claimMix').textContent = disk + ' 盘上 / ' + self + ' 自报';

    var tbody = $('#claimRows');
    if (!d.claims.length) {
      tbody.innerHTML = '<tr><td colspan="5"><div class="state-box" style="padding:34px"><div class="state-icon"><svg><use href="#i-file"/></svg></div><h3>' + (d.key === 'pending' ? '没有可核声明' : '正在逐条核对') + '</h3><p>' + esc(d.why) + '</p></div></td></tr>';
    } else {
      tbody.innerHTML = d.claims.map(function (c) { return claimRowHTML(c, d); }).join('');
    }
    $('#claimFoot').textContent = d.claims.length + ' / ' + d.claims.length + ' 行';

    $('#evidenceList').innerHTML = sourceListHTML(d);

    var facts = d.receipt;
    $('#receiptFacts').innerHTML = '' +
      '<div><dt>生成</dt><dd>' + esc(facts.generated) + '</dd></div>' +
      '<div><dt>工具</dt><dd>' + esc(facts.tool) + '</dd></div>' +
      '<div><dt>声明</dt><dd>' + esc(facts.spec) + '</dd></div>' +
      '<div><dt>落盘</dt><dd>' + esc(facts.landing) + '</dd></div>';

    var relayed = $('#relayedCard');
    if (d.relayed.length) {
      relayed.hidden = false;
      $('#relayedList').innerHTML = d.relayed.map(function (r) {
        return '<li><span class="k">' + esc(r.k) + '</span><span class="tag">转述</span><span class="v">' + esc(r.v) + '</span></li>';
      }).join('');
    } else {
      relayed.hidden = true;
    }

    var accept = $('#acceptBtn');
    var ret = $('#returnBtn');
    var mustReturn = d.status === 'bad';
    accept.disabled = !d.decidable || mustReturn;
    ret.disabled = !d.decidable;
    accept.title = mustReturn ? '有声明与盘上不符，整单必须退回' : '';

    var note = $('#decisionNote');
    if (note) {
      note.textContent = !d.decidable
        ? (d.key === 'pending' ? '没有可核对的声明，收 / 退都无从谈起；先让交付方补齐声明。' : '只读核对尚未完成，出回执前不能决定。')
        : mustReturn ? '有声明与盘上事实不符（MISMATCH），按规则整单必须退回；不能收下。'
        : d.status === 'warn' ? '收下 = 记录决定并保留核不了结论；历史与回执仍标 UNVERIFIED，不会变成通过。'
        : '收下 = 把决定写进回执；它不为代码质量或测试充分性背书。';
    }

    var ds = $('#decisionState');
    if (d.decision === 'accepted') {
      ds.innerHTML = '<div class="decision-state"><svg style="width:13px;height:13px"><use href="#i-check"/></svg>已收下 · 决定已写进回执（样例）</div>';
    } else if (d.decision === 'returned') {
      ds.innerHTML = '<div class="decision-state bad"><svg style="width:13px;height:13px"><use href="#i-x"/></svg>已退回：' + esc(d.reason || '未填理由') + '</div>';
    } else if (!d.decidable) {
      ds.innerHTML = '<div class="decision-state" style="background:var(--unk-bg);border-color:var(--unk-line);color:var(--unk)"><svg style="width:13px;height:13px"><use href="#i-clock"/></svg>' + (d.key === 'pending' ? '没有声明，无法收 / 退' : '核对中，暂不能决定') + '</div>';
    } else {
      ds.innerHTML = '';
    }
  }

  function navigate(screen) {
    state.screen = screen;
    $$('.screen').forEach(function (s) { s.classList.toggle('is-active', s.id === 'screen-' + screen); });
    $$('.nav-item').forEach(function (b) {
      var target = b.getAttribute('data-nav');
      var active = target === screen || (screen === 'detail' && target === 'queue');
      if (active) b.setAttribute('aria-current', 'page');
      else b.removeAttribute('aria-current');
    });
    $('#main').scrollTop = 0;
    if (screen === 'queue') renderQueue();
  }

  function openDetail(id) {
    var d = DELIVERIES.filter(function (x) { return x.id === id || x.key === id; })[0];
    if (!d) return;
    renderDetail(d);
    navigate('detail');
  }

  /* ---------- drawer ---------- */

  function codeTable(lines, hit) {
    return '<pre class="code"><table>' + lines.map(function (line, i) {
      var n = i + 1;
      return '<tr' + (hit === n ? ' class="hit"' : '') + '><td class="ln">' + n + '</td><td>' + esc(line) + '</td></tr>';
    }).join('') + '</table></pre>';
  }

  function metaRow(d, c) {
    return '<div class="evidence-meta">' +
      '<span>声明 <b class="mono">' + esc(c.id) + '</b></span>' +
      '<span>kind <b class="mono">' + esc(c.kind) + '</b></span>' +
      '<span>依据档 <b class="mono">' + esc(c.basis) + '</b></span>' +
      '<span>来源 <b class="mono">' + (c.cls === 'disk' ? '盘上' : '交付方自报') + '</b></span>' +
    '</div>';
  }

  function paneNotApplicable(what) {
    return '<div class="state-box" style="padding:28px 12px"><div class="state-icon"><svg><use href="#i-info"/></svg></div><h3>这一类证据不涉及本声明</h3><p>本声明核对的是' + esc(what) + '；抽屉只展示回执登记过的证据。</p></div>';
  }

  function filePane(c) {
    if (c.verdict === 'absent') {
      return metaRow(null, c) +
        '<div class="absent-box"><div class="a-title">ABSENT · 读不到</div><p>' + esc(c.detail || '文件不存在，读不到内容。') + '</p></div>' +
        '<p class="drawer-note">缺席不是 0，也不是通过。回执会保留这条缺席及原因；收下这单也不会把它改成 MATCH。</p>';
    }
    if (c.kind === 'file_contains') {
      var lines = ['def mean(xs):', '    if not xs:', '        return 0', '    return sum(xs) / len(xs)'];
      if (c.verdict === 'bad') lines = ['def mean(xs):', '    # TODO: handle empty list', '    return sum(xs) / len(xs)'];
      return metaRow(null, c) +
        codeTable(lines, c.verdict === 'bad' ? 3 : 2) +
        '<p class="drawer-note">命中行已高亮；文本按 UTF-8 读取，行号从 1 起。</p>';
    }
    return metaRow(null, c) +
      '<div class="evidence-meta" style="margin-bottom:0">' +
        '<span>路径 <b class="mono">' + esc(c.target) + '</b></span>' +
        '<span>期望 <b class="mono">' + esc(c.expected == null ? '—' : c.expected) + '</b></span>' +
        '<span>盘上 <b class="mono">' + esc(c.actual == null ? '—' : c.actual) + '</b></span>' +
      '</div>' +
      '<p class="drawer-note">' + esc(c.detail || '值与声明一致。') + '</p>';
  }

  function logPane(c) {
    if (c.kind !== 'log_exit' && c.kind !== 'log_contains') return paneNotApplicable('文件或 JSON 值');
    var tail = ['Ran 3 tests in 0.041s', '', 'OK · 1 件', c.verdict === 'bad' ? 'exit_code=1' : 'exit_code=0'];
    return metaRow(null, c) + codeTable(tail, c.kind === 'log_exit' ? 4 : 3) +
      '<p class="drawer-note">log_exit 只认最后一行 <span class="mono">exit_code=N</span>；找不到这一行记 ABSENT，不当 0。</p>';
  }

  function tracePane(c) {
    if (c.kind !== 'json_value' && c.kind !== 'json_len') return paneNotApplicable('文件、日志或账本');
    var path = c.target.split('#')[0];
    var key = c.target.split('#')[1] || '';
    return metaRow(null, c) +
      '<pre class="code"><table>' +
        '<tr><td class="ln">1</td><td>{</td></tr>' +
        '<tr><td class="ln">2</td><td>  "result": {</td></tr>' +
        '<tr class="hit"><td class="ln">3</td><td>    "' + esc(key.split('.').slice(-1)[0]) + '": ' + esc(c.actual) + '</td></tr>' +
        '<tr><td class="ln">4</td><td>  }</td></tr>' +
        '<tr><td class="ln">5</td><td>}</td></tr>' +
      '</table></pre>' +
      '<p class="drawer-note">来自 <span class="mono">' + esc(path) + '</span>。这是交付方的轨迹产物，依据档仍是转述；本件不重算模型行为。</p>';
  }

  function journalPane(c, d) {
    var cells = '';
    for (var i = 0; i < 49; i++) {
      var cls = (i % 7 === 3 || i === 21 || i === 34) ? ' ok' : '';
      cells += '<span class="cell' + cls + '"></span>';
    }
    return metaRow(null, c) +
      '<div class="evidence-meta" style="margin-bottom:10px"><span>seal <b class="mono">2940 / 2940</b></span><span>分组 <b class="mono">60</b></span><span>每格 <b class="mono">49</b></span></div>' +
      '<div class="cellgrid" aria-hidden="true">' + cells + '</div>' +
      '<p class="drawer-note">49 格结构自洽（20 入 / 29 出）；本件只核形状，不核每格内容对不对。' + (d.key === 'journal' ? '' : '此账本为形状样例，与本交付无因果关系。') + '</p>';
  }

  function openDrawer(claim) {
    var d = state.current;
    $('#drawerKicker').textContent = claim.id + ' · ' + claim.kind + ' · ' + verdictText(claim.verdict);
    $('#drawerTitle').textContent = claim.why;
    $('#drawerSub').textContent = claim.target;
    $('#pane-file').innerHTML = filePane(claim);
    $('#pane-log').innerHTML = logPane(claim);
    $('#pane-event').innerHTML = tracePane(claim);
    $('#pane-journal').innerHTML = journalPane(claim, d);
    var defaultPane = claim.kind.indexOf('log_') === 0 ? 'log' : claim.kind.indexOf('json_') === 0 ? 'event' : 'file';
    setDrawerTab(defaultPane);
    $('#drawer').classList.add('is-open');
    $('#drawer').setAttribute('aria-hidden', 'false');
    $('#overlay').classList.add('is-open');
    $('#drawerClose').focus();
  }

  function setDrawerTab(pane) {
    $$('.drawer-tab').forEach(function (t) {
      var on = t.getAttribute('data-pane') === pane;
      t.classList.toggle('is-on', on);
      t.setAttribute('aria-selected', on ? 'true' : 'false');
    });
    $$('.drawer-pane').forEach(function (p) { p.classList.toggle('is-on', p.id === 'pane-' + pane); });
  }

  function closeDrawer() {
    $('#drawer').classList.remove('is-open');
    $('#drawer').setAttribute('aria-hidden', 'true');
    $('#overlay').classList.remove('is-open');
  }

  /* ---------- modal ---------- */

  function openModal(mode) {
    var d = state.current;
    if (!d || !d.decidable) return;
    if (mode === 'accept' && d.status === 'bad') { toast('有 MISMATCH 的交付必须退回', true); return; }
    state.modal = mode;
    var isReturn = mode === 'return';
    $('#decisionTitle').textContent = isReturn ? '退回这版交付？' : '收下这版交付？';
    $('#decisionSub').textContent = isReturn
      ? '退单必须写理由；理由会写进回执，交付方与后来人都能看到。'
      : '把决定写进回执；后续任何人都能看见当时凭什么收。';
    $('#acceptBody').hidden = isReturn;
    $('#returnBody').hidden = !isReturn;
    $('#modalConfirm').textContent = isReturn ? '确认退回' : '确认收下';
    $('#modalConfirm').className = 'btn ' + (isReturn ? 'danger' : 'accent');
    $('#reasonInput').value = '';
    $$('.reason-chip').forEach(function (c) { c.classList.remove('is-on'); });
    var disk = d.claims.filter(function (c) { return c.cls === 'disk'; }).length;
    $('#modalStatus').textContent = d.statusCode;
    $('#modalClaims').textContent = d.claims.length + ' 条';
    $('#modalMeasured').textContent = disk;
    $('#modalRelayed').textContent = (d.claims.length - disk);
    $('#acceptHint').textContent = d.status === 'ok'
      ? '这一单每条声明都由盘上证据复核通过；收下只确认这一点，不为代码质量背书。'
      : '这单仍有声明无法回盘或与盘上不符。收下只会记录「我知道它核不了」；历史与回执会保持核不了 / 需退状态。';
    updateConfirmState();
    $('#decisionModal').classList.add('is-open');
    setTimeout(function () { (isReturn ? $('#reasonInput') : $('#modalConfirm')).focus(); }, 30);
  }

  function updateConfirmState() {
    if (state.modal !== 'return') {
      $('#modalConfirm').disabled = false;
      return;
    }
    $('#modalConfirm').disabled = $('#reasonInput').value.trim().length === 0;
  }

  function closeModal() {
    $('#decisionModal').classList.remove('is-open');
    state.modal = null;
  }

  function confirmDecision() {
    var d = state.current;
    if (!d || !state.modal) return;
    if (state.modal === 'return') {
      var reason = $('#reasonInput').value.trim();
      if (!reason) return;
      d.decision = 'returned';
      d.reason = reason;
      toast('已退回 · 理由已写入回执（样例）', true);
    } else {
      if (d.status === 'bad') { toast('有 MISMATCH 的交付必须退回', true); return; }
      d.decision = 'accepted';
      toast('已收下 · 决定已写入回执（样例）', false);
    }
    closeModal();
    renderDetail(d);
    syncHistory();
  }

  /* ---------- toast ---------- */

  function toast(msg, bad) {
    var wrap = $('#toastWrap');
    var el = document.createElement('div');
    el.className = 'toast' + (bad ? ' bad' : '');
    el.innerHTML = '<svg><use href="#' + (bad ? 'i-alert' : 'i-check') + '"/></svg><span>' + esc(msg) + '</span>';
    wrap.appendChild(el);
    setTimeout(function () {
      el.style.transition = 'opacity .2s ease';
      el.style.opacity = '0';
      setTimeout(function () { el.remove(); }, 220);
    }, 3200);
  }

  /* ---------- export / copy ---------- */

  function downloadReceipt() {
    var d = state.current;
    if (!d) return;
    var payload = {
      receipt_version: 1,
      prototype: true,
      generated_at: new Date().toISOString(),
      delivery: { id: d.id, title: d.title, agent: d.agent, status: d.statusCode },
      decision: d.decision || 'undecided',
      reason: d.reason || '',
      claims: d.claims.map(function (c) {
        return { id: c.id, kind: c.kind, why: c.why, verdict: verdictText(c.verdict), basis: c.basis, expected: c.expected, actual: c.actual };
      }),
      note: '原型导出的样例回执；未连接真实核对引擎。'
    };
    var blob = new Blob([JSON.stringify(payload, null, 2) + '\n'], { type: 'application/json' });
    var url = URL.createObjectURL(blob);
    var a = document.createElement('a');
    a.href = url;
    a.download = '回执-' + d.id + '-样例.json';
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
    toast('回执已导出（样例）', false);
  }

  function copySummary() {
    var d = state.current;
    if (!d) return;
    var disk = d.claims.filter(function (c) { return c.cls === 'disk'; }).length;
    var txt = d.id + ' ' + d.title + '\n状态：' + d.statusCode + '（' + d.statusLabel + '）\n' +
      '声明：' + d.claims.length + ' 条（盘上 ' + disk + ' / 自报 ' + (d.claims.length - disk) + '）\n' +
      '判定：' + d.why;
    function fallback() {
      var ta = document.createElement('textarea');
      ta.value = txt;
      document.body.appendChild(ta);
      ta.select();
      try { document.execCommand('copy'); toast('摘要已复制', false); }
      catch (e) { toast('复制失败：浏览器拦截了剪贴板', true); }
      ta.remove();
    }
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(txt).then(function () { toast('摘要已复制', false); }, fallback);
    } else fallback();
  }

  /* ---------- events ---------- */

  function bind() {
    $$('[data-nav]').forEach(function (b) {
      b.addEventListener('click', function () {
        var target = b.getAttribute('data-nav');
        if (target === 'detail') return;
        closeDrawer();
        navigate(target);
      });
    });

    $('#queueRows').addEventListener('click', function (e) {
      var tr = e.target.closest('tr[data-open]');
      if (tr) openDetail(tr.getAttribute('data-open'));
    });
    $('#queueRows').addEventListener('keydown', function (e) {
      if (e.key !== 'Enter' && e.key !== ' ') return;
      var tr = e.target.closest('tr[data-open]');
      if (tr) { e.preventDefault(); openDetail(tr.getAttribute('data-open')); }
    });

    $$('#triage .triage-card').forEach(function (card) {
      card.addEventListener('click', function () {
        var f = card.getAttribute('data-filter');
        state.filter = state.filter === f ? 'all' : f;
        syncFilters();
        renderQueue();
      });
    });

    $('#queueChips').addEventListener('click', function (e) {
      var chip = e.target.closest('.chip');
      if (!chip) return;
      state.filter = chip.getAttribute('data-filter');
      syncFilters();
      renderQueue();
    });

    $('#queueSearch').addEventListener('input', function (e) {
      state.q = e.target.value;
      renderQueue();
    });

    $('#demoState').addEventListener('change', function (e) {
      state.demo = e.target.value;
      $('#demoLabel').textContent = '演示状态：' + e.target.options[e.target.selectedIndex].text;
      renderQueue();
    });

    document.addEventListener('click', function (e) {
      if (e.target.closest('[data-retry]')) { state.demo = 'normal'; $('#demoState').value = 'normal'; $('#demoLabel').textContent = '演示状态：正常'; renderQueue(); }
      if (e.target.closest('[data-import]')) toast('导入入口：原型不连接文件系统', false);
    });

    $('#refreshBtn').addEventListener('click', function () {
      state.demo = 'loading';
      $('#demoState').value = 'loading';
      $('#demoLabel').textContent = '演示状态：读取中';
      renderQueue();
      setTimeout(function () {
        state.demo = 'normal';
        $('#demoState').value = 'normal';
        $('#demoLabel').textContent = '演示状态：正常';
        renderQueue();
        toast('已重新读取 6 单（样例）', false);
      }, 900);
    });

    $('#importBtn').addEventListener('click', function () { toast('导入入口：原型不连接文件系统', false); });

    $('#claimRows').addEventListener('click', function (e) {
      var tr = e.target.closest('tr[data-claim]');
      if (!tr || !state.current) return;
      var id = tr.getAttribute('data-claim');
      var claim = state.current.claims.filter(function (c) { return c.id === id; })[0];
      if (claim) openDrawer(claim);
    });
    $('#claimRows').addEventListener('keydown', function (e) {
      if (e.key !== 'Enter' && e.key !== ' ') return;
      var tr = e.target.closest('tr[data-claim]');
      if (!tr) return;
      e.preventDefault();
      tr.click();
    });

    $('#drawerClose').addEventListener('click', closeDrawer);
    $('#overlay').addEventListener('click', closeDrawer);
    $$('.drawer-tab').forEach(function (t) {
      t.addEventListener('click', function () { setDrawerTab(t.getAttribute('data-pane')); });
    });

    $('#evidenceList').addEventListener('click', function (e) {
      var b = e.target.closest('.evidence-item');
      if (!b) return;
      var src = b.getAttribute('data-src');
      var d = state.current;
      var label = src === 'pgagent' ? 'pgagent 轨迹' : src === 'agentd' ? 'agentd 事件层' : '内核账本';
      toast(label + '：' + (d.sources[src] === 'ok' ? 'GREEN' : d.sources[src] === 'warn' ? 'ABSENT' : d.sources[src] === 'bad' ? 'RED' : '未使用'), d.sources[src] === 'bad' || d.sources[src] === 'warn');
    });

    $('#acceptBtn').addEventListener('click', function () { openModal('accept'); });
    $('#returnBtn').addEventListener('click', function () { openModal('return'); });
    $('#modalCancel').addEventListener('click', closeModal);
    $('#modalConfirm').addEventListener('click', confirmDecision);
    $('#decisionModal').addEventListener('click', function (e) { if (e.target === $('#decisionModal')) closeModal(); });

    $('#reasonChips').addEventListener('click', function (e) {
      var chip = e.target.closest('.reason-chip');
      if (!chip) return;
      chip.classList.toggle('is-on');
      var on = $$('.reason-chip.is-on').map(function (x) { return x.textContent; });
      $('#reasonInput').value = on.join('；');
      updateConfirmState();
    });
    $('#reasonInput').addEventListener('input', updateConfirmState);

    $('#exportBtn').addEventListener('click', downloadReceipt);
    $('#copyBtn').addEventListener('click', copySummary);
    $('#historyExport').addEventListener('click', function () { toast('导出全部：原型不写盘', false); });

    $$('.history-row').forEach(function (row) {
      row.addEventListener('click', function () { openDetail(row.getAttribute('data-delivery')); });
    });

    $('#detailBackTop').addEventListener('click', function () { navigate('queue'); });

    $('#expandAllBtn').addEventListener('click', function () {
      var d = state.current;
      if (!d || !d.claims.length) return;
      toast('逐条证据已在右侧抽屉；点任一行展开', false);
    });

    $('#copyTemplate').addEventListener('click', function () {
      toast('模板已复制（样例）', false);
    });

    window.addEventListener('hashchange', applyRoute);

    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') {
        if ($('#decisionModal').classList.contains('is-open')) closeModal();
        else if ($('#drawer').classList.contains('is-open')) closeDrawer();
      }
      var tag = (e.target.tagName || '').toLowerCase();
      if (e.key === '/' && tag !== 'input' && tag !== 'textarea') {
        e.preventDefault();
        if (state.screen !== 'queue') navigate('queue');
        $('#queueSearch').focus();
      }
    });
  }

  function syncFilters() {
    $$('#triage .triage-card').forEach(function (c) {
      var on = c.getAttribute('data-filter') === state.filter;
      c.classList.toggle('is-on', on);
      c.setAttribute('aria-pressed', on ? 'true' : 'false');
    });
    $$('#queueChips .chip').forEach(function (c) {
      c.classList.toggle('is-on', c.getAttribute('data-filter') === state.filter);
    });
  }

  function applyRoute() {
    var h = decodeURIComponent((location.hash || '').replace(/^#/, ''));
    if (!h) return;
    var q = {};
    h.split('&').forEach(function (kv) {
      var p = kv.split('=');
      if (p[0]) q[p[0]] = p.slice(1).join('=');
    });
    if (q.screen) navigate(q.screen);
    if (q.state && q.state !== 'normal') {
      state.demo = q.state;
      var sel = $('#demoState');
      var lbl = $('#demoLabel');
      if (sel) sel.value = q.state;
      if (lbl) lbl.textContent = '演示状态：' + ((sel && sel.options[sel.selectedIndex] || {}).text || q.state);
      navigate('queue');
    }
    var id = q.d || q.id;
    if (id) {
      openDetail(id);
      if (q.claim && state.current) {
        var c = state.current.claims.filter(function (x) { return x.id === q.claim; })[0];
        if (c) {
          openDrawer(c);
          if (q.pane && ['file', 'log', 'event', 'journal'].indexOf(q.pane) >= 0) setDrawerTab(q.pane);
        }
      }
      if (q.modal && !$('#drawer').classList.contains('is-open')) openModal(q.modal);
    }
  }

  function init() {
    refreshCounts();
    bind();
    renderQueue();
    syncHistory();
    navigate('queue');
    applyRoute();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
