const fs = require('fs');
const crypto = require('crypto');
const SESSION = 'closedloop-1019-yi';
const ACTOR = 'qoder-agent-yi';

const summary = '第6发（记账与收尾阶段自记）：构造 record_call 入参时实测到两处 wire 类型缺口——Budget.Shares 是 map[PartKind]int（账本渲染里却是 "history=30" 字符串数组）、Cuts 是 []kernel.Cut 切片（不是分档对象）；两次 check_call 在门口被挡（Shares、Cuts 各一次），改对后 5 发落账、链自洽 245 条。declare_reader 逐格声明 49 次，48 成 1 拒（output:call 被判与 input:call 同键重复——该工具按 reader+key 去重、忽略 side，故 call 的两格无法被同一读者分别声明）。readers_report：输入 20 格/输出 29 格均 0 格无声明者。';
const why = '本发无折叠无裁尾；content_bytes/part_totals 是裸整数，结构上不能表达缺席，账上的 0 是「没量到」；shares 与两级额度是本调用方自定策略数；ToolCalls=16 是我对自己这一段工具调用的自数（含 2 次 wire 修正、3 次 check、5 发 record、1 次 declare 循环、tally/verify/report），非内核测量。';

function MAbs(why) { return { N: 0, Basis: 0, Source: '', Absent: true, Refused: false, Why: why }; }
const sha = crypto.createHash('sha256').update(summary, 'utf8').digest('hex');
const bytes = Buffer.byteLength(summary, 'utf8');
const input = {
  Call: 6,
  Order: ['system', 'user', 'history', 'toolspec'],
  Parts: [
    { Kind: 'system', Parts: 1, Bytes: 0 }, { Kind: 'user', Parts: 1, Bytes: 0 },
    { Kind: 'history', Parts: 1, Bytes: 0 }, { Kind: 'toolspec', Parts: 1, Bytes: 0 },
  ],
  ContentBytes: 0,
  Tokens: MAbs('分词器在 harness 对端，模型这一侧数不到；连 content_bytes 都没量到，估一个数没有依据'),
  Budget: {
    CallBytesCeiling: 200000, TransportSlackPct: 15, ContentCeiling: 170000, EffectiveCeiling: 170000,
    ClampRounds: 0, LeftoverPct: 0,
    FixedOverhead: MAbs('骨架字节由 harness 装配，模型这一侧数不到；没量到不是 0'),
    Shares: { history: 30, memory: 10, skill: 10, system: 20, toolspec: 10, user: 20 },
  },
  Cuts: [],
  Notice: { Sent: false, Trimmed: false, Why: '本发没有裁剪记录，也就没有要发的知情通知', Text: why },
};
const output = {
  Call: 6, Streaming: false,
  Finish: { Reason: '', Said: false }, Model: '', ModelSaid: false, WireFormat: '', WireFormatSaid: false,
  Says: { Bytes: bytes, Kept: bytes, SHA256: sha },
  UsageIn: MAbs('harness 没把 usage 递到模型这一侧；没量到不是 0'),
  UsageOut: MAbs('harness 没把 usage 递到模型这一侧；没量到不是 0'),
  WireBytesOut: MAbs('本发的请求体经 harness 传输，模型这一侧没有字节计数点'),
  WireBytesIn: MAbs('本发的响应体经 harness 传输，模型这一侧没有字节计数点'),
  Chunks: MAbs('按非流式记，结构上没有分帧数'),
  FirstByteMs: MAbs('按非流式记，结构上没有首帧等待'),
  MaxGapMs: MAbs('按非流式记，结构上没有帧间静默'),
  ToolCalls: 16, Malformed: 0, MalformedStreak: 0,
  Failure: { Kind: '', Detail: '', Status: MAbs('没故障，也就没有要记的状态码'), RetryAfterMs: MAbs('没故障，对端没说要等多久'), Downgrade: false },
};
const args = { session: SESSION, actor: ACTOR, input, output };
fs.writeFileSync('shot6.check.json', JSON.stringify({ jsonrpc: '2.0', id: 106, method: 'tools/call', params: { name: 'kernel.check_call', arguments: args } }));
fs.writeFileSync('shot6.record.json', JSON.stringify({ jsonrpc: '2.0', id: 206, method: 'tools/call', params: { name: 'kernel.record_call', arguments: args } }));
console.log('shot6 built, says_bytes=' + bytes);
