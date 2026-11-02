const fs = require('fs');
// argv: L1018path L8799path
const files = { L1018: process.argv[2], L8799: process.argv[3] };
const agg = {};
function blank() { return { n: 0, filled: 0, absent: 0, emptyStr: 0, seqFilled: [], seqAbsent: [], seqEmpty: [] }; }
const shots = { L1018: new Set(), L8799: new Set() };
const meta = {};
for (const tag of Object.keys(files)) {
  const path = files[tag];
  const lines = fs.readFileSync(path, 'utf8').split('\n').filter(l => l.trim());
  let header = 0, entries = 0, bad = 0, gate = 0;
  const basisHist = {};
  for (const l of lines) {
    let o; try { o = JSON.parse(l); } catch (e) { if (!l.startsWith('{')) header++; else bad++; continue; }
    if (o.gate !== undefined && o.seq === undefined) { gate++; continue; }
    if (o.seq === undefined || o.kind === undefined) { bad++; continue; }
    entries++;
    shots[tag].add(o.session + '#' + o.step);
    basisHist[o.basis] = (basisHist[o.basis] || 0) + 1;
    if (!agg[o.kind]) agg[o.kind] = { L1018: blank(), L8799: blank() };
    const a = agg[o.kind][tag]; a.n++;
    let dec = ''; try { dec = Buffer.from(o.payload_b64 || '', 'base64').toString('utf8'); } catch (e) { }
    const isEmptyStr = (dec === '""');
    if (o.basis === 5) { a.absent++; if (a.seqAbsent.length < 3) a.seqAbsent.push(o.seq); }
    else if (isEmptyStr) { a.emptyStr++; if (a.seqEmpty.length < 3) a.seqEmpty.push(o.seq); }
    else { a.filled++; if (a.seqFilled.length < 3) a.seqFilled.push(o.seq); }
  }
  meta[tag] = { path, lines: lines.length, header, entries, bad, gate, basisHist, shots: shots[tag].size };
}
const table = [
  ['input', 'call'], ['input', 'parts'], ['input', 'part_totals'], ['input', 'content_bytes'], ['input', 'tokens'], ['input', 'call_bytes_ceiling'], ['input', 'transport_slack_pct'], ['input', 'content_ceiling'], ['input', 'effective_ceiling'], ['input', 'clamp_rounds'], ['input', 'leftover_pct'], ['input', 'fixed_overhead'], ['input', 'shares'], ['input', 'notice_sent'], ['input', 'notice_trimmed'], ['input', 'notice_why'], ['input', 'notice_text'], ['input', 'folded'], ['input', 'clipped'], ['input', 'dropped'],
  ['output', 'call'], ['output', 'streaming'], ['output', 'finish'], ['output', 'finish_said'], ['output', 'endpoint_model'], ['output', 'endpoint_model_said'], ['output', 'wire_format'], ['output', 'wire_format_said'], ['output', 'model_says_bytes'], ['output', 'model_says_kept'], ['output', 'model_says_clipped'], ['output', 'model_says_sha256'], ['output', 'usage_in'], ['output', 'usage_out'], ['output', 'wire_bytes_out'], ['output', 'wire_bytes_in'], ['output', 'chunks'], ['output', 'first_byte_ms'], ['output', 'max_gap_ms'], ['output', 'tool_calls'], ['output', 'malformed_actions'], ['output', 'malformed_streak'], ['output', 'fail_kind'], ['output', 'fail_detail'], ['output', 'fail_status'], ['output', 'retry_after_ms'], ['output', 'downgrade'], ['output', 'sent'], ['output', 'cost_countable'],
];
console.log('=== META ===');
for (const t of ['L1018', 'L8799']) console.log(t, JSON.stringify(meta[t]));
console.log('total shots =', meta.L1018.shots + meta.L8799.shots, '(L1018 ' + meta.L1018.shots + ' + L8799 ' + meta.L8799.shots + ')');
console.log('total entries =', meta.L1018.entries + meta.L8799.entries);
console.log('');
console.log('=== per-cell (filled=basis!=5 && payload!="" ; absent=basis5 ; emptyStr=payload=="" ) ===');
let neverFilledBoth = [];
for (const [side, key] of table) {
  const kind = 'model_' + side + ':' + key;
  const a = agg[kind] || { L1018: blank(), L8799: blank() };
  const totFilled = a.L1018.filled + a.L8799.filled;
  const verdict = totFilled === 0 ? 'NEVER_FILLED' : 'filled';
  if (totFilled === 0) neverFilledBoth.push(kind);
  console.log(kind + '\tL1018[n=' + a.L1018.n + ' f=' + a.L1018.filled + ' abs=' + a.L1018.absent + ' emp=' + a.L1018.emptyStr + ']\tL8799[n=' + a.L8799.n + ' f=' + a.L8799.filled + ' abs=' + a.L8799.absent + ' emp=' + a.L8799.emptyStr + ']\t' + verdict);
}
console.log('');
console.log('=== NEVER FILLED in BOTH ledgers ===');
for (const k of neverFilledBoth) {
  const a = agg[k];
  console.log(k);
  console.log('   L1018: ' + a.L1018.n + ' entries all absent=' + a.L1018.absent + ' (seq ' + a.L1018.seqAbsent.join(',') + ')');
  console.log('   L8799: ' + a.L8799.n + ' entries all absent=' + a.L8799.absent + ' (seq ' + a.L8799.seqAbsent.join(',') + ')');
}
console.log('count never-filled =', neverFilledBoth.length, '/', table.length);
fs.writeFileSync('cite_result.json', JSON.stringify({ meta, neverFilledBoth }, null, 1));
