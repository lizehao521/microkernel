# 事件层 · 证据索引与置信度

- 生成：2026-10-22（Qoder 架构线，路由 `architecture-visualization` → `system-modeler` 当前态 + `evolution-planner` 目标态，图源 Graphviz DOT）
- 范围：`C:\Users\Admin\Desktop\微内核\微内核\微内核\cmd\agentd` 一个容器。**E1/E2/E3 已落进这棵树**（不是计划态）；E4–E9 仍是计划态，下面两张 DOT 里蓝虚线那部分才是没做的。
- 与 `架构-1020` 的关系：那份答「今天有几块、要新建哪几块」；这份答其中「事件层那一块内部长什么样、八条针钉在哪」。

## 分母从哪来（本文件不印数 —— 印过一次的就会过期一次）

M2 路 B 的 P2-9 点名过：这张表原来写着「本轮实跑/实数，不手抄」，下面却是手抄的三档
（文件数 10、行量 3364、Test 34），到 E2 落地时已经是 15 / 5573 / 66 —— 写着"不手抄"的表底下全是抄的。
现在只列命令，值由命令当场印：

| 读数 | 谁印的 |
|---|---|
| agentd 文件数 / 行量 | `ls cmd/agentd/*.go \| wc -l`、`wc -l cmd/agentd/*.go \| tail -1` |
| Test 函数数 | `grep -h "^func Test" cmd/agentd/*_test.go \| wc -l` |
| 宿主测试结果 | `go test ./cmd/agentd/ -count=1`（工作目录 `微内核/微内核`） |
| 内核快闸 | `go run ./cmd/kcheck` |
| 变异臂（A/B/C 三族） | `臂检-事件层-1022.py`、`臂检-C族-E3.py`，读数落 `读数/臂检-*.jsonl` |
| 端到端真读数（S0–S8） | `冒烟-事件层-1022.py`，读数 `读数/冒烟-事件层.jsonl` |
| graphviz | 本机不存在（`which dot` 空）⇒ **两张 DOT 未渲染 SVG**，布局未经肉眼核验 |

## 当前态节点（每条都能在盘上指到）

| 节点 | 出处 | 置信度 |
|---|---|---|
| stdout 正文由 `r.say` 单点写 | `cmd/agentd/loop.go:216` | 高（代码直读） |
| 诊断/横幅另走一路（不进 stdout） | `loop.go:121` `errf`、`main.go:145` `printEventBanner` | 高（E1 起；由 `TestEmitFailureIsLoudOnStderr` 钉） |
| 停止入口只有一条（进程内与 SIGINT 同路） | `loop.go:130` `Stop` | 高（E3 起；臂 `TestStopEntryIsSingleAndIdempotent`，变异 C6） |
| 循环入口 | `loop.go:221` `loop()` | 高 |
| abort 两处看一眼 | `loop.go:242`、`loop.go:270` `r.abort` | 高 |
| 预检调用点 | `loop.go:309` `kernel.check_call` | 高 |
| 落账调用点 | `loop.go:331` `kernel.record_call` | 高 |
| 回边读回 | `loop.go:454`、`487`、`636`、`rpc.go:105` `kernel.read_back` | 高 |
| 账→决定 | `loop.go:405` `r.decide`（唯一 KPI 来源，调用点 `loop.go:405`） | 高 |
| 续跑先核链 | `loop.go:576` `r.resume` | 高 |
| 收口落盘 | `loop.go:792` `r.checkpoint` | 高 |
| 收口 | `loop.go:753` `closeOut`（verify/tally/读者/checkpoint 都在它里面） | 高 |
| 事件总线：append-only 落点与序号接续 | `events.go:344` `newEventBus`（`O_APPEND` + 从既有日志 seed seq/states/run） | 高（E1 起；臂 `TestEventLogAppendsAcrossRuns`） |
| 一条事件的完整身份是 `(session, run, turn, seq)` | `events.go:337` `blockOf`、`events.go:337`（run 由总线盖） | 高（M2 两路各自撞到跨趟追加会撞回执；**路 B 给的最小修法复算不成立**，缺的是趟轴） |
| 回执 turn_accepted | `events.go:735` `acceptedEv`，挂点 `loop.go:263`，锚点 `loop.go:151` `ackAnchor` | 高（E2；臂 `TestLateReceiptGoesRed` + 生产路径 `TestProductionAckLatencyIsMeasurable`，变异 B1/B2/B3） |
| 回执判据（可达形态） | `events.go:454` `ValidateAcceptsWithin`（`events.go:454` 用契约 100ms） | 高（臂 `TestAcceptArmsCatchEachBadShape` 走盘喂坏值；上限可注入是因为满载实测过 483ms） |
| 结算 settleTurn（一发只结一次） | `loop.go:165` `settleTurn`、`events.go:123` `stopTokens`、`events.go:124` `ValidateSettlement` | 高（E3；臂 `TestSettleTurnIsIdempotent`/`TestSettlementArmsCatchEachBadShape`，变异 C1–C9） |
| 相位表（reached/not_reached 的唯一来源） | `events.go:104` `turnPhases` | 高（`read_back`/`decide` 尚无事件 → 不在表内，缺口记 `u.hook-coverage`） |
| 事件挂点 | `loop.go:236`、`254`、`292`、`311`、`320`、`340`、`365`、`763` `r.emit` | 高（存在性由 `TestEventSeqMonotonicWithinEachTurn` / `TestTurnAcceptedLeadsEveryTurn` / `TestEveryTurnSettlesExactlyOnce` 逐名点） |
| 序号判据的可达形态 | `events.go:552` `ValidateLog`（Emit 里那条不可达死牙已删） | 高（臂 `TestValidateLogArmRejectsDuplicateAndRegress`） |
| 五档 + 状态白名单 + 落盘后才计数 | `events.go:26` `eventStates`、`events.go:570` `Emit` | 高（臂 `TestAbsentWithoutWhyIsRefusedAndNotWritten`） |
| 事件落点推导与撞车守卫 | `main.go:152` `eventLogPath` | 高（臂 `TestEventLogPathDerivationAndCollision`） |
| 轨迹页跑完才写 | `trace.go:89` `writeTrace`，由 closeOut 调 | 高 |
| 六态退出码 | `main.go:149` `exitOf`（0/2/3/4/5/6） | 高 |
| 本机 HTTP/SSE 形状已有先例 | `fakesrv.go:117-134` `Hijacker`、`Flusher` | 高 |
| 内核不写盘、只编字节 | `微内核/微内核/README.md` §2.1；表冻结见 `README.md:631` | 高（§2.1 那半只验存在，尺子点名为「仅存在性」） |

## 目标态（设计假设，不是现状）

E1–E9 全部为**计划**，落点与验收针见同目录 `计划-agentd事件层.json`；契约形状来自 `../研究-协同工作-1022.md` §5.1，
八条针口径来自同文件 §8.2。状态标记：Present/Wired/Exercised 都还不成立，只能说 **Planned**。

## 仍未核清的空洞（不许糊）

1. **两张 DOT 未渲染**：本机无 graphviz，只保证「图源可维护」，未验证布局与出图；要出 SVG 需另一条许可路径（不提议装软件）。
2. **事件层八条针一次都没跑过**：针本身还没写，E9 才是把针变成一条命令的那一发。
3. `E2` 回执 ≤100ms 那条针，`-shot-delay` 与真端点耗时下的实测口径未定；本机目前只有 scripted 的时序可复现。
4. **真模型端点 NOT_RUN、真人可读性 0/1**：事件层做完也只到「机械正确」，不许说成「协同体验已验证」。
5. 断线心跳/半开/代理缓冲那一族（研究件 §9.5）本轮不做，如实记未测。
