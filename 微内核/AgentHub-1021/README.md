# AgentHub 1021 · 能对话、能自己调用工具的本地 Agent 应用

一句话：你在框里打一句人话，它自己挑工具、真跑、把每一步（工具名 / 参数 / 状态 / 返回）画在中间那一栏，
最后按出处分档给结论；跑不动的那一格写"没量到 + 为什么"，不写 0。

## 30 秒跑起来

```bat
cd AgentHub-1021\src\hubd
C:\Users\Admin\sdk\go\bin\go.exe run . -port 8790 -step-delay 120ms
start http://127.0.0.1:8790/?run=1
```

只监听 `127.0.0.1`。`?run=N` 会连着跑 N 发样例（截图与实测用）。

## 目录

```
AgentHub-1021\
├── 设计-数据流.md      ← 模块设计、数据流、事件契约、扩展新工具的三条路、不承诺清单
├── README.md            ← 本件
├── 运行记录.txt         ← 每一跑现场：跑了什么、抓到什么、修了什么
├── 报告-验收.txt        ← 一条命令的现算输出（道数也现数，不写死在结论里）
├── 工具\验收.py         ← python 工具/验收.py <go.exe 路径>
├── 读数\                ← SSE / 浏览器 DOM / 自检输出 / 截图（每个数都有出处文件）
├── 构建-hubd\           ← 编出来的 exe 与会话数据
└── src\hubd\
    ├── main.go registry.go guard.go tools_builtin.go eval.go
    ├── planner.go agent.go retry.go memory.go sane.go
    ├── httpapi.go fakesrv.go selfcheck.go hubd_test.go
    ├── tools\本机健康.json     ← 清单挂载示例（带 triggers）
    └── web\index.html app.js style.css
```

## 这台机器能干什么（都有现算读数）

| 能力 | 怎么看 |
|---|---|
| 对话 + 流式 | 页面左栏；`curl -N` 打 `POST /api/chat` 能收 7 类 SSE 事件 |
| 自主选件真跑 | 中栏时间线：每步带参数、**参数来处**、状态、尝试次数、风险档、返回正文 |
| 多步与记忆 | 「列一下当前目录，按大小排，再统计最大的那个文件有多少行」⇒ 两步跑完，第二步的路径是上一发的读数拼的 |
| 重试与降级 | 「用 flaky 演示重试，前 2 次要失败」⇒ 试 3 次并等；「前 9 次都要失败」⇒ 走降级并写明从谁降级来 |
| 门口挡 | 「把结论存成笔记…」默认不放行 ⇒ `refused`、`attempts=0`、`absent` 带理由，且不找替身 |
| 出网边界 | 「取一下 https://example.com/…」⇒ 清单外主机，句子里明写"没打到外面，不是打失败了" |
| 加新工具 | 往 `src\hubd\tools\` 放一个带 `triggers` 的 JSON，不重编译就能被自然语言选起（闸 5 量的就是这个） |
| 自证 | 三个数**都不写在这儿** —— 写死的数会随下一支针变成谎（10-25 现场：这句话还停在「27 个函数」，而 `报告-验收.txt:3` 那一趟自己印的是 `^func Test` 现数）：`hubd -selfcheck` 几条、`go test` 几支 Test、`工具\验收.py` 一条命令跑完几道闸，**一律看本面 `报告-验收.txt` 里各行自己印的数**，「最新」只按 mtime 认。臂的形状：前端结构针 + "注册了没人接"针 + 假端点正文臂，每根都配臂；`工具\几何探针.js` 量七档几何与对比度（每把尺子配会红的臂） |

## 页眉那六个格子怎么设（全是启动旗标，改完重启；只有 `tools\*.json` 不用重编）

| 页眉 | 旗标 | 默认 |
|---|---|---|
| 本机认识 N 个工具 | `-tools-dir <目录>`（放一个 `.json` 多一个） | `<工作目录>\tools` |
| 记忆 N 条 | `-data <目录>` —— 这本账就是这里的一本 JSONL，换目录=换一本账 | `%TEMP%\hubd-数据` |
| 下一发是第 N 发 | 跟着 `-data` 走，跨进程接着数；页面上按**开一本新账**清零 | 同上 |
| 模型端点 | `-model-endpoint <完整 POST 地址>` + `-model-name` + `-model-key-env <环境变量名>`；`-fake-endpoint` 起一个本机假端点（页眉会明写"不是模型"） | 空 ⇒ `NOT_RUN（没配）` |
| 写文件 | `-allow-write`（仍限 `-fs-roots` 之内） | 关 |
| 执行 | `-allow-exec`（在临时目录里跑，配 `-exec-timeout-ms`） | 关 |

另有 `-port`、`-max-steps`、`-context-chars`、`-fs-roots`、`-net-allow`、`-step-delay`、`-selfcheck`。
**口令只走环境变量**：`-model-key-env` 指的那个变量为空时，那一发明写"没有口令，这一路打不出去"，不会假装成功。
一键演示：`工具\启动-演示.bat`（干净账 + 假端点 + 流式停顿，**不**默认放行写文件/执行）。

## 三条边界（别读成"挡住了"）

1. **模型这一路 NOT_RUN**：本机没有口令，`-model-endpoint` 留空 ⇒ 选件全是本机规则（署 `estimated`）。
   `modelPlanner` 是真的 OpenAI 式适配器；`-fake-endpoint` 能让它在真页面上跑出 `model_says` 那几步，
   但那台假端点按剧本回选件、**不是模型**（页眉那一格会自己写明）。真端点仍 NOT_RUN。
2. **审计层不是防线**：13 条整列自洽判据只管这台机器自己有没有说谎，不证明结论对世界正确。
3. **真人试读 0/1**：页面上的"看得懂"由 DOM 读数与判据说话，不是真人反馈。

## 复跑口径

```bat
C:\Users\Admin\sdk\go\bin\go.exe -C src\hubd test -count=1 ./...
C:\Users\Admin\sdk\py314\python.exe -X utf8 工具\验收.py C:\Users\Admin\sdk\go\bin\go.exe
```

第二条会自己编 exe、起服、收 SSE、跑反臂、挂清单验扩展、比读数新鲜度，并把结果写进 `报告-验收.txt`。
