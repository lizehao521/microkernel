# SBOM 导出与自检脚本

作者侧离线脚本，用于生成、校验和反臂测试 `G2-SBOM-CycloneDX-草案.json`。无网络、无第三方库。

| 文件 | 作用 |
| --- | --- |
| `gen_cyclonedx.py` | 读取两份分域 SBOM 的实体与固定读数，确定性导出 CycloneDX 1.5 草案 |
| `check_cyclonedx.py` | 17 项结构自检；可传一个 JSON 路径校验副本 |
| `arm_cyclonedx.py` | 4 类篡改（哈希 / 悬空边 / 缺 evidence / 重复 bom-ref），在临时副本上跑，要求全红 |

## 运行

在 `试点-1020` 目录下：

```bash
PYTHONIOENCODING=utf-8 /c/Users/Admin/sdk/py314/python.exe 工具/sbom/gen_cyclonedx.py
PYTHONIOENCODING=utf-8 /c/Users/Admin/sdk/py314/python.exe 工具/sbom/check_cyclonedx.py
PYTHONIOENCODING=utf-8 /c/Users/Admin/sdk/py314/python.exe 工具/sbom/arm_cyclonedx.py
```

## 预期读数（2026-10-20）

```text
serial urn:uuid:3a07276d-6015-5d38-a617-919f3230c59b
components 16 deps 8 bytes 19381
sha256 be1be0cb20387a432e4ce01093efd082f7e4bcfc3996cee5d64277e2902d593e
OK 17 FAIL 0
arms 4 red 4
```

## 边界

- 路径由脚本位置推导：`试点-1020` 与仓库根 `微内核`；在别处运行需保持同样目录层级。
- 自检的 7 个文件哈希依赖 `构建-1017/agentkernel/bin/` 下 5 个二进制与 2 个工具脚本存在；运行时（Node / Python）哈希只登记在 JSON 中，**不在 17 项自检内**。
- 只做结构自检，**不做 JSON Schema 校验**、**不做漏洞扫描**；`schema-validation=NOT_RUN` 是事实，不是通过。
- 本机离线盘点（2026-10-20）：`cyclonedx-cli`、`cyclonedx`、`govulncheck`、`osv-scanner`、`trivy`、`syft`、`grype`、`dependency-check` 共 8 个工具均 `absent`；本地 Go 漏洞库缓存 `absent`；8 个常见目录未找到 `bom-1.5.schema.json`，Python 3.14.1 无 `jsonschema` 模块。
