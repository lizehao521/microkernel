# 接 GPU + Qwen3 本地端点 · 方案与验收（写给"到位即可执行"，含本机实测规格）

生成 2026-10-17 21:55。**这份件不写会漂的数**：下面凡标「本机实测」的都是今天探针印出来的，
凡标「工程估算」的是选型阈值、不是这台机测出来的，两者不许混着读。

## 0 · 本机实测（决定"这台机不能干什么"）

| 项 | 实测 |
|---|---|
| GPU | **没有**。`nvidia-smi` 不存在；唯一显示设备 `ELINK DISPLAY WDDM DRIVER`、`AdapterRAM 0`（云实例虚拟显卡） |
| CPU | Intel Xeon Platinum 8378C @ 2.80GHz，`NUMBER_OF_PROCESSORS=8` |
| 内存 | 总 16 GB，**空闲 7.1 GB**（探针印） |
| 磁盘 | C: 剩 **39.2 GB**（已用 40.7 GB） |
| 推理运行时 | `ollama` / `llama-server` / `llama-cli` / `vllm` **全部没有**；`11434/8000/8080/1234/5000` 上无监听 |
| 已有 SDK | `C:\Users\Admin\sdk\go`（Go 1.27.2）、`C:\Users\Admin\sdk\py314`（Python 3.14.1） |
| 端点口令 | `AGNES_BASE` / `AGNES_MODEL` / `AGNES_KEY` **本 shell 未设置**（上次那把只活在当时的会话环境里，不跨会话） |

⇒ 这台机跑不了 vLLM（要 CUDA）。CPU 推理能跑但很紧：8B Q4 权重 ~5 GB vs 空闲 7.1 GB，长上下文容易溢；4B 稳。
⇒ 要真接 GPU，得等你那台云 GPU 服务器；这台只适合当**调用方 + 记账方**（内核、驱动、验收都在这里跑）。

## 1 · "Qwen3.8 flash" 我按哪种理解（两种都给）

**先报一条验行号时撞出来的事实，它可能直接取消"要买卡"这个前提**：
仓库三个驱动**默认就指着一个 hosted OpenAI 兼容端点** ——
`tasks/mcp/llm_probe.py:27` / `tasks/mcp/agent.py:28` / `tasks/mcp/qa_loop.py:27` 都写着
`BASE = os.environ.get("AGNES_BASE", "https://api.agnes-ai.cn/v1")`，
模型名默认是 **`agnes-3.0-flash`**（同三个文件的 `:28` / `:29`）。
⇒ 所以「带上内核」这件事**本来就不需要 GPU**：内核已经会往一个 flash 档位的 hosted 端点发；
   今天缺的只有一样——`AGNES_KEY`（本 shell 实测未设置）。
⇒ 你要 GPU 的场景是另一种：**把端点换成自己租的机器**（不想依赖那家、要本地权重、要可控的流式与 usage 形状）。这两种我都需要你确认是哪一种，
   因为"Qwen3.8 flash"这个说法和仓库里那个 `agnes-3.0-flash` 太像，我不敢替你猜。

- **若你确实要本地 Qwen3-8B 开源权重** ⇒ 走 §2–§4，端点由你自托管，内核只需把 `AGNES_BASE` 指过去。
- **若你指的是阿里云百炼 / DashScope 的 `qwen-flash` 那一档**：那也是 hosted API、**不需要卡**，与上一条同理，只是端点与计量口径不同。
- 若是 **Qwen3-8B 的某个具体量化/指令版本**（Instruct / Thinking / GGUF / AWQ），§2 的阈值按权重实际位宽对号入座。

## 2 · 选型阈值（工程估算，不是本机实测）

| 目标 | 显存阈值（含 KV cache 余量） | 说明 |
|---|---|---|
| Qwen3-8B **fp16** | ≥ 24 GB 起步，长上下文要 40 GB+ | 权重 ~16 GB + KV |
| Qwen3-8B **4bit（AWQ/GPTQ/Q4_K_M）** | 12–16 GB 可用，24 GB 舒服 | 权重 ~5 GB |
| Qwen3-4B 4bit | 8 GB 级即可（L4/T4 能跑） | 想快速把通路打通就用它 |
| 卡型对照 | T4 16G：建议 4B；L4/A10/RTX4090 24G：8B-4bit + 中等上下文；A100/L20 40–80G：8B-fp16 + 长上下文 | 云上要的是"显存 + 带宽"，不是核数 |

## 3 · 运行时怎么选（两条都出 OpenAI 兼容 `/v1/chat/completions`）

- **vLLM**（要 CUDA）：`usage` 字段真给、批处理好。接内核最省事。
- **llama.cpp / `llama-server`**：CPU 也能跑（这台机就是它的用武之地），GPU 版走 CUDA 后端。
  `usage`/tokens 有，但**流式时给不给 `usage` 要实测**（见 §5 那条陷阱）。

## 4 · 内核怎么接：**不动封板树**

- 认环境变量的驱动有三个：`tasks/mcp/agent.py:28-30`、`tasks/mcp/llm_probe.py:27-29`、`tasks/mcp/qa_loop.py:27-29` ⇒
  只要把 `AGNES_BASE` 指到本地/云上端点（如 `http://<gpu-host>:8000/v1`）、`AGNES_MODEL` 指模型名、`AGNES_KEY` 给 token（本地 vLLM 可任意串），**代码一行不用改**。
- **输出落点这件事，三个件不对等（逐行验过，别按同一种跑法套）**：
  - `agent.py:32-33` 有 env 旋钮：`AGENT_REPORT`（默认 `报告/agent-真跑.txt`）、`AGENT_BOOK`（默认 `报告/样例-agent.jsonl`，**在册 294 行那份真凭据**）⇒ 设这两个 env 就能把产物支到 TEMP。
  - `qa_loop.py:35-36` 同样有：`QA_REPORT`、`QA_BOOK`。
  - **`llm_probe.py:34` 没有 env 旋钮**：`REPORT` 写死成 `报告/接入LLM-第一发.txt` ⇒ 直接跑就是一次覆盖。
    它只有 `LEDGER`（`:35`，落 TEMP）与 `readback1.txt`（`:210`，落 TEMP）走临时目录。
    ⇒ **跑 `llm_probe.py` 之前必须先把树拷到 TEMP**，或者先备份那一份——这条没有例外。
- **`cmd/kresearch` 是唯一的源码级例外**：`cmd/kresearch/main.go:32` `const base = "http://123.56.218.60:18000"` 写死了外网地址，
  且它把账写到 `报告/样例-真接口两发.jsonl`（仓库里的凭据，覆盖就没了）。
  ⇒ 要接自己的端点：先用 `llm_probe.py`/`qa_loop.py` 这条路；真要改 `kresearch`，那是**改封板件**，得按 §8 停新增与三件配齐立一条等表态，我不擅自动。
- **跑任何驱动前先做两件事**（这两条都是今天踩过血的）：
  1. 把树拷到 TEMP 再跑，或显式传输出路径 —— `llm_probe.py:34` 的默认输出直指 `报告/` 里的真凭据（`样例-agent.jsonl` 294 条、`接入LLM-第一发.txt`）；
  2. 判定行的 `forbidden` 列表里**不要放口令前缀** —— 一旦 FAIL，`client.py` 的 Judge 会把禁项原样印进报告（全仓 5 处这种调用点，看板 #53 那族）。

## 5 · 验收清单：接上之后"什么算过"，逐条对着打勾

内核 `contract.md` §4 白纸黑字列了 10 格从未被填过（`fixed_overhead tokens chunks first_byte_ms max_gap_ms retry_after_ms usage_in usage_out wire_bytes_in wire_bytes_out`），
原因是**采集点不存在**：`usage_*` 的 owner 是「对端·自报」、`wire_bytes_*` 是「传输层·计数」、三格流式是「传输层·流式回调」。
所以验收就看这三条通路有没有从 `absent+理由` 变成有数：

1. **非流式一发**：`usage_in`/`usage_out` 应从 absent → **对端·自报(relayed)**；`wire_bytes_in`/`wire_bytes_out` → **传输层·计数(measured)**；
   `tokens`/`fixed_overhead` 有真值。而 `chunks`/`first_byte_ms`/`max_gap_ms` **应当仍是 absent**
   （驱动现在的原话就是 `"这一发非流式：没有「首帧」这个量"`）——把"仍然 absent"读成"没接上"是误读，这一条要专门看。
2. **流式一发**：三格流式应有值。**已知陷阱（上次那条 hosted 端点实测到的形状）**：流式时 `usage` 三个数全 0、非流式才给真数，
   于是 `relayed 0` 与 `measured 28264 字节` 会并排落在同一发上，**没有判据拦**（#47 那族）。
   ⇒ 验收必须把这一形状单独记一次，别让它悄悄进账。
3. **`wire_format` / `wire_format_said`**：非流式对端自报 `chat.completion`、流式自报 `chat.completion.chunk`，两支不同
   （`contract.md` §3 那句 + `报告/格式自报-流式对照.txt`）⇒ 换端点（vLLM ↔ llama.cpp）后**这两格要重新各测一发**，
   因为措辞是对端写的，不是我们的接线常量。
4. **账与链**：`encode_journal` 带原像导出（内存账重启即失，接真流量前一定先导），`verify` 要"全部比对过原像"；
   落账后 `tally` 的分桶变化要能逐名解释（哪几格从 absent 搬进 relayed/measured，搬了几格）。
5. **判据仍能红**：整轮之前先跑 `kprobe` 那 9 根等价性预验（`m13b-,m20-,m25-,m33-,m80-,g1-,g2-,g3-,g4-`），
   分类与封板存档逐字对上才放大轮；基线自校验/逐字节比对这类断言**只能在两轮都不在跑的时候做**。
6. **仍然没闭合的那一件与 GPU 无关**：E 段要的是**一个没碰过本仓库的人**跑 `acceptance_probe.py` 并自签 `--attest-caller`。
   自建/本地端点只是把"证据源"从模型侧补上，**不等于第三方验收**——别把"接上 GPU"读成"唯一验收闭了"。

## 6 · 今天还缺的两样（要动就得你给）

1. **走 hosted（不用卡，最快）**：仓库默认端点就是 `https://api.agnes-ai.cn/v1` + 模型 `agnes-3.0-flash`，
   只差 `AGNES_KEY` 一把口令——你设进环境变量我就跑（**只走 env，我不把它写进任何文件、报告或记忆**）。
   跑法按 §4 那条不对等来：`agent.py`/`qa_loop.py` 用 `AGENT_*`/`QA_*` 支到 TEMP，`llm_probe.py` 必须拷树再跑。
2. **走本地 GPU（要自托管端点）**：等云 GPU 服务器到手，把 host/model 名给我；
   这台机当调用方 + 记账方（内核、驱动、验收都在这儿），§5 那张清单就是"接上算不算成功"的判据。
3. 顺带一句成本：这台机 C 盘只剩 39.2 GB、空闲内存 7.1 GB ⇒ 即使将来在这台跑 CPU 推理，
   **也别在 C 盘堆多份权重**；下模型前先数这两个数。
