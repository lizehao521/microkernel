const fs = require('fs');

const FILES = [
  ['L1018', 'C:/Users/Admin/Desktop/\u5fae\u5185\u6838/\u6784\u5efa-1017/\u5ba2\u670d\u9776\u573a/\u5bfc\u51fa/\u8d26\u672c-\u5168\u91cf-1018.jsonl'],
  ['L8799', 'C:/Users/Admin/Desktop/\u5e97\u9762\u6e38\u620f/\u8d26\u672c-8799-\u7b2c\u4e8c\u6b21\u5feb\u7167-included.jsonl'],
];

const stat = {};   // kind -> {total, absent, nonAbsent, perFile:{}}
let lines = 0, skipped = 0, badJson = 0;
const perFileCounts = {};

for (const [tag, p] of FILES) {
  const raw = fs.readFileSync(p, 'utf8').split('\n');
  perFileCounts[tag] = { lines: raw.length, entries: 0, headerSkipped: 0 };
  for (const ln of raw) {
    const t = ln.trim();
    if (!t) continue;
    lines++;
    if (t[0] !== '{') { skipped++; perFileCounts[tag].headerSkipped++; continue; }
    let o;
    try { o = JSON.parse(t); } catch (e) { badJson++; continue; }
    const k = o.kind;
    if (typeof k !== 'string') { badJson++; continue; }
    perFileCounts[tag].entries++;
    if (!stat[k]) stat[k] = { total: 0, absent: 0, nonAbsent: 0, bases: {}, perFile: {} };
    const s = stat[k];
    s.total++;
    s.perFile[tag] = (s.perFile[tag] || 0) + 1;
    const b = o.basis;
    s.bases[b] = (s.bases[b] || 0) + 1;
    if (b === 5) s.absent++; else s.nonAbsent++;
  }
}

const kinds = Object.keys(stat).sort();
const never = kinds.filter(k => stat[k].nonAbsent === 0);

console.log('=== \u5206\u6bcd\u81ea\u5370 ===');
console.log('files:', JSON.stringify(perFileCounts));
console.log('nonblank lines:', lines, ' non-JSON skipped(header):', skipped, ' badJson:', badJson);
console.log('distinct kinds:', kinds.length);
console.log('total entries:', kinds.reduce((a, k) => a + stat[k].total, 0));

console.log('');
console.log('=== never-filled (nonAbsent === 0) ===');
console.log('count:', never.length);
for (const k of never) {
  const s = stat[k];
  console.log(k, '| total', s.total, '| absent', s.absent, '| bases', JSON.stringify(s.bases), '| perFile', JSON.stringify(s.perFile));
}

console.log('');
console.log('=== per-file never-filled (\u53ea\u770b\u5355\u672c\u8d26\u65f6) ===');
const stat2 = {};
for (const [tag, p] of FILES) {
  const raw = fs.readFileSync(p, 'utf8').split('\n');
  const acc = {};
  for (const ln of raw) {
    const t = ln.trim();
    if (!t || t[0] !== '{') continue;
    let o; try { o = JSON.parse(t); } catch (e) { continue; }
    if (typeof o.kind !== 'string') continue;
    if (!acc[o.kind]) acc[o.kind] = { total: 0, nonAbsent: 0 };
    acc[o.kind].total++;
    if (o.basis !== 5) acc[o.kind].nonAbsent++;
  }
  stat2[tag] = acc;
  const nfk = kinds.filter(k => !(acc[k] && acc[k].nonAbsent > 0));
  console.log(tag, 'never-filled count:', nfk.length, '->', nfk.join(', '));
}

console.log('');
console.log('=== all kinds with basis histogram (for audit) ===');
for (const k of kinds) {
  const s = stat[k];
  console.log(k, '| total', s.total, '| nonAbsent', s.nonAbsent, '| bases', JSON.stringify(s.bases));
}
