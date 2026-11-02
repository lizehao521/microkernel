# G2 SBOM · CycloneDX 1.5 草案说明

- **日期**：2026-10-20
- **状态**：`draft`（结构自检通过；**未做 schema 校验**）
- **文件**：`G2-SBOM-CycloneDX-草案.json`
- **大小**：19,381 B
- **SHA-256**：`be1be0cb20387a432e4ce01093efd082f7e4bcfc3996cee5d64277e2902d593e`
- **serialNumber**：`urn:uuid:3a07276d-6015-5d38-a617-919f3230c59b`（uuid5，确定性）
- **timestamp**：`2026-10-20T00:00:00Z`（固定值，非真实生成时刻）
- **上游**：`G2-SBOM-试点工具.md`、`G2-SBOM-内核模块.md`
- **生成方式**：作者侧离线脚本 `工具/sbom/gen_cyclonedx.py`，确定性导出（固定 serial / timestamp）；自检与反臂脚本同目录；**未调用官方 CycloneDX 工具**

---

## 1. 覆盖范围

| 类型 | 数量 | 组件 |
| --- | --- | --- |
| `file`（工具脚本） | 2 | `切片与校验.js`、`打非作者试读包.py` |
| `application`（源码） | 1 | `agentkernel` Go 模块（`(devel)`，无 VCS 修订） |
| `file`（二进制） | 5 | `kaudit` / `kcheck` / `kresearch` / `mcphttp` / `mcpkernel` |
| `framework` | 1 | Go 标准库 1.27.2 |
| `library` | 4 | `golang.org/x/{crypto,net,sys,text}`（GOROOT 内嵌版本） |
| `platform` | 2 | Node.js 22.23.2、Python 3.14.1 |
| `operating-system` | 1 | Windows（部署版本 **absent**；构建机 10.0.22631.6936 已测） |
| **合计** | **16** | |

证据状态：`measured` 15 / `absent` 1（部署 OS 版本）/ `not_run` 0。

7 个文件类组件的 SHA-256 已与实体逐一对上（2 个脚本 + 5 个二进制）。

2 个运行时组件补了本机实体读数（构建机路径，**不随包分发**；自检的 7 文件哈希项**未覆盖**这两个，仅登记）：

| 组件 | 版本 | 实体 | 字节 | SHA-256 |
| --- | --- | --- | --- | --- |
| Node.js | v22.23.2 | `.codearts/runtimes/node/node.exe` | 86,997,320 | `0d0f5e39f9f3d9587bc19f73eab3c2c9c4903fd02d6dbf9c853dd81b3d95fad4` |
| Python | 3.14.1 | `sdk/py314/python.exe` | 106,328 | `3179d8b7d28ccc7547e59c3080bf2f715442b692c33798e928fd311f2c97f57b` |

Python 另记 `python314.dll`（6,757,720 B / `ac1223782497ad05c80d34c2216818eb16a25d7687bf1f2596b0b2eb25ca7b5d`）与 `python3.dll`（74,072 B / `1fe883c6123a0485af1789c1fc56d7e7bb27eb465f65b154d48d1181c8ca5465`）。三项都在构建机上，部署机对应版本 / 哈希 **absent**。

构建机 OS 读数（只作构建环境记录，不代替部署机清单）：Windows `10.0.22631.6936` / 23H2（注册表 ProductName 仍写 Windows 10 Enterprise）；`kernel32.dll` 文件版本 `10.0.22621.6931`、815,584 B、SHA-256 `C8088D514F1A6F7421CF00534CF9EC7AF6F1E9D1AF186417F2B23934606C5AD7`。

## 2. 依赖边（8 条，仅运行时语义）

```text
ak-tool-slice-verify  -> ak-node-runtime
ak-tool-trial-zip     -> ak-python-runtime
ak-go-stdlib          -> ak-go-x-crypto, ak-go-x-net, ak-go-x-sys, ak-go-x-text
ak-bin-* (5)          -> ak-go-stdlib, ak-os-windows
```

- 构建关系（同源编译、`go build` 输出）不在 `dependencies` 里，记在组件的 `ak:build-*` 属性中。
- 5 个二进制均导入 `kernel32.dll`；构建机 `kernel32.dll` 版本 / 哈希已测（见 §1）；**部署机**系统 DLL 版本与 forwarder 清单 **absent**。
- 5 个二进制的内嵌构建信息（`go version -m`）一致：`go1.27.2`、`CGO_ENABLED=0`、`GOOS=windows`、`GOARCH=amd64`、`GOAMD64=v1`、模块依赖 **0**；**无 `-trimpath`**、**无 VCS 修订**（模块版本 `(devel)`）。

## 3. 结构自检读数

自检脚本 `工具/sbom/check_cyclonedx.py` 共 17 项，**17 OK / 0 FAIL**：

| # | 检查项 | 结果 |
| --- | --- | --- |
| 1 | JSON 可解析 | OK |
| 2 | `bomFormat=CycloneDX` | OK |
| 3 | `specVersion=1.5` | OK |
| 4 | serial 为 UUID URN | OK |
| 5 | `version` 为整数 | OK |
| 6 | `metadata.timestamp` RFC3339 | OK |
| 7 | 组件数 = 16 | OK |
| 8 | `bom-ref` 唯一 | OK |
| 9 | 每组件含 type/name/bom-ref | OK |
| 10 | 每组件 `ak:evidence` ∈ {measured, absent, not_run} | OK |
| 11 | 7 个文件组件实体存在 | OK |
| 12 | 7 个 SHA-256 与实体一致 | OK |
| 13 | 依赖条数 = 8 | OK |
| 14 | 依赖边全部可解析（无悬空） | OK |
| 15 | 无自环 | OK |
| 16 | metadata 声明 `schema-validation=NOT_RUN`、`completeness=not-complete` | OK |
| 17 | 严格密钥正则 5 类 | 0 命中 |

**反臂（证明尺子会红）**：临时副本 4 类篡改，原文件未动，4/4 按预期报红——

| 反臂 | 篡改 | 结果 |
| --- | --- | --- |
| A1 | 改 `kaudit` 二进制哈希首字符 | RED（哈希不符） |
| A2 | 追加悬空依赖 `ak-nonexistent` | RED（悬空边） |
| A3 | 删除 `ak-kernel-src` 的 `ak:evidence` | RED（evidence 缺失） |
| A4 | 复制一条组件（重复 bom-ref） | RED（组件数 17、bom-ref 不唯一） |

## 4. 本草案**没有**做什么

| 项 | 状态 | 原因 |
| --- | --- | --- |
| CycloneDX JSON Schema 校验 | `NOT_RUN` | 本机 `cyclonedx-cli` / `cyclonedx` 均 `absent`（8 个工具盘点见下行）；另查 8 个常见目录无 `bom-1.5.schema.json`、Python 3.14.1 无 `jsonschema`；未调用在线校验（不上传第三方）；只做结构自检，不声明 schema 合规 |
| 漏洞扫描（CVE / govulncheck） | `NOT_RUN` | `govulncheck` / `osv-scanner` / `trivy` / `syft` / `grype` / `dependency-check` 均 `absent`，本地 Go 漏洞库缓存 `absent`；不声明“0 依赖 = 无漏洞” |
| 完整产品 SBOM | `absent` | 仅工具 + 内核两域；部署机系统 DLL 版本未盘点（构建机读数已记） |
| OS DLL 版本与 forwarder | `absent` | 未采集 Windows 系统件版本 |
| 构建签名 / SLSA / 出处证明 | `absent` | 无签名链；同机重建 5/5 字节一致不等于签名出处 |
| 跨机重建复现 | `NOT_RUN` | 仅同机同工具链验证过 |
| 内核测试重跑 / `go test` | `NOT_RUN` | 检查时 2 个 `mcpkernel.exe` 在跑，按“轮在跑不动内核/树”跳过 |

## 5. 与两份分域 SBOM 的关系

- 本 JSON 是两份域级 SBOM 的**统一导出视图**，不替代它们；
- 域级文档保留命令、读数、缺口与判定（工具级 / 内核级）；
- 本文件只回答“有哪些组件、什么版本、什么哈希、谁依赖谁”，不回答“是否安全”。

## 6. 非声明

- 不是完整 SBOM；不是安全审查报告；不是合规认证；不是漏洞扫描结论；
- “结构自检 17/17” ≠ “schema 校验通过”；
- “模块级第三方依赖 0” ≠ “无漏洞”；“同机重建 5/5” ≠ “可复现构建已证明”；
- 未做 schema 校验、未做漏洞扫描、未盘点部署机系统 DLL，三项均保持 `NOT_RUN` / `absent`；
- 对外只能说“已有一份 CycloneDX 1.5 **草案**，完成结构自检”，不得说“SBOM 已完成 / 已合规”。
