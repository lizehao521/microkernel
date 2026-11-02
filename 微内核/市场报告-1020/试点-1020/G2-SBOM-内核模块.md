# G2 SBOM · 内核模块与发布二进制（草案 v0.1）

- **日期**：2026-10-20
- **范围**：Go 模块 `agentkernel` 源码 + `构建-1017/agentkernel-2026-10-19-win-x64.zip` 内 5 个 Windows 二进制
- **状态**：`draft`；完整 SBOM 仍为 **0 / 1**（本文件是第 2 份分域草案，第 1 份见 `G2-SBOM-试点工具.md`）
- **不是**：完整产品 SBOM、安全审查、漏洞扫描报告、许可证合规意见、构建签名 / SLSA 证明；CycloneDX 1.5 统一导出草案见 `G2-SBOM-CycloneDX-草案.json`（结构自检通过，**未 schema 校验**）

> 范围边界：本文件只覆盖内核模块与其发布二进制；试点 Python / Node 脚本见 `G2-SBOM-试点工具.md`。  
> 两份草案合起来仍不等于“完整 SBOM”：统一格式仅为未校验草案、漏洞扫描、部署机 OS 依赖清单、客户环境清单仍缺。

---

## 1. 组件总表

| ID | 组件 | 版本 | 形态 | 数量 / 大小 | SHA-256 | 等级 |
| --- | --- | --- | --- | --- | --- | --- |
| AGK-KERNEL-SRC | `agentkernel` 源码 | `(devel)`；无 VCS 提交号（仓库不是 git） | `.go` + `go.mod` | 当前树 35 个 `.go`（18 测试 / 17 非测试）+ `go.mod`（28 B，`aee4a04c2108218c26f18c4f86e61f761791c2d74bdb96c60814dd3b5d173407`）；`.go` 合计 642,072 B | 模块清单 `049af7f6...`（36 行，见 §3.4） | A |
| AGK-KERNEL-BIN-01 | `kaudit.exe` | `(devel)` / go1.27.2 | Windows amd64 可执行 | 10,092,032 B | `3a9c863d...` | A |
| AGK-KERNEL-BIN-02 | `kcheck.exe` | 同上 | 同上 | 6,529,024 B | `1858e089...` | A |
| AGK-KERNEL-BIN-03 | `kresearch.exe` | 同上 | 同上 | 11,999,744 B | `9dca0d37...` | A |
| AGK-KERNEL-BIN-04 | `mcphttp.exe` | 同上 | 同上 | 13,125,632 B | `f6061740...` | A |
| AGK-KERNEL-BIN-05 | `mcpkernel.exe` | 同上 | 同上 | 6,090,240 B | `468c6e32...` | A |
| AGK-GO | Go 工具链 / 标准库 | `go1.27.2 windows/amd64` | 编译期与静态链接 | `CGO_ENABLED=0` | GOROOT `LICENSE` `911f8f57...` | A |
| AGK-X-CRYPTO | `golang.org/x/crypto`（GOROOT 内嵌） | `v0.52.1-0.20260526024921-9beb694f9766` | Go 发行版内嵌，非模块依赖 | GOROOT `src/vendor` | `LICENSE` `911f8f57...`；`PATENTS` `96f408bf...` | A |
| AGK-X-NET | `golang.org/x/net`（GOROOT 内嵌） | `v0.55.1-0.20260731170536-c1d18010be90` | 同上 | 同上 | 同上两个哈希 | A |
| AGK-X-SYS | `golang.org/x/sys`（GOROOT 内嵌） | `v0.45.0` | 同上 | 同上 | 同上两个哈希 | A |
| AGK-X-TEXT | `golang.org/x/text`（GOROOT 内嵌） | `v0.37.0` | 同上 | 同上 | 同上两个哈希 | A |
| AGK-OS-WIN | Windows 系统 DLL | 部署机未登记（目标系统决定）；构建机 10.0.22631.6936 | 运行时 | 5 / 5 仅导入 `kernel32.dll`；构建机 `kernel32.dll` 10.0.22621.6931、815,584 B、`C8088D51...` | 部分：DLL 名已枚举；构建机已测；部署机版本 / 哈希 `absent` |

**版本口径**：5 个二进制的 `go version -m` 均显示 `mod agentkernel (devel)`，没有版本标签或提交号；本文件不把 `(devel)` 写成某个发布版本号。

---

## 2. 依赖闭合

| 检查 | 命令 | 读数 | 状态 |
| --- | --- | --- | --- |
| `go.mod` | `cat go.mod` | `module agentkernel` / `go 1.27`；无 `require`、无 `replace` | present |
| `go.sum` | `ls go.sum` | 不存在（0 个外部模块，无需校验和） | n/a |
| `vendor/` | `find . -name vendor -type d` | 模块内不存在 | n/a |
| 外部导入 | 解析 35 个 `.go` 的 `import` | 外部模块路径 **0**；`import "C"` **0** | present |
| 模块图 | `GOPROXY=off GOTOOLCHAIN=local go list -m all` | 仅 `agentkernel` | present |
| 包闭包（全树） | `go list -deps ./...` | 217 个包 | present |
| 包闭包（5 个发布命令） | `go list -deps ./cmd/{kaudit,kcheck,kresearch,mcphttp,mcpkernel}` | 215 个包 | present |
| 发布命令是否依赖探针 | `grep -E -e tasks -e kwire -e omitjournal deps5.txt` | 无命中 | present |

**17 个含点号路径是什么**：全部来自 GOROOT，不是 `agentkernel` 的模块依赖——

- `crypto/internal/entropy/v1.0.0`（标准库内部版本化路径）1 个；
- `vendor/golang.org/x/{crypto,net,sys,text}/...` 16 个，随 Go 1.27.2 发行版内嵌，版本见 §1。

因此口径是：**模块级第三方依赖 0；Go 工具链内嵌第三方代码 4 个模块（版本随 go1.27.2 固定）**。不能把这两句话说成同一件事。

---

## 3. 构建与完整性

### 3.1 构建参数（5 / 5 一致）

`go version -m <exe>` 均显示：

```
build  -buildmode=exe
build  -compiler=gc
build  CGO_ENABLED=0
build  GOARCH=amd64
build  GOOS=windows
build  GOAMD64=v1
```

未出现 `-trimpath`、`-ldflags` 或 VCS 设置；模块版本为 `(devel)`，无提交号。构建机 OS 为 `10.0.22631.6936`，`kernel32.dll` 文件版本 `10.0.22621.6931`。

### 3.2 同机重建（5 / 5 字节一致）

用 `go1.27.2 windows/amd64`、`GOPROXY=off`、`GOTOOLCHAIN=local`，从当前源码重建到临时目录，与发布二进制逐字节比较：

| 二进制 | 重建 = 发布？ | 共同 SHA-256 |
| --- | --- | --- |
| `kaudit.exe` | 是 | `3a9c863dfdc58c365cb2f850085a460d5c71c60060dfd5748f5f06c287c8ebf6` |
| `kcheck.exe` | 是 | `1858e0892d2462b0bf5c32d169d1d4154fee1a831fb078c391d760a941c9c67c` |
| `kresearch.exe` | 是 | `9dca0d37f39ee6761edd77ba729ab5fa9b8a6a9f5ea448c17107d1603260bb44` |
| `mcphttp.exe` | 是 | `f60617409932b57ce164007a1f56742ee2a731abf18451513b40b728524cd0a7` |
| `mcpkernel.exe` | 是 | `468c6e322e59c899606dd45f2904b22cd5291e4ef9aa175c1c1b07bc5a0a7519` |

**这只证明同机、同工具链、同源码可复现**；跨机器 / 跨工具链复现为 `NOT_RUN`。

### 3.3 发布包

| 项 | 读数 |
| --- | --- |
| 文件 | `构建-1017/agentkernel-2026-10-19-win-x64.zip` |
| 条目 | 33（5 二进制 + docs + evidence + 清单；不含 `.go` 源码） |
| 字节 | 26,774,478 B |
| SHA-256 | `236517a21d50ab9d3969c46354e477a881e2a1c58a4362245a104b15540abeab` |
| 包内 `MANIFEST.sha256` | 32 / 32 全对（跳过注释与空行） |
| 包内 `source-fingerprint.sha256` | 35 / 35 全对（对当前源码） |

### 3.4 源码覆盖差异（必须写明）

- 当前树有 **35 个 `.go` + `go.mod` = 36 个文件**；发布包指纹只含 **35 个**；
- 未入指纹的文件：`tasks/probe/omitjournal/main.go`（探针程序，5 个发布二进制均不依赖，§2 已核）；
- `cmd/` 下有 6 个命令目录，发布 `bin/` 只有 5 个；`kwire` 无对应发布二进制；
- 模块清单（36 行，按路径排序，`sha256  path`）整体 SHA-256：`049af7f6ac0395e77e1d7d34fd9486ecf59ec66f576383531b623877a729c856`。

> 源码指纹 + 同机重建把“二进制由这份源码构建”从宣称变成可核；但不等于签名或构建证明。

### 3.5 PE 导入（OS 依赖面）

解析 5 个二进制的 PE Import Directory：

| 二进制 | 导入 DLL |
| --- | --- |
| `kaudit.exe` | `kernel32.dll` |
| `kcheck.exe` | `kernel32.dll` |
| `kresearch.exe` | `kernel32.dll` |
| `mcphttp.exe` | `kernel32.dll` |
| `mcpkernel.exe` | `kernel32.dll` |

- 方法：读 PE optional header 的 `DataDirectory[1]`，遍历 `IMAGE_IMPORT_DESCRIPTOR` 取 DLL 名；只用 Python 标准库；
- 未覆盖：`kernel32.dll` 的转发目标、目标机器补丁级别；构建机 DLL 版本已测（见 3.1），部署机 DLL 版本仍未登记；
- `CGO_ENABLED=0`，无外部 CRT 导入；这仍不是完整 OS 包清单。

---

## 4. 许可证清单（只登记文件，不作合规结论）

| 组件 | 许可证文件 | SHA-256 | 状态 |
| --- | --- | --- | --- |
| Go 1.27.2 标准库 | `GOROOT/LICENSE`（BSD-3-Clause 正文） | `911f8f5782931320f5b8d1160a76365b83aea6447ee6c04fa6d5591467db9dad` | present |
| `x/crypto` `x/net` `x/sys` `x/text` | 各自 `LICENSE`（4 个文件同一哈希） | `911f8f57...` | present |
| 同上 | 各自 `PATENTS`（4 个文件同一哈希） | `96f408bfae65bf137fc2525d3ecb030271c50c1e90799f87abf8846d8dd505cc` | present |
| `agentkernel` 模块 | 模块根目录无 `LICENSE` | — | `absent` |

- 未做逐文件版权头扫描：`NOT_RUN`；
- 本清单不构成许可证合规意见。

---

## 5. 未覆盖与缺口

| 项 | 状态 | 说明 |
| --- | --- | --- |
| 漏洞扫描（含 Go 标准库） | `NOT_RUN` | 本机无 `govulncheck`，离线未安装；**0 个外部模块 ≠ 0 漏洞** |
| SPDX / CycloneDX | 部分 | CycloneDX 1.5 草案见 `G2-SBOM-CycloneDX-草案.json`（结构自检 17 / 17、反臂 4 / 4；**未 schema 校验**）；SPDX `absent` |
| 完整产品 SBOM | `absent` | 工具级见另一份；部署机 OS / 运行时 / 客户环境未纳入（构建机 OS 读数见 3.1） |
| Windows 系统 DLL / CRT 清单 | 部分 | 5 / 5 仅导入 `kernel32.dll`；构建机 `kernel32.dll` 版本 / 哈希已测；部署机版本 / 哈希 / 转发目标未登记 |
| 跨机器 / 跨工具链复现 | `NOT_RUN` | 只做了本机同工具链 |
| 构建签名 / 来源证明 | `absent` | 无签名、无 SLSA / in-toto；内嵌构建信息无 VCS 修订 |
| 内核测试本轮复跑 | `NOT_RUN` | 检查时 2 个 `mcpkernel.exe` 在跑，按“轮在跑不动内核/树”跳过 |
| `cmd/kwire` 发布件 | `absent` | 有源码，`bin/` 无对应二进制 |
| 客户环境 | `absent` | 不在本文件范围 |

---

## 6. 复现命令

```bash
export PATH="/c/Users/Admin/sdk/go/bin:$PATH"
export GOPROXY=off GOTOOLCHAIN=local GOFLAGS=-mod=readonly
cd "C:/Users/Admin/Desktop/微内核/微内核/微内核"

go version                                  # go version go1.27.2 windows/amd64
cat go.mod                                  # module agentkernel / go 1.27
go list -m all                              # agentkernel
go list -deps ./... | wc -l                 # 217
go list -deps ./cmd/kaudit ./cmd/kcheck ./cmd/kresearch ./cmd/mcphttp ./cmd/mcpkernel | wc -l   # 215

for n in kaudit kcheck kresearch mcphttp mcpkernel; do
  go build -o "/tmp/ak-sbom/$n.exe" "./cmd/$n"
  sha256sum "/tmp/ak-sbom/$n.exe" "C:/Users/Admin/Desktop/微内核/构建-1017/agentkernel/bin/$n.exe"
done

go version -m "C:/Users/Admin/Desktop/微内核/构建-1017/agentkernel/bin/kcheck.exe"
sha256sum "C:/Users/Admin/Desktop/微内核/构建-1017/agentkernel-2026-10-19-win-x64.zip"

# 源码指纹与发布清单
unzip -p "C:/Users/Admin/Desktop/微内核/构建-1017/agentkernel-2026-10-19-win-x64.zip" \
  agentkernel/evidence/source-fingerprint.sha256 > /tmp/ak-sbom/source-fp.txt
sha256sum -c /tmp/ak-sbom/source-fp.txt      # 35 / 35 OK
```

---

## 7. 变更规则

1. 任一 `.go` / `go.mod` 变化 → 重算源码指纹 → 重建 5 个二进制 → 逐字节比较；
2. 任一二进制哈希变化 → 出新发布 zip，旧 SBOM 作废，不静默覆盖；
3. Go 工具链升级 → 更新 GOROOT 内嵌 `x/*` 版本与许可证哈希；
4. 漏洞扫描未跑 → 不得把 SBOM 标为“完整”；
5. 对外只说“分域草案”，不说“已具备完整 SBOM”。

---

## 8. 非声明

- 不证明内核安全、正确、无漏洞、合规；
- 不证明二进制与源码的绑定经过第三方验证（只有作者侧指纹 + 同机重建）；
- 不证明所有依赖都已登记（OS 运行时、客户环境、Go 工具链内部细节未穷举）；
- 不把 `go.sum` 缺失解读为“没有第三方代码”——Go 发行版内嵌 `x/*` 已单列；
- 不证明“只导入 `kernel32.dll`”等于无 OS 漏洞或可在任意 Windows 版本运行；
- 不把本文件与 `G2-SBOM-试点工具.md` 相加后称为“完整 SBOM”。
