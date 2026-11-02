# 市场报告-1022 · Agentkernel 市场进入研究 v3（证据更新版）

## 交付物

| 件 | 读数 | 说明 |
|---|---|---|
| `agentkernel-市场进入研究-v3-1022.pdf` | 字节数 / 页数 / SHA256 **全部以 `MANIFEST.txt` 为准**（构建自印，本行原先手抄过一对数，那对数停在 10-22 16:0x 的那一次构建，`MANIFEST.txt:5-8` 早已自印成另一对 —— 两份并存就是账实不符） | 对外可读版。「哪份是最新」只按 mtime 认；要改仓库里的数就重跑 `build_pdf.py`（交付动作，需单独批准） |
| `报告.html` | 字节数与 sha256 同样以 `MANIFEST.txt` 为准（`html_bytes` / `html_sha256` 两行，构建自印） | 单文件 HTML（PDF 的源），双击即看 |
| `MANIFEST.txt` | 页数/字节/双 sha/CJK 字数/目录键/密钥扫描 | 构建自印，不手抄 |
| `src/0*.html` | 8 段源 | 版式沿用 `市场报告-1020/src/00-head.html` |
| `build_pdf.py`、`print_cdp.js` | 从 1020 克隆并**已适配**（TMP/输出名、`KEY_TEXT` 28 键、索引结束标记改成「图表索引」） | 拼装 → Edge `--headless=new` CDP `Page.printToPDF` → `pdftotext` 回填页码，最多 5 轮直到稳定 |

## 怎么重跑（工作目录 `市场报告-1022`）

```bash
C:/Users/Admin/sdk/py314/python.exe build_pdf.py
C:/Users/Admin/sdk/py314/python.exe ../研究-1022/话术闸.py 报告.html
```

第一条打印 `PASS <轮次> pages 29 filled 28 missing 0` 才算装配过；`missing` 非 0 说明 `src/01-cover-toc.html` 的 `data-key` 与 `build_pdf.py` 的 `KEY_TEXT` 不同步。
第二条扫交付件**本身**（不是扫源件）：四类越界话术 + `[High]` 无凭据，五条臂都验过会红。

## v3 与 v2 的分工

v2（`../市场报告-1020/`，48 页，SHA256 `2766192e…cacff`）**不作废、不覆盖**。
想知道「为什么值得看这个件」读 v2；想知道「哪些话现在不能说」读 v3。逐主张对照见 v3 附录 B。

## 本轮被图与闸抓到的两处真缺陷（都已修，留档防复发）

1. **封面文字压在页眉上被裁**：我把 `<p class="glow">` 当正文用了，而 `.glow` 在 CSS 里是**绝对定位的装饰层**。改用 v2 的真实结构（`.sub`/`.object`/`.verdict`/`table.stats`/`.foot`）。
2. **判定框里 `strong` 读不出来**：全局 `b,strong{color:#0b1f33}` 是给浅色页的深墨，落进封面深色底上对比度只有 **1.01**。加了作用域规则后实测 **12.32**（过 WCAG AA 正文门槛 4.5）。
   教训：**「构建 PASS + 页码齐」不等于页面能读**——出图这一步不是装饰，是验收。

## 未验 / 不做（不折成 0）

- 窄屏与打印分页的逐页肉眼核验：只看了封面与浅色正文首屏（Edge 无头截图），**其余 27 页未逐页开图**。
- 外部字体：无（`system-ui`/`Microsoft YaHei`/`Cascadia Mono` 本机族），故离线可看。
- 本报告不给市场规模结论、不给「符合某法规」的声明；真人 0/1、访谈 0/10、LOI 0、付费 0、事件层 E1–E9 仍是 Planned。
