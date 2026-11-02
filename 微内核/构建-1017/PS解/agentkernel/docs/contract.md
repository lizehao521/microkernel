# agentkernel 对外契约（待接件 · v0）

**这份文档是给「下一个要接它的人」看的，不是给读源码的人看的。**
目的只有一个：让接的时候**不必重读 2400 行源码去猜口径**。

| 项 | 值 |
|---|---|
| 状态 | **待接件**：本 module **之外**没有任何调用方。范围要说死：仓库内 `import agentkernel` 命中 **3 处**，都在 `cmd/`（`kcheck` 闸门、`kresearch` 真端点样例、`mcpkernel` stdio 外壳），它们是**内核自己的工具**，不是接入方 —— 拿它们当"已有人接"是假绿。`mcpkernel` 只把「谁来调」这件事从"等框架写好"变成"任何会发 JSON-RPC 的进程"，壳仍然在本 module 里 |
| 包的版本 | `module agentkernel` / `go 1.27`（`go.mod`） |
| 格位表来源 | 键名与字段路径由 `Cells()` **机械导出**，不是手抄。可执行的那一步是 `tasks/audit/celltable_audit.py`（见第 6 节）—— 它把这张表与 `kcheck` 第 5 节的实读逐格对。早先这里指向的生成器 `celltable.go` 不在仓库内，那句话当时不可执行 |
| 本文件写入前的回滚点 | `git-snapshot` 点 `mp-mujmoqkh-25f`（manifest 后端，覆盖 25 个文件） |
| 一句话 | 内核只管**账**：每格带「谁算的」、缺席要说得出理由、缺依据进不了门；它不调度、不联网、不写盘 |

---

## 0. 一发

一次模型调用 = 一发，发号 `Call` 从 1 起。两侧账：

- `InputMeta` —— 请求**装配完之后**：我们发了什么
- `OutputMeta` —— 响应**回来之后**：我们收到了什么

**记账单位是「格」，不是「键名」**：`Cells()` 交出 **49 格**，其中唯一键名 **48 个**——
`call` 在两侧各有一格（同一个量、两条记录）。任何统计必须说清自己数的是格还是键；
把两者混着说，就是这个包最恨的「一个名字住两个量」。

---

## 1. 四条不变量

1. **每格带出处**：`Basis` 的零值是 `unset`（=0），门口直接拒。不存在「默认按实测算」。
2. **缺席 ≠ 0 ≠ 忘了填**：三态分离。缺席必须带理由，且**缺席不可拿去做判定**。
3. **一格一量**：撞名判据靠**字段路径**——两侧都有 `call`（同为 `Call`）不算撞；
   两个字节量共用一个键名（字段路径不同）当场撞出来。`bytes_out` 这个名字被**单独点名禁掉**。
4. **一个定义只有一个 owner，且 owner 要被复核**：例如预算公式的唯一出口是 `DeriveBudget`，
   `InputMeta.Check()` 会把公式**重算一遍**再比对；手搭一份 `ContentCeiling=999999` 的预算进不了门。

---

## 2. 序列化契约（**接线的人必须按这一节对表**）

### 2.1 Basis —— 落盘是**整数**，渲染是字符串

`Basis` **没有自定义 JSON 序列化**（全包无 `MarshalJSON`/`UnmarshalJSON`），所以默认按 `int` 落：

| 常量 | 落盘 | `String()` / `Claim` 里的字 |
|---|---|---|
| `BasisUnset` | 0 | `unset` |
| `BasisMeasured` | 1 | `measured` |
| `BasisRelayed` | 2 | `relayed` |
| `BasisEstimated` | 3 | `estimated` |
| `BasisModelSays` | 4 | `model_says` |
| `BasisAbsent` | 5 | `absent` |

> **口径陷阱（照原样记下，别改）**：`Cells()` 交出来的格子上 **`Basis` 永远不是 5**。
> 缺席在键名表这一层表现为 `Basis = 0`（`measureCell` 在 `m.Absent` 时把出处置零），
> 由 `basisOf()` 在**落账时**翻译成 `BasisAbsent`(5)。
> 所以：**读 `Cells()` 的人不能把 0 读成「忘了填」**——0 在这一层是「要么没填、要么这一格缺席」，
> 只有账本上那一条（`basis=5`）才是「这一发结构上没有这个数」。
> 两处若对不上，`basisOf` 会拒收（错误句点名是哪一格）。

### 2.2 账本条目的命名与指纹

| 项 | 值 |
|---|---|
| `KindModelInput` / `KindModelOutput` | `"model_input"` / `"model_output"` |
| 账本条目名 | `<kind>:<key>`，例如 `model_input:content_bytes`（逐格一条） |
| `Claim` | 人话版本，短；**永不为空**（空值落成常量 `emptyClaim`，另有「空表说自己的名字」的零话） |
| `Payload` | `json.Marshal(值)` 的字节；**全**，给第三方重算 |
| `PayloadH` | `Payload` 的 SHA-256 十六进制（64 位） |
| `Hash`（seal） | sha256(`Seq\nSession\nActor\nStep\nKind\nClaim\nBasis.String()\nSource\nAt(RFC3339Nano,UTC)\nPayloadH\nPrevHash`)，两段之间用 `\n` |
| `Entry.Payload` | tag 是 `json:"-"` ⇒ **不随 Entry 序列化**。落盘方要自己决定带不带原像；不带就只剩指纹，第三方**重算不出原值** |

### 2.3 字节格式（JSONL）—— 内核拥有格式，框架仍然拥有磁盘

`journal.go` 交出去的是 `[]byte`，**内核一行都不写磁盘**（那份文件连 `os` 都没 import）。
接线的人要决定的是下面这一格，而不是"要不要自己写一遍 Marshal"：

| 入口 | 作用 | 必须知道的口径 |
|---|---|---|
| `MarshalJournal(docs, mode)` | 编成 JSONL，一行一条 | `mode` 的零值 `PayloadUnset` **被门口拒**；不许靠默认值过关 |
| `ReadJournal(b)` | 解回 `Journal`（不验链） | 解不开的行进 `BadLines` 并**带行号**；`Lines` 与 `Parsed` 是两个分母 |
| `CheckChain(docs)` | 三态体检：过 / 没过 / 核不了 | `Ledger.Verify()` 就是委派到这一份，判据只有这一个 owner |
| `LoadLedger(b)` | 读成一本**能接着记**的账本 | 链不符拒绝载入；没有原像**不是**拒收的理由 |

读侧那一半（`CellsOf` / `Keys` / `AbsentKeys`）按 **`session` + 发号 + 侧** 三个轴认「同一发」，
与写侧 `alreadyRecorded` 是同一个定义。少带 `session` 不是「读不到」而是**读错**：
两个 session 各记一次第 1 发，只按发号与侧过滤会回 40 格（这一条是 MCP 挂载实测撞出来的，
现在由 `TestCellsOfKeepsTwoSessionsApart` 与慢闸针 `j10` 钉着）。

`payload_b64` 那一格的三态（**别把它读成两态**）：

| 字节流里的样子 | 读回来 | 含义 |
|---|---|---|
| `"payload_b64":"ag1=="` | `WithPayload++` | 带原像，第三方能重算 `payload_sha256` |
| `"payload_b64":""` | `WithPayload++` | 带了一个**空原像**（absent 那一档在内存里就是 nil，它的指纹就是对空算的） |
| `"payload_b64":null`（或这个字段整个省略） | `NoPayload++`、`payloadAbsent=true` | 没有原像：**核不了**，不是篡改 —— 今天编码器写的就是 `null` |

第三行是本包最容易被读错的一格。`Verify()` 在那种情况下报的话里有「没有原像」而**绝不**有「被动过」；
`ChainReport.String()` 开头打 `—` 不打 `✓`。把这两句话合并的说法（"指纹对不上就是内容被动过"）
会把 47 条完好无损的账全指控成篡改，于是下一次真篡改淹在假警报里。

**还有一句必须写在脸上的：这本账是审计件，不是恢复件。**
`payload_b64` 装的是**每一格自己的值**的原像（用来让第三方重算那一格的指纹），
不是模型说过的话。输出侧装着「模型说了什么」的格只有四格 ——
`model_says_bytes`、`model_says_kept`、`model_says_clipped`、`model_says_sha256`，
全是数与指纹，**没有一格存原文**；输入侧的题面、`observation`、system 说明书同样只有字节数与段名。
所以换新进程只带这本账，可以做到的事是：验链、读回每一格的数、
**拿别处存着的原文逐发重算指纹核对**（`tasks/mcp/replay.py` 真跑了这一条：5 发里可比 3 发、3 发全对上）；
做不到的事是：把下一发的 `messages` 重建出来。
账上确实有两处自由文本 —— `fail_detail` 与 `notice_text` —— 但那两处住的是**我们自己写的句子**，
不是模型的输出（这一条别读成「原文有地方放，是我没填」）。

**`PayloadOmitted` 的代价要写在脸上**：链仍然自洽（seal 盖的是 `PayloadH` 那 11 格），
但"第三方能按同一规则重算原值"这一半从此核不了 —— `Journal.String()` 会把这件事直接说出来，
别把它折进"读回 47 条"里（那一轮还是一发 47 格；现在是 49）。



### 2.4 值域（枚举）

| 类型 | 取值 | 备注 |
|---|---|---|
| `PartKind` | `system` `skill` `memory` `history` `toolspec` `observation` `user` `truncation-notice` | `MayFold` = observation/history；`MayShrink` = observation/history（**「整段没进」只许用在可分片的类段上**） |
| `Role` | `system` `user` `assistant` `tool` | 裁剪记录必须带 |
| `Squeeze` | `""`(没被挤) `folded` `tail-dropped` `dropped-whole` `budget-exhausted` | 账上的三档键名是 `folded`/`clipped`/`dropped`；`clipped` 对应 `tail-dropped` |
| `FailKind` | `""`(正常) `transport` `config` `http` `protocol` `malformed_action` `budget` | **两根分开的轴**：`MayCarryStatus()` = http/config/protocol/malformed_action（收到过对端响应才有码可记），`RetrySame()` = transport/http。以前用「是不是 http」一根轴冒充两根，被一发真 401 与一发 200 坏 body 各撞开一次 |
| `SentState` | `没数到` / `数到了，是 0` / `数到了，非 0` | `sent` 那一格就是这个三态的字符串 |
| `SHA256` 字段 | 必须 **64 位十六进制**，唯一的判据函数是 `checkFingerprint` | **裁剪记录（含「整段没进」）也必须有指纹**——空串会被拒 |

---

## 3. 格位表（48 键 / 49 格）

`basis_on_empty_sample` 一列是**空样本**（`InputMeta{}` / `OutputMeta{}`）上 `Cells()` 报的出处，不是「必须长这样」；
`owner` / `presence_policy` 两列是接线时由**接入方**确认的，不是内核声明（内核不认识框架）。

> **这一列怎么读（2026-10-13 对账时补）**：空样本上大多数格报 `unset`，因为 `Measure` 的零值出处就是 `unset`。
> 但 `fixed_overhead`、`tokens` 这类格在**真装配出来的一发**上会报 `estimated`（`DeriveBudget` 要求写明估的是什么）。
> 所以这一列**不是取值约束**，只是「这张表当初是从哪种形状上抄下来的」的记录。
> 把它读成「这一发应该填 estimated」会读错方向：空样本上填 `estimated` 反而会被 `Check()` 拒（有出处却没值）。
> 2026-10-13 之前这一行写的是 `estimated` —— 那是从一份**填过的**样例抄来的，与列定义不符，已改回实读的 `unset`。

| key | sides | field | basis_on_empty_sample | owner（待接入方确认） | presence_policy |
|---|---|---|---|---|---|
| `call` | both | `Call` | measured | 框架·发号 | required |
| `parts` | input | `Order` | measured | 框架·装配器 | required |
| `part_totals` | input | `Parts` | measured | 框架·装配器 | required |
| `content_bytes` | input | `ContentBytes` | measured | 框架·装配器 | required |
| `tokens` | input | `Tokens` | unset | 框架·分词/转述 | required_or_absent_with_reason |
| `call_bytes_ceiling` | input | `Budget.CallBytesCeiling` | measured | 人·配置 | required |
| `transport_slack_pct` | input | `Budget.TransportSlackPct` | measured | 人·配置 | required |
| `content_ceiling` | input | `Budget.ContentCeiling` | measured | 内核·公式 | required |
| `effective_ceiling` | input | `Budget.EffectiveCeiling` | measured | 框架·回夹 | required |
| `clamp_rounds` | input | `Budget.ClampRounds` | measured | 框架·回夹 | required |
| `leftover_pct` | input | `Budget.LeftoverPct` | measured | 内核·公式 | required |
| `fixed_overhead` | input | `Budget.FixedOverhead` | unset | 框架·骨架统计 | required_or_absent_with_reason |
| `shares` | input | `Budget.Shares` | measured | 人·配置 | required |
| `notice_sent` | input | `Notice.Sent` | measured | 框架·裁剪器 | required —— 钉在段表上（见 §5 那条）|
| `notice_trimmed` | input | `Notice.Trimmed` | measured | 框架·裁剪器 | required |
| `notice_why` | input | `Notice.Why` | measured | 框架·裁剪器 | required |
| `notice_text` | input | `Notice.Text` | measured | 框架·裁剪器 | required |
| `folded` | input | `Cuts#folded` | measured | 框架·裁剪器 | required |
| `clipped` | input | `Cuts#clipped` | measured | 框架·裁剪器 | required |
| `dropped` | input | `Cuts#dropped` | measured | 框架·裁剪器 | required |
| `streaming` | output | `Streaming` | measured | 框架·调用器 | required |
| `finish` | output | `Finish.Reason` | relayed | 对端·响应 | required_or_absent_with_reason |
| `finish_said` | output | `Finish.Said` | measured | 框架·调用器 | required |
| `endpoint_model` | output | `Model` | model_says | 对端·自报 | required_or_absent_with_reason |
| `endpoint_model_said` | output | `ModelSaid` | measured | 框架·调用器 | required |
| `wire_format` | output | `WireFormat` | relayed | 对端·响应体 `object` | required_or_absent_with_reason |
| `wire_format_said` | output | `WireFormatSaid` | measured | 框架·调用器 | required |
| `model_says_bytes` | output | `Says.Bytes` | measured | 框架·响应体 | required |
| `model_says_kept` | output | `Says.Kept` | measured | 框架·响应体 | required |
| `model_says_clipped` | output | `Says.Clipped()` | measured | 框架·响应体 | required |
| `model_says_sha256` | output | `Says.SHA256` | measured | 框架·响应体 | required |
| `usage_in` | output | `UsageIn` | unset | 对端·自报 | required_or_absent_with_reason |
| `usage_out` | output | `UsageOut` | unset | 对端·自报 | required_or_absent_with_reason |
| `wire_bytes_out` | output | `WireBytesOut` | unset | 传输层·计数 | required |
| `wire_bytes_in` | output | `WireBytesIn` | unset | 传输层·计数 | required |
| `chunks` | output | `Chunks` | unset | 传输层·流式回调 | absent_with_reason_when_nonstream |
| `first_byte_ms` | output | `FirstByteMs` | unset | 传输层·流式回调 | absent_with_reason_when_nonstream |
| `max_gap_ms` | output | `MaxGapMs` | unset | 传输层·流式回调 | absent_with_reason_when_nonstream |
| `tool_calls` | output | `ToolCalls` | measured | 框架·响应解析 | required |
| `malformed_actions` | output | `Malformed` | measured | 框架·响应解析 | required |
| `malformed_streak` | output | `MalformedStreak` | measured | 框架·响应解析 | required |
| `fail_kind` | output | `Failure.Kind` | measured | 框架·调用器 | required |
| `fail_detail` | output | `Failure.Detail` | measured | 对端/框架·说法 | required_when_failed |
| `fail_status` | output | `Failure.Status` | unset | 对端·HTTP | required_or_absent_with_reason |
| `retry_after_ms` | output | `Failure.RetryAfterMs` | unset | 对端·响应头 | optional_absent_with_reason |
| `downgrade` | output | `Failure.Downgrade` | measured | 框架·策略 | required |
| `sent` | output | `Sent()` | measured | 框架·调用器 | required |
| `cost_countable` | output | `CostCountable()` | measured | 内核·派生 | required |

**presence_policy 的取值含义**：`required`＝每发都得有；`required_or_absent_with_reason`＝要么有值、要么记 `absent` 且带理由；
`absent_with_reason_when_nonstream`＝非流式那一发必须记 `absent+理由`（写 0 直接拒）；
`required_when_failed`＝只在报故障那一发要求；`optional_absent_with_reason`＝没这一格就记 `absent+理由`。

---

**这一轮新增/改动的四行，解释住在这里（表的第 4 栏要留给机器读的出处 token）：**

- `fail_status` —— 出处**随故障类别那根轴而变**（`FailKind.MayCarryStatus()`）：
  收到过对端响应的那几类（`http`/`config`/`protocol`/`malformed_action`）是 `measured`；
  `transport`/`budget` 与没故障的那一发是 `absent` 带理由。
  以前这一格在 `cells.go` 里被写死成 `measured`，于是**每一发正常往来都在账上说「量到状态码是 0」**
  （实测：在册 27 发全是那个长相）。
- `wire_format` / `wire_format_said` —— 对端在响应体顶层自己写的 `object`（实测非流式
  `chat.completion`、流式 `chat.completion.chunk`，两支不同，见 报告/格式自报-流式对照.txt）。
  只能转述：填我们自己那套接线常量（`openai-chat/v1`）就是转述对端没说过的话。
  另有一条互核：说对端自报了格式，却是 `transport`/`budget` 那一类（压根没收到响应）⇒ 整发拒收。
- `notice_sent` —— **钉在段表上**：`Notice.Sent=true` 要求 `Order` 里真有 `truncation-notice` 那一段，
  有那段却没记 Sent 同样拒。实例是真撞出来的（不是设想）：驱动把折叠排在附通知之前，
  于是有一发裁剪表多了记录、`Sent` 写着"是"、段里没有通知，内核当时整发照收
  （报告/挤历史-判生死.md 第 7 节）。
- `Cut.RefCall` —— 被挤掉的**历史**段必须指名它来自第几发，且那一发必须早于当前发
  （指 0 或指未来都拒）。`Ref` 是人写的散文，这是第一个能机器用的跨发引用
  （报告/挤历史-判生死.md：三把指纹单位不同，"它是第几发"当时只在散文里）。

## 4. 已知空洞（**别当已实现**）

**第一轮（证据源 runloop，真模型端点）** 实测后 **10 格从未被填过**：`fixed_overhead` `tokens` `chunks`
`first_byte_ms` `max_gap_ms` `retry_after_ms` `usage_in` `usage_out` `wire_bytes_in` `wire_bytes_out`。
原因不是疏忽，是**采集点不存在**：`usage_*` 的 owner 是「对端·自报」、`wire_bytes_*` 是「传输层·计数」、
三格流式是「传输层·流式回调」——这三条通路在接入方一侧还没建。接的时候要么建通路，要么按
`absent+理由` 记（**不是记 0**）。

**第二轮（2026-10-13，`cmd/kresearch` 接 Deep Research HTTP 服务，见 `报告/实测-真端点形状缺陷.md`）**
上面这 10 格里 **7 格被真量到了**：`chunks` `first_byte_ms` `max_gap_ms` `wire_bytes_in` `wire_bytes_out`
记成 `measured`（1368 个事件块 / 首帧 90ms / 最长静默 16819ms / 收到 495461 字节 / 请求体 0 字节），
`fixed_overhead` `tokens` 记成 `estimated` 并写明估的是什么。
**仍然填不上的 3 格是 `usage_in` `usage_out` `retry_after_ms`** ——
这一轮的原因换了：不是我们没有采集点，而是**这个端点不提供 usage 字段、成功的往来也不给 Retry-After**。
所以「建通路」这一条要分成两种活：传输层与流式那几格接了客户端就有；对端自报那两格**取决于对端给不给**，
给不出来的时候如实记缺席，比记一个推导出来的数诚实。

**第三轮（2026-10-13，`tasks/mcp/llm_probe.py` 经挂载好的内核接一个 OpenAI 兼容的对话端点，
见 `报告/接入LLM-第一发.md` 与 `报告/样例-LLM两发.jsonl`）**
上面那 3 格**又填上两格**：`usage_in` `usage_out` 第一次拿到真数（93/18、127/10），
出处是**转述** —— 分词器在对端，记成实测就是假绿。`endpoint_model` 不再是「模型没说」
（自报 `agnes-3.0-flash`，档位仍是 `model_says`：永远是线索不是事实），`finish` 第一次有真值 `stop`。
**只剩 `retry_after_ms` 仍然缺席**：这两发都是 200，没断，也就没有要等多久（这里缺席是对的）。
所以第 200-203 行那句「取决于对端给不给」今天被正面验证了，并且推掉一个更强的说法：
**格位表里没有死格，只有还没接到的端点**。以后不许写「某格永远填不上」，要写就写「这个端点不给」。

第四处**形状**缺陷也是这一轮才现形的，方向和规矩二相反：
`tokens`（输入侧）与 `usage_in`（输出侧）是**同一个物理量的两格**，实测各说各话。
调用方把第 2 发的 `tokens` 沿用了第 1 发的 93，而端点对第 2 发报的是 127 ——
**两格一起落了账，出处字符串一模一样，内核一条都没拦**；按两个键名分别累加是 186 与 220，
两张成本分母是 214 与 248。撞名判据看不见这一族，因为两个名字本来就不该撞。
现形的条件正是上面那件事：上一轮的端点不给 usage，`usage_in` 恒为缺席，结构上撞不出矛盾。
修不修是口径问题（钉成相等 / 允许不等但必须带理由 / 输入侧只留估算那一档），**这份文档不替你定**。

同一轮还翻出三处**形状**缺陷（不是数值错，是格子不够/口径串了）：
`wire_bytes_out` 对无请求体的发会渲染成「没发出去」；46 个键名（封板后 48 个）里**没有一格装整发耗时**；
而隔离闸把包内核（116 个包）与整棵树（208 个包）压成同一个读数。详见那份报告的发现 1、2、4。

**第四轮（2026-10-13，`tasks/mcp/tools_probe.py` 带 `tools` 打同一个对话端点，
见 `报告/工具提议-实测.md` 与 `报告/样例-工具提议.jsonl`）**
工具那一族三格第一次有**真响应上的非零数**：`tool_calls=2`、`malformed_actions=1`、
`malformed_streak=1`（流式那一发的第二个提议被截成 `{"a": 9`，参数解不出 JSON）。
`finish` 拿到第二种非 stop 真形状 `tool_calls`（出处 `relayed`）；输入侧 `toolspec`、`observation`、
`truncation-notice` 三个段类第一次被真数填上，`Cuts` 三档里 `dropped` 有了第一条真记录
（被省掉那条 317 字节、带原文指纹，第三方能核回是哪一段）。
另外两件事要写给接线的人：
**内核第一次当面拒了一次装配**（HTTP 200、原话 0 字节、0 个提议却按正常收尾记 —— 拒得对，改调用方），
**以及一个歪提议会把下一发毒掉**（对端回 400：`arguments must be valid JSON`），
所以「省略它并把省略记进裁剪表」不是排版选择，是通路问题。

这一轮新出两处形状缺陷，都是**改判据表**的事，这份文档不替你定（详 README 第 8 节缺口 10、11）。
**第一处先要纠正本文自己写错的一句**：它一度说 `failure.kind` 与 `failure.status` 互不复核 ——
其实**复核在**（`kind=http ⇒ status≠0`、`kind≠http ⇒ status=0`），而把它撞出来的是一发故意的假 key：
真 401 按 `FailConfig`（取值表写的正是「密钥错」）装配，整发被拒，原话
「config 不是 http 那一类，却带着状态码 401」。于是开着的问题是：**`FailConfig` 那三种成因在 HTTP 上
全都带 4xx，而只有 `http` 那一档许带那个数** —— 一条真 401 要么丢了码记 `config`，
要么为了留住那个数改口记 `http`，而后者把 `RetrySame()` 翻成 true（账上写「原样再发有用」，
实际只会再吃一次同样的 400/401）。中间那一轮把真 400 记成 `http` 就是走通了后者，**内核收下了**：
这条互核挡得住「config 带码」，挡不住「把 config 谎报成 http」，因为类别那一格是调用方自己填的。
另外 `fail_detail` 的出处**跟着状态码走**（`≠0 ⇒ relayed`，否则 `measured`），
所以记 `config` 时把对端原话抄进去，那一格会被标成「我们量的」——
现在调用方只写自己构造的判定句（标 measured 名副其实），代价是那个 401 **只能住在散文里**。
> **上面这两句到 2026-10-13 封板轮为止是历史，别再照它们写代码。**
> 那两条按类别的互核已删除，换成 `FailKind.MayCarryStatus()`（`http`/`config`/`protocol`/`malformed_action`
> = 收到过对端响应，才有码可记），`fail_detail` 与 `fail_status` 两格的出处都跟着这张表：
> 真 401 现在**码照实记、对端原话照实抄并标 `relayed`**，`transport`/`budget` 与没故障的那一发
> 的 `fail_status` 是 `absent` 带理由 —— 「量到状态码 0」这个形状从根上没了
> （在册 27 发全是那个长相）。挡不住「把 config 谎报成 http」那一半仍然成立：类别还是调用方自己填的，
> 这一格依旧没有第二根轴能反证它。详见 报告/假key一发-401.md、报告/挤历史-判生死.md 第 6 节。
第二处：工具提议的**内容**（哪个工具、参数是什么）在账上无处可放，
而 `malformed_action` 一个档位装了两种成因（歪了一个 vs 根本没有），分开它们的只有 `fail_detail` 那句自由文本。

其他三条按 README 第 8 节照搬，不许被写成已验证：

1. **读者声明表是空的**：内核能机械核的是写侧（每个字段都有格替它落账）；
   「落了账但没人读」那一半要接入方声明，内核自己核不到。
2. **隔离闸看不见三条路**：`plugin.Open`、`os/exec` 起一个框架进程、把框架结构体塞进 `Cell.Value` 那个 `any`。
3. **`Failure.Detail` 的脱敏是契约、不是被核过的不变量**（擦码器在框架那一侧，内核 import 不到）。

---

## 5. 接的时候按这个顺序（不含任何改动到别处）

0. **先按封板版的形状对齐三处入参**（`InputMeta`/`OutputMeta` 没有独立 wire 形状，
   键名就是 Go 导出字段名 —— 所以**字段类型变了就是接口变了**，旧写法不会"兼容地跑起来"，会当场拒）：

   | 字段 | 封板后的形状 | 填错的后果 |
   |---|---|---|
   | `Failure.Status` | 不再是裸整数，是一个 Measure 对象：`{"N":401,"Basis":1,"Source":"","Absent":false,"Refused":false,"Why":""}`；没收到对端响应那一类（`transport`/`budget`）与没故障那一发填 `{"N":0,"Basis":0,"Absent":true,"Why":"…为什么没有…"}` | 把"没收到"写成 `N:0,Basis:1` 会被"量到状态码 0"那一族挡下。**交整数目前是静默丢字段**（见下面那条洞），别以为会被拒 |
   | `OutputMeta.WireFormat` / `WireFormatSaid` | 新增两格。装**对端在响应体顶层自报的原字**（`chat.completion` / `chat.completion.chunk`），不是我们自己那套接线常量；没收到响应时两者填 `""` / `false` | 说 `Said=true` 而值是空串 ⇒ 拒；说报了格式却归到 `transport`/`budget` 那一类 ⇒ 拒 |
   | `Cut.RefCall` | 裁剪记录新增一格：被挤掉的那段来自**第几发**。`history` 类必填且 `> 0` 且 `< 当前发号` | 指 0（没说来自哪一发）或指未来那一发 ⇒ 整发拒收 |

   还有一条不需要改字段、但会被新判据挡住的：**`Notice.Sent=true` 必须真在 `Order` 里有
   `truncation-notice` 那一段**（反向同样）。通知段一旦进了历史就会随后续每发一起发出去，
   所以"这一发没发通知"在后面的发上是假的 —— 从真发出去的段里读，别由裁剪表宣称。

   **上面这三条是 2026-10-13 用挂载好的外壳一条条问出来的**（`报告/契约核对-入参形状.txt`，8 项），
   其中一条把契约自己的错抓了出来，而且我第一版把它**写得太重**，这里按实测改准：
   交整数 `401` 时，`kernel.check_call` 回「两侧账：自洽」，而 `kernel.record_call` **拒收**：
   「fail_status 那一格进不了账：有值 0 却没说谁算的」。两件事叠在一起才造成这个现象：
   ① `cmd/mcpkernel` 的 `args[T]` 里 `_ = json.Unmarshal(raw, &v)` **把解码错误丢了**，那个字段静默变成"没填"；
   ② 「忘了填」这一族是在**落账时**由 `CheckCells` 拦的，而 `Check()` 本身不查 —— 于是
   **§5 第 1 步（先问）比第 2 步（落账）松**：它说自洽的那一份，真落账时可能被拒。
   对外的说法只能是：`check_call` 不是担保，别把它当预检通过证。待修（解码错误必须报出来，
   且第 1 步应与第 2 步用同一套严格度），已记为缺口。

1. **先读，不写**：拿一段真实调用，把两侧账构造出来，只调 `InputMeta.Check()` / `OutputMeta.Check()`，看它报什么。
2. **只落账、不落盘**：`Ledger.RecordCall` → `Ledger.Verify()`，确认链自洽、拒收有数。
3. **再谈落盘**：格式用 `MarshalJournal` / `ReadJournal`（见 2.3），**别自己 `json.Marshal(entry)`** ——
   那一条最自然的写法会默认丢掉 `Payload` 的原像。要决定的是 `PayloadMode`：带原像（第三方可重算，
   但敏感原文跟着落盘）或不带（只留指纹，"能重算"那一半从此核不了）。写文件那一步仍是框架做。
   重启后要接着记，用 `LoadLedger` —— 它把旧账真填进账本，去重闸因此看得见历史。
4. **最后谈并发**：`Ledger` **没有锁**，且去重闸 `alreadyRecorded` 每次落账**全账本线扫**（O(N²)）。
   多 goroutine 共用一本账不在承诺之内——要么调用方串行化，要么各用各的账本。

---

## 6. 怎么核这张表（防它漂）

```
py -3 tasks/audit/celltable_audit.py <go.exe 路径> <本包目录> [报告输出路径]
```

它**不复制第二份真相**：实读那一侧就地解析 `go run ./cmd/kcheck` 第 5 节自己印的输出，
文档那一侧解析本文件第 3 节的表，然后逐格对四项 —— 键名、`sides`、字段路径、空样本出处。
报告写进 `报告/格位表一致性-最新.txt`（UTF-8），终端只留一行纯 ASCII
—— 因为 Windows 的 GBK 控制台打不出 `✓`，脚本会**崩在打印那一行**，而崩会被读成不合格（2026-10-13 实测到过一次）。

三态，与闸门同一条纪律：**0 = 一致；1 = 漂了（逐格点名）；2 = 核不了**
（没有 go、闸门没过、表解析不出行）。「核不了」不许被读成合格。

**这一份是 2026-10-13 补的。** 在此之前这里写的是「在 `%TEMP%\kernel-attach` 下的 `cellcount` 子模块里
`go run celltable.go`」，而 `celltable.go` **从来不在这个仓库里** —— 于是「由 `Cells()` 机械导出、不是手抄」
这句话在实际意义上是不可执行的：它靠上一次有人手动跑过。补上这根检之后，改任何一个键名而忘了改这张表，**这里会红**。
已经真红过一次：`fixed_overhead` 那一行的空样本出处写的是 `estimated`，实读是 `unset`（已按代码改回）。

**判据**：`go test ./...` 与 `go run ./cmd/kcheck` 全绿时，这份表才可信
（**测试有几条以 `go test -v` 自己数的为准**，这份文件不抄 —— 抄了就会漂，而漂了的数比没有数更有害）；
表与代码不一致时，**以代码为准，改这份文件**。

---

## 7. 这份文件自己没做的事

- 这份文件写下的那天没改内核（写入前回滚点 `mp-mujmoqkh-25f`）。**但代码之后动过**：
  2026-10-13 的挂载第二轮把读侧三个入口（`CellsOf`/`Keys`/`AbsentKeys`）加了 `session` 这一根轴，
  并补了 `TestCellsOfKeepsTwoSessionsApart` 与慢闸针 `j10`（见 README 2.3 与 `报告/挂载-跨进程实测.md`）。
  这张表与代码不一致时以代码为准 —— 那条纪律今天用上了。
- `owner` / `presence_policy` 两列是**接线视角的提案**，不是内核声明，也没被任何判据守着。
- 没有接入方签名，没有真端点数据——它只是一张表，不是已验证的契约。
- 第 4 节那三处形状缺陷之外，今天还有一条同族的：**读侧曾经少一根轴**（见上一条与 README 2.3）。
  它是「写侧能核不等于读侧能用」的一个具体形状，也是挂成进程之后才暴露出来的。
