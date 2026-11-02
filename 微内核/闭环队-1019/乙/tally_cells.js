// 清点两份历史账本：49 格里哪几格从没被填过
// 用法: node tally_cells.js <账本1> <账本2> ...
const fs = require('fs');

const files = process.argv.slice(2);
const perFile = {};

for (const f of files) {
  const raw = fs.readFileSync(f, 'utf8');
  const lines = raw.split('\n').filter(l => l.trim() !== '');
  const st = {
    path: f, lines: lines.length, header: 0, gateLines: 0, badLines: 0, entries: 0,
    sessions: new Set(), calls: new Set(), basisHist: {},
    keys: {} // key(side:key) -> {n, basis:{}, nullPayload:0, emptyPayload:0, nonEmpty:0, samples:[]}
  };
  lines.forEach((l, i) => {
    let o;
    try { o = JSON.parse(l); } catch (e) {
      // 表头行（人读）或坏行
      if (i === 0 && !l.startsWith('{')) { st.header++; return; }
      st.badLines++; return;
    }
    if (o && o.gate !== undefined && o.seq === undefined) { st.gateLines++; return; }
    if (o.seq === undefined || o.kind === undefined) { st.badLines++; return; }
    st.entries++;
    st.sessions.add(o.session);
    st.calls.add(o.session + '#' + o.step + '#' + o.kind.split(':')[0]);
    st.basisHist[o.basis] = (st.basisHist[o.basis] || 0) + 1;
    const k = o.kind;
    if (!st.keys[k]) st.keys[k] = { n: 0, basis: {}, nullPayload: 0, emptyPayload: 0, nonEmpty: 0, filled: 0, emptyStr: 0, samples: [], samplesFilled: [] };
    const kk = st.keys[k];
    kk.n++;
    kk.basis[o.basis] = (kk.basis[o.basis] || 0) + 1;
    if (o.payload_b64 === undefined || o.payload_b64 === null) {
      kk.nullPayload++;
    } else if (o.payload_b64 === '') {
      kk.emptyPayload++;
      if (kk.samples.length < 3) kk.samples.push({ seq: o.seq, basis: o.basis, claim: (o.claim||'').slice(0,60), pb64: '(empty)' });
    } else {
      kk.nonEmpty++;
      let dec = '';
      try { dec = Buffer.from(o.payload_b64, 'base64').toString('utf8'); } catch (e) { dec = '?'; }
      const isEmptyStr = (dec === '""');
      if (isEmptyStr) kk.emptyStr++;
      if (o.basis !== 5 && !isEmptyStr) kk.filled++;
      if ((o.basis !== 5 && !isEmptyStr && kk.samplesFilled.length < 2) || ((o.basis === 5 || isEmptyStr) && kk.samples.length < 3)) {
        (o.basis !== 5 && !isEmptyStr ? kk.samplesFilled : kk.samples).push({ seq: o.seq, basis: o.basis, claim: (o.claim||'').slice(0,60), payload: dec.slice(0, 80) });
      }
    }
  });
  perFile[f] = st;
}

// 49 格权威键表（从 contract.md 第 3 节表抄；call 两侧各一格）
const inputKeys = ['call','parts','part_totals','content_bytes','tokens','call_bytes_ceiling','transport_slack_pct','content_ceiling','effective_ceiling','clamp_rounds','leftover_pct','fixed_overhead','shares','notice_sent','notice_trimmed','notice_why','notice_text','folded','clipped','dropped'];
const outputKeys = ['call','streaming','finish','finish_said','endpoint_model','endpoint_model_said','wire_format','wire_format_said','model_says_bytes','model_says_kept','model_says_clipped','model_says_sha256','usage_in','usage_out','wire_bytes_out','wire_bytes_in','chunks','first_byte_ms','max_gap_ms','tool_calls','malformed_actions','malformed_streak','fail_kind','fail_detail','fail_status','retry_after_ms','downgrade','sent','cost_countable'];

const out = { files: {}, cells: [], extraKinds: {} };
for (const f of files) {
  const st = perFile[f];
  out.files[f] = {
    lines: st.lines, header: st.header, gateLines: st.gateLines, badLines: st.badLines,
    entries: st.entries, sessions: [...st.sessions], shots: st.calls.size, basisHist: st.basisHist
  };
  // 找出账本里出现但不在 49 格表里的 kind
  const known = new Set([...inputKeys.map(k=>'model_input:'+k), ...outputKeys.map(k=>'model_output:'+k)]);
  for (const k of Object.keys(st.keys)) if (!known.has(k)) out.extraKinds[k] = st.keys[k].n;
}

// 逐格判定：filled = 存在 basis!=5 且 payload 非空(非null非"")的条目
for (const [side, keys] of [['input', inputKeys], ['output', outputKeys]]) {
  for (const key of keys) {
    const kind = 'model_' + side + ':' + key;
    const row = { side, key, kind, perFile: {}, everFilled: false, everPresentAsEntry: false };
    for (const f of files) {
      const kk = perFile[f].keys[kind];
      if (!kk) { row.perFile[f] = null; continue; }
      row.everPresentAsEntry = true;
      const basis5 = kk.basis[5] || 0;
      const filled = kk.filled; // basis!=5 且 payload 非空
      row.perFile[f] = { entries: kk.n, basis: kk.basis, nullPayload: kk.nullPayload, emptyPayload: kk.emptyPayload, nonEmptyPayload: kk.nonEmpty, emptyStrPayload: kk.emptyStr, filled, samples: kk.samples, samplesFilled: kk.samplesFilled };
      if (filled > 0) row.everFilled = true;
    }
    out.cells.push(row);
  }
}

fs.writeFileSync('cells_result.json', JSON.stringify(out, null, 1));

// 摘要打印
console.log('=== per-file ===');
for (const f of files) console.log(f, JSON.stringify(out.files[f]));
console.log('=== never-filled cells (49格中两本账都没填过) ===');
let nf = 0;
for (const c of out.cells) {
  if (!c.everFilled) { nf++; console.log(c.kind); }
}
console.log('never-filled count =', nf, '/ 49');
console.log('=== extra kinds not in table ===');
console.log(JSON.stringify(out.extraKinds));
// 分侧计数校验
console.log('input keys:', inputKeys.length, 'output keys:', outputKeys.length, 'total cells:', inputKeys.length + outputKeys.length);
