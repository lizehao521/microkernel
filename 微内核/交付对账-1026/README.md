# 交付对账（1026）

把编程 Agent 的「交付声明」逐条对到盘上的证据，出一张三态回执：每条声明是
MATCH / MISMATCH / ABSENT，整体是 ACCEPTED / NOT-ACCEPTED-MISMATCH /
NOT-ACCEPTED-UNVERIFIED。给用 Agent 写代码的人自己交差前自查，也给团队负责人收货时抽检。

## 三条边界（不可协商）

1. **只读**：不执行被交付的代码，不改任何输入文件。验收会逐文件取 sha256 前后对比。
2. **不联网、不跑模型**：`工具/对账单.py` 只 import 标准库（argparse / base64 / datetime /
   hashlib / html / json / os / re / sys）。验收用 AST 静态扫描挡住网络与模型客户端。
3. **不判对错**：核对的是「声明 vs 盘上证据」是否一致，不判断代码或结论本身对不对；
   证据是怎么产生的，本件也证不了（日志可能是事后补的）。

## 一发行怎么走

```
交付声明.json ──> 工具/对账单.py ──> 读数/<名>.json + 读数/<名>.html ──> 退出码
```

- 声明里的路径**相对声明文件所在目录**解析。
- 回执里钉住工具 sha256 与声明 sha256，可追到是哪一版工具、哪一份输入。
- HTML 是自包含单文件，浏览器直接打开；末行印 `landing check: n/n rows OK`，
  与 JSON 的条数、HTML 的行数三者互相核对（落盘后从盘上重读，不信内存；
  对不上印 `MISMATCH` 并以 rc=1 退出）。

## 支持哪些声明（claim kind）

| kind | 核对 | 备注 |
|---|---|---|
| `file_exists` / `file_absent` | 文件在 / 不在 | `file_absent` 命中即 MATCH |
| `file_sha256` | 文件指纹 | 收 64 位全量，或 16 位前缀 |
| `file_bytes` / `file_lines` | 字节数 / 行数 | 字节数取盘上真实尺寸（`getsize`），不是字符数；行数按 `splitlines` 计 |
| `file_contains` | 某行/任意行含子串 | 可选 `line`（1 起）；行号越界记 ABSENT；`value` 缺失或空串直接 ABSENT（空串会恒真） |
| `log_exit` | 日志**最后一条非空行**是 `exit_code=N` | 整行必须只有这个形状；别的尾巴记 ABSENT，不当 0 |
| `log_contains` | 日志含子串 | 逐字匹配 |
| `json_value` / `json_number` / `json_bool` / `json_string` | JSON 某格的值与类型 | 路径支持 `a.b[0].c` |
| `json_len` | 数组/对象/字符串长度 | — |

不认识的 kind **不会静默通过**，记 ABSENT 并写明「本件不认识这个核对类型」。
JSON 读不出来、文件缺失、路径越界，一律 ABSENT 且带原因；**量不到绝不写成 0**。

## 三态、两档来源

- 声明判定：MATCH / MISMATCH / ABSENT。
- 声明来源：`disk`（盘上可复核）或 `self`（交付方自己的产物）。
  **只有明写 `"evidence_class": "disk"` 才算盘上证据**；省略、写错、写成 `self`
  一律按自报处理——自报不可能换来 ACCEPTED。
  - `self` 声明无论判 MATCH 还是 MISMATCH，依据档都记 `relayed`（值不是我们量出来的）；
    `disk` 的 MATCH / MISMATCH 才是 `measured`。
  - **只要有一条 `self` 声明，整单最多 NOT-ACCEPTED-UNVERIFIED**，不可能 ACCEPTED。
- 证据源判定：GREEN / RED / ABSENT；单条判据另有 **VACUOUS**——
  表示「本批根本没有这类事情」，不是通过。交付方自报的读数进 `relayed` 列表，标「本件不重算」。
  `evidence` 里出现本件不认识的源键时记一档 ABSENT（S0），不静默丢弃。

## 状态与退出码

| status | rc | 含义 |
|---|---|---|
| `ACCEPTED` | 0 | 每条声明都由盘上证据复核通过，证据源无红，且没有仅凭自报的项 |
| `NOT-ACCEPTED-MISMATCH` | 2 | 有声明与盘上事实不符，或某个证据源判红 |
| `NOT-ACCEPTED-UNVERIFIED` | 3 | 有声明无法回盘核 / 证据源核不全 / 有仅凭自报的项；**0 条声明也归这一档**（没有可核的东西，不是通过） |
| （本件自己出错） | 1 | 输入不是合法 UTF-8 JSON、重复声明 id、落盘校验不一致等 |

## 三个证据源各核什么

**pgagent 轨迹**（可选）：P0 指纹与钉住值（对上也明判 GREEN）、P1 JSON 可解析、P2 步数、P3 每步 ran=true、
P4 每步 basis 合法、P5 末步是终态、P6 五档恒等（findings+unknowns）、P7 finding/unknown 的
basis、P8 unknown 带 `why_absent`、P9 条数与钉住值、P10 finding 的行号能回盘。
P10 在「源码没随交付一起交」或 findings 没带 `where.lines` 时记 ABSENT（**不是**绿）；
交了源码但行号越界才判红。自报的 `trace_sane` / `chain_sane` / `kpi_ledger_decided` /
`mix_identity_ok` 只在报 false 时挂红，报 true 进 `relayed`。

**agentd 事件层**：E0 指纹、E1 逐行可解析（非对象行另计）、E2 必备字段、E3 每个 (session, turn) 的 seq
严格递增且不重号（**不要求从 1 开始**，turn 0 是运行级记账）、E4 依据档合法、
E5 拒绝必带理由、E6 absent 必带理由、E7 每个 run 有 run_started+run_settled，
每个 turn>0 有 turn_settled、E8 事件流非空（空文件记 ABSENT，不是 GREEN）。
E5/E6 在一批里没有对应事件时记 VACUOUS。

**内核账本**：J0 指纹、J1 逐行可解析（表头行单独计）、J2 条数、J3 表头行数、
J4 seal 重算、J5 `prev_hash` 链接、J6 seq 从 1 连号、J7 payload 指纹、
J8 按 (session, step) 分 49 格组、20 入 / 29 出、J9 账本非空（空文件记 ABSENT）。
**只核可复算的形状，不核每格内容对不对**
（内核 v1 已冻结：48 键 / 49 格，本件只消费格子，不新增格子）。

## 盘上有什么

```
交付对账-1026/
├─ 工具/对账单.py          主工具（单文件，只 import 标准库）
├─ 工具/臂检-对账单.py     每根臂一个单点变异 + 1 条负对照（臂数由件自印）
├─ 工具/验收.py            三份样例回放 + HTML 结构 + 只读性 + 静态边界 + 臂检
├─ 示例-编程/              好交付样例（声明 + 工作区 + 证据）
├─ 示例-编程-谎报/         谎报样例（同一份声明，盘上没改）
├─ 样例/交付声明-真端点.json  pgagent 真端点那一发的声明
├─ 读数/对账单-*.json|html  三份回执
├─ 读数/截图-对账单-*.png   三份回执的无头浏览器截图（肉眼核过）
├─ 读数/臂检-对账单.txt     臂检自印的读数
└─ 报告-验收.txt            验收自印的读数
```

「最新」只按 mtime 认，不抄时间戳进文档。

## 怎么跑（工作目录：本目录）

```bash
C:/Users/Admin/sdk/py314/python.exe 工具/对账单.py 示例-编程/交付声明.json -o 读数/x.json --html 读数/x.html
C:/Users/Admin/sdk/py314/python.exe 工具/臂检-对账单.py
C:/Users/Admin/sdk/py314/python.exe 工具/验收.py
```

- 控制台只印 ASCII（本机 GBK 控制台印 `✓` / 中文会崩，崩掉的是退出码契约）。
  产物文件一律 UTF-8 句柄写，与控制台编码无关。
- 本机 SDK Python 3.14 打开了 `safe_path`：CWD 与脚本目录不在 `sys.path` 上。
  主工具不靠同目录 import；若要扩工具，别用隐式相对导入。
- 臂检把样例整树复制进 TEMP，一次只改一处，断言「相对干净对照的精确增量」；
  汇总行自印臂数与通过数，负对照故意写错，必须红（`FAIL-AS-EXPECTED` 才算有牙）。

## 三份样例的诚实说明

1. `示例-编程` / `示例-编程-谎报`：**人工扮演的 Agent**，不是模型自主产出。它们证明的是
   回执的形状与分辨力（好交付 8/8 绿；谎报 5 条红、3 条真话仍绿），不证明任何模型水平。
2. `样例/交付声明-真端点.json`：来自 2026-10-23 真端点那一发 pgagent（13 步轨迹）。
   但**被审的源码没有随交付一起交**（D3 ABSENT），findings 的 `where.lines` 是 `[0,0]`
   回不了盘（P10 ABSENT），且 9 条声明里 8 条只有交付方自己的产物作证（`self`）。
   所以这单是 **NOT-ACCEPTED-UNVERIFIED，rc=3**——这正是本件的价值：把「核不了」如实印出来，
   而不是拿自报当绿灯。
3. 同一份声明里的 agentd 与内核账本是**形状样例，与该交付无因果关系**；
   内核账本是 10-18 客服靶场导出的 2940 条，不是这一发的账本。本件只核它自己的链与 49 格形状。

## 验收说什么才算数

`工具/验收.py` 现跑 **85 项检查全过、rc=0**：

- 每份回执先删旧文件再跑，`generated_at` 必须不早于本趟起点（旧件冒充不了新件）；
- 三份样例的状态、rc、逐条判定、依据档、证据源判定、自报项值都与期望一致；
- HTML 标签配平、行数三处一致、**逐行 id+判定与 JSON 对账**、证据源段数与 JSON 一致、
  无替换字符（U+FFFD）、横幅颜色与状态一致、末行 `landing check: n/n rows OK`；
- 回执里钉的工具 sha256 / 声明 sha256 与盘上当前件一致；
- 所有输入文件跑前跑后 sha256 不变（真只读）；任何一项失败就把上一趟读数还原，不留半新半旧；
- 两个工具件的 import 白名单与禁网扫描；
- 臂检 `arms=24 pass=24 fail=0 neg_control_biting=True`，结论 `ALL-ARMS-BITE`。
  臂的汇总行与落盘读数都要对上，臂数只作下限（`>= 24`），不是从索引表抄来的分母。

`ALL-GREEN` 只代表上面这些成立；它不替模型水平、代码质量、真人可用性背书。

## 这张单子证明不了什么

- 只读盘上文件：不执行被交付的代码，不联网，不改任何输入。
- 核对的是「声明 vs 盘上证据」是否一致，不判断代码或结论本身对不对。
- 证据怎么产生的，本件证不了：日志与文件可能是事后补的，本件只核它们与声明是否对得上。
- 交付方自报的读数（trace_sane / KPI / chain_sane 等）记为 relayed，本件不重算。
- 内核账本只核 seal / 链接 / 序号 / payload / 49 格分组这些可复算的形状，不核每格内容对不对。
- ACCEPTED 只代表「每条声明都由盘上证据复核通过，且没有仅凭自报的项」；不代表代码正确或测试充分。

## 自己写一份声明

```json
{
  "session": "谁的哪次交付",
  "delivery": {"by": "交付方", "task": "一句话任务", "produced_at": "2026-10-26"},
  "claims": [
    {"id": "C1", "kind": "file_sha256", "path": "工作区/calc.py",
     "value": "<64 位或 16 位前缀>", "evidence_class": "disk", "why": "为什么核这条"}
  ],
  "evidence": {
    "pgagent": {"path": "…", "sha256": "…", "relation": "本交付的证据",
                "expect": {"steps": 13, "findings": 1, "unknowns": 6}},
    "agentd":  {"path": "…", "sha256": "…", "relation": "形状样例"},
    "journal": {"path": "…", "sha256": "…", "relation": "形状样例",
                "expect": {"records": 2940, "header_lines": 1, "groups": 60, "cells_per_group": 49}}
  }
}
```

`evidence` 整块可省略；三个源都可单独出现。`sha256` 是钉指纹——钉了就会有一条
P0/E0/J0 的明判（对上 GREEN、对不上 RED），不钉就没有这一条（不是 ABSENT）。
