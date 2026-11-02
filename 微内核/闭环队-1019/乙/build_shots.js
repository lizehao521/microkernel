// 生成落账请求体：shots 1..5（第 6 发收尾时另行生成）
const fs = require('fs');
const crypto = require('crypto');

const SESSION = 'closedloop-1019-yi';
const ACTOR = 'qoder-agent-yi';

const shots = [
  {
    call: 1, tools: 4,
    summary: '读 contract.md 431 行全文；探明输出目录不存在需自建；wc -l 两本历史账本=2941/491 行；head 抽样确认 JSONL 形状（seq/session/actor/step/kind/claim/basis/ts/payload_b64/payload_sha256/prev_hash/hash）。',
    why: '本发无折叠无裁尾；content_bytes/part_totals 是裸整数，结构上不能表达缺席，账上的 0 是「没量到」不是「量到 0」；shares 与两级额度是本调用方自定的策略数。',
  },
  {
    call: 2, tools: 5,
    summary: 'MCP 接入 127.0.0.1:18803/mcp：initialize 一次调通（回 protocolVersion 2024-11-05，与我发的 2025-03-26 不同，服务端未报错）；notifications/initialized；tools/list 得 10 工具；解码全部 inputSchema。',
    why: '同上披露：输入侧裸整数 0 = 没量到。本发是接线发，未动历史账本。',
  },
  {
    call: 3, tools: 4,
    summary: 'kernel.celltable 取权威 49 格表（20 入+29 出/48 键），与 contract.md 第 3 节逐行比对一致；写清点脚本 tally_cells.js 第一版，首跑发现分母 bug：输出侧漏了 call 一格（49=20+29，call 两侧各一格），model_output:call 被误判为表外 kind。',
    why: '同上披露：输入侧裸整数 0 = 没量到。',
  },
  {
    call: 4, tools: 13,
    summary: '修分母后重跑：两本账各格条目数恰为发次数（1018 账 60 发、8799 账 10 发，每发 49 格全到，无整格缺席条目）；粗判据（payload_b64 非空）下 never-filled=2；逐格明细发现 fail_kind/fail_detail 等格 basis=1 但 payload 解码为空串 ""（claim=（这一格是空的）），判据需收紧。',
    why: '同上披露：输入侧裸整数 0 = 没量到。',
  },
  {
    call: 5, tools: 13,
    summary: '收紧判据（filled = basis≠5 且解码 payload ≠ 空串 ""）重扫：49 格中 never-filled=2（model_output:fail_status、model_output:retry_after_ms，两本账 70 条全部 basis=5 带缺席理由）；解码 8799 账第 1 发全部 49 格 payload 作为本次落账入参样板。',
    why: '同上披露：输入侧裸整数 0 = 没量到。第 1-5 发为事后补记（推理发生时未落账），第 6 发实时记录，此事实已在报告披露。',
  },
];

function M(n, basis, source, why) {
  return { N: n, Basis: basis, Source: source || '', Absent: false, Refused: false, Why: why || '' };
}
function MAbs(why) {
  return { N: 0, Basis: 0, Source: '', Absent: true, Refused: false, Why: why };
}

for (const s of shots) {
  const sha = crypto.createHash('sha256').update(s.summary, 'utf8').digest('hex');
  const bytes = Buffer.byteLength(s.summary, 'utf8');
  const input = {
    Call: s.call,
    Order: ['system', 'user', 'history', 'toolspec'],
    Parts: [
      { Kind: 'system', Parts: 1, Bytes: 0 },
      { Kind: 'user', Parts: 1, Bytes: 0 },
      { Kind: 'history', Parts: 1, Bytes: 0 },
      { Kind: 'toolspec', Parts: 1, Bytes: 0 },
    ],
    ContentBytes: 0,
    Tokens: MAbs('分词器在 harness 对端，模型这一侧数不到；连 content_bytes 都没量到，估一个数没有依据'),
    Budget: {
      CallBytesCeiling: 200000,
      TransportSlackPct: 15,
      ContentCeiling: 170000,
      EffectiveCeiling: 170000,
      ClampRounds: 0,
      LeftoverPct: 0,
      FixedOverhead: MAbs('骨架字节由 harness 装配，模型这一侧数不到；没量到不是 0'),
      Shares: { history: 30, memory: 10, skill: 10, system: 20, toolspec: 10, user: 20 },
    },
    Cuts: [],
    Notice: { Sent: false, Trimmed: false, Why: '本发没有裁剪记录，也就没有要发的知情通知', Text: s.why },
  };
  const output = {
    Call: s.call,
    Streaming: false,
    Finish: { Reason: '', Said: false },
    Model: '',
    ModelSaid: false,
    WireFormat: '',
    WireFormatSaid: false,
    Says: { Bytes: bytes, Kept: bytes, SHA256: sha },
    UsageIn: MAbs('harness 没把 usage 递到模型这一侧；没量到不是 0'),
    UsageOut: MAbs('harness 没把 usage 递到模型这一侧；没量到不是 0'),
    WireBytesOut: MAbs('本发的请求体经 harness 传输，模型这一侧没有字节计数点'),
    WireBytesIn: MAbs('本发的响应体经 harness 传输，模型这一侧没有字节计数点'),
    Chunks: MAbs('按非流式记，结构上没有分帧数'),
    FirstByteMs: MAbs('按非流式记，结构上没有首帧等待'),
    MaxGapMs: MAbs('按非流式记，结构上没有帧间静默'),
    ToolCalls: s.tools,
    Malformed: 0,
    MalformedStreak: 0,
    Failure: { Kind: '', Detail: '', Status: MAbs('没故障，也就没有要记的状态码'), RetryAfterMs: MAbs('没故障，对端没说要等多久'), Downgrade: false },
  };
  const args = { session: SESSION, actor: ACTOR, input, output };
  fs.writeFileSync('shot' + s.call + '.check.json', JSON.stringify({ jsonrpc: '2.0', id: 100 + s.call, method: 'tools/call', params: { name: 'kernel.check_call', arguments: args } }));
  fs.writeFileSync('shot' + s.call + '.record.json', JSON.stringify({ jsonrpc: '2.0', id: 200 + s.call, method: 'tools/call', params: { name: 'kernel.record_call', arguments: args } }));
  console.log('shot', s.call, 'says_bytes=' + bytes, 'sha=' + sha.slice(0, 12) + '...');
}
