# agentkernel 市场进入研究 · 1019

**问题**：以哪种方式面对市场——研究出版、开源、企业私有化、托管按次、竞赛生态，先走哪条。

**结论**：**D + A 先行**（研究出版 + 开源证据闸门）；**B 条件触发**（企业私有化，Gate 2 通过后再走）；**C 不做**（托管按次）；**E 可选**（竞赛/生态）。六个月四道闸，不过就冻结为研究资产 C。

## 交付物

| 文件 | 说明 |
|---|---|
| `agentkernel-市场进入研究-1019.pdf` | 最终报告，67 页，13 章 + 5 附录，11 图 15 表 |
| `报告.html` | 与 PDF 同源的完整 HTML（含已回填页码） |
| `MANIFEST.txt` | 构建时间、页数、字节数、SHA256、页码键与密钥扫描结果 |
| `src/` | 8 个 HTML 片段（正文唯一源；改内容改这里） |
| `build_pdf.py` | 拼装 → 打印 PDF → 抽页回填 62 个目录/图表页码 → 校验 → 写 MANIFEST |
| `print_cdp.js` | Edge headless + CDP `Page.printToPDF`，自定义页脚（标题 + 当前页/总页），不显示本地 URL |

最终 PDF：2,097,438 字节，SHA256 `d11cbcd254c3f073cfd71fc7cce121060d648ac113920bb948f52dc23877df31`。

## 重建

依赖：Python 3、Microsoft Edge、`pdftotext`、Node（或 Qoder 自带 Electron）。

```bash
cd "C:/Users/Admin/Desktop/微内核/市场报告-1019"
"C:/Users/Admin/sdk/py314/python.exe" build_pdf.py
```

- Node 依次尝试 `NODE_EXE` 环境变量、`C:\Users\Admin\AppData\Local\Programs\Qoder CN\Qoder CN.exe`、`node`；用 Electron 时脚本自动设 `ELECTRON_RUN_AS_NODE=1`。
- `pdftotext` 需在 PATH（本机在 Git Bash 的 `/mingw64/bin`）。
- 产物先写 `C:/Users/Admin/agentkernel-market-1019.{html,pdf}`，稳定后复制进本目录。
- 目录页码是**构建期回填**：内容增删后必须重跑，否则目录页码与正文不符。

## 来源与口径

- 外部市场数据为 **D 级**（公开资料，见附录 C 参考文献 [1]–[33]）；规模给区间不给单点，子层占比属 **C 级假设**。
- 产品证据为 **A/B 级**（内核账本、离线测试、双臂盲测与独立复算）；作者自测、未过真人复核的项标 **X 级**。
- 分级定义：A 工具自印 + 独立复算/双源；B 单源自印；C 作者复算/规划假设；D 外部公开资料；X 不可核/未验证，**不塌成 0**。
- 本报告**未找到付款证据**，故写“未找到付款证据”，不写“0 个买家”。
- 26 策略引擎只作技术品牌附件：目录 26 条、有实现分支 20 条、恒等返回 1 条（`context_switch`）、元策略 5 条；真实靶场 NOT_RUN，宿主引擎在 Qoder 内执行 0 次。

## 限制

- 本地 `market-research-reports` skill 仅有 `SKILL.md`，缺 LaTeX 样式与绘图脚本；本报告改用 HTML/CSS + 内联 SVG + CDP 打印，因此**不是**该 skill 的默认 LaTeX 产物。
- 访谈、LOI、安全审查、真人计时均未执行；四道闸是**待跑判据**，不是已完成结果。
- 财务为三情景规划值，非承诺；乐观情景 Y3 柱形在坐标上限 2,000 处截断，caption 已注明。
- 已知版面小瑕疵：第 47 页顶部有表 14 末行 R12 与表头分离；第 40 页决策树顶部留白偏大；第 25 页图 4 后有大片空白。均不影响内容完整性。
- 本文不是投资、法律或合规意见；不构成对任何监管义务的符合性声明。

## 复现校验

```bash
pdftotext -enc UTF-8 agentkernel-市场进入研究-1019.pdf - | tr -cd '\f' | wc -c   # 67 个换页符 → 67 页
sha256sum agentkernel-市场进入研究-1019.pdf
```
