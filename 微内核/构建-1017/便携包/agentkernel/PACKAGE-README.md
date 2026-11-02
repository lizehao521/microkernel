# agentkernel 交付包 · 说明

这是 `agentkernel`（模型输入/输出元数据微内核）在 Windows/x64 上的一次构建产物。
包内所有数字都在 `凭据/` 里由生成它的工具自己印出来，这份说明**不抄任何会漂的数**。

## 包里有什么

| 目录 | 内容 |
|---|---|
| `bin/` | 5 个可执行件：`kaudit` `kcheck` `kresearch` `mcphttp` `mcpkernel` |
| `docs/` | `README.md`（第一屏定位）、`contract.md`（判据契约）、`产品定位.md` |
| `凭据/` | 工具链自印、逐件构建日志、`go test` 与闸门原样输出、源码字节指纹、Better Harness 与 Mobile Use 的实测证据、打包读数 |
| `校验-清单.sha256` | 包内每一件的 sha256（清单自身除外） |

## zip 里为什么名字不一样

同一套件打两份：**中文原样树**（仓库侧看的那份，清单是 `校验-清单.sha256`）与 **便携树**（zip 从它生成，条目名全 ASCII，清单是 `MANIFEST.sha256`）。
原因是实测：`zipfile` 与 `Compress-Archive` 写出的中文条目名，在 Git Bash 的 Info-ZIP 里解出来是乱码（PowerShell 那份额外还带反斜杠），
清单立刻核不了 —— 一个解不开的交付包不算交付。两边名字的对应关系写在包内 `NAME-MAP.txt`，
zip 自身的 sha256 记在包外的 `agentkernel-<日期>-win-x64.zip.sha256`（sidecar，不能记在包内：包在 zip 里）。

## 拿到之后怎么验（两条命令，都要跑）

```
sha256sum -c MANIFEST.sha256        # 从 zip 解出来的便携树里
bin/kcheck.exe
```

第一条核字节没被动过（中文原样树里那一把叫 `校验-清单.sha256`，两条清单各管自己那棵树）；
第二条是**这个二进制自己跑内核闸门**，末行 `✓ 全部通过`、退出码 0。
`kcheck` 要在解出来的仓库目录当工作目录下跑，它扫的是仓库树而不是自己：详见 `docs/README.md` 第 1 节。
控制台是 GBK 的话把输出重定向进文件再读，否则 `✓/✗` 成乱码。

## 这份产物钉死了哪套源码

`凭据/源码指纹.sha256` 记下了构建时所依据的全部 `.go` 与 `go.mod` 的字节指纹，
并附了一份「盘上没有 / 对不上」的自检读数在 `凭据/打包读数.txt`。

## 两个插件在这次交付里各做了什么

- **Better Harness（0.2.20）**：跑了 `harness evidence-bundle`（normal 深度）、`harness analyze`、
  `harness checkup --phase scan`，以及为诊断具名不可用道而跑的 `core-change-watch project-profile`。
  结果：报告道按它自己的契约**在本仓库停住**——必填的 `projectHarness` 道挂在
  `git rev-parse --show-toplevel`，而这个仓库按作者规矩不是 git 工作树（回滚靠 `.hermess-snapshots` 快照点，
  本次没有执行 `git init`）。原始 JSON 与逐条台账见 `凭据/09-BH-bundle.json`、`凭据/14-BH-台账.txt`。
  能出件的只有只读扫描道，它自己印的读数是「findings 0 条、会话源 7 条全部 exists=false」。
- **Mobile Use / Phone Use（0.7.5）**：不适用，且是不适用**有证据**的那种不适用。
  `list_targets` 返回空数组；环境自检报 Android SDK/adb/emulator/JDK 全缺、HarmonyOS DevEco 全缺、
  iOS 在 win32 主机上标 `UNSUPPORTED`；整个工作区里找不到任何一个移动端工程入口标记
  （`AndroidManifest.xml` / `build-profile.json5` / `*.xcodeproj` / `Package.swift` / `module.json5`）。
  这个内核是 Go 命令行与 MCP 服务端件，没有 App 形态可给它操作。原始输出见 `凭据/08-手机侧.txt`。

## 重建

需要 Go 1.27 与一个只依赖标准库的环境；构建命令与逐件产物名见 `凭据/02-逐件构建.txt`，
工具链版本是那一份自己印的 `凭据/00-工具链.txt`。
