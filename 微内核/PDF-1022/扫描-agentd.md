# 扫描 · agentd（用 PDF 的 L1–L5 框架评估）

- 扫描时间：2026-10-22 23:3x。工作区无 git，下文「最新」一律按 mtime 认。
- 对象：Go 宿主 `cmd/agentd`。树根 `C:/Users/Admin/Desktop/微内核/微内核/微内核`（**三层**，少一层 glob 会静默落空）。下文 `cmd/agentd/...:line` 都相对这个树根；事件层的件相对 `C:/Users/Admin/Desktop/微内核/事件层-1022`。
- **只读声明**：本扫描没有跑 `go test ./cmd/agentd`，没有 build/起 exe，没有改任何代码或读数件（另一会话正在改 `cmd/agentd`）。下文所有 `measured` 全部来自**盘上已有读数件**，逐条标 mtime；本轮没有新造读数。需要现跑才能拿的数，一律写 `NOT_RUN` 并给为什么。
- 现数（本扫描自己印，23:3x）：`ls cmd/agentd/*.go | wc -l` = **24**；`wc -l cmd/agentd/*.go | tail -1` = **8143**；`grep -h "^func Test" cmd/agentd/*_test.go | wc -l` = **100**。交接件（mtime 23:29）写的是 24 / 8105 / 100 —— 行量差 38，两个分母不自治。**别抄任何一个**，跑闸前现数。
- `cmd/agentd/README.md` **不存在**（absent）。why：这一面的文档只在 `AGENTS.md`（根与内核树各一份）和 `事件层-1022/*.md`，`ls cmd/agentd/README.md` 无此文件。所以「必读 README」以 `事件层-1022/说明书-闸与尺子怎么跑-1022.md` + 代码替代。

---

## 0 结论（先给级）

**L2（下沿）。** 不是 L1：一发之内不需要人逐步确认，流程自己往下走，人可随时打断。也**够不到 L3**：没有目标拆解、没有结果验证、没有回滚。

更准确的一句：**agentd 是一条预定义 6–8 发的记账流水线**。它真正的工具是内核的 10 个 MCP 件里的 9 个，由循环**写死顺序**调用（预检 → 落账 → 读回）；模型只活在提示词与剧本里，它提议的 `ledger_add` **没有任何执行器**（全树无 `os/exec`，`ToolCalls` 只被计数、不被派发：`cmd/agentd/fakesrv.go:265-275`、`cmd/agentd/wire.go:172`）。

所以它的「L2」只覆盖**流程自主 + 可打断 + 可结算**这三件，**不覆盖**「模型自主选工具」。按 PDF 的核心轴复核，L3 的三条判据（独立拆解目标 / 验证结果 / 异常时回滚）一条都不成立，见 §1 与 §8。

---

## 1 五条核心轴逐条对照

| 轴 | 现状 | 证据 | 判定 |
|---|---|---|---|
| 人类介入频率 | 运行中 **0 次确认**；人只有两个口子：开局 20 个旗标（`cmd/agentd/main.go:28-48`）、随时 SIGINT（`main.go:133-142` → `loop.go:134-148`）。任务本身是编译进二进制的常量，没有输入面（`loop.go:117 userAsk`） | 全树只有一处 `signal.Notify`（`main.go:134`）；无 stdin、无审批提示、无 HTTP 写入口（`sse.go:211 eventsMux` 只挂只读 `/events`） | 形态 **L2**（可打断的固定流程）；但「0 次介入」不是「被信任」，是**没有审批面**（见 §6） |
| 规划自主性 | **0**。计划 = 剧本剩余发数，只有 `scripted` 驱动给得出（`loop.go:245-250 plannedTotal`、`events.go:835-840 plannedLeft`），别的驱动一律 `nil`（`events.go:84` 注释：不知道就 nil，绝不写 0）。无拆解、无子目标、无计划重排 | `cmd/agentd/driver.go:75-109` 两份固定剧本（full 8 发 / happy 6 发） | 不到 **L3** |
| 错误恢复 | **有一张 6 行的 `fail_kind → 动作` 表**（`cmd/agentd/policy.go:16-23`），下一发按它改装配（折历史 / 换说法 / 原样再发 / 停）。**无重试上限、无退避、无回滚**；`RetryAfterMs` 只被记录，**从不拿来等**（`loop.go` 里只有 `time.After(shotDelay)` 与 `time.After(tickIdle)` 两处，:362 / :196） | 见 §4 | **L3 的一半**（识别 + 换招），缺「验证 + 回滚」 |
| 跨域泛化 | **单域**：一个加法记账流程。无第二个域、无外部系统、无多 Agent | `loop.go:113-119` 常量：system/toolspec/用户问题/数字串全是写死的 | 不到 **L4** |
| 安全可控 | 有**记账级**拦截（预检 / 落账原子拒 / 容量 / 核链拒写），**无权限模型、无审批、无沙箱对象**（因为没有可执行的东西） | 见 §6 | **L2**；「危险动作拦截率」等三格是 **NOT_APPLICABLE**，不是 100% |

---

## 2 工具清单（数出来的，不凭记忆）

### 2.1 内核 MCP 工具：注册 10 个，agentd 调用 9 个

注册处只有一份：`mcpsrv/mcpsrv.go:269-286`。`docker-like` 的「工具注册表」就是这张表，宿主用 `kernelRPC.call()` 在**同进程**里走同一条 `Serialize` 路（`cmd/agentd/rpc.go:13-23`、`:30-68`）。

| # | 工具 | 注册处 | agentd 调用点 | 它是干什么的 |
|---|---|---|---|---|
| 1 | `kernel.celltable` | `mcpsrv/mcpsrv.go:269` | **未调用**（只有 `cmd/agentd/same_ruler_test.go:59` 用） | 交出键名表 |
| 2 | `kernel.check_call` | `mcpsrv/mcpsrv.go:270` | `loop.go:402` | 预检：在账的副本上真跑一遍 RecordCall，一条不写回 |
| 3 | `kernel.record_call` | `mcpsrv/mcpsrv.go:271` | `loop.go:424` | 一发两侧整发落账（任一侧不自洽 ⇒ 整发拒收） |
| 4 | `kernel.verify` | `mcpsrv/mcpsrv.go:272` | `loop.go:660`、`:837`、`:878` | 重算整条哈希链（自洽 / 不符 / 核不了） |
| 5 | `kernel.tally` | `mcpsrv/mcpsrv.go:273` | `loop.go:766`、`:882` | 按出处五档分桶 + 被拒次数 |
| 6 | `kernel.read_back` | `mcpsrv/mcpsrv.go:274` | `loop.go:547`、`:589`、`:739`；`rpc.go:105` | 读回某一发某一侧的格（这是「回边」的本体） |
| 7 | `kernel.declare_reader` | `mcpsrv/mcpsrv.go:278` | `loop.go:622` | 声明「我读了这一格」（键名拼错当场拒） |
| 8 | `kernel.readers_report` | `mcpsrv/mcpsrv.go:281` | `loop.go:886` | 报「N 格里 M 格没有任何声明者」 |
| 9 | `kernel.encode_journal` | `mcpsrv/mcpsrv.go:282` | `loop.go:790` | 把整本账编成 JSONL 字节（**不写盘**） |
| 10 | `kernel.load_journal` | `mcpsrv/mcpsrv.go:285` | `loop.go:652`、`:822` | 读回字节顶掉当前账（续跑与回读自证） |

分母口径：非测试代码里 `grep -o "kernel\.[a-z_]*" cmd/agentd/*.go` 现数，出现 9 个不同的工具名；`celltable` 只在测试里出现。**不要把 `celltable` 算进「agentd 用了 10 个工具」。**

### 2.2 宿主自身能力：8 类，都不是「工具」

这些没有 schema、没有注册表、模型不可选——它们是宿主的固定器官：

| 能力 | 落点 | 说明 |
|---|---|---|
| 驱动接缝（4 路） | `driver.go:16-22`、`:111-132` | `scripted`（本地剧本，不开 socket）/ `fake`（本机真 HTTP 端点）/ `real`（只回 NOT_RUN）/ `session`（未接） |
| 本机假端点 | `fakesrv.go:31-44`、`:107-183` | 真开 `127.0.0.1:0`、真发 HTTP、真数字节；**它不是模型**（`fakesrv.go:19-22`、`:310`） |
| 事件总线 + SSE 投送 | `events.go:355`、`sse.go:146`、`:200` | append-only；投送层只读日志，不另起第二本账 |
| 轨迹解剖页 | `trace.go:89 writeTrace` | **跑完才写**（`closeOut` 调），事后审计件 |
| 往轮轨迹（transcript） | `loop.go:691 appendTranscript`、`:713 rebuildHistory` | 账里存不下原文，宿主自己留文本 + 用账上 sha 对指纹 |
| checkpoint / resume | `loop.go:788 checkpoint`、`:645 resume`、`:814 verifyRoundTrip` | 编字节 → 宿主写盘 → 另起空账读回核 |
| 事件判据（一条命令） | `checklog.go:18-49` | `-check-log`：四支判据，0 全绿 / 4 有红 / 2 读不动 |
| CLI 旗标 20 个 | `main.go:28-48` | 其中 15 个影响行为，5 个只是落点/身份 |

### 2.3 最容易被误读的一格：`ledger_add`

提示词与 tool spec 里声明了一个工具（`loop.go:114-116`：`toolspec` 只给 `ledger_add`），剧本里也有一条「参数没填全」的提议（`driver.go:89`）。但：

- **没有执行器**：全树无 `os/exec`、无工具派发函数；`ToolCalls` 只进 `OutputMeta.ToolCalls`（`wire.go:172`），`Malformed` 只进元数据（`wire.go:253-255`）。
- 也就是说：**「模型选工具」这一层在 agentd 里不存在**，存在的只是「模型说了一句话，宿主把这句话的字节数与 sha 记进账」。这是本扫描最该先说的口径，否则会把 L2 读成「能自主调工具」。

---

## 3 典型任务流程（入口 → 收口，逐段给 path:line）

1. **入口**：`main.go:143 r.tRequest = time.Now()`（针1 的锚点：进程拿到任务那一刻）→ `main.go:144 r.say(userAsk)` → `main.go:155 r.loop()`。任务是常量，**没有输入参数**（`loop.go:117`）。
2. **驱动选择**：`main.go:63 buildDriver(*driverName, *script)`。选谁由**旗标**决定，不由模型决定；`real` 只检查 env 有没有凭据，没有就回 `NOT_RUN`（`driver.go:54-58`），有凭据也说「这一版还没接」。
3. **每发起点**：`loop.go:327 turnEnter` → `:330-337` 先看 abort（被打断就不写假回执）→ `:338-345` 剧本跑完 / 额度到 → `:352` 回执（`acceptedEv`，`events.go:819`）先落盘 → `:356 startTick()` 挂 10s 看门狗 → `:360-368` `-shot-delay` 窗口（可被打断）。
4. **装配**：`loop.go:370 assemble()`（`loop.go:291-317`）：system + toolspec + [history | 折成桩] + user + observation。折历史 / 换说法两个旗标来自**上一发账上读回的决定**（`:294-297`）。
5. **驱动出提议**：`:379 r.drv.Propose(...)`。`scripted` 按数组顺序取（`driver.go:37-45`），`fake` 真发 HTTP（`fakesrv.go:200-278`），`real/session` 回错。
6. **发号**：`:393 r.shot = call` 只有真要发出去的那一发才占号。
7. **预检**：`:402 kernel.check_call`。回帧坏 ⇒ failed 收口停（`:407`）；预检 `IsErr` ⇒ `refused` 结算后 **continue 下一发**（`:419-420`），这一发一条都不写。
8. **落账**：`:424 kernel.record_call`。被拒分两种：账满 ⇒ 结算 `refused` + `stop=capped` 退出（`:456-458`）；其他拒 ⇒ 结算后 continue（`:463-464`）。
9. **回边（唯一 KPI 来源）**：`:475 readBackCell()`（`:543-560`）读 `output/fail_kind`；读不到就把这一发记为「本地信息，没问内核」，KPI 不加。读到且与驱动当场给的 `Fail` 不漂移 ⇒ `r.kpi++`（`:504`）。
10. **账 → 下一发**：`:496-499` 用 `POLICY[fail]` 选动作；`:570 decide()` 落两个旗标（budget ⇒ 折历史，malformed ⇒ 换说法）。动作以「停」开头 ⇒ 结算 `completed` + `stop=policy` 退出（`:514-518`）。
11. **结算**：`:523 settleTurn("completed", ...)`；`settleTurn` 是唯一收口函数（`:254-287`），`interrupted / failed / refused / completed` 都走它，`settled` 标志保证一发只结一次；相位表 `turnPhases`（`events.go:120`）算 reached / not_reached。
12. **收口**：`main.go:156 closeOut()` → `loop.go:846-912`：关看门狗 → 印补位失败 → `run_settled`（`stop` token + `stop_why` 整句 + done/total/limit）→ `verify / tally / readers_report` → `checkpoint("收口")` → 写轨迹页 → `os.Exit(exitOf(stop))`（`main.go:161`、`:203-218`）。

**规划 / 反思 / 回滚三件，逐条：**

| 件 | 有没有 | 证据 |
|---|---|---|
| 规划 | **无**。只有「剧本还剩几发」这一个静态计数 | `loop.go:245-250`、`events.go:835-840` |
| 反思（对账目） | **有 4 件**：`driftOf` 比对读回值与当场值（`policy.go:39-41`、`loop.go:490-495`）；`confirmFold` 回账确认折叠真落了（`loop.go:585-611`）；`verifyRoundTrip` 另起空账读回核（`loop.go:814-844`）；收口 `verify+tally+readers_report`（`:878-890`） | 都是**记账自检**，不是「答案对不对」的自检 |
| 反思（对任务结果） | **无**。没有 oracle、没有算一遍 84、没有把答案回写再校验 | 全树唯一的「结果」是剧本里的那句话；`ledger_add` 不执行 |
| 回滚 | **无**。append-only，落进去的账不可撤。存在的两个近似物：① 一发被拒时**整发不写**（49 格原子，`mcpsrv.go:421-450`）；② 续跑**核链不符就拒写**（`loop.go:662-668`，rc=2）——这是「拒绝往下写」，不是「撤回已写的」 | `events.go:367-369`（O_APPEND 注释）、`loop.go:645-673` |

**人类打断点（全部）：**
- SIGINT：`main.go:133-142`（`signal.Notify(sigs, os.Interrupt)`）→ 同一入口 `r.Stop("signal:SIGINT")` → 循环在发首（`loop.go:330`）或 `-shot-delay` 窗口（`:363`）看见 abort → 结算 `interrupted` → 照常 `closeOut()`。**先交账再走**。
- 进程内 `Stop(why)`：`loop.go:134-148`（同锁判「关过没有」，重复叫停不炸；why 只记首发）。
- 额度 `-max-turns`（`main.go:33`、`loop.go:342`）、容量 `-entry-cap`（`main.go:39`、`mcpsrv.go:424`）、`-checkpoint-every`（`main.go:34`、`loop.go:531`）。
- **没有**：运行中审批、暂停/继续、单步确认、第二发入口（E6 已复算「没有产品落点」，见交接 §4 第 3 条）。

**结算与重试：**
- 结算 = `settleTurn`（发级）+ `run_settled`（趟级，`loop.go:860-872`）。趟级 `turn=0` 且不带 step，六态 token 走 `stop`，整句走 `stop_why`（`events.go:57-58`、`ValidateTurnShape` `:562-572`）。
- 重试 = **不是重试循环**，是「下一发换装法」：transport/http 原样装、budget 折历史、malformed 换说法、config/protocol 停。**没有次数上限、没有 `RetryAfter` 等待、没有熔断、没有死信**（`policy.go:16-23` vs `loop.go` 全文无 `RetryAfterMs` 消费点）。

---

## 4 错误恢复：哪些有真负载、哪些只有单测、哪些 NOT_RUN

### 4.1 六态退出码（`main.go:17-24`、`exitOf` `:203-218`）

| 码 | 含义 | 端到端（真 exe）证据 | 只有单测 / 未测 |
|---|---|---|---|
| 0 | 跑完剧本 | `事件层-1022/读数/冒烟-事件层.jsonl:6`（S5 `script=0`，mtime 23:26） | — |
| 2 | 这一路跑不了 | 同 S5 `real=2`、`bad_resume=2` | — |
| 3 | 轮次额度到 | 同 S5 `turns=3`；`读数/真负载-E5兜底进度-1022.txt:4`（`run rc 3`，23:24） | — |
| 4 | 账上 `fail_kind` 指向停 | **无**。S5 只测了 0/2/3/5（`冒烟-事件层-1022.py:134-144`） | `TestPolicyStopsOnConfig`（`agentd_test.go`）单测；`-check-log` 也用 4，**同码两义**（`checklog.go:16-17` 自认「沿用这两个」） |
| 5 | 账到上限 | S5 `capped=5` | — |
| 6 | 外部打断 | **无**（没有一支测试给子进程发过信号：`grep Process.Signal|os.Interrupt` 在 `*_test.go` 里 0 命中） | `TestInterruptSettlesWithinSecond` 走**进程内** `r.Stop`，断言 rc=6（`events_settle_test.go:87-89`）。OS 级 SIGINT = **NOT_RUN**（交接 §3 明写） |

> 结论：六态里 **4 个**有真 exe 读数（0/2/3/5），**1 个**只有单测（4），**1 个**只有进程内单测、OS 级 NOT_RUN（6）。别把「六态退出码未改」读成「六态都端到端验过」。

### 4.2 `resume / checkpoint / run_settled / resume-lost`

| 件 | 状态 | 证据 | 能说什么 / 不能说什么 |
|---|---|---|---|
| checkpoint（每 N 发编账写盘） | measured | `loop.go:788-810`；`TestCheckpointLoadsSelfConsistent`、`TestCheckpointEveryNLeaksNothingToTheLastShot` | 写盘是宿主的动作（内核只交字节）；编出的字节能被**另一本空账**读回核（`:814-844`） |
| resume（跨进程续跑） | 部分 measured | ① 真 exe 三步（**修前**）：`事件层-1022/收口表-M5.md:70`（`读数/收口表-M5.jsonl:34`，22:02）——第 2 程打印「读回 294 条 = 6 发 / 发号从第 7 发接着走」，第 3 步 `-check-log` **rc=4**（结算判据红）；② 修后：`TestResumedRunContinuesTurnAxis`（`events_resume_axis_test.go:17-108`）走**同进程两个 run 对象** | 能说：发号轴已接续、合并日志四支判据全绿（单测层）。**不能说**：修后**没有**一次真 exe 的跨进程续跑读数落盘（`grep S-RES` 只命中收口表与它的 jsonl）。exe 级 = **NOT_RUN** |
| 核链不符拒写 | measured（单测） | `TestResumeRefusesInconsistentLedger`、`TestHostRoundTripRefusesTamperedFile`；代码 `loop.go:658-668` | 拒写 rc=2；这是「拒绝」，不是「回滚」 |
| 往轮原文重建 | measured（单测） | `TestResumeRebuildsHistoryOnlyWhenFingerprintsMatch`；`loop.go:713-760` 对两遍 sha（文件自报 + 账上 `model_says_sha256`） | 对不上就不带这一段；matched=0 就整趟不带历史 |
| `run_settled` 必在 | measured | 判据 `ValidateSettlement`（`events.go:140-…`）+ `TestRunSettledPresence`；M5 P1-4 修后只对「有 run_started 的趟」要求 | 修前「整本没有 run_settled 四支全绿」是真缺陷（收口表 P1-4） |
| `resume-lost` | measured（单测 + 真 HTTP） | `sse.go:169-186`（接不上但老实说不可续 ⇒ 先发一帧 `event: resume-lost`）；`TestResumeLostIsDistinguishable`；臂 I6 | 修前「200 + 零帧」与「真追平」逐字同形，客户端分不出来（P1-1） |

### 4.3 被拒/失败那一族：11 处 `settleTurn`，7 处有负载、4 处公开路径不可达

分母自印：`grep -c "settleTurn(" cmd/agentd/loop.go` = **12**（1 处定义 + **11 处调用**，`loop.go:364/375/384/389/407/419/429/456/463/515/523`）。件里自己印的命中表在 `cmd/agentd/events_refused_load_test.go:14-22`：

- 有负载 7 处：`364 interrupted`（打断两支）、`384 failed-NOT_RUN`（新针 A）、`389 failed-端点没有下一条`（新针 B）、`419 refused-预检拒收`（新针 C）、`456 refused-账满`、`463/515/523 completed 支`（多支）。
- **不可达 4 处**：`375 装配散`、`407/429 回帧坏`（进程内 RPC 永不返回传输错）、`463 refused-落账拒非账满`（预检的 `checkBoth` 已在副本上跑过，任何 record 拒都先被 419 抓到）。这不是「没测」，是「产码里走不到」——按房规应记 `NOT_APPLICABLE` + 给这条理由，不许挂成未决。

### 4.4 重试/降级的三处口径缺口（读码即见，不需要跑）

1. `POLICY[http] = "等一等再原样发"`（`policy.go:19`），但**没有任何等待**；`RetryAfterMs` 从 `proposal` 一路进账（`wire.go:231-235`）就结束了。真端点若靠 `Retry-After` 限流，这一版会立刻重发。
2. 重试**无上限**：`-max-turns` 是总发数上限，不是「同一故障重试几次」。transport/http 连续失败会一路烧到额度。
3. `-shot-delay` 是**所有发**的固定延迟，不是退避；把它当退避会同时拖慢正常发。

### 4.5 三态总表（错误恢复这一块）

| 类 | 真负载（真 exe / 真 socket） | 只有单测 | NOT_RUN |
|---|---|---|---|
| 5 类注入故障（transport/http/config/protocol/malformed） | `fake` 驱动真过网线（`fakesrv.go:107-183`）；`TestFakeEndpointMakesWireBytesMeasured` 等 | 剧本那一路（不开 socket，过网线字节记 absent） | **真模型端点**（`driver.go:54-58` 恒 NOT_RUN） |
| 打断 | `-shot-delay` 窗口可被打断（S? 未单列）；E5 真负载 rc=3 | 进程内 `Stop` 两支 | **OS 级 SIGINT**；`-race`（需 cgo，本机 `go: -race requires cgo`） |
| 续跑 | 修前 1 趟三步（红） | 修后组合针 | 修后 **exe 级跨进程** |
| 并发安全 | — | 静态读码（`Emit` 全程持锁） | `-race` = NOT_RUN ⇒ **并发安全是「未确证」** |

---

## 5 跨会话记忆：能召回什么，不能召回什么

### 5.1 机械召回（有，且有指纹核）

| 载体 | 能召回 | 证据 |
|---|---|---|
| 账（49 格 × 每发） | 每发的**元数据**：字节数、段数、sha256、token 估/转述、故障类别、状态码、finish、折叠切表 | `wire.go:70-127`（输入侧 20 格）、`:159-257`（输出侧 29 格）；`trace.go:165-196` 一页摆出 49 格 |
| `read_back(session, call, side)` | 某一发某一侧的格值与出处 | `rpc.go:101-110`、`mcpsrv.go:474-498`；身份三轴（session+call+side） |
| checkpoint / resume | 整本账 + 发号基线（`turnFloor`） | `loop.go:645-673`；`TestResumeContinuesAndRefusesSecondRecording` |
| transcript（宿主自留） | 往轮**原文**；用账上 `model_says_sha256` 两遍对指纹 | `loop.go:691-760` |
| 事件日志（append-only，跨趟接续） | 每一发的过程 + 身份四元组 `(session, run, turn, seq)`，可重放 | `events.go:45-51`、`:355-399`；`sse.go:16-22`；`TestCrossRunLogStaysJudgeable` |

**跨进程续跑的证据等级**（这条要写清）：修前有**一次真 exe 的三步现场**（第 2 程真读回 294 条、发号从 7 起），且它当场暴露了「发号轴与载荷轴不同源」的真缺陷（`events.go:194` vs `loop.go:187`，收口表 P1-2）。修后（`turnFloor` + `turnNo()`，`loop.go:63`、`:963-966`）只有**同进程两 run** 的组合针（`events_resume_axis_test.go:17`），**没有再跑一次真 exe 跨进程**。所以「跨进程续跑」今天能说的是：机制在、单测钉住了发号轴、修前现场证明过它能通；**不能说**「修后在真进程上复验过」——那一格是 `NOT_RUN`。

### 5.2 语义记忆：**NOT_APPLICABLE**，不是「没做」

PDF 的场景是「隔几轮再问之前提到的约束、偏好或数据」。agentd：

- 全程只有**一条**用户消息，而且是常量（`loop.go:117 userAsk`）。没有第二轮人类输入，没有「之前提到的约束」这种东西可存。
- 没有键值存储、没有向量检索、没有摘要记忆、没有用户画像；`session` 只是一个字符串旗标（`main.go:32`），不是身份或账户。
- 唯一的「历史」是**上一发模型自己的回答**（`loop.go:525-529` 把 `p.Text` 追加进 `historyOrig`，下一发装回去），以及折叠后的桩 + 指纹。

所以这一格记 **NOT_APPLICABLE**，why = 「没有多轮人类输入面，也没有约束/偏好存储；要测这条得先加输入面与记忆件，属于新增能力，不是补测」。若硬要测，只能用 `-resume` 造「跨进程记得上一趟的模型原话」，那测的是 5.1 的机械召回，**不是**语义记忆。

---

## 6 安全边界：哪些是防线，哪些只是审计层

| 件 | 它实际做什么 | 是防线还是审计层 | 证据 |
|---|---|---|---|
| `kernel.check_call` 预检 | 在**账的副本**上跑一遍落账判据；拒了就不发、不写 | **防线**，但防的是「账不自洽」，不是「越权」 | `mcpsrv.go:270`、`loop.go:402-421` |
| `kernel.record_call` 整发原子 | 任一侧不自洽 ⇒ 整发拒收、两侧都不写 | **防线**（数据完整性） | `mcpsrv.go:271`、`:421-450` |
| `-entry-cap` 容量 | 账到上限就挡，且**不计进 KPI** | **防线**（资源上限），不是权限 | `main.go:39`、`mcpsrv.go:424-430`、`loop.go:438-458` |
| `resume` 先核链 | 链不符/读不出原像 ⇒ 拒写 rc=2 | **防线**（防把坏账往下传） | `loop.go:658-668` |
| 无执行面 | 无 `os/exec`、无 shell、无插件加载；写盘只有 4 条路径，全部来自旗标（journal / events / transcript / trace） | **最强的一条防线**：模型文本没有可达的执行/写路径 | `grep os/exec` 0 命中；`loop.go:701/803`、`events.go:369`、`trace.go:265` |
| 只绑回环 | 投送层 `127.0.0.1:0`；假端点同样 | **防线**（网络面收口） | `sse.go:200-207`、`fakesrv.go:36` |
| 密钥只走 env | 只**读** `AGENTNES_KEY` / `AGNES_KEY` 判有没有，不打印、不落盘 | **防线** | `driver.go:55`（全树唯一 `Getenv`） |
| `declare_reader` / `readers_report` | 记录「谁读了哪一格」；键名拼错才拒 | **审计层**。它不阻止任何读取，只让「死格」可见 | `loop.go:614-633`、`mcpsrv.go:499-517` |
| `tally` / `verify` / 事件日志 / 轨迹页 | 事后可核 | **审计层** | `loop.go:878-890`、`trace.go:89` |
| 权限 / 审批 / 沙箱 | **不存在**（没有可授权的对象，也没有审批入口） | 不适用 | 全树唯一 `signal.Notify`；无 HTTP 写入口 |

**三格必须写 NOT_APPLICABLE，不许写 0 或 100%：**
- 越权操作率：没有主体/客体/权限模型，也没有外部系统可越。
- 敏感信息泄露率：账里只有元数据与 sha（`events.go:167-175` 只记 `Says.Bytes/Kept/SHA256`；`TestEventsCarryNoPayloadText` 钉「事件不带原话正文」）；没有敏感数据源。
- 危险动作拦截率：没有危险动作面。「挡得住」在这里是**没有这个东西**，不是「挡住了」——这是本现场的房规，别混。

**一处操作面的开放问题（不是模型面的）**：`--events-out` 不给时默认落 `--journal-out` 同位置（`main.go:167-181`），而 `--journal-out` 默认是固定共享 TEMP 路径（`main.go:220-222`）。两趟并发会写同一本事件日志；加 `run` 轴后判据不再假红，但「要不要拦」仍是口径问题（`验收-E2-合并-1022.md`「还欠的」第 3 条）。

---

## 7 最近读数与失败（带 mtime；不手抄分母）

### 7.1 读数件

| 件 | mtime | 现数（原文） | 能说什么 | 不能说什么 |
|---|---|---|---|---|
| `事件层-1022/读数/臂检-全部族.jsonl` | 23:30 | 71 根：`BIT 70 + BIT(进程崩，症状可见) 1`；`control_rc` 全 0 | 判据在这棵树上咬得住；对照全绿 | 不覆盖「合法 resume 日志」与「判据被摘平成恒绿」两族（收口表 §四） |
| `事件层-1022/读数/冒烟-事件层.jsonl` | 23:26 | 9/9；S7 结构支 rc=0、**预算支 rc=4（最大 ack_ms=288）**；S8 GREEN；exe sha `27e44107febf` | 回执/结算口径在真 exe 上成对；288ms 是**发现**不是闸 | 不覆盖 20–50 次重复；不覆盖 rc=4/6 |
| `事件层-1022/读数/真负载-E5兜底进度-1022.txt` | 23:24 | 14 行；`progress_tick elapsed_ms=10089`（turn1）与 `22140`（turn2）；`run_settled stop=turns`；`-check-log` 四支 GREEN（ack 60000）；exe 14,317,056 B / md5 `e68dec80…` | 10s 兜底在真 exe 上落到了第 10 秒；额度夹住计划 | 只 1 趟、2 发；不能当稳定性基线 |
| `事件层-1022/读数-锚点核对.txt` | 23:20 | 27/27 命中；两臂有效 | **对它跑的那一刻的树**成立 | 见 7.2：loop.go 23:22 又改过，**这份比源码旧 2 分钟** |
| `事件层-1022/读数-证据模型核对.txt` | 23:20 | 34 节点 / 23 边 / 102 refs（符号可核 32、仅存在性 70）；四臂能红 | 证据模型自洽 | 不覆盖本轮新件（尺子分母未登记，工具债 #117） |
| `事件层-1022/读数/E4真负载.jsonl` | 20:26 | 10 步 / 9 过 / 0 红 / 1 未测；S9 三趟 rc `[0,0,0]`、96 条事件；S11 有结算的发 18、对不上的 0；S14 坏游标 409；S16 半路被杀 rc=4 点名半结算 | 3 趟重复下结构稳定、判据会红 | 3 趟 ≠ 20–50；S13b（停笔后重放两次）**NOT_MEASURABLE**（投送层随进程生死） |
| `事件层-1022/收口表-M5.md` | 22:02 | 41 项：过 26 / 警告 6 / 失败 2 / 未测 1 / 部分真 2 / 真 4 | 逐项三态、5 条 P1 的复现读数 | 它的 P1-2/3/4/5/6 已在 22:4x–22:5x 修（交接 §2c），**表未回写**；引用时要写明「修前」 |
| `AgentHub-1021/报告-验收.txt`、`编程Agent-1020/报告-验收.txt` | 14:51 | 各有现数 | 那是**另外两面**的读数 | **agentd 没有 `报告-验收.txt`**（absent；why：这一面的读数件在 `事件层-1022/读数/` 与 `微内核/微内核/微内核/报告/`，没有按面落一份验收 txt） |

### 7.2 最近失败 / 尺子自身的问题

1. **收口表 22:02 的两条「失败」仍成立**：① 判据被摘平成恒绿时冒烟**不红**（9/9，`收口表-M5.md:62`）；② 两族坏法可带四道闸全绿过关（`:82`）。第一条今天仍没有反臂。
2. **锚点读数比源码旧**：`读数-锚点核对.txt`（23:20，27/27）之后 `loop.go` 在 23:22 又被改过（现 966 行，件里印 955 行）。按现树手工核两条：`evidence.md` 写「循环入口 `loop.go:221` `loop()`」，现树 `loop()` 在 **319**，218–223 窗口里没有 `loop`；写「预检调用点 `loop.go:392` `kernel.check_call`」，现在在 **402**，389–394 窗口里没有 `check_call`。⇒ 那 27/27 对**现树**不成立，至少要重跑一次尺子（本轮只读，没跑）。
3. **计划件与交接件对 E5 的口径打架**：`事件层-1022/计划-agentd事件层.json:188` 仍是 `"status": "Planned"`（mtime 19:31），而 `evidence.md`（23:27）与交接（23:29）都写 E5 已落码有针有臂；`evidence.md` 自己又写「状态以计划 JSON 的 status 为准」。两个 owner，一个旧。引用 E5 状态时必须两处都写。
4. **真负载抓到过的真 defect（已修，留作「负载有用」的证据）**：`-shot-delay 12s -max-turns 2` 那趟补位写成 `done=1 total=6 limit=2`（剧本 6 发、额度 2 发）；修法是 `plannedTotal()` 夹到额度 + why 里写明（`loop.go:182-189`、`:204-212`）。改后读数：第 10 秒 `elapsed_ms=10089`、`total=2=limit`。
5. **C2 曾 `CONTROL-NOT-GREEN`**（交接 §2d）：64 根那一趟里「打断后 1 秒交账」计时针在并发编译下不绿，那一趟读数**作废**；23:30 这趟 `control_rc` 全 0。计时型针会抖，别当恒绿。
6. **`-race` NOT_RUN**：本机 cgo 关，`go: -race requires cgo` ⇒ `eventBus` 三个共享态（`seq/written/states`）只有静态读码支撑，**并发安全是「未确证」**，不是「测过没问题」。
7. **人可读性 0/1**：`resumable:false` + 那句 why 给界面当底，**没人看过**（交接 §3）。这条对 PDF 的「安全可控」是空白，不是绿。

---

## 8 表 A · 6 场景 × 现状/证据/状态/缺什么

> 状态只用三态：`measured`（有盘上读数）/ `NOT_RUN`（能测，本轮或本机没测）/ `NOT_APPLICABLE`（这个面上没有这件事）。一格写两态时，是**两件不同的事**分别标，不是塌成一态。

| # | 场景 | 现状 | 证据 | 状态 | 缺什么 / 为什么 |
|---|---|---|---|---|---|
| 1 | 模糊目标拆解 | 没有输入面：任务是常量「把 27、15、8、34 加起来」；没有 planner、没有子目标、没有澄清提问 | `loop.go:117`；`loop.go:245-250`（计划=剧本余发）；`driver.go:75-109`（两份固定剧本） | **NOT_APPLICABLE** | 缺**任务入口**（现在是编译期常量）、缺拆解器、缺子目标状态与验收。要测这条不是补测，是新增一层；本报告不把它挂成未决 |
| 2 | 工具失败恢复 | 6 行 `fail_kind→动作` 表；注入 5 类故障后 4 类接着跑、1 类按 POLICY 停；预检/落账被拒时整发不写、下一发继续；`fake` 驱动真过网线跑同样 5 类 | `policy.go:16-23`；`driver.go:81-96`（full 剧本故障序列）；`fakesrv.go:107-183`；`events_refused_load_test.go:14-22`（7 处有负载 / 4 处不可达） | **measured**（剧本 + 假端点） | 缺：真端点上的同类恢复（NOT_RUN）；重试上限/退避/`Retry-After`（读码即见没有）；**异常恢复率没有比值读数**（见 §9） |
| 3 | 长链路任务（6–10+ 步，含校验、回写） | 最长一条链是 full 的 8 发（每发 4 相：accept/work/check_call/record_call）；happy 6 发；单趟真实 E5 只 2 发 | `driver.go:81-96`；`冒烟-事件层.jsonl:7`（S6 done=6/total=6/limit=20）；`真负载-E5兜底进度-1022.txt:6-11`（2 发） | **measured**（6–8 发链） | 缺：10 步以上的链；**结果自校验**（没有 oracle，账只核哈希链不核算术）；「回写」这一步不存在（没有外部系统）；死循环/冗余率没有读数 |
| 4 | 跨会话记忆 | 机械召回有：账 49 格元数据、read_back、checkpoint/resume、transcript 两遍 sha 对指纹、事件日志跨趟 append + 四元组重放。语义召回没有：只有一条固定用户消息，没有约束/偏好存储 | `loop.go:645-760`；`events.go:45-51`、`:355-399`；`events_resume_axis_test.go:17`；`收口表-M5.md:70`（修前真 exe 三步） | **measured**（机械召回）/ **NOT_APPLICABLE**（语义召回） | 机械召回缺：**修后 exe 级跨进程**复验（`NOT_RUN`）；语义召回缺：多轮人类输入面、约束存储、检索、以及「隔几轮再问」的题面。why：本件从设计上就没有「用户偏好」这一格 |
| 5 | 安全边界（诱导越权 / 敏感数据 / 危险动作） | 最强的一条是**没有执行面**（无 exec、无 shell、写盘 4 条固定路径、只绑回环、密钥只读 env）；记账级拦截有预检/原子拒/容量/核链拒写 | §6 全表；`driver.go:55`；`sse.go:200-207`；`loop.go:402-421` | **measured**（结构性缺面）/ **NOT_APPLICABLE**（三格比率） | 缺：权限模型、审批入口、注入面（没有外部输入可注入）；「越权操作率 / 泄露率 / 危险动作拦截率」**没有分母**，不许写 0 或 100%；真人可读性 0/1（无人看过） |
| 6 | 重复运行稳定性（20–50 次） | 最大重复数：E4 三趟同落点（rc 0/0/0）、冒烟 4 趟（pass1–4）、臂两遍、`same_ruler_test.go:111` 的 8 次连跑（比字节） | `读数/E4真负载.jsonl:2`（96 条、18 结算）；`收口表-M5.md:45`（两遍非易失字段 0 漂）；`臂检-全部族.jsonl`（71 根，23:30） | **NOT_RUN**（20–50 档）/ **measured**（n=3–4） | 缺 20–50 次的成功率、失败边界、成本报表（PDF 的 L4 判据）。现有 n 太小，**不能**用 3 趟的 0 漂说「稳定」；跑 20–50 需要批准（本轮只读、且 cmd/agentd 正被并发修改） |

---

## 9 表 B · 7 指标 × 有没有读数/值/来源/状态/为什么缺

| # | 指标（PDF） | 有没有读数 | 值 | 来源 | 状态 | 为什么缺 / 口径 |
|---|---|---|---|---|---|---|
| 1 | 任务完成率 / 目标达成率 | 有「收口率」，**没有**「目标达成」 | 收口 3/3 趟（rc 0/0/0，96 条事件、18 发结算）；冒烟 9/9；E5 真负载 1 趟 rc=3（额度到，按设计） | `读数/E4真负载.jsonl:2`（20:26）、`冒烟-事件层.jsonl`（23:26）、`真负载-E5…txt:4`（23:24） | **measured**（收口）/ **NOT_APPLICABLE**（目标达成） | 「办成事」没有 oracle：`ledger_add` 不执行，84 是剧本里的话；账只核哈希链，不核算术。把「rc=0」说成「任务完成率 100%」是升格 |
| 2 | 工具选择准确率 / 参数正确率 | **没有** | 分母 = 0（可选工具集只有 1 个声明件，且不执行） | `loop.go:114-116`（只声明 `ledger_add`）；`fakesrv.go:265-275`（只数 `ToolCalls`/`Malformed`）；全树无执行器 | **NOT_APPLICABLE** | 没有「从 N 个工具里选」这件事，也没有参数 schema 校验/执行。「Malformed=1」是剧本注入的一个计数，不是准确率的分母 |
| 3 | 异常恢复率 | 有形状，**无比值** | 5 类故障 / 1 趟：4 类下一发继续、1 类（config）按 POLICY 停 | `driver.go:81-96`；`policy.go:16-23`；`events_refused_load_test.go` | **measured**（形状）/ 比值**NOT_RUN** | 没人把「遇到的故障数 ÷ 恢复数」印出来；且 n=1 趟、全注入。真端点 = NOT_RUN |
| 4 | 人工介入频率 | 有（结构性 0） | **0 次/趟**；人只出现在开局旗标与 Ctrl-C | `main.go:28-48`、`:133-142`；全树唯一 `signal.Notify` | **measured** | 这个 0 不是「被信任」，是**没有审批面**。按 PDF 它落在 L2 的「流程内自主」；别把 0 读成 L4 的「仅高风险审批」 |
| 5 | 多步连贯性 | 有结构读数，**无语义读数** | 6 发链；S8 `有未走到步骤的份数=0`；`done=6/total=6`；history 折叠经账上 `input/folded` 确认；往轮原文与账上 sha 逐发对上 | `冒烟-事件层.jsonl:9`（23:26）；`loop.go:585-611`、`:713-760`；`TestFoldIsConfirmedFromTheLedgerNotFromTheFlag` | **measured**（结构）/ **NOT_RUN**（语义） | 「上下文丢没丢」有结构证据；「前后矛盾」没有题面（剧本每句写死，矛盾不可能出现）。真模型下会不会丢 = NOT_RUN |
| 6 | 安全护栏（越权率/泄露率/拦截率） | **没有比率**；有结构性缺面与 4 条防线 | 见 §6：无执行面、4 条写路径、只绑回环、密钥只读 env、预检/原子拒/容量/核链拒写 | `§6` 各行 | **NOT_APPLICABLE**（三格比率）/ **measured**（缺面与防线） | 没有权限主体、没有敏感数据源、没有危险动作可拦 ⇒ 比率没有分母。写 0 或 100% 都是假账 |
| 7 | 成本与延迟 | 有部分 | `ack_ms` 最大 **288 ms**（23:26 冒烟，预算 100 判红）；E4 三趟最大 **17 ms**（20:26）；单趟 `elapsed_ms` 逐事件；token 只有**对端自报** | `冒烟-事件层.jsonl:8`；`E4真负载.jsonl:3`；`events.go:62`、`:85`、`:656-658`；`wire.go:200-209` | **measured**（ack 最大 + elapsed）/ **NOT_RUN**（P95/P99、真实成本） | P95/P99 缺：n=3–6 趟，不够分位；无真端点，token 是 fixture 自报（`relayed`），没有计价、没有单任务成本汇总。288 ms 那一发是**机器负载**下的读数，只当发现 |

---

## 10 「剧本绿」与「真模型绿」必须分开

| 绿 | 谁走出来的 | 能说什么 | 证据 |
|---|---|---|---|
| 剧本绿 | `scripted`（固定 8/6 条提议） | 循环、结算、事件、判据在这条固定形状上成立 | `driver.go:27-45`、`:75-109`；横幅自己会说（`main.go:59-61`：「这一路是剧本走出来的绿，不是模型自主决定的绿」）；轨迹页也印（`trace.go:118-120`） |
| 假端点绿 | `fake`（真 socket、真数字节，但**不是模型**） | 5 类故障在真管路上可分；`chunks/first_byte_ms/max_gap_ms` 第一次可量 | `fakesrv.go:19-22`、`:310`；`TestFakeEndpointMakesWireBytesMeasured` |
| 真模型绿 | `real` / `session` | **什么都没有** | `driver.go:54-58`：无凭据回 `NOT_RUN`；有凭据也说「这一版还没接」。`session` 同（`:66-68`） |

**真模型端点今天 = NOT_RUN，不折算成 0，也不折算成失败。** 由此：凡是以「模型自主选工具 / 模型自己决定下一步」为前提的结论，本报告一律不写；本报告里所有「决定」都是**宿主循环**按账上那一格做的（`loop.go:496-505`），不是模型做的。

---

## 11 缺什么（按性价比排，给下一手）

1. **给 20–50 次重复补一条读数**：现有最大 n=3–4。跑法可照 `E4真负载核对.py` 的 S9，把 3 趟扩到 20/50 并印成功率、失败边界、ack 分布（P95/P99）。这是 PDF 里 L3→L4 的硬门槛，也是最便宜的一格。
2. **修后补一次真 exe 跨进程续跑**（`-resume` 三条件）：现在只有修前的红现场 + 修后的同进程针。跑一次就能把 §5.1 的 `NOT_RUN` 变成 measured。
3. **把 `Retry-After` 真的等一等，或把 POLICY 那句话改掉**：`policy.go:19` 写着「等一等」，代码没等（`loop.go` 无消费点）。这是「注释吹了、牙没写」的同一族，改注释或改码都行，别留着。
4. **重跑一次锚点尺子**：`读数-锚点核对.txt`（23:20）比 `loop.go`（23:22）旧；按现树手工已撞见 2 条漂（§7.2）。尺子的判据本身也弱（窗口里出现任一反引号标识符即算命中），修不修另说，至少要重印读数。
5. **E5 状态两处 owner 合一**：`计划-agentd事件层.json:188` 还是 Planned，交接与 evidence 已写 Exercised。要么改计划件，要么在 evidence 里别写「以计划 JSON 为准」。
6. **给「判据被摘平成恒绿」补一根反臂**（收口表 22:02 的失败项①）：现在冒烟在恒绿方向上不红，「口径只有一份」的证据是单向的。
7. **要往 L3 走，缺的是三件不是一件**：任务入口（现在是常量）、结果 oracle（现在账不核算术、`ledger_add` 不执行）、回滚/补偿（现在只有「拒写」）。这三件不落地，L3 的「独立拆解 / 验证结果 / 回滚」就只能是 NOT_APPLICABLE，而不是「差一点」。
