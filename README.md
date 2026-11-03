# 微内核项目资料与使用指南

这是一个围绕 Go 微内核及其周边 Agent 工具整理的工作区快照，包含内核、AgentHub、编程 Agent、研究与验收资料。它不是单一的 Go module；请根据下面的目录说明进入对应子项目操作。

## 环境要求

- Git
- Go 1.27 或更高版本
- 如需运行验收脚本，再安装 Python 3

先确认 Go 已安装并可从终端调用：

```powershell
go version
```

克隆仓库：

```powershell
git clone https://github.com/lizehao521/microkernel.git
cd microkernel
```

## 运行微内核检查

微内核 Go module 位于 `微内核/微内核/微内核/`。在仓库根目录执行：

```powershell
Set-Location .\微内核\微内核\微内核
go test ./...
go run ./cmd/kcheck
```

`go test ./...` 运行 Go 测试；`kcheck` 运行项目的快速一致性检查。以命令退出码和本次实际输出为准。

详细设计、字段定义与项目边界见[微内核说明](./微内核/微内核/微内核/README.md)。

## 运行 AgentHub 演示

AgentHub 是独立的 Go 子项目。它默认在本机回环地址提供演示界面：

```powershell
Set-Location .\微内核\AgentHub-1021\src\hubd
go run . -port 8790 -step-delay 120ms
```

启动后在浏览器打开 <http://127.0.0.1:8790/>。停止服务请在运行终端按 `Ctrl+C`。

更多启动参数、验收命令和功能说明见 [AgentHub 使用说明](./微内核/AgentHub-1021/README.md)。

## 目录导航

| 路径 | 内容 |
|---|---|
| [`微内核/微内核/微内核/`](./微内核/微内核/微内核/) | Go 微内核源码、测试、契约与说明 |
| [`微内核/AgentHub-1021/`](./微内核/AgentHub-1021/) | 本地 AgentHub 应用及验收资料 |
| [`微内核/编程Agent-1020/`](./微内核/编程Agent-1020/) | 编程 Agent 子项目 |
| [`微内核/事件层-1022/`](./微内核/事件层-1022/) | 事件层设计、验收与交接资料 |
| [`微内核/架构-1020/`](./微内核/架构-1020/) | 架构研究资料 |
| [`微内核/TEMP-备份/`](./微内核/TEMP-备份/) | 历史备份与中间产物，通常不作为运行入口 |

该仓库保留了研究记录、历史快照和构建产物；修改或运行某个子项目时，请先阅读该目录内的 README/AGENTS 说明，不要把备份目录当作当前源码入口。
