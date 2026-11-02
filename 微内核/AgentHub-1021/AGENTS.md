# AgentHub（`AgentHub-1021`）· 局部指南

通用「对话 + 自主调工具」Web Agent：Go 单二进制 `hubd` + 零构建前端 + SSE 过程流。
口径、工具链、备份规矩见 `../AGENTS.md`。方法论已结晶为技能 `agenthub-web-agent`。

## 这一面的闸

工作目录 `AgentHub-1021`：

```bash
C:/Users/Admin/sdk/py314/python.exe 工具/验收.py C:/Users/Admin/sdk/go/bin/go.exe
```

读数落 `报告-验收.txt`，行数由件现数。**闸 1b 是 `node --check app.js`**：Go 侧全绿救不了整页静默死掉，
这条必须和 Go 侧同一条命令里跑。它还会打印「跑的就是这一份」的 exe 路径、字节数、sha16 —— 改完别拿旧 exe 读数冒充新 build。

## 旗标（`src/hubd/main.go:69-81`）

- `-fs-roots` / `-net-allow` 默认收口：文件根限当前目录 + 笔记目录，出网只 127.0.0.1/localhost/::1。放宽是单独决定。
- `-max-steps 1` 是步数上限的反臂；默认旗标下写文件必须被门口挡下且 `attempts=0`。
- `-fake-endpoint` 起本机假端点，只让 `model_says` 那一族在页面上看得见，页面上不许说成模型。
- `-step-delay` 是演示节奏，不是真实工作量；报进度时两者不许混着说。

## 这一面已知没做的三件（改之前先认，别当已实现）

- **断线语义未声明**：`RunTurn` 里没有 `ctx.Done()` 判定（静态核对 `src/hubd/agent.go`），客户端断开只体现为工具调用被取消，循环可能继续走到步数上限。此形**未实跑**，记 NOT_RUN。
- **SSE 没有 `id` / `Last-Event-ID`**（`src/hubd/httpapi.go` 只写 `event:` + `data:`）⇒ 断线不可续，只能重发。别说成「可续」。
- **`answer_delta` 是收口后切块**（`httpapi.go:92` 注释自认流式的是已算完的结论）：那是呈现节奏，不是 token 流式。

按 `../研究-协同工作-1022.md` §8 补这三件时，验收针在同文件 §8.2（回执/序号/缺席/结算/补步/续传/混列/投影）。

## 并发与前端

一发一把锁：`TryLock` 直接拒第二发并写明「不排队、不混列」。前端只投影后端数，保留「量到的 0」；
屏幕脏字栏（`undefined`/`NaN`/`[object Object]`/`map[`/`%!`）由闸 3 现数，非 0 即红。
