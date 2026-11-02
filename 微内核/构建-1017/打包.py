"""构建产物打包器（第二版）。
两棵树：
  PKG  = 原样中文树（给仓库侧看，清单 校验-清单.sha256 覆盖它）；
  STG  = 便携树（条目名全 ASCII，zip 从它生成 —— 中文名在 Info-ZIP/PowerShell 那边会解成乱码，实测过）。
每把尺子都要有反对照：改一个字节必须报对不上，否则不许交付。数字全部自印，不手抄。"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import time
import zipfile

WORK = r"C:\Users\Admin\Desktop\微内核\构建-1017"
SRC = r"C:\Users\Admin\Desktop\微内核\微内核\微内核"
PKG = os.path.join(WORK, "agentkernel")
STG = os.path.join(WORK, "便携包", "agentkernel")
LOG = os.path.join(WORK, "日志")
# STAMP 是**生成日**，不是某个钉死的日期。原先写死 "2026-10-17" ⇒ 每次重跑都在原地覆盖同名 zip，
# 上一份的字节就此消失、只剩它的哈希散落在几份 stdout 里（10-18 一夜撞了三次，作者口令是「保留旧的不动」）。
STAMP = time.strftime("%Y-%m-%d")
ZIP = os.path.join(WORK, "agentkernel-%s-win-x64.zip" % STAMP)
MAN_TREE = "校验-清单.sha256"
MAN_ZIP = "MANIFEST.sha256"
MAPFILE = "NAME-MAP.txt"
# 凭据目录里由打包器自己生成的两件（不是从 日志/ 搬来的），prune 时不能当"无源副本"剔掉
GENERATED = ("源码指纹.sha256", "打包读数.txt")
# 垃圾形状：`go build -o X.exe` 撞上 X.exe 正被进程占用时，会把旧映像改名成 `X.exe~` 再写新的
# （10-18 那台在跑的 mcphttp/mcpkernel 就是这么留下件的；它既不是交付物也没有源，跟着进包就是噪声）。
JUNK_SUFFIX = ("~", ".tmp")
skipped_junk = []

# 便携树里的名字映射（三层：整名 / 目录名 / 目录内文件名）；中文名在 Info-ZIP、PowerShell 那边会解成乱码，实测过
FULL_MAP = {
    "交付说明.md": "PACKAGE-README.md",
    "docs/产品定位.md": "docs/product-positioning.md",
}
DIR_MAP = {"凭据": "evidence"}
EV_MAP = {
    "00-工具链.txt": "00-toolchain.txt",
    "02-逐件构建.txt": "02-build-each.txt",
    "05-分母.txt": "05-denominators.txt",
    "07-sha256sum独立复核.txt": "07-sha256sum-independent.txt",
    "08-手机侧.txt": "08-mobile-use.txt",
    "12-BH-git根因.txt": "12-BH-git-cause.txt",
    "13-BH-canvas初始化.json": "13-BH-canvas-init.json",
    "14-BH-台账.txt": "14-BH-ledger.txt",
    "15-解包后独立核.txt": "15-extracted-independent-check.txt",
    "16-解包件跑闸.txt": "16-extracted-gate.txt",
    "18-逐件smoke.txt": "18-binary-smoke.txt",
    "19-两面-tools清单.txt": "19-tools-list-both-faces.txt",
    "20-BH-checkup-plan.md": "20-BH-checkup-plan.md",
    "21-BH-plan确定性.txt": "21-BH-plan-determinism.txt",
    "打包读数.txt": "pack-readings.txt",
    "源码指纹.sha256": "source-fingerprint.sha256",
}


def portable(rel):
    if rel in FULL_MAP:
        return FULL_MAP[rel]
    parts = rel.split("/")
    if parts[0] in DIR_MAP:
        parts[0] = DIR_MAP[parts[0]]
    if parts[-1] in EV_MAP:
        parts[-1] = EV_MAP[parts[-1]]
    out = "/".join(parts)
    if not out.isascii():
        raise AssertionError("这个条目名含中文、又没进映射表，硬上会解成乱码：%s" % rel)
    return out


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for blk in iter(lambda: f.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


def walk_files(root, skip_names=()):
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for name in sorted(filenames):
            if name in skip_names:
                continue
            if name.endswith(JUNK_SUFFIX):
                # 剔掉要留名、留数：静默 skip 就是"包里没有这件"这句话没人知道（本仓库的规矩）。
                skipped_junk.append(os.path.relpath(os.path.join(dirpath, name), root).replace(os.sep, "/"))
                continue
            full = os.path.join(dirpath, name)
            out.append((os.path.relpath(full, root).replace(os.sep, "/"), full))
    return out


def write_manifest(root, files, manifest_name):
    lines = ["# agentkernel 交付包指纹清单 ｜ 生成 %s ｜ 条目 %d 个" % (STAMP, len(files))]
    lines += ["%s  %s" % (sha256(full), rel) for rel, full in files]
    path = os.path.join(root, manifest_name)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    return path


def verify(manifest_path, root):
    total = ok = 0
    bad, missing = [], []
    with open(manifest_path, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n").rstrip("\r")
            if not line or line.startswith("#") or "  " not in line:
                continue
            want, rel = line.split("  ", 1)
            total += 1
            full = os.path.join(root, rel.replace("/", os.sep))
            if not os.path.exists(full):
                missing.append(rel)
            elif sha256(full) == want:
                ok += 1
            else:
                bad.append(rel)
    return total, ok, bad, missing


def ctrl(label, manifest_path, root, corrupt_rel, pristine=None):
    """反对照：对 root 里那一件改一个字节再验 —— 尺子量不出改动就不许拿去交付。
    还原走「从真包原样拷回」，不走「把读到的前 64 字节写回去」（那样会把文件截断，读数成 26/27，是假的）。"""
    if not corrupt_rel:
        total, ok, bad, missing = verify(manifest_path, root)
        w("%s ｜ 分母 %d ｜ 对上 %d ｜ 对不上 %d ｜ 盘上没有 %d" % (label, total, ok, len(bad), len(missing)))
        return total, ok, bad, missing
    full = os.path.join(root, corrupt_rel.replace("/", os.sep))
    with open(full, "rb") as f:
        before = f.read(8)
    with open(full, "r+b") as f:
        f.seek(0)
        f.write(b"X")
    total, ok, bad, missing = verify(manifest_path, root)
    hit = "是" if bad == [corrupt_rel] else "否 -> %r" % bad[:3]
    w("%s ｜ 改 %s 头一字节（改前 8 字节 %s）：分母 %d ｜ 对上 %d ｜ 抓到对不上 %d ｜ 抓准了：%s"
      % (label, corrupt_rel, before.hex(), total, ok, len(bad), hit))
    assert bad == [corrupt_rel] and ok == total - 1 and not missing, "反对照没红或串味 —— 这把尺子不许拿去交付"
    shutil.copy2(pristine, full)
    total, ok, bad, missing = verify(manifest_path, root)
    w("%s ｜ 从真包原样拷回后：分母 %d ｜ 对上 %d ｜ 对不上 %d ｜ 盘上没有 %d（字节回去，读数必须回去）"
      % (label, total, ok, len(bad), len(missing)))
    assert ok == total and not bad and not missing, "还原后没回到全绿 —— 还原或清单有一边是假的"
    return total, ok, bad, missing


# 10-18 踩过：读数里一个 `✓` 就能让 GBK 控制台把打包器打崩（UnicodeEncodeError），
# 崩在 print 上而不是崩在打包上 —— 读数必须自己保证发得出去。
try:
    import sys
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

rep = []


def w(s):
    rep.append(s)


def main():
    os.makedirs(os.path.join(PKG, "凭据"), exist_ok=True)
    # 取材 + 剔件都自印，不静默。口径写在脸上：
    # ① `.log` 是**运行日志**（哪台实例在什么时候起来），不是"某一轮的读数"，所以不进交付包的凭据；
    #    10-18 那两份 mcphttp-*.log 就是这么混进 33→35 的，包外想看日志的人去 日志/ 看原件。
    # ② 凭据/ 里由 LOG 派生的副本，如果 LOG 里已经没有这件了，必须**剔走**而不是留着 ——
    #    留着就是"交付一件没有源的字节"，而且下次谁删了读数，包里还是那份旧的（10-18 实撞：
    #    源文件挪走了，`凭据/` 里两份副本还跟着 zip 走）。剔走的原件进 剔出-凭据-<生成日>/，不删。
    dropped_log, pruned = [], []
    for name in sorted(os.listdir(LOG)):
        src = os.path.join(LOG, name)
        if not os.path.isfile(src):
            continue
        if name.lower().endswith(".log"):
            dropped_log.append(name)
            continue
        shutil.copy2(src, os.path.join(PKG, "凭据", name))
    # have 里**不含 .log**：上一轮已经搬进 凭据/ 的那两份，本轮既然定了"运行日志不进包"，
    # 就必须被剔走。原先 have 用的是 LOG 的全部文件名，于是"跳过"只管搬新的、管不着旧的 ——
    # 10-18 深夜实测：改完打包器，zip 里照样躺着 2 份 .log（自检那条抓出来的）。
    have = {n for n in os.listdir(LOG)
            if os.path.isfile(os.path.join(LOG, n)) and not n.lower().endswith(".log")} | set(GENERATED)
    quar = os.path.join(WORK, "剔出-凭据-%s" % STAMP)
    for name in sorted(os.listdir(os.path.join(PKG, "凭据"))):
        full = os.path.join(PKG, "凭据", name)
        if name in have or not os.path.isfile(full):
            continue
        os.makedirs(quar, exist_ok=True)
        shutil.move(full, os.path.join(quar, name))
        pruned.append(name)
    w("【凭据取材】收 %d 件 ｜ 剔运行日志 %d：%s ｜ 剔无源副本 %d：%s（挪到 剔出-凭据-%s\\，没删）"
      % (len([n for n in os.listdir(os.path.join(PKG, "凭据")) if os.path.isfile(os.path.join(PKG, "凭据", n))]),
         len(dropped_log), "、".join(dropped_log) or "无", len(pruned), "、".join(pruned) or "无", STAMP))

    # 0) 文档同步：仓库里那三份 .md 是唯一源，交付树只是快照。
    #    10-18 踩过：改了仓库的 产品定位.md，打包器根本不读它，新口径静默进不了包（三份 hash 才对不上）。
    synced = []
    for name in ("README.md", "contract.md", "产品定位.md"):
        a = os.path.join(SRC, name)
        b = os.path.join(PKG, "docs", name)
        if not os.path.isfile(a):
            continue
        if not os.path.isfile(b) or sha256(a) != sha256(b):
            os.makedirs(os.path.dirname(b), exist_ok=True)
            shutil.copy2(a, b)
            synced.append(name)
    w("【文档同步】仓库 .md → 交付 docs ｜ 本轮同步 %d 份：%s"
      % (len(synced), "、".join(synced) if synced else "无（本就一致）"))

    # 1) 源码指纹：这份二进制钉死在哪套字节上
    src_files = []
    for dirpath, dirnames, filenames in os.walk(SRC):
        dirnames[:] = [d for d in dirnames if d not in ("报告", ".hermess-snapshots", "tasks", ".qoder", "构建")]
        for name in sorted(filenames):
            if name.endswith(".go") or name == "go.mod":
                rel = os.path.relpath(os.path.join(dirpath, name), SRC).replace(os.sep, "/")
                src_files.append((rel, os.path.join(dirpath, name)))
    fp = os.path.join(PKG, "凭据", "源码指纹.sha256")
    with open(fp, "w", encoding="utf-8", newline="\n") as f:
        f.write("# 构建所依据的源码字节指纹 ｜ .go + go.mod ｜ 条目 %d 个\n" % len(src_files))
        for rel, full in src_files:
            f.write("%s  %s\n" % (sha256(full), rel))
    t, o, b, m = verify(fp, SRC)
    w("【源码指纹】分母 %d ｜ 对上 %d ｜ 对不上 %d ｜ 盘上没有 %d" % (t, o, len(b), len(m)))
    assert t and o == t, "源码没全对上，不打包：%r" % (b[:2] + m[:2])

    # 2) 中文原样树：清单 + 自验 + 反对照（反对照在 tmp 副本上做，真包不动）
    tree_files = walk_files(PKG, skip_names=(MAN_TREE,))
    man_tree = os.path.join(PKG, MAN_TREE)
    write_manifest(PKG, tree_files, MAN_TREE)
    t1, o1, b1, m1 = verify(man_tree, PKG)
    w("【原样树清单】条目 %d ｜ 自验：分母 %d ｜ 对上 %d ｜ 对不上 %d ｜ 盘上没有 %d" % (len(tree_files), t1, o1, len(b1), len(m1)))
    assert t1 and o1 == t1 and not b1 and not m1, "原样树自验没过"
    tmp = os.path.join(WORK, "反对照-原样树")
    shutil.rmtree(tmp, ignore_errors=True)
    shutil.copytree(PKG, tmp)
    victim = [r for r, p in tree_files if r.startswith("bin/")][0]
    ctrl("【反对照·原样树】", man_tree, tmp, victim, os.path.join(PKG, victim.replace("/", os.sep)))
    shutil.rmtree(tmp, ignore_errors=True)
    t0, o0, b0, m0 = verify(man_tree, PKG)
    w("【真包未受影响】重验原样树 ｜ 分母 %d ｜ 对上 %d ｜ 对不上 %d ｜ 盘上没有 %d" % (t0, o0, len(b0), len(m0)))
    assert (t0, o0, len(b0), len(m0)) == (t1, o1, 0, 0), "反对照串到真包上了"

    # 3) 便携树：条目名全 ASCII，映射表随包走
    shutil.rmtree(os.path.join(WORK, "便携包"), ignore_errors=True)
    rel_map = {}
    for rel, full in tree_files:
        rel_map[rel] = portable(rel)
        dst = os.path.join(STG, rel_map[rel].replace("/", os.sep))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(full, dst)
    # 原样树的清单点名的是中文名，不进便携树；便携树自己生成一份 ASCII 名的
    zip_files = walk_files(STG)
    with open(os.path.join(STG, MAPFILE), "w", encoding="utf-8", newline="\n") as f:
        f.write("# 原样中文名 -> 便携包内 ASCII 条目名 ｜ 映射表 ｜ 未列出的名字两边一致\n")
        for k in sorted(rel_map):
            if k != rel_map[k]:
                f.write("%s -> %s\n" % (k, rel_map[k]))
    zip_files = walk_files(STG)
    man_zip = os.path.join(STG, MAN_ZIP)
    write_manifest(STG, zip_files, MAN_ZIP)
    tz, oz, bz, mz = verify(man_zip, STG)
    w("【便携树清单】条目 %d ｜ 自验：分母 %d ｜ 对上 %d ｜ 对不上 %d ｜ 盘上没有 %d" % (len(zip_files), tz, oz, len(bz), len(mz)))
    assert tz and oz == tz and not bz and not mz, "便携树自验没过"
    # 两棵树各扫一遍，所以同一个垃圾名字会出现两次 —— 去重后自印，别让它变成一个说不清的差值。
    w("【剔垃圾形状】结尾是 ~ 或 .tmp 的条目 %d 件：%s（`go build -o` 撞上 exe 被占用时留下的旧映像，不进包）"
      % (len(set(skipped_junk)), "、".join(sorted(set(skipped_junk))) or "无"))
    tmp2 = os.path.join(WORK, "反对照-便携树")
    shutil.rmtree(tmp2, ignore_errors=True)
    shutil.copytree(STG, tmp2)
    victim2 = rel_map[victim]
    ctrl("【反对照·便携树】", man_zip, tmp2, victim2, os.path.join(STG, victim2.replace("/", os.sep)))
    shutil.rmtree(tmp2, ignore_errors=True)

    # 同一天重跑会覆盖同日那份（名字里只到日）。比原先"写死 10-17、每天覆盖同一件"好一档，
    # 但覆盖本身要留痕：先把被覆盖那份的哈希记进 重跑记录.txt 并自印，不许无声。
    if os.path.isfile(ZIP):
        with open(os.path.join(WORK, "重跑记录.txt"), "a", encoding="utf-8", newline="\n") as f:
            f.write("%s 覆盖同日上一份 %s ｜ 被覆盖件 sha256=%s ｜ %d 字节\n"
                    % (time.strftime("%H:%M:%S"), os.path.basename(ZIP), sha256(ZIP), os.path.getsize(ZIP)))
        w("【同日重跑】即将覆盖已有 zip ｜ 被覆盖那份的哈希已记进 重跑记录.txt")
    # 4) 压 zip（名字已全 ASCII），并用两种解法各解一次
    if os.path.exists(ZIP):
        os.remove(ZIP)
    with zipfile.ZipFile(ZIP, "w", zipfile.ZIP_DEFLATED) as z:
        for rel, full in walk_files(STG):
            z.write(full, "agentkernel/" + rel)
    zn = zipfile.ZipFile(ZIP).namelist()
    # 这一行原先标成【zip】，读起来像"交付件的大小"——它不是。第 5 步还会重写包内清单再压一次
    # （清单里剔掉了 MANIFEST 自己），字节数因此会变：10-19 这一轮印的是 26769371，
    # 而盘上真件 26769303，差 68 字节；10-18 那轮同样差 12 字节。名字改成【zip-初压】，
    # 交付件的真字节与 sha256 只在【终检】那一行说一次（那才是压完的最后一版）。
    # 件数与非 ASCII 那两项在两次压之间不会变（同一棵便携树 walk 出来的），可以留在这里当自检。
    w("【zip-初压】%s ｜ %d 字节（这不是交付件，交付件见【终检】）｜ 内含 %d 件 ｜ 名字含非 ASCII 的条目 %d 个"
      % (os.path.basename(ZIP), os.path.getsize(ZIP), len(zn), len([x for x in zn if not x.isascii()])))
    # 包内形状自检：扫的是**成品包**，不是输入目录。这条今天真红过一次 —— 上一版只在"搬运时跳过 .log"上动手，
    # 已经躺在 凭据/ 里的旧副本没人管，`unzip -Z1 | grep -c '\.log$'` 还是 2 件。
    # 只看输入的那把尺子会把"我改了"读成"包干净了"，正是本仓库最恨的那种假绿。
    junk = [x for x in zn if x.endswith(".log") or x.endswith("~") or x.endswith(".tmp")]
    w("【包内形状自检】成品包 %d 件里混进运行日志/垃圾 %d：%s" % (len(zn), len(junk), "、".join(junk) or "无"))
    assert not junk, "成品包里还有运行日志或垃圾条目，别当交付物发出去：%s" % junk

    ext = os.path.join(WORK, "解包验")
    shutil.rmtree(ext, ignore_errors=True)
    with zipfile.ZipFile(ZIP) as z:
        z.extractall(ext)
    man_ext = os.path.join(ext, "agentkernel", MAN_ZIP)
    te, oe, be, me = verify(man_ext, os.path.join(ext, "agentkernel"))
    w("【解包后自验(Python 解)】分母 %d ｜ 对上 %d ｜ 对不上 %d ｜ 盘上没有 %d" % (te, oe, len(be), len(me)))
    assert te and oe == te and not be and not me, "解包后的包内清单没过"
    exe = os.path.join(ext, "agentkernel", "bin", "kcheck.exe")
    r = subprocess.run([exe], cwd=SRC, capture_output=True, text=True, encoding="utf-8", errors="replace")
    lines = [l for l in (r.stdout or "").splitlines() if l.strip()]
    w("【解包件跑闸门】退出码 %s ｜ 输出 %d 行 ｜ 末行：`%s`" % (r.returncode, len(lines), lines[-1] if lines else "(没输出)"))
    assert r.returncode == 0, "解出来的 kcheck 跑不过闸门"
    shutil.rmtree(ext, ignore_errors=True)
    uz = shutil.which("unzip")
    w("【unzip 在哪】%s（Info-ZIP 交叉核由 shell 另跑，读数落在包外的 最终复核.txt）" % (uz or "这个 PATH 里没有"))

    # 5) 逐件读数 + 闸的读数原样摘要
    for rel, full in walk_files(STG):
        if rel.startswith("bin/"):
            w("  %-18s %10d 字节  sha256=%s" % (rel, os.path.getsize(full), sha256(full)))
    for logname, label in [("00-工具链.txt", "工具链"), ("03-go-test.txt", "go test"), ("04-kcheck-exe.txt", "交付件自跑 kcheck")]:
        p = os.path.join(PKG, "凭据", logname)
        ls = [l for l in open(p, encoding="utf-8", errors="replace").read().splitlines() if l.strip()]
        w("【%s】共 %d 行；末行：`%s`" % (label, len(ls), ls[-1]))

    out = "\n".join(rep) + "\n"
    with open(os.path.join(WORK, "打包读数.txt"), "w", encoding="utf-8", newline="\n") as f:
        f.write(out)
    print(out)
    # 读数进两棵树 → 两棵树重生成清单 → 重压 zip → 终检
    shutil.copy2(os.path.join(WORK, "打包读数.txt"), os.path.join(PKG, "凭据", "打包读数.txt"))
    shutil.copy2(os.path.join(WORK, "打包读数.txt"), os.path.join(STG, "evidence", "pack-readings.txt"))
    tf = walk_files(PKG, skip_names=(MAN_TREE,))
    write_manifest(PKG, tf, MAN_TREE)
    zf = walk_files(STG, skip_names=(MAN_ZIP,))
    write_manifest(STG, zf, MAN_ZIP)
    a = verify(os.path.join(PKG, MAN_TREE), PKG)
    b = verify(os.path.join(STG, MAN_ZIP), STG)
    if os.path.exists(ZIP):
        os.remove(ZIP)
    with zipfile.ZipFile(ZIP, "w", zipfile.ZIP_DEFLATED) as z:
        for rel, full in walk_files(STG):
            z.write(full, "agentkernel/" + rel)
    with open(ZIP + ".sha256", "w", encoding="utf-8", newline="\n") as f:
        f.write("%s  %s\n" % (sha256(ZIP), os.path.basename(ZIP)))
    final = ("【终检】原样树 分母 %d 对上 %d 差 %d ｜ 便携树 分母 %d 对上 %d 差 %d ｜ zip %d 字节 内含 %d 件 ｜ zip sha256=%s（记在包外 sidecar）"
             % (a[0], a[1], len(a[2]) + len(a[3]), b[0], b[1], len(b[2]) + len(b[3]),
                os.path.getsize(ZIP), len(zipfile.ZipFile(ZIP).namelist()), sha256(ZIP)))
    with open(os.path.join(WORK, "打包读数.txt"), "a", encoding="utf-8", newline="\n") as f:
        f.write(final + "\n")
    print(final)
    assert a[1] == a[0] and b[1] == b[0] and a[0] and b[0], "终检没过"


main()
