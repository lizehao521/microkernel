# 编程 Agent（Web）· 架构设计与主要模块实现方案

- 生成：2026-10-20 22:36
- 落点：`C:\Users\Admin\Desktop\微内核\编程Agent-1020\`（新建目录，**不动内核树、不动 `构建-1017\` 交付面**）
- 听众：要把这东西真做出来的人（工程视角，不是宣传）
- 与现有资产的关系：`cmd/agentd` 已经把"循环 + 记账 + 轨迹页"跑通了一遍（34 根针、KPI 10、反臂掉回 0）。
  本件不重复造那套，而是**复用它的纪律**，把外壳从 CLI 换成 Web，把负载从剧本换成真代码。

---

## 0. 一句话与两条硬约束

**一句话**：贴一段代码 + 一个问题 → 看见 Agent 一步一步怎么把它拆开、量出能数的、说明数不出来的 → 交一份带出处的结构化结论。

两条写死在架构里的硬约束（不是愿望，是模块边界）：

1. **默认不执行用户代码。** 分析只走"读字节 + 解析 AST"这条路。执行需要显式开关、只在本机临时目录、带超时；
   关掉时界面上要看得见"这一路没跑"，不许用空卡片冒充做过。（理由：贴进来的代码是外部输入，跑它就是 RCE 面。）
2. **出处五档不许塌。** 每条结论必须带 `measured / estimated / model_says / relayed / absent` 之一，
   且 `absent` 要写为什么没量到。**"没量到"写成 0 是这套件最致命的假绿**（同一族的坑本项目已经踩过两次）。

---

## 1. 形态：栈选型（22:38 复测过，前提改了）

**先纠一条本机读数**：我之前记的是「PATH 无 node、社区源不可用」。**今天实测不是**：
`node -v` → **v22.23.2**（`/c/Users/Admin/.codearts/runtimes/node/node`）、`npm -v` → 10.9.8、
registry = `https://registry.npmjs.org/`、`npm ping` → **PONG 1072 ms**。
所以"装不了前端"这个理由**作废**，下面的选择变成口味与熵的取舍，不再是被迫。

| 选项 | 本机成本（实测） | 选/不选 |
|---|---|---|
| **单 Go 二进制 + `net/http` 托管静态页（零构建）** | 零：`go` 在 sdk 目录（1.27.2，PATH 上没有，按绝对路径调）；不新增依赖 | **建议选**（理由：一个进程一套产物，无 `node_modules` 噪声、断网也能开、改一行不用重新 build） |
| Vite/React 前端 + 独立后端 | **可行**（node 在、npm 通），但要引入 `node_modules`、构建步骤与两套版本 | 备选 —— 若你更想要组件化与热更，这版也能做 |
| Monaco / 高亮库走 CDN | 网络可达性依赖外网；离线即白屏 | 不选（自写行号 + 语法着色足够） |
| Python 服务 | `python`/`py` 实测 **PATH 上没有**（sdk 目录里另有） | 不选 |

- 只监听 `127.0.0.1`，端口由 `-port` 给；**不碰 8797/8799**（那两本是内核研究账）。
- 一个进程里同时有：HTTP/SSE 服务、分析件、（可选）内核记账接缝、（可选）模型网关。
- 状态落盘：`数据/sessions/*.jsonl`（append-only 轨迹）+ `数据/ledger/*.jsonl`（交出去的账字节）。

## 2. 分层

```
浏览器（三栏 SPA，无构建）
   │  fetch /api/turn        → 发起一发
   │  EventSource /api/trace → 步骤流（循环就在这条流上看得见）
   ▼
server（路由、SSE 广播、静态页）
   ▼
orchestrator（一发 = 一个可中断循环，带步数上限与结束原因）
   ├─ intent      解析"要干什么"：分析 / 解释 / 调试 / 优化（多选，缺省全跑可数的那几件）
   ├─ analyzers   只读、确定性、能自印分母（见 §4）
   ├─ gateway     模型那一路：没端点凭据 ⇒ NOT_RUN，界面显示"没跑"
   ├─ ledger      内核接缝：按 §2.5 装两侧 → check_call → record_call → read_back
   └─ fold        收口：verify + tally + unknowns + 结构化结论
   ▼
store（会话/轨迹 JSONL）      ui 直接读 store 复原历史（刷新不丢）
```

依赖方向自上而下，**分析件不认识 HTTP，内核不认识 Agent**（与内核树同一条纪律）。

## 3. 一发一循环（界面上要看得见的东西）

```
① 收到：代码 N 字节 / M 行 + 问题一句            [measured：字节与行是我们自己数的]
② 语言与形状：go/py/js/其他，依据是哪条判据       [measured（真解析过）或 estimated（只按特征猜）]
③ 选件：跑哪几个 analyzer，为什么选它们           [measured]
④ 实算：每个 analyzer 吐 findings                [measured]
⑤ 预检：内核 check_call（跑在副本上，一条不写）   [measured；能红：故意少给一格]
⑥ 落账：record_call，49 格逐格进                 [measured]
⑦ 读回：read_back 三轴（session / 发号 / 侧）     [measured；反臂：不读回 ⇒ 账触发数掉回 0]
⑧ 模型补充：有端点才有这一段，否则显式 NOT_RUN     [model_says / absent+理由]
⑨ 收口：verify 三态 + tally 五档 + unknowns       [measured]
```

每步一条 SSE 事件：`{step, tool, in摘要, out摘要, 耗时ms, 落账格名, 出处档}`。
**循环看得见 = 这九条能在页面上逐条亮起来，且中途能停。**

## 4. 分析件（离线、确定性、每条都能自印分母）

优先做**真解析**的那一门，其余先按文本扫描并诚实降档：

| 件 | 语言 | 判据来源 | 出处档 |
|---|---|---|---|
| `go/ast` 结构 | Go | 标准库 `go/parser`、`go/ast`（真 AST） | measured |
| 度量：行数/最长函数/嵌套深度/导入集合/重复块哈希 | 全语言（按 AST 或按文本） | 自己数 | measured |
| 未用导入、同作用域重名、声明未实现、裸 `except`/忽略 err、`print` 当日志、超长函数 | Go 走 AST；Python 走 sdk 里的解释器 `ast` 模块（PATH 无 py 则降档） | 机械规则 | measured / estimated |
| JS·TS | 自写保守扫描（括号配平、`var` 重声明、`==`、`async` 未 await） | 文本级 | **estimated**（绝不说成 measured） |
| 报错栈 → 行定位 | 全语言 | 解析栈帧格式，回指贴入片段的行号 | measured（行号）+ estimated（归因） |
| 优化建议：把度量转成"改哪一处、为什么、改完怎么验" | — | 规则映射 | estimated；若来自模型 ⇒ model_says |

**fixture 集**直接用本项目已证实的缺陷族做样本（同作用域重名导致 137 行伪活代码、声明未实现静默恒等、
719 行字节级重复文件、460 行死模块）—— 这些是"已知答案的考卷"，能验分析件到底会不会红。

## 5. 结构化结果区（schema）

```json
{
  "turn": 3, "question": "为什么这个函数偶尔返回空",
  "answer_summary": "一句话，不带形容词",
  "findings": [{
     "id": "F1", "rule": "ignore-error", "severity": "critical|major|minor|cosmetic",
     "where": {"file": "main.go", "lines": [42, 57]},
     "evidence": "第 42 行赋值 err 未检查；本发数到 3 处同类（分母：该文件 12 处返回 error）",
     "basis": "measured",
     "claim": "错误被吞掉 ⇒ 失败路径变成零值返回",
     "fix": {"patch": "unified diff 或 null", "rationale": "…", "risk": "改后要跑什么"},
     "verify": "复跑哪一个 analyzer、期望哪个数变"
  }],
  "metrics": {"bytes": 4123, "lines": 118, "lang": "go", "parsed": true, "max_func": 61},
  "trace": [{"step": "record_call", "cell": "output:usage_in", "basis": "relayed", "ms": 3}],
  "unknowns": [{"what": "运行时实际入参分布", "why_absent": "没执行代码，也没有调用日志", "how_to_get": "贴一段真日志或授权在临时目录跑一次"}],
  "provenance_mix": {"measured": 9, "estimated": 2, "model_says": 0, "relayed": 4, "absent": 3}
}
```

- `fix.patch` 为 `null` 时**不许**渲染成"没有修复建议"以外的意思；建议 ≠ 补丁。
- `provenance_mix` 五档必须**加总等于 findings+unknowns 条数**，前端当场核，不等就报红。

## 6. 界面

- 三栏 grid：`编辑区 | 对话历史 | 结构化结果`；断点 1100px（结果变下抽屉）、760px（三栏变标签页，历史与结果各一屏）。
- 编辑区：行号、软 Tab、括号配平高亮、粘贴保留缩进、`Ctrl+Enter` 发起一发；语言手选（默认自动，自动那条要显示判据）。
- 历史区：每轮一问一答，点开看该轮 trace；**出处徽章**（五档五形，不只靠颜色——色盲也能分）。
- 结果区：findings 卡按严重度排序 + 度量表 + `unknowns` 段（不许折叠掉）；页顶一条**结论带**（账触发过几次、有没有 NOT_RUN 的格子）。
- 排版：正文系统字族、代码 `ui-monospace`；对比度按 WCAG AA；焦点可见；键盘可完成整圈。
- 空态/加载/错误/打断四态各有一张真样子（不是 spinner 到底）；被打断时**照样交已落的那部分账**并标明结束原因。

## 7. 内核记账接缝（只消费格，表不动）

- 复用 agentd 的姿势：同进程 `mcpsrv.New()` + `Serialize(line)`，**不另写一套 Check**、不起子进程、不开端口。
- 内核包与 `contract.md` 的 **48 键 / 49 格一个字不动**；本应用只往格子里填真值：
  输入侧填 `content_bytes / parts / shares / folded`，输出侧填 `usage_in/out / wire_bytes_in/out / chunks / fail_kind` 等；
  量不到的**记 absent + 理由**，绝不记 0。
- `declare_reader` 逐格声明谁读了什么（agentd 已把 input 20/20、output 29/29 这条路跑通过）。
- **KPI 仍是"账本触发过几次决定"**，反臂同一条：不 `read_back` ⇒ 掉回 0。这条不掉，Web 版就不算接上。
- 真流量默认不打：网关未配置 ⇒ 那一档记 `absent`/`NOT_RUN`，而不是"成功但空"。

## 8. 模型网关（这一路怎么诚实）

- 配置只走环境变量（端点 + 口令名），**口令不写盘、不入账、不进日志、不进本文档**。
- 未配置 ⇒ 返回 `NOT_RUN`，UI 显示灰徽章"这一路没跑"；结果区里凡本该由模型给的字段一律 `absent + 理由`。
- 已配置 ⇒ 走 `chat.completion` 兼容形状，字节数/分帧/首字延迟/最大间隔**从真 socket 上数**（agentd 的 `fakesrv.go` 那套计数姿势可以直接搬），
  模型自报的 token 记 `relayed`，绝不算 `measured`。
- 本机现状（实测 22:35）：环境变量名里只有一个 `QODER_SDK_CUSTOM_BASE_URL_BYOK`，长度 1；
  **我没有拿它去连任何端点**（那属于要先批准的动作），所以这一路今天记 `未核`，不记 `可用`。

## 9. 测试与验收（每条都得能红）

1. **单测**：analyzer 对 fixture 集逐条判据（该红的红、该不误报的不误报）；五档加总恒等式；schema 校验。
2. **反臂**（必须是叶子，不能套在正臂里）：去掉 `read_back` ⇒ KPI=0；把 `measured` 硬写成 0 ⇒ 判据红；
   伪造 `absent` 成成功卡 ⇒ 前端当场报红。
3. **端到端**：`browser-use` 真开这页，跑一圈：贴 fixture → 发问 → 九步逐条亮 → 结果区出现 findings → 刷新后历史能复原。
4. **打断**：跑一半点停 ⇒ 已落的账照常交、结束原因写在结论带，与 agentd 六态退出码同族（Web 侧映射成状态字）。
5. **安全**：不执行用户代码这条要有针 —— 造一个 fixture 里带 `os/exec` 调用的样本，断言 analyzer 只报不改、且进程没起子进程。
6. **响应式**：1440 / 1100 / 760 / 390 四档截图留档，窄屏下三栏切换可用。

## 10. 分期（每段一轮可单独验收）

| 段 | 交付 | 验收读数 |
|---|---|---|
| W1 | 骨架：Go 服务 + 零构建三栏页 + 一发只跑 `go/ast` 度量，端到端出结构化 JSON | 浏览器能开、能发问、能出结果 |
| W2 | 循环看得见：SSE 九步流 + trace 抽屉 + 能停 | 步骤逐条亮、停下发数与已落账一致 |
| W3 | findings 完整 schema + 五档徽章 + unknowns 段 | 加总恒等式在页上核过 |
| W4 | 内核接缝进这一发 + `declare_reader` + KPI/反臂 | KPI≥1 且去掉读回掉回 0；表未动（`diff -rq`） |
| W5 | 调试路径（报错栈→行定位）与优化路径（度量→建议→验法） | fixture 考卷通过率自印 |
| W6 | 网关：假端点（本机 127.0.0.1）把管路数出真值；真端点无凭据 ⇒ NOT_RUN | 分帧三格有真数；NOT_RUN 不写 0 |
| W7 | 多语言降档（Python/JS 保守扫描，全标 estimated） | 每一格降档都有理由 |
| W8 | 响应式与可达性打磨 + 端到端 browser 实测留档 | 四档截图 + AA 对比 + 键盘走通整圈 |

## 11. 今天还不能说的话

- 不能说"它能修好代码"：默认只出建议与可选补丁，不执行、不自动改用户仓库。
- 不能说"模型判断过了"：W1–W5 全部离线确定性可数；凡走模型那一段没配置就是 NOT_RUN。
- 不能说"挡住了注入/攻击"：这是**审计层不是防线**（与内核同口径，只对应 MCP08 那一格）。
- 未决：BYOK 那一格要不要试（要先批准）；页面要不要并入现有面板方案（`报告/面板方案-待批.txt` 的三个决定还悬着）。

## 12. 落点与文件清单（W1 要建的东西）

```
编程Agent-1020/
  架构设计-编程Agent.md      ← 本件
  数据/                      ← sessions / ledger 落盘（W1 起）
  src/pgagentd/  main.go server.go sse.go orchestrator.go analyzers.go schema.go store.go gateway.go ledger.go
  web/         index.html app.js style.css
  fixtures/    go_缺陷族.txt py_降档.txt js_降档.txt 报错栈.txt
  运行记录.txt  ← 每段跑完把读数追加在这里（与 agentd 同格式）
```

> 这一版是**设计与实现方案**，代码还没落。W1 开工前只剩两个选型要我按你的答复来定：
> ① 前端走**零构建**（我建的那个静态页）还是 **Vite/React**（node 与 npm 实测都通，做得到，代价是 `node_modules` 与构建步骤）；
> ② 分析件先只做 **Go 真解析**（能数、可验），还是同时铺 **Python/JS 保守扫描**（全在 estimated 档，界面上要看得出它是降档）。
> 不选也行的默认：**零构建 + 先只做 Go**，其余按 §10 分段往下推。
