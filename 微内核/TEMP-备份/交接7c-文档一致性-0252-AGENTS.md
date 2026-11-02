# agentkernel 研究现场 · 编码代理 operating guide

本目录不是单一工程，是四条并列面（记账内核 / Go 宿主 / 编程 Agent / AgentHub）加研究件。
这份文件只写**不可推断的本机事实**：不在 PATH 的工具链、实跑过的命令、冻结边界、改前的备份规矩。
架构与口径细节一律路由给 owner，这里不复述。
三面各有一份局部指南，改动那三面之前先读它（运行环境若不自动加载嵌套指南，就手动读）：
内核 Go 树 `微内核/微内核/AGENTS.md` · 编程 Agent `编程Agent-1020/AGENTS.md` · AgentHub `AgentHub-1021/AGENTS.md`。

## 工具链（前两个不在 PATH，必须用绝对路径）

| 件 | 路径 | 2026-10-22 实跑版本 |
|---|---|---|
| Go | `C:/Users/Admin/sdk/go/bin/go.exe` | go1.27.2 windows/amd64 |
| Python | `C:/Users/Admin/sdk/py314/python.exe` | 3.14.1 |
| Node | PATH 上直接 `node` | v22.23.2 |

Shell：Git Bash（`C:\Program Files\Git\bin\bash.exe`）/ Windows 10.0.22631。
下面每条命令都带工作目录，照抄即可，把 `cd` 换成自己的目录会失败（脚本按相对路径找 工具/ 与 读数/）。

## 实跑过的四条闸

1. 内核快闸 —— 工作目录 `微内核/微内核`：

   ```bash
   C:/Users/Admin/sdk/go/bin/go.exe run ./cmd/kcheck
   ```

2. 宿主测试 —— 工作目录 `微内核/微内核`：

   ```bash
   C:/Users/Admin/sdk/go/bin/go.exe test ./cmd/agentd/ -count=1
   ```

3. 编程 Agent 那七道 —— 工作目录 `编程Agent-1020`：

   ```bash
   C:/Users/Admin/sdk/py314/python.exe 工具/验收.py C:/Users/Admin/sdk/go/bin/go.exe
   ```

4. AgentHub 那六道 —— 工作目录 `AgentHub-1021`：

   ```bash
   C:/Users/Admin/sdk/py314/python.exe 工具/验收.py C:/Users/Admin/sdk/go/bin/go.exe
   ```

2026-10-22 这一趟：1 退出码 0、2 `ok agentkernel/cmd/agentd`、3 结论「7 道闸全过」、4 结论「8 行闸读数全过」。
3 与 4 只监听 127.0.0.1 随机空闲端口，数据目录建在 TEMP 且跑完删；现数读数各自落在本面的 `报告-验收.txt`，别把上面的数抄进文档当基线。

0. 想一次跑完「内核快闸 + 宿主测试 + 尺子那几道 + 事件层八条针」（道数别在这儿抄，读 `报告-全闸.txt` 自己印的行数），用这一件（工作目录 `事件层-1022`）：

   ```bash
   C:/Users/Admin/sdk/py314/python.exe 体检-全闸-1023.py C:/Users/Admin/sdk/go/bin/go.exe "C:/Users/Admin/Desktop/微内核/微内核/微内核"
   # 臂检那一道一趟十几分钟，可加 --skip-arms；加了它会核「臂读数比树新不新」并如实标 FRESH/STALE
   ```

   它自己不判任何东西 —— 每道闸的判据仍归各自主人；它只保证「没人只跑两道就报全绿」。
   读数落 `事件层-1022/报告-全闸.txt`（八条针那份在 `报告-验收.txt`）。
   事件层的臂件已收成一个 owner：`臂检-全部族.py`（五件历史散臂检软隔离在 `TEMP-备份/臂检散件-1022/`，别再单独跑）。

**未跑，不当成已验**：`构建-1017/打包.py` 会重生成 zip 与便携树（zip 哈希会变），属交付动作，要单独批准再跑。

## 改任何东西之前

- **本目录不是 git 仓库，没有回滚。** 改文件前先复制进 `TEMP-备份/`。`Desktop\微内核.zip` 那份兜底快照停在 09-27，不要指望它。
- **内核 v1 已冻结**：48 键 / 49 格，`微内核/微内核/README.md:631` 明写 §8「15 条为止，停止新增」。下游三面**只消费格子，不新增格子**；动判据表要三件配齐，是单独的决定。
- **8797 / 8799 是两本内核研究账**，未经批准不许把真流量写进去。别按端口号猜是谁的账，先验 owner。
- **密钥只走环境变量**，绝不写进仓库文件、记忆或账本。
- **默认不执行用户代码**；要跑必须显式批准 + 临时目录 + 超时。
- **GBK 控制台**：Python 打印 `✓` / `⇒` 会崩，崩掉的是退出码契约（rc=1 会冒充闸红）。产物文件用 UTF-8 句柄写，与控制台编码无关。

## 先看哪份再动哪块

| 要改的 | 先读 owner |
|---|---|
| 模块边界、新增容器、谁连谁 | `架构-1020/README.md` → `current-state.md` / `target-agent.md` / `evidence.md` |
| 交付件要出 PDF（本机无 LaTeX，但有走通的替代路） | `市场报告-1020/build_pdf.py` + `print_cdp.js`：分段 HTML（`src/0*.html`）→ Edge `--headless=new` 起 CDP → `Page.printToPDF` → `pdftotext` 回填页码。v3 已适配版在 `市场报告-1022/`（`build_pdf.py` 要 `missing 0` 且 `KEY_TEXT` 与 `data-key` 同步；出完必须无头截图肉眼核，`PASS` 不等于能读） |
| 宿主的事件、进度、断线语义 | `研究-协同工作-1022.md` §5 事件契约 + §8 落地清单与 8 条验收针 |
| 事件层要落成哪几发 | `事件层-1022/README.md` → `计划-agentd事件层.json`（E1–E9）与两张 DOT；证据索引 `事件层-1022/evidence.md` |
| 这四条闸与六族臂**怎么跑**、每条印什么 | `事件层-1022/说明书-闸与尺子怎么跑-1022.md`（本机 10-22 现跑过） |
| 接手事件层：现在在哪格、哪些数不能说什么、下一手 | `事件层-1022/交接-agentd事件层-1022.md` |
| 架构件的引用还对不对（尺子有几把别在这儿数，看 `说明书-闸与尺子怎么跑-1022.md` §5） | 工作目录 `事件层-1022`：`C:/Users/Admin/sdk/py314/python.exe 锚点核对.py` 与 `证据模型核对.py`；**另有一把只读普查 `锚点普查-散文行号-1023.py`**（不进任何合取、升成闸要批准；后面传的是**目录**，别照抄全闸那条命令行把 `go.exe` 传进去）。退出码 3 有两种成因：坏件 **或臂没红**——臂不红时「全命中」不作数 |
| wire 形状（Basis 枚举、PartCount、49 格出处） | `微内核/微内核/contract.md` §2.5 —— schema 里看不出来，别靠读代码猜 |
| 只读面板 / 审计那一块 | `微内核/微内核/报告/面板方案-待批.txt`（三个决定还没圈，没圈不许开工） |
| 某个读数的来历 | 该面的 `报告-验收.txt` 与 `读数/`，「最新」只按 mtime 认 |

## 报数口径（这个现场的硬规矩，由作者定）

- 分母自己印，不手抄；每条结论要能追到 `path:line` 或盘上读数。
- 三态不许塌：`absent` 必须带「为什么缺席」的理由；量不到绝不写成 0；「本来没这回事」不许挂成未决。
- 剧本走出来的绿、离线判据的绿，绝不写成「模型自主决定的绿」。
- 全绿先问「这把尺子会不会红」：每条判据配反臂，臂必须是叶子。
- 真模型端点与真人可用性目前均 NOT_RUN，明写 NOT_RUN，不折算成 0。

## 已知缺口（别当已完成）

- 无 git / 无 CI / 无 CODEOWNERS：没有任何强制门禁，全靠上面四条闸手动跑。
- `sanjiantao-neihe-agent` 技能声明的 `scripts/run.sh` 在盘上不存在（该技能目录只有 `SKILL.md`）。三件套内核直接走 `C:/Users/Admin/Desktop/Agent与模型/Agent项目/Agent项目/工程熵治理/agentkernel/cli.js`，入口是 `node cli.js verify` / `node cli.js redtest`。
