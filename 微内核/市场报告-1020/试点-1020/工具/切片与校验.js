const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

const [, , ledgerArg, startArg, endArg, outArg] = process.argv;
if (!ledgerArg || !startArg || !endArg || !outArg) {
  console.error('usage: node 切片与校验.js <ledger.jsonl> <startSeq> <endSeq> <outDir>');
  process.exit(2);
}

const ledgerPath = path.resolve(ledgerArg);
const outDir = path.resolve(outArg);
const start = Number(startArg);
const end = Number(endArg);
const basisName = { 0: 'unset', 1: 'measured', 2: 'relayed', 3: 'estimated', 4: 'model_says', 5: 'absent' };
const sha256 = (buf) => crypto.createHash('sha256').update(buf).digest('hex');
const sealOf = (r) => [r.seq, r.session, r.actor, r.step, r.kind, r.claim, basisName[r.basis], r.source || '', r.ts, r.payload_sha256, r.prev_hash].join('\n');
const payloadOf = (r) => (r.payload_b64 == null ? null : Buffer.from(r.payload_b64, 'base64'));

const raw = fs.readFileSync(ledgerPath);
const lines = raw.toString('utf8').split(/\r?\n/);
let firstLineIsJson = false;
try { JSON.parse(lines[0]); firstLineIsJson = true; } catch (_) {}
const dataLines = (firstLineIsJson ? lines : lines.slice(1)).filter(Boolean);
const entries = dataLines.map((line) => ({ line, rec: JSON.parse(line) }));
const all = entries.map((e) => e.rec);
if (!all.length) throw new Error('empty ledger');

const slice = entries.filter(({ rec }) => rec.seq >= start && rec.seq <= end);
if (!slice.length) throw new Error('empty slice');
if (slice.length !== end - start + 1) throw new Error('slice not contiguous by count');
slice.forEach(({ rec }, i) => {
  if (rec.seq !== start + i) throw new Error('seq gap at ' + rec.seq);
});

const anchorIndex = entries.findIndex(({ rec }) => rec.seq === start - 1);
const anchor = anchorIndex >= 0 ? entries[anchorIndex].rec : null;
const first = slice[0].rec;
const last = slice[slice.length - 1].rec;

const sealOk = [];
const payloadOk = [];
const linkOk = [];
for (let i = 0; i < slice.length; i++) {
  const r = slice[i].rec;
  sealOk.push(sha256(sealOf(r)) === r.hash);
  const payloadRaw = payloadOf(r);
  payloadOk.push(payloadRaw != null && sha256(payloadRaw) === r.payload_sha256);
  if (i > 0) linkOk.push(r.prev_hash === slice[i - 1].rec.hash);
}

const fullSealOk = [];
const fullPayloadOk = [];
const fullLinkOk = [];
for (let i = 0; i < all.length; i++) {
  const r = all[i];
  fullSealOk.push(sha256(sealOf(r)) === r.hash);
  const payloadRaw = payloadOf(r);
  fullPayloadOk.push(payloadRaw != null && sha256(payloadRaw) === r.payload_sha256);
  if (i > 0) fullLinkOk.push(r.prev_hash === all[i - 1].hash);
}
const seqContiguous = all.every((r, i) => r.seq === all[0].seq + i);

const anchorSealOk = anchor ? sha256(sealOf(anchor)) === anchor.hash : null;
const anchorPayloadRaw = anchor ? payloadOf(anchor) : null;
const anchorPayloadOk = anchor ? (anchorPayloadRaw != null && sha256(anchorPayloadRaw) === anchor.payload_sha256) : null;
const anchorPrevLinkOk = anchorIndex > 0 ? anchor.prev_hash === entries[anchorIndex - 1].rec.hash : null;

fs.mkdirSync(outDir, { recursive: true });
const slicePath = path.join(outDir, `链切片-${start}-${end}.jsonl`);
fs.writeFileSync(slicePath, slice.map((e) => e.line).join('\n') + '\n', 'utf8');

const anchorPath = anchor ? path.join(outDir, `锚点-${anchor.seq}.json`) : null;
if (anchor) fs.writeFileSync(anchorPath, JSON.stringify(anchor, null, 2) + '\n', 'utf8');

const basisCount = {};
for (const { rec } of slice) basisCount[basisName[rec.basis]] = (basisCount[basisName[rec.basis]] || 0) + 1;
const fullBasisCount = {};
for (const r of all) fullBasisCount[basisName[r.basis]] = (fullBasisCount[basisName[r.basis]] || 0) + 1;
const absent = slice.filter(({ rec }) => rec.basis === 5).map(({ rec }) => ({ seq: rec.seq, kind: rec.kind, claim: rec.claim }));
const nonMeasured = slice.filter(({ rec }) => rec.basis !== 1).map(({ rec }) => ({ seq: rec.seq, kind: rec.kind, basis: basisName[rec.basis], claim: rec.claim, source: rec.source || null }));

const firstNl = raw.indexOf(10);
const preambleBytes = firstLineIsJson ? 0 : (firstNl >= 0 ? firstNl + 1 : 0);

const report = {
  schema: 'agentkernel-slice-check/v2',
  generated_at: new Date().toISOString(),
  source: {
    file: ledgerPath,
    bytes: raw.length,
    sha256: sha256(raw),
    preamble: firstLineIsJson ? null : lines[0],
    preamble_bytes: preambleBytes,
    jsonl_bytes: raw.length - preambleBytes,
    records: all.length
  },
  slice: {
    file: slicePath,
    bytes: fs.statSync(slicePath).size,
    sha256: sha256(fs.readFileSync(slicePath)),
    seq_start: start,
    seq_end: end,
    count: slice.length,
    session: first.session,
    actor: first.actor,
    step: first.step,
    ts_first: first.ts,
    ts_last: last.ts,
    kinds: new Set(slice.map(({ rec }) => rec.kind)).size,
    basis: basisCount,
    source_nonempty: slice.filter(({ rec }) => String(rec.source || '').trim() !== '').length,
    payload_b64_null: slice.filter(({ rec }) => rec.payload_b64 == null).length
  },
  full_chain: {
    count: all.length,
    first_seq: all[0].seq,
    last_seq: all[all.length - 1].seq,
    seq_contiguous: seqContiguous,
    basis: fullBasisCount,
    seal_ok: fullSealOk.filter(Boolean).length + '/' + fullSealOk.length,
    prev_link_ok: fullLinkOk.filter(Boolean).length + '/' + fullLinkOk.length,
    payload_value_image_ok: fullPayloadOk.filter(Boolean).length + '/' + fullPayloadOk.length,
    first_prev_hash: all[0].prev_hash
  },
  anchor: anchor ? {
    seq: anchor.seq,
    file: anchorPath,
    bytes: fs.statSync(anchorPath).size,
    sha256: sha256(fs.readFileSync(anchorPath)),
    record_hash: anchor.hash,
    seal_ok: anchorSealOk,
    payload_value_image_ok: anchorPayloadOk,
    prev_link_ok: anchorPrevLinkOk,
    prev_seq: anchorIndex > 0 ? entries[anchorIndex - 1].rec.seq : null
  } : null,
  checks: {
    anchor_seq: start - 1,
    anchor_hash: anchor ? anchor.hash : null,
    anchor_present: Boolean(anchor),
    anchor_seal_ok: anchorSealOk,
    anchor_prev_link_ok: anchorPrevLinkOk,
    first_prev_hash: first.prev_hash,
    anchor_link_ok: Boolean(anchor) && first.prev_hash === anchor.hash,
    seal_ok: sealOk.filter(Boolean).length + '/' + sealOk.length,
    prev_link_ok: linkOk.filter(Boolean).length + '/' + linkOk.length,
    payload_value_image_ok: payloadOk.filter(Boolean).length + '/' + payloadOk.length
  },
  absent_cells: absent,
  non_measured_cells: nonMeasured,
  limits: [
    'payload_b64 是逐格值镜像，不是产物原件；原件不在账内',
    '本切片只有一次调用；没有 gate 行、没有复核记录、没有版本三元组',
    '全链复算只证明账本自洽，不证明调用内容真实或正确'
  ]
};

fs.writeFileSync(path.join(outDir, `链校验-${start}-${end}.json`), JSON.stringify(report, null, 2) + '\n', 'utf8');
console.log(JSON.stringify({
  slice: report.slice.file,
  count: report.slice.count,
  seal_ok: report.checks.seal_ok,
  prev_link_ok: report.checks.prev_link_ok,
  anchor_link_ok: report.checks.anchor_link_ok,
  anchor_seal_ok: report.checks.anchor_seal_ok,
  payload_image_ok: report.checks.payload_value_image_ok,
  full_chain: report.full_chain,
  basis: report.slice.basis,
  payload_null: report.slice.payload_b64_null
}, null, 2));
