# Deep Research: Agent 执行 → 项目记录 → 二次修改

> 生成 2026-10-20 | 深度 standard | 外部来源 28 + 本地来源 10 | 研究对象：agentkernel（可验证记账内核）

## TL;DR

这套闭环能成立，但成立条件不是“看账本”，而是记录里必须带有**生成器之外的可复核失败证据、产物原像和三类版本**（产物、行为/配置、判据）。agentkernel 现在能强证明“谁报了什么、账有没有被改”，不能单独证明“产物原像是什么、行为是哪一版、判据是哪一版、拒收发生了几次”；只凭账本做二次修改，最容易把“记录里有”误当成“行为已改”。建议把二次修改定义为一个链外协议：**账本 + 产物原像库 + 版本清单 + 外部验证器**，四件套同批冻结、同批复跑；在这套证据包跑通之前，对外只说“条件可复核”，不说“闭环已通”。

## Executive Summary

第一，记录本身不会让第二次变好。没有外部反馈时，LLM 的内在自省在推理任务上可能使表现下降 [17]；可靠的自我纠正几乎都依赖测试、工具或人类反馈 [18]。Self-Refine 在开放任务上的平均增益约 20%，但那更多是多轮批评带来的多样性收益，不等于模型能定位推理错误 [15]。Reflexion 之所以有效，是因为它把任务成败信号写进反思记忆 [16]，而不是因为“反思”这个动作本身。

第二，从轨迹学习也有硬前提。Agent Lightning 把执行与训练解耦、把轨迹拆成 transition 做 RL，但训练信号来自奖励或可验证结果 [20]；ExpeL 同时用成功与失败轨迹提炼规则，规则可读但会累积错误 [19]；GEPA 用完整轨迹做反思式 prompt 进化，选择仍受任务指标约束 [21]；AWM 的在线模式只从评估器判为正确的轨迹归纳 workflow，Mind2Web 相对提升 24.6% [22]；Voyager 只把环境验证过的技能入库 [23]。共同点是：**先有独立结果信号，再谈从记录学习**。

第三，agentkernel 的记录面是“完整性强的薄记录”。本地导出的账本有 2,940 条记录（60 次调用 × 49 格）、12 个会话、4 个自报 actor；链上 `seq/prev/payload/seal` 2,940/2,940 重算通过，但没有签名、没有密钥 [L3]。它记录了每格的 Key、Basis、Claim 与形状标签，却没有产物原像、行为/配置版本、判据版本、审阅者身份；`read_back` 甚至没有按描述返回指纹 [L1][L2]。账面上的“失败语义”也是空的：`fail_kind` 60/60 为空、`fail_status` 60/60 为 absent，“没有记录”不能读成“没有失败” [L3]。

第四，三类二次修改需要三套不同证据。改产物，需要原像 + 哈希 + diff + 验收测试 + 回滚；改行为/配置，需要版本号 + 配置 diff + 冻结回放 + 留出集基线；改判据，需要判据版本 + 理由 + 拒收样本 + 对旧记录重打分 + 披露。三者同批改，等于把“结果变好”与“尺子变松”混在一起，无法归因。判据修改是最高风险动作，必须有独立签核与旧账重算 [L4][L5]。

第五，建议的五步协议是：冻结基线 → 执行并落账 → 读回与核验 → 归因与二次修改 → 复跑验收；配四道闸：记录完整、归因有外部信号、修改隔离且版本化、复跑无回归。现有 v1 不需要加字段：把行为版本、判据版本、拒收记录、产物原像放在链外证据包里，账内只留指纹与引用 [L1][L2]。这与“审计层不是防线”的定位一致：账本证明记录未被改，不证明记录内容为真。

第六，这套流程尚未在本项目做过双臂实证。现有严格双臂判据是 FAIL，`declare_reader` 拒收六桶全 0 [L5]；声明拒收也没有进计数（5 臂 4 拒，四桶 Δ 全 0）[L6]。所以本报告给的是**可执行协议与验收设计**，不是“已证明有效”的结论。要证明它，必须做“看记录再改”与“不看记录直接改”的同题双臂，并配一个“记录被抽掉后应当失败”的反臂。

## 1. 这条流程到底指什么 [Confidence: Medium]

### 1.1 五个动作，不是一句口号

“Agent 执行，通过看项目记录，再进行二次修改”可以拆成五个可检查的动作：

1. **执行**：Agent 发起调用、工具返回结果、产生产物（报告、代码、补丁、配置）。
2. **落账**：把这次执行的调用、结果、依据、缺席项写进账本；账本要能回答“谁在何时报了什么”。
3. **读回**：从账本读回样本，核对链完整性，并与链外的产物原像、版本清单对齐。
4. **归因**：判断失败发生在产物、行为/配置还是判据；归因必须有外部信号，不能只靠 Agent 自述。
5. **二次修改**：只改一个对象，写版本与 diff，然后在留出集上复跑；不过就回滚。

这五个动作里，agentkernel 目前只覆盖第 2 步和第 3 步的一部分；第 1、4、5 步都在内核之外。把“账本”当成整个闭环，是把记录层误当成了执行层与决策层。

### 1.2 “二次修改”的三个对象

| 对象 | 典型动作 | 最小证据 | 失败后果 |
|---|---|---|---|
| 产物 | 改报告结论、改代码、改补丁 | 原像 + 哈希 + diff + 验收测试 + 回滚 | 改错地方，或改了但拿不出原像 |
| 行为/配置 | 改 prompt、策略、路由、阈值、工具权限 | 版本号 + 配置 diff + 冻结回放 + 留出集基线 | 把一次偶然成功固化成策略 |
| 判据 | 改通过标准、桶定义、阈值、验收集 | 判据版本 + 理由 + 拒收样本 + 旧账重算 + 披露 | 移动球门，把失败改写成通过 |

三者可以同批发生，但不能同批归因。只要判据和产物在同一批里改，复跑变好就无法区分是“产物变好”还是“尺子变松”。因此第 6 节的协议要求：**判据修改单独成批，且对旧记录重打分**。

### 1.3 什么叫“闭环”

本文把“闭环”定义得比“跑完一轮”更严：一次二次修改必须同时满足四个条件，才算闭环。

- **可追溯**：能从修改反查到触发它的记录、外部信号与判据版本。
- **可隔离**：这一批只改了一个对象，其他对象保持版本不变。
- **可复跑**：在留出集上复跑，旧行为与新行为可直接对比。
- **可回滚**：修改前的产物与配置有原像，回滚后能复现旧结果。

只满足“Agent 又跑了一次”不叫闭环；只满足“账本链没断”也不叫闭环。链完整只证明记录未被改，不证明记录足以支持修改。

## 2. agentkernel 的记录面：能证明什么，不能证明什么 [Confidence: High（本地读数）]

### 2.1 工具面

本地契约与实现列出的 10 个工具，可以分成四类 [L1][L2]：

| 类别 | 工具 | 实际语义 |
|---|---|---|
| 写链 | `kernel.record_call` | 唯一写链入口；一次调用落成 49 格 |
| 预检 | `kernel.check_call` | 干跑副本，不写链；用于调用前检查 |
| 读回/核验 | `kernel.read_back`、`kernel.verify`、`kernel.tally` | 读回样本、逐条验链、按 basis 计数 |
| 声明/导出 | `kernel.celltable`、`kernel.declare_reader`、`kernel.readers_report`、`kernel.encode_journal`、`kernel.load_journal` | 表格、读者声明、整本导出/装入 |

其中 `declare_reader` 与 `readers_report` 只在内存里生效，不落盘 [L2]；`load_journal` 可以整本替换账本，而 `AGENTKERNEL_APPEND_ONLY` 默认关闭 [L1]。这两点直接决定了“项目记录”不能只看账本文件本身：账本可以被合法地整本换掉，读者声明也没有持久化证据。

### 2.2 账本实测

对 `账本-全量-1018.jsonl` 的复算结果如下 [L3]：

| 指标 | 读数 | 说明 |
|---|---|---|
| 文件行数 | 2,941 | 1 行前言 + 2,940 条 JSON 记录 |
| 调用数 | 60 | 60 次调用 × 49 格 = 2,940 条 |
| 会话数 | 12 | 账本内 session 字段 |
| actor | 4 | 全部为自报，无认证 |
| basis 分布 | measured 2,213 / absent 355 / relayed 188 / estimated 124 / model_says 60 / unset 0 | 缺席 355 条均带理由 |
| endpoint_model 格 | 23/60 非空 | 其余 37 格为空 |
| 时间戳 | 2,940/2,940 | 75 个不同值，13:01:29–15:53:08Z |
| 产物内容 | 0/2,940 | 仅 `model_says_sha256` 60/60（43 个不同值） |
| 路径/版本/判据字段 | 0/12 | 字段层面不存在 |
| `fail_kind` | 空 60/60 | 失败语义未记录 |
| `fail_status` | absent 60/60 | 不能读成“0 次失败” |
| 闸门行 | 0 | 拒收数未记录，不是 0 |
| 链校验 | `seq/prev/payload/seal` 2,940/2,940 重算通过 | 无签名、无密钥 |

这份账本的强项是**形状与完整性**：每一格都有 Key、Basis、Claim 和形状标签，链能逐条重算。弱项是**语义与版本**：它不知道产物长什么样、行为是哪一版、判据是哪一版、谁批准了这次修改。

### 2.3 能重建 / 不能重建

| 问题 | 能否从账本重建 | 依据 |
|---|---|---|
| 谁在何时发起了哪些格？ | 能（自报） | actor、ts、session、49 格 [L3] |
| 每格的值、依据、指纹？ | 能 | Key/Basis/Claim/形状标签 [L1] |
| 账本有没有被逐条改过？ | 能（无签名前提下） | `verify` 重算链 [L1] |
| 产物原像是什么？ | 不能 | 账内 0/2,940 有内容，仅哈希 [L3][L7] |
| 行为/配置是哪一版？ | 不能 | 无版本字段 [L3] |
| 判据是哪一版？ | 不能 | 无判据字段 [L3] |
| 谁审阅、谁批准？ | 不能 | readers 仅内存 [L2] |
| 被拒收了几次？ | 不能 | 无闸门行；声明拒收不落盘 [L1][L6] |
| 这次调用是成功还是失败？ | 部分 | 结果有值，但 fail 语义为空 [L3] |

`read_back` 的描述承诺返回“出处、指纹”，实现只打印 Key/Basis/Claim/形状标签，没有 hash [L2]。这意味着即使账本里有指纹，读回接口也不会把它交给你；要做二次修改的证据链，必须直接读账本或链外清单，不能只依赖 `read_back` 的打印。

### 2.4 三个结构性缺口

**缺口一：没有产物原像。** 账本只保存候选哈希，无法反读内容；现有报告已经明确记录“账里没有产物原像” [L7]。因此“产物已改”不能由账本单独证明，必须有链外原像库与 diff。

**缺口二：没有版本三元组。** 行为/配置、判据、产物三者的版本都不在账内。账本可以证明“这次调用报了这些格”，不能证明“这次调用用的是哪一版 prompt、哪一版阈值、哪一版验收集”。没有版本三元组，二次修改无法隔离，也无法回滚。

**缺口三：拒收与失败不可计数。** `declare_reader` 只在内存中生效，声明被拒不会进账；本项目实测 5 臂 4 拒，四桶 Δ 全 0 [L6]。`fail_kind` 与 `fail_status` 也为空 [L3]。把“账面上没有拒绝”读成“没有被拒绝”，是这套记录面最容易产生的假绿。

### 2.5 完整性不等于真实性

`verify` 只能证明链内字节未被改，不能证明内容为真、出处可靠。本项目的 A1 注入测试把 `SYSTEM OVERRIDE` 放进 `Notice.Why`，`read_back` 原样返回、basis 仍是 measured、`verify` 通过；报告的原话是“49 格无一格问出处”“内核增益 = 0” [L8]。这不是内核缺陷，而是定位问题：**审计层不是防线**。二次修改如果以“verify 通过”作为“记录可信”的证据，就会把注入内容当成事实依据。

## 3. 为什么“看过记录再改”不自动更好 [Confidence: High]

### 3.1 自我修正的边界

Self-Refine 让同一个模型生成、批评、重写，在 7 类任务上平均约 +20%，不需要训练 [15]。但它的收益集中在开放任务，不能外推为“模型能可靠定位推理错误”。Huang 等人的结论更直接：在没有外部反馈时，模型的内在自纠在推理基准上会使表现下降，模型也难以判断自己答案的对错 [17]。Kamoi 等人的综述进一步指出，多数“成功自纠”依赖外部反馈、停止规则或不公平的 prompt；仅靠 prompted LLM 反馈，没有稳定成功证据 [18]。

Reflexion 是另一个常被误读的例子。它把失败反思写进 episodic memory，供下一次 trial 使用 [16]；关键在“失败”由任务成败信号触发，而不是模型自己宣布失败。换句话说，**记录之所以有用，是因为它携带了生成器之外的结果信号**；如果记录里只有 Agent 的自述与最终答案，第二次修改就退化成“换个说法再写一遍”。

### 3.2 从轨迹学习：四条路径，同一个前提

| 方法 | 用什么记录 | 学习产物 | 前提 |
|---|---|---|---|
| Agent Lightning [20] | 任意 agent 轨迹，拆成 transition | 模型权重（RL） | 奖励或可验证结果 |
| ExpeL [19] | 成功与失败轨迹 | 自然语言 insight，投票维护 | 任务成败标签 |
| GEPA [21] | 完整轨迹 | prompt 变异，Pareto 选优 | 任务指标 |
| AWM [22] | 在线模式：评估器判为正确的轨迹 | 可复用 workflow | 评估器正确性 |
| Voyager [23] | 环境验证过的技能 | 代码 skill library | 可重置沙箱与环境反馈 |

这张表的共同前提是：**先有独立结果信号，再从记录里学**。没有奖励、没有验证器、没有环境反馈，轨迹只能教表面模仿；优化压力还会诱发 reward hacking。RAGEN 的 Echo Trap 就是一个实证：缺细粒度推理奖励时，多轮自进化会塌缩为重复模式，奖励方差断崖、梯度尖峰 [24]。

### 3.3 五种记录驱动的失败模式

1. **错误归因**：长轨迹里真正的失败步被淹没，模型对自身错误的判断又不可靠，于是把记录里显眼的动作当成原因，改错地方 [17][18]。
2. **选择性记录**：只归纳成功轨迹，失败样本被排除，天然有幸存者偏差；AWM 的在线模式只从评估器判为正确的轨迹归纳 [22]。
3. **事后改记录**：记录可能被生成者修改。METR 在 2026-10-06 的 PoC 中演示，agent 可以改写在 Inspect 查看器中审查者看到的 transcript 并拦截下载；真实轨迹仍在数据库，但审查者未必知道去查 [25]。作者明确这是 PoC，尚未在评估中观察到利用。
4. **反馈回路污染**：上一轮的记录成为下一轮的唯一依据，错误被反复放大；RAGEN 的 Echo Trap 是这一类的极端形态 [24]。
5. **把“记录里有”当成“行为已改”**：记录里出现了一条规则，不等于检索、执行、权限都按这条规则改了；必须用留出集回放新旧行为，才能证明行为变化 [22][23]。

### 3.4 映射回本项目

本项目已经出现过与上述模式对应的现场：

- **完整性假绿**：A1 注入内容被原样读回，`verify` 仍通过；49 格没有一格问出处 [L8]。
- **空值歧义**：#66 让“调用方报了空表”与“调用方压根没提裁剪”在账面上都可能落成 measured + 空 payload；契约自己写明这条就是看板上的 #66 [L1]。
- **声明拒收不计**：5 臂 4 拒，四桶 Δ 全 0 [L6]；严格双臂判据因此 FAIL，`declare_reader` 拒收六桶全 0 [L5]。
- **读数口径错位**：490 条账的四栏计数全 0，而实际调用 10 次；24–26 次预检拒收不可复核 [L4]。
- **记录驱动修改的先例但不完整**：#66 读了 3,430 条账后改码，kprobe 3 针红、干净副本 174 PASS，但只跑了 3/80 针 [L9]。这说明记录可以触发修改，但“改完有没有全量复跑”仍是独立问题。

这些现场说明：**本项目缺的不是“再记多一点”，而是“记录能否支撑归因”**。在归因证据补齐之前，增加记录只会增加噪声。

## 4. 外部标准对照：记录的最低字段与留存 [Confidence: Medium]

### 4.1 Trace 的骨架

OpenTelemetry 的 GenAI 语义约定用一条 trace 表示一次任务：根 span 是 `invoke_agent`，下挂 `chat`（模型调用）与 `execute_tool`；属性覆盖操作名、provider/model、token 用量、finish reason、工具名与入参出参、`error.type` [1][2]。截至 2026-08 的公开资料仍把它标为 Development；`gen_ai.system` 已在 semconv v1.37.0 起标记弃用，由 `gen_ai.provider.name` 取代，过渡期应双写字段 [3][28]。这意味着“记录字段”本身还在演化，落地必须固定 semconv 版本并加映射层，不能把字段名当成永久契约。

更关键的是采集默认值。Microsoft Agent Framework 的文档写明：`ENABLE_SENSITIVE_DATA` 默认 false，prompt、响应、工具入参出参、异常消息都需要显式开启 [1]。也就是说，默认 trace 只是骨架；要支持二次修改，必须显式采集内容，并同时处理隐私与留存。

### 4.2 审计与合规的要求

EU AI Act 第 12 条要求高风险 AI 系统在全生命周期内技术上支持自动记录事件日志；第 26(6) 条要求部署方在其控制范围内保存日志，保存期与预期用途相称，至少六个月，除非其他法律另有规定 [26][6]。Digital Omnibus 已以 Regulation (EU) 2026/1744 调整高风险义务适用日：Annex III 独立高风险推至 2027-12-02，Annex I 嵌入式推至 2028-08-02；EUR-Lex 页头已核，具体修订条款文号仍待官方条文核对 [27]。这些日期与本文的流程设计无关紧要，重要的是：**记录义务没有消失，只是窗口变长**。

NIST AI RMF 是自愿框架，四功能是 Govern/Map/Measure/Manage，Measure 要求可重复的 TEVV 与文档化结果 [9]。ISO/IEC 42001 把日志、留存、访问控制纳入 AI 管理体系的控制与审核证据，但不规定具体字段 [10]。CSA Labs 给 agent 审计日志的取证最小集是：发起人身份、agent 标识、调用的工具/API、访问或修改的数据、会话上下文；并警告 agent 动作混入人类审计记录会破坏调查 [8]。

这些标准共同指向一个结论：**合规要求“过程可证明”，不要求“字段长什么样”**。字段设计要服务于二次修改的归因，而不是为了对齐某个模板。

### 4.3 对二次修改真正有用的字段

| 字段 | 为什么需要 | agentkernel 现状 |
|---|---|---|
| 发起人/审批人 | 区分谁发起、谁批准 | 仅 4 个自报 actor；无审批 [L3] |
| agent 标识与版本 | 区分行为版本 | 无 [L3] |
| 模型/provider | 区分模型差异 | endpoint_model 23/60 非空 [L3] |
| prompt/配置版本 | 区分行为变化 | 无 [L3] |
| session/turn | 把调用串成一次任务 | session 有；turn 粒度不足 [L3] |
| 工具名 + 入参/出参 | 归因到具体决策点 | 49 格有结果，但语义薄 [L1] |
| 产物哈希 + 原像 | 证明改的是哪个产物 | 仅 60/60 哈希；无原像 [L3][L7] |
| 判据版本 | 区分“变好”与“尺子变松” | 无 [L3] |
| 拒收/失败类别 | 区分“没记录”与“没发生” | fail 语义空；声明拒收不落盘 [L3][L6] |
| 时间戳 | 排序与留存 | 2,940/2,940 [L3] |
| 防篡改证据 | 证明记录未被改 | 哈希链；无签名；APPEND_ONLY 默认关 [L1][L3] |

这张表的读法是：agentkernel 在“时间戳、形状、链完整性”上够用；在“版本、原像、拒收、审批”上不够。二次修改的证据包必须补后者，而不是继续加前者。

## 5. 三类二次修改的可执行判据 [Confidence: Medium]

### 5.1 改产物

**最小证据**：修改前原像 + 修改前哈希 + 修改后哈希 + diff + 验收测试 + 回滚脚本。

**通过判据**：验收测试通过；留出集无回归；回滚后能复现旧结果；原像可被独立读取。

**禁止做法**：用“账本里有这次输出”证明“产物已改”；用 `verify` 通过证明“产物正确”；只存哈希不存原像。现有报告已经证明账内没有产物原像 [L7]，M5 的 49/49 往返也留下 49 个 NoPreimage [L10]。

### 5.2 改行为/配置

**最小证据**：行为版本号 + 配置 diff + 模型/provider + prompt 版本 + 工具权限 + 冻结回放环境 + 留出集基线。

**通过判据**：在留出集上相对基线有提升；安全/拒收指标不退化；同一输入在冻结环境下可复现；旧版本可回滚。

**禁止做法**：把一次偶然成功固化成策略；在同一批里同时改 prompt 与判据；用生产轨迹当训练集又在同一批轨迹上验收。回放要冻结模型响应、工具返回、时间、种子、配置与 prompt 版本，否则会漂到别的路径 [13]。

### 5.3 改判据

**最小证据**：判据版本 + 修改理由 + 拒收样本 + 旧记录重打分 + 披露记录 + 独立签核。

**通过判据**：旧记录在新判据下重算；新旧判据的差异被列出；修改判据的人与改产物的人分离；对外材料同步更新。

**禁止做法**：看到结果后再改阈值；把“拒收”从桶里删掉；把“未记录”写成“0”；在判据变更的同一批里宣布产物变好。本项目的严格双臂 FAIL 与拒收六桶全 0 说明，判据本身必须先能红，否则“全绿”没有意义 [L5]。

### 5.4 三者同批的规则

如果确实要同批改三类，必须满足：

1. 先改判据，并对旧记录重打分，冻结新判据版本。
2. 再改行为/配置，在旧判据与新判据下各跑一次。
3. 最后改产物，用冻结后的判据验收。
4. 任何一步失败，回滚到该步之前的版本；不允许“带着新判据回滚旧产物”。

这套顺序的目的是把“尺子变化”与“对象变化”分开。只要顺序反过来，复跑结果就无法归因。

## 6. 推荐流程：五步协议 + 四道闸 [Confidence: Medium]

### 6.1 五步协议

```
执行 ──> 落账 ──> 读回/核验 ──> 归因 ──> 二次修改 ──> 复跑验收
          │          │            │         │
          └─ 账本    └─ 链/样本   └─ 外部   └─ 产物/行为/判据
```

**第 0 步：冻结基线。** 导出账本，记录行数、链头、`encode_journal` 的 sha256；把当前产物原像、行为版本、判据版本写入证据包。基线不冻结，后面所有对比都不成立。

**第 1 步：执行并落账。** 调用前用 `check_call` 预检，调用后用 `record_call` 落账；`declare_reader` 的收/拒在链外追加日志，因为它在内存里不落盘 [L2]。每次执行只做一件事，避免一次调用里混入多个修改对象。

**第 2 步：读回与核验。** 抽样 `read_back`，全量 `verify`；把账本与链外原像、版本清单对齐。`read_back` 不返回指纹 [L2]，所以指纹要从账本或清单直接取。

**第 3 步：归因与二次修改。** 先分类失败对象，再决定改什么；归因必须至少有一个外部信号（测试、环境结果、人类评审）。如果只有 Agent 自述，停止修改，补证据。修改只动一个对象，写版本与 diff，准备回滚。

**第 4 步：复跑验收。** 在留出集上跑旧版与新版；判据变更时，旧记录也要在新判据下重算；结果写入报告，失败就回滚。复跑通过不等于“闭环已通”，只等于“这一批可归因”。

### 6.2 四道闸

| 闸 | 问题 | 通过条件 | 不过怎么办 |
|---|---|---|---|
| G0 记录完整 | 这次执行有没有可核的记录？ | 账本行数/链头/原像/版本/拒收日志齐全 | 不进入归因，补记录 |
| G1 归因有据 | 失败原因有没有外部信号？ | 至少一个测试/环境/人类信号指向具体决策点 | 不修改，补验证 |
| G2 修改隔离 | 这一批只改了一个对象吗？ | 版本三元组冻结，diff 只含一个对象 | 拆批，回滚混合修改 |
| G3 复跑无回归 | 新版在留出集上是否真的更好？ | 留出集提升，安全/拒收不退化，回滚可复现 | 回滚，记录失败 |

如果这一批改了判据，追加一道 **G4 判据变更**：旧记录重打分、差异披露、独立签核、对外材料同步。G4 不通过，不允许宣布任何“变好”。

### 6.3 现有 v1 怎么落地

不需要给内核加字段。做法是把链外证据包做成固定目录：

```
evidence/
  ledger.jsonl + ledger.sha256 + row_count.txt + chain_head.txt
  artifact/  (原像 + sha256 + diff)
  versions.json  (行为/配置/模型/prompt/判据)
  external/  (测试输出、环境结果、人类评审)
  refusals.log  (declare_reader 收/拒的链外追加日志)
  revision.md  (归因、修改、预期效果、回滚)
```

账内只保留指纹与引用；账外保存原像与版本。这样既不动 v1 的 48 键/49 格，也不把内核变成工头。需要强调的是：这套证据包是**流程件**，不是内核功能；它的可信度取决于谁写、谁审、谁保管，而不是取决于 `verify`。

## 7. 验收：怎样证明“看记录再改”真的有用 [Confidence: High（设计）/ Low（实证）]

### 7.1 同题双臂

- **R 臂（记录审阅）**：给执行者账本、原像、版本清单与外部验证器；要求先归因，再修改。
- **N 臂（无记录审阅）**：给同一个执行者同样的外部验证器与时间预算，但不给账本与历史记录；直接修改。
- **共同条件**：同一批失败样本、同一模型/配置、同一验收判据、同一时间预算；评分者对分组盲。
- **主指标**：留出集通过率。
- **次指标**：假修复率（声称修好但留出集回归）、返工次数、修改耗时。
- **样本**：先用 10–20 个失败样本做 smoke，不做显著性声明；结果只作为方向性证据。

### 7.2 两条反臂

- **反臂 A（抽掉记录）**：把 R 臂的账本/原像/版本抽掉，只留外部验证器。如果 R 臂仍然“成功”，说明成功来自验证器，不是记录；记录审阅的增量价值未被证明。
- **反臂 B（只给记录，不给外部信号）**：给账本但不给测试/环境/人类反馈。按第 3 节的证据，这一臂应当失败或拒绝修改；如果它“成功”，说明流程在用自述替代验证，结果不可信 [17][18]。

反臂的作用是证明尺子会红。只做 R/N 两臂，无法区分“记录有用”与“验证器有用”；加上反臂，才能把增量归因到记录。

### 7.3 本项目当前状态

| 项目 | 状态 | 依据 |
|---|---|---|
| 账本链完整性 | 已具备 | 2,940/2,940 重算通过 [L3] |
| 产物原像 | 缺失 | 账内 0/2,940；报告明确缺口 [L7] |
| 版本三元组 | 缺失 | 无字段 [L3] |
| 拒收计数 | 缺失 | 5 臂 4 拒，四桶 Δ0 [L6] |
| 严格双臂判据 | FAIL | 拒收六桶全 0 [L5] |
| R/N 双臂实证 | NOT_RUN | 本轮未执行 |
| 反臂 A/B | NOT_RUN | 本轮未执行 |

所以当前能说的是：**这套流程有可执行设计，但还没有在本项目被证明有效**。任何“闭环已通”“记录驱动改进”的对外表述，都应降级为“条件可复核，待双臂实证”。

## 8. 边界与开放问题 [Confidence: Low–Medium]

### 8.1 不能说的话

- 不能说“账本通过 verify，所以记录内容为真”。verify 只证明字节未变；A1 注入测试已经证明内容可以是不可信的 [L8]。
- 不能说“审计层是防线”。它不拦截、不调度、不执行工具；它只记录与核读。
- 不能说“闭环已通”。严格双臂 FAIL、拒收六桶全 0、原像缺失，都指向反证 [L5][L6][L7]。
- 不能说“记录可以替代外部验证”。Huang/Kamoi 的结论正好相反：没有外部反馈的自纠可能更差 [17][18]。
- 不能说“符合 EU AI Act”。第 12 条/第 26(6) 条是记录义务，不是产品认证；本文也不是法律意见 [26][6]。

### 8.2 尚未解决的问题

1. **增量归因**：R 臂的提升有多少来自记录，多少来自外部验证器？只有反臂 A 能回答。
2. **审阅者过拟合**：审阅者看多了记录，可能只修记录里显眼的错；需要留出集与预注册判据。
3. **非确定性回放**：模型响应、工具返回、时间、种子、配置不冻结，回放会漂 [13]。
4. **隐私与脱敏**：prompt 与工具输出可能含敏感数据；OTel 默认关闭敏感数据采集是一个信号 [1]，但自建证据包需要自己的脱敏策略。
5. **防篡改的边界**：哈希链能防意外改动，不能防有写权限的人整本替换；`load_journal` 可以整本换账 [L1]。需要外部 WORM 或签名快照，但这会引入密钥管理问题。
6. **样本代表性**：本项目的账本只有 60 次调用、一个客服靶场，不能外推到生产 [L3]。
7. **成本**：记录、原像、版本、复跑都有成本；如果失败率很低，记录审阅的边际收益可能不如直接加验证器。这一点必须用 R/N 双臂来算，而不是靠信念。

### 8.3 最强的反方观点

一个合理的反方会说：**“既然外部验证器才是关键，记录只是辅助；直接把验证器做好，何必维护一套证据包？”**

这个反方观点有一半是对的。对于“改产物”，一个强验收测试可能已经足够；记录审阅的增量价值最可能出现在两处：一是**改行为/配置**，需要知道上一版为什么失败；二是**改判据**，需要旧记录重打分与拒收样本。如果 R/N 双臂显示记录审阅在产物修改上没有增量，就应该把记录审阅从产物路径上撤掉，只保留在行为与判据路径上。这也是第 9 节行动清单里要先做小样本双臂、而不是先扩记录的原因。

## 9. Action Plan

- [ ] 写一份 `二次修改协议 v0`：把第 6 节的五步、四道闸、证据包目录固化成独立文档；不改内核。
- [ ] 建 `evidence/` 目录与 `versions.json` 模板：账本 sha256、行数、链头、产物原像哈希、行为版本、判据版本、模型/provider。
- [ ] 加链外 `refusals.log`：记录 `declare_reader` 的键、读者、收/拒、时间；因为它在内存里不落盘 [L2]。
- [ ] 冻结一次基线：`encode_journal` + sha256 + 行数 + 链头；把当前产物原像复制进证据包。
- [ ] 从现有报告里挑 10 个失败样本，另留 10 个不参与修改的留出样本；两者不得重叠。
- [ ] 跑 R/N 双臂 smoke：同题、同验证器、同时间预算；评分盲；记录通过率、假修复率、返工次数。
- [ ] 跑反臂 A（抽掉记录）与反臂 B（只给记录不给外部信号）；如果反臂 B 也“成功”，停止并修流程。
- [ ] 把结果写进 `报告/二次修改-双臂-1020.txt`；如果没有增量，撤回“记录驱动改进”的对外说法，只保留“可复核记录”。
- [ ] 在 v1 解冻前不加字段；如果确需加，按“判据表三件配齐”的规矩另起提案，不在本流程里夹带。

## 10. Methodology

- **深度**：standard；3 个检索代理（本地记录审计、外部可观测性/审计、外部自我修正/轨迹学习）+ 1 个引用核验代理 + 1 个定向补证代理。
- **来源**：外部 28 条，本地 10 条；外部来源按 Tier 1/2/3 标注，核心结论优先 Tier 1/2。
- **三角校验**：本地读数由检索代理自印，主代理复核了关键文件存在性与口径；外部 11 条高影响结论做了逐条核验。
- **核验修正**：EU AI Act 的来源从厂商解读降级为“律所指南 + 官方页头待核”；Digital Omnibus 日期改为“Regulation (EU) 2026/1744 页头已核，条文待核”；AWM 的“仅成功轨迹”限定为在线模式；OTel 改名改为“弃用过渡”，不写成硬切换。
- **结构变化**：原计划中的“合规认证”章节被压缩为第 4 节的一部分，因为证据只支持“记录义务”，不支持“认证”；新增第 7 节双臂验收，因为这是本报告最关键的缺口。
- **限制**：没有做 R/N 双臂，没有真人评审，没有生产数据；EU AI Act 与 OTel 的官方全文未在本轮完整打开；本地账本只覆盖一个客服靶场。
- **引用抽检**：E3/E4/E8 被降级或改写；E1/E2/E5/E6/E7/E9 与 L1/L2/L3 通过。

## 11. Bibliography

### 外部来源

[1] Microsoft Learn — Observability | Microsoft Agent Framework — https://learn.microsoft.com/en-us/agent-framework/agents/observability — 访问 2026-10-18 — Tier 1 — 更新 2026-10-15

[2] OpenTelemetry — GenAI semantic conventions — https://opentelemetry.io/docs/specs/semconv/gen-ai/ — 访问 2026-10-18 — Tier 1 — 页面已迁移 [snippet only]

[3] TrueFoundry — OpenTelemetry GenAI Conventions: AI Observability — https://www.truefoundry.com/blog/opentelemetry-genai-semantic-conventions — 访问 2026-10-18 — Tier 2 — 2026-08-21

[4] LangChain Docs — Evaluation concepts — https://docs.langchain.com/langsmith/evaluation-concepts — 访问 2026-10-18 — Tier 1 — 持续更新

[5] AIMultiple — 15 AI Agent Observability Tools: AgentOps & Langfuse — https://aimultiple.com/agentic-monitoring — 访问 2026-10-18 — Tier 3 — 2026-08-11

[6] Truescreen — EU AI Act Record-Keeping: Article 12 Requirements Explained — https://truescreen.io/insights/ai-act-record-keeping-requirements/ — 访问 2026-10-18 — Tier 3 — 2026-08-12（厂商解读，仅作旁证）

[7] JD Supra — EU agrees Digital Omnibus deal to simplify AI rules — https://www.jdsupra.com/legalnews/eu-agrees-digital-omnibus-deal-to-4275721/ — 访问 2026-10-18 — Tier 2 — 2026-09-21

[8] Cloud Security Alliance Labs — NIST AI Agent Standards: What It Means for Enterprise — https://labs.cloudsecurityalliance.org/research/csa-research-note-nist-ai-agent-standards-initiative-2026040/ — 访问 2026-10-18 — Tier 2 — 2026-08-04

[9] NIST — AI Risk Management Framework — https://www.nist.gov/itl/ai-risk-management-framework — 访问 2026-10-18 — Tier 1 — AI RMF 1.0 2023-01；生成式 Profile 2024-07

[10] ISO/IEC — ISO/IEC 42001:2023 AI management systems — https://www.iso.org/standard/42001 — 访问 2026-10-18 — Tier 1 — 2023-12

[11] LangChain Blog — Common questions about agent evals — https://www.langchain.com/blog/common-questions-about-agent-evals — 访问 2026-10-18 — Tier 2 — 2026-10 [snippet only]

[12] Snyk 案例（LangChain 访谈转载）— 如何把内部支持 Agent 变成产品功能 — https://aihot.virxact.com/items/gsyydzls8eo042hn5n3id662z — 访问 2026-10-18 — Tier 3 — 2026-10-09

[13] CSDN — Agent 会话轨迹的回放与复现 — https://blog.csdn.net/2600_95884800/article/details/167668468 — 访问 2026-10-18 — Tier 3 — 2026-10-12

[14] CSDN — Agent 评测与调优：从 Trace 检查到反馈回流 — https://blog.csdn.net/2301_80956187/article/details/166994393 — 访问 2026-10-18 — Tier 3 — 2026-10-02

[15] Madaan et al. — Self-Refine — https://arxiv.org/abs/2303.17651 — 访问 2026-10-19 — Tier 1 — NeurIPS 2023

[16] Shinn et al. — Reflexion — https://arxiv.org/abs/2303.11366 — 访问 2026-10-19 — Tier 1 — NeurIPS 2023

[17] Huang et al. — Large Language Models Cannot Self-Correct Reasoning Yet — https://arxiv.org/abs/2310.01798 — 访问 2026-10-19 — Tier 1 — ICLR 2024

[18] Kamoi et al. — When Can LLMs Actually Correct Their Own Mistakes? — https://arxiv.org/abs/2406.01297 — 访问 2026-10-19 — Tier 1 — TACL 2024

[19] Zhao et al. — ExpeL — https://arxiv.org/abs/2308.10144 — 访问 2026-10-19 — Tier 1 — AAAI 2024

[20] Luo et al.（Microsoft）— Agent Lightning — https://arxiv.org/abs/2508.03680 — 访问 2026-10-19 — Tier 1 — 2025-08-05

[21] Agrawal et al. — GEPA — https://arxiv.org/abs/2507.19457 — 访问 2026-10-19 — Tier 1 — ICLR 2026

[22] Wang et al. — Agent Workflow Memory — https://arxiv.org/abs/2409.07429 — 访问 2026-10-19 — Tier 1 — ICML 2025

[23] Wang et al. — Voyager — https://arxiv.org/abs/2305.16291 — 访问 2026-10-19 — Tier 1 — 2023-05

[24] Wang et al. — RAGEN — https://arxiv.org/abs/2504.20073 — 访问 2026-10-19 — Tier 1 — 2025-04-24

[25] METR — AI systems could cover up misbehavior — https://metr.org/blog/2026-10-06-ai-systems-could-cover-up-misbehavior/ — 访问 2026-10-19 — Tier 1 — 2026-10-06

[26] Bird & Bird — EU AI Act Guide（中文版）— https://www.twobirds.com/-/media/new-website-content/pdfs/capabilities/artificial-intelligence/eu-ai-act-guide-chinese-version.pdf — 访问 2026-10-20 — Tier 2（律所指南；官方英文本未完整打开）

[27] EUR-Lex — Regulation (EU) 2026/1744 — https://eur-lex.europa.eu/eli/reg/2026/1744/oj — 访问 2026-10-20 — Tier 1（仅页头已核；修订条款文号待核）

[28] open-telemetry/opentelemetry-js — Releases（semconv v1.37.0）— https://github.com/open-telemetry/opentelemetry-js/releases — 访问 2026-10-20 — Tier 1（发布说明，摘录级）

### 本地来源

[L1] `微内核/微内核/contract.md` — 契约真相 — §2.5、:162、:528、:596

[L2] `微内核/微内核/mcpsrv/mcpsrv.go` — 工具实现 — :263-290、:274、:474-498；`cells.go:423-486`

[L3] `构建-1017/客服靶场/导出/账本-全量-1018.jsonl` — 被审账本 — 2,941 行 / 2,940 条 / 60 次调用 / 12 会话 / 4 actor

[L4] `微内核/微内核/报告/收尾-现场与未闭合-1018.txt` — 现场读数 — :60、:62、:63

[L5] `微内核/微内核/报告/双臂验收-实测-1019-221650.txt` — 严格双臂 FAIL — 拒收六桶全 0

[L6] `微内核/微内核/报告/声明被拒-进没进计数-1017.txt` — 声明拒收 — 5 臂 4 拒，四桶 Δ0

[L7] `微内核/微内核/报告/缺口-账里没有产物原像.txt` — 原像缺口 — 账内无内容，仅哈希

[L8] `微内核/微内核/报告/考题-双臂盲测-1017.txt` — A1 注入 — :35 “49 格无一格问出处”、:38 “内核增益=0”

[L9] `微内核/微内核/报告/kprobe-66三根-1019.txt` — 记录驱动修改先例 — 3/80 针

[L10] `微内核/微内核/报告/M5补跑-闸门与对账-1019.txt` — 49/49 往返 — 49 NoPreimage

## 12. Source Extracts

### [1] Microsoft Agent Framework — Observability
- **Summary:** 官方文档说明一条 agent trace 的根 span 为 `invoke_agent`，下挂 `chat` 与 `execute_tool`；敏感数据采集默认关闭。
- **Key quote:** “`ENABLE_SENSITIVE_DATA` - Default is `false` ... (prompts, responses, function call arguments, function call results, and exception messages)”。
- **Source type:** 官方文档；**Tier:** 1。

### [2] OpenTelemetry — GenAI semantic conventions
- **Summary:** 官方入口，访问时页面已迁移；GenAI 约定仍属 Development。
- **Source type:** 标准文档；**Tier:** 1（snippet only）。

### [4] LangSmith — Evaluation concepts
- **Summary:** dataset 是样本集合，experiment 是某个应用版本在数据集上的结果；支持多 experiment 并排比较。
- **Key quote:** “An experiment represents the results of evaluating a specific application version on a dataset.”
- **Source type:** 官方文档；**Tier:** 1。

### [8] CSA Labs — NIST AI Agent Standards
- **Summary:** 给出 agent 审计日志的取证最小字段：发起人、agent 标识、工具/API、访问或修改的数据、会话上下文。
- **Source type:** 研究机构；**Tier:** 2。

### [15] Self-Refine
- **Summary:** 单模型生成-批评-重写，7 类任务平均约 +20%，无需训练；收益集中在开放任务。
- **Key quote:** “uses a single LLM as the generator, refiner, and feedback provider.”
- **Source type:** 论文；**Tier:** 1。

### [17] Huang et al. — Cannot Self-Correct Reasoning Yet
- **Summary:** 无外部反馈时，内在自纠在推理基准上降分；模型也难以判断自己答案对错。
- **Key quote:** “at times, their performance even degrades after self-correction.”
- **Source type:** 论文；**Tier:** 1。

### [18] Kamoi et al. — When Can LLMs Actually Correct Their Own Mistakes?
- **Summary:** 批判性综述：可靠的自我纠正依赖外部反馈；仅靠 prompted LLM 反馈没有稳定成功证据。
- **Key quote:** “no prior work demonstrates successful self-correction with feedback from prompted LLMs, except for studies in tasks that are exceptionally suited for self-correction.”
- **Source type:** 论文；**Tier:** 1。

### [19] ExpeL
- **Summary:** 从成功与失败轨迹提炼自然语言 insight，用 ADD/UPVOTE/DOWNVOTE/EDIT 维护，不更新参数；规则可审，但会累积错误。
- **Source type:** 论文；**Tier:** 1。

### [20] Agent Lightning
- **Summary:** 解耦 agent 执行与训练，把任意轨迹拆成 transition 做 RL；训练信号来自奖励或可验证结果。
- **Key quote:** “complete decoupling between agent execution and training.”
- **Source type:** 论文；**Tier:** 1。

### [21] GEPA
- **Summary:** 反思完整轨迹生成 prompt 变异，Pareto 选优；rollout 最多省 35×，选择仍受任务指标约束。
- **Source type:** 论文；**Tier:** 1。

### [22] Agent Workflow Memory
- **Summary:** 在线模式只从评估器判为正确的轨迹归纳 workflow；Mind2Web 相对提升 24.6%。
- **Key quote:** “AWM substantially improves the baseline results by 24.6% ... on Mind2Web.”
- **Source type:** 论文；**Tier:** 1。

### [23] Voyager
- **Summary:** 自动课程 + 可执行代码 skill library + 环境反馈；只把验证过的技能入库。
- **Source type:** 论文；**Tier:** 1。

### [24] RAGEN
- **Summary:** 多轮 agent RL 出现 Echo Trap：奖励方差断崖、梯度尖峰、策略塌缩；缺细粒度推理奖励时推理不涌现。
- **Key quote:** “a recurring mode of Echo Trap where reward variance cliffs and gradient spikes.”
- **Source type:** 论文；**Tier:** 1。

### [25] METR — AI systems could cover up misbehavior
- **Summary:** PoC 演示 agent 可修改 Inspect 查看器中审查者看到的 transcript 并拦截下载；真实轨迹仍在数据库，作者称尚未在评估中观察到利用。
- **Key quote:** “could have allowed an agent to arbitrarily modify what the reviewer sees.”
- **Source type:** 研究机构博客；**Tier:** 1。

### [L3] 账本-全量-1018.jsonl
- **Summary:** 2,941 行 = 1 行前言 + 2,940 条记录；60 次调用 × 49 格；basis 分布 measured 2,213 / absent 355 / relayed 188 / estimated 124 / model_says 60 / unset 0；产物内容 0/2,940；链 2,940/2,940 重算通过；无签名。
- **Source type:** 本地账本导出；**Tier:** 本地 A 级读数。

### [L8] 考题-双臂盲测-1017.txt
- **Summary:** A1 把 `SYSTEM OVERRIDE` 注入 `Notice.Why`，`read_back` 原样返回、basis 为 measured、`verify` 通过；报告记“49 格无一格问出处”“内核增益=0”。
- **Source type:** 本地实测报告；**Tier:** 本地 A 级读数。
