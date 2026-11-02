# 环境与安装（准备件，未定稿）

- 目标平台：Windows 10/11 x64。
- 依赖：PowerShell 5.1+（系统自带）、`curl.exe`（Windows 10 1803+ 自带）。不需要 Go、不需要 Node、不需要联网、不需要管理员权限。
- 空间：解压后约 60 MB（zip 26,774,478 B）。

## 这里有三个文件

| 文件 | 作用 | 是否含产品源码 |
|---|---|---|
| `install.ps1` | 校验 zip 哈希 → 解压 → 按 `MANIFEST.sha256` 逐条核 → 跑 `kcheck.exe` | 否；只有校验与启动逻辑 |
| `demo.ps1` | 启动只读服务 → 查 `/v1/verify` → 查 `/v1/read_back` → 证明 `POST` 405 → 篡改第 50 条并证明拒绝载入 | 否；只有断言与 HTTP 调用 |
| `demo-ledger.jsonl` | 100 条演示账本（完整账本 2,940 条的前 100 条） | 否；是数据，不是源码 |

两个脚本刻意写成 **ASCII-only**：Windows PowerShell 5.1 会把无 BOM 的 `.ps1` 按 ANSI 读，中文字符串可能先把解析器弄崩，导致“任何检查都没跑”。中文说明只放在这份 README 里。

## 三条命令

```powershell
# 1) 解压并自检（最后会跑快闸；目标目录必须为空或不存在）
.\install.ps1 -ZipPath "C:\path\agentkernel-2026-10-19-win-x64.zip" -Target "$env:TEMP\ak-demo"

# 2) 一条命令跑完四段演示（自带期望值断言）
.\demo.ps1 -PackageDir "$env:TEMP\ak-demo\agentkernel" -Ledger ".\demo-ledger.jsonl"

# 3) 只想手动起服务
$env:KAUDIT_TOKEN = [guid]::NewGuid().ToString("N")
& "$env:TEMP\ak-demo\agentkernel\bin\kaudit.exe" -journal ".\demo-ledger.jsonl" -listen 127.0.0.1:8788
```

`demo.ps1` 退出码 0 = 全部期望读数命中；1 = 至少一条不符，并会打印哪一条。

## 预期读数（本机实测）

| 步骤 | 读数 | 出处 |
|---|---|---|
| zip 哈希 | `236517a21d50ab9d3969c46354e477a881e2a1c58a4362245a104b15540abeab` | `../证据/install-ps1-run.txt` |
| 清单 | 可核 32 条，32 OK / 0 不符 / 0 缺 / 0 解析失败 | 同上 |
| 快闸 | 退出码 0；40 行 ✓（含末行汇总）、7 行 —；其中 1 条依赖闭包“核不了” | `../证据/kcheck-output.txt` |
| 演示账本 | 100 条，49,048 B，SHA-256 `54ffcf0239afe835d7399c2c8ba7c7c1de6ec4e17a213ec6e51fae04f16786f3` | 本文件同目录 |
| verify | `checked=100, entries=100, state=green` | `../证据/verify-100.json` |
| read_back | 20 格 = 18 measured + 2 estimated；absent 0 | `../证据/readback-20cell.json` |
| POST | 405，118 B | `../证据/post-405.headers` |
| 篡改 | 拒绝载入，rc=1，点名第 50 条 | `../证据/kaudit-tampered-refused.txt` |

完整账本（2,940 条，1,483,862 B，SHA-256 `fb1fa5ef7a9347769eede05d48b06a3e712861cc1e979076cdf18f922543d220`）不在本目录；它的实测读数是 `checked=2940, state=green`，见 `../证据/verify-2940.json`。演示切片是它的前 100 条，链仍然自洽，所以 `checked=100`。

## 两个脚本不做什么

- 不安装 Windows 服务、不写注册表、不改防火墙、不监听非回环地址。
- 不下载任何东西；不带 Go / Node / Python 运行时。
- 不覆盖非空目录；不做 `rm -rf`、不做静默清理。
- 不包含 `.go` 产品源码；`.ps1` 内没有内核判据逻辑，只调用发布件。

## 已知限制

- 只在 Windows x64 上测过；Linux / macOS 没有发布件。
- `kcheck` 是快闸，不跑“判据能红”的逐根针；它自带判据与清单，不读当前目录源码。
- `kaudit` 只在 127.0.0.1 上验证过；跨机访问需要绑定网段地址并设 `KAUDIT_TOKEN`，本准备件没有验防火墙入站规则。
- 演示账本是合成靶场数据，不含真实客户流量。
