"""臂检件的崩溃自证（2026-10-23）：证明「跑臂跑到一半被打断」既不在 %TEMP% 留下整棵树的副本，
也不毁掉上一份臂读数。

被审的是 `臂检-全部族.py` 自己。它把树拷进 %TEMP%\\allfam-<pid> 再往副本落变异，
所以**真树全程只读**（这一条本轮先被我说错过，见交接 §7b）；代价是副本必须保证被带走 ——
件里用 `atexit` 登记清理。第二件修法：读数先写 `.part`，跑完才 `os.replace` 到正式名 ——
原先一开跑就把上一份 82 行读数 `open(..., "w")` 截成 0 字节，而合取件只看 mtime ⇒ 空读数被判成绿。

三头都判（同一份「上一份好读数」预置在各案例自己的 读数/ 里，跑完看它还剩什么）：

- **新件**：崩在「刚把变异写进副本、还没还原」那一步 ⇒ 副本**必须不留下**、真树 mtime+size 必须不变、
  上一份读数必须**一字未动**、且 `读数/` 里不许留 `.part`；
- **旧件（负对照 A）**：`TEMP-备份/文档-1023/臂检-全部族.py`（既无 atexit 也无原子发布）
  ⇒ 同样的崩法**必须留下副本**且**必须把上一份读数截成 0 字节**；
- **中间件（负对照 B）**：`臂检-全部族-改前2.py`（已有 atexit、还没原子发布）
  ⇒ 副本照样带走，但读数**仍被截成 0 字节** —— 这一发把两笔账分开：清理 ≠ 不毁读数。

两头打架才说明修的是那件事，不是运气。为什么用环境变量开关而不是 mock：`臂检-全部族.py`
是 module-level 直跑的件（exec 它就开跑全臂），没法 import 进来打桩；开关只在显式设置时生效，
正常跑法那行恒不执行。

退出码：0=全过；3=有判据不过（含「负对照居然没留副本/没截读数」—— 那说明开关没接上，自证本身是空的；
含「中间件对照件不在盘上」—— 分开记账的那条证据就缺了）。
产物：`读数/臂检崩溃自证-1023.txt`（UTF-8）；控制台只走 ASCII（GBK 打中文会崩，崩掉的 rc 会冒充闸红）。
"""
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.join(HERE, "臂检-全部族.py")
OLD = os.path.join(HERE, "..", "TEMP-备份", "文档-1023", "臂检-全部族.py")
PREV2 = os.path.join(HERE, "..", "TEMP-备份", "文档-1023", "臂检-全部族-改前2.py")
TREE = os.environ.get("ARMCHECK_TREE", r"C:/Users/Admin/Desktop/微内核/微内核/微内核")
GO = os.environ.get("ARMCHECK_GO", r"C:/Users/Admin/sdk/go/bin/go.exe")
PY = sys.executable
OUT = os.path.join(HERE, "读数", "臂检崩溃自证-1023.txt")
ROOT = os.path.join(os.environ["TEMP"], "arm-crash-selfcheck-1023")

HOOK = ('\n    if os.environ.get("ARMCHECK_CRASH_AFTER_MUTATE") == "1":\n'
        '        raise RuntimeError("crash switch fired after writing mutant '
        '(ARMCHECK_CRASH_AFTER_MUTATE=1)")\n')

_lines = []


def w(fmt, *a):
    s = fmt % a if a else fmt
    _lines.append(s)
    print(s.encode("ascii", "backslashreplace").decode("ascii"))


def inject_hook(path):
    """给旧版副本只装崩溃开关、不装 atexit —— 它才是这次修改的负对照。"""
    src = io.open(path, encoding="utf-8").read()
    anchor = 'open(cpath, "w", encoding="utf-8", newline="\\n").write(mut)\n'
    n = src.count(anchor)
    assert n == 1, "mutant-write anchor hit %d (expected 1) in %s" % (n, path)
    return src.replace(anchor, anchor + HOOK, 1)


def allfam():
    return {d for d in os.listdir(os.environ["TEMP"]) if d.startswith("allfam-")}


def tree_stamp():
    d = os.path.join(TREE, "cmd", "agentd")
    return {f: (os.stat(os.path.join(d, f)).st_mtime, os.stat(os.path.join(d, f)).st_size)
            for f in os.listdir(d) if f.endswith(".go")}


def run_case(tag, src_text, seed=""):
    box = os.path.join(ROOT, tag)
    shutil.rmtree(box, ignore_errors=True)
    os.makedirs(box)
    tool = os.path.join(box, "arm-tool-under-test.py")   # ASCII 名：子进程 traceback 里别漏进乱码
    io.open(tool, "w", encoding="utf-8", newline="\n").write(src_text)
    # 预先在件会写读数的位置放一份「上一趟的好读数」：崩完之后它还在不在，就是原子发布的全部证据。
    os.makedirs(os.path.join(box, "读数"), exist_ok=True)
    prev = os.path.join(box, "读数", "臂检-全部族.jsonl")
    io.open(prev, "w", encoding="utf-8", newline="\n").write(seed)
    seed_md5 = hashlib.md5(io.open(prev, "rb").read()).hexdigest()
    before_dirs, before_tree = allfam(), tree_stamp()
    env = dict(os.environ)
    env["ARMCHECK_CRASH_AFTER_MUTATE"] = "1"
    t0 = time.time()
    try:
        r = subprocess.run([PY, tool, GO, TREE], cwd=box, capture_output=True,
                           text=True, encoding="utf-8", errors="replace", env=env, timeout=900)
        rc, blob = r.returncode, (r.stdout or "") + (r.stderr or "")
    except subprocess.TimeoutExpired:
        rc, blob = None, "TIMEOUT"
    left = sorted(allfam() - before_dirs)
    for d in left:                       # 负对照留下的副本：证据记完就带走，不攒垃圾
        shutil.rmtree(os.path.join(os.environ["TEMP"], d), ignore_errors=True)
    live = io.open(prev, "rb").read()
    return {"tag": tag, "rc": rc, "sec": round(time.time() - t0), "left": left,
            "fired": "crash switch fired" in blob, "tree_same": tree_stamp() == before_tree,
            "prev_md5_same": hashlib.md5(live).hexdigest() == seed_md5,
            "prev_bytes": len(live), "part_left": os.path.isfile(prev + ".part"),
            "tail": [l for l in blob.splitlines() if l.strip()][-3:]}


def main():
    if not os.path.isdir(TREE) or not os.path.isfile(GO):
        w("缺 go.exe 或树根：ARMCHECK_GO / ARMCHECK_TREE —— 本次不判")
        return 4
    if not os.path.isfile(OLD):
        w("负对照原件不在 %s —— 这条自证退化成单边，不判" % OLD)
        return 4
    shutil.rmtree(ROOT, ignore_errors=True)
    os.makedirs(ROOT)
    seed = "".join(json.dumps({"arm": "PRE %d" % i, "verdict": "BIT"}) + "\n" for i in range(3))
    cases = [run_case("new-atexit", io.open(TOOL, encoding="utf-8").read(), seed),
             run_case("old-noexith", inject_hook(OLD), seed)]
    new, old = cases
    if os.path.isfile(PREV2):
        # 中间那份（已带 atexit、还没原子发布）：单独证明「光有清理救不了读数」，
        # 免得把截断读数这一条牙记在 atexit 那笔账上。它本就带崩溃开关；万一没带就补装，
        # 否则这一发会变成「跑完整趟」而不是「崩在变异窗口里」。
        src_mid = io.open(PREV2, encoding="utf-8").read()
        if "ARMCHECK_CRASH_AFTER_MUTATE" not in src_mid:
            src_mid = inject_hook(PREV2)
        cases.append(run_case("prev-noatomic", src_mid, seed))
    mid = [c for c in cases if c["tag"] == "prev-noatomic"]
    for c in cases:
        w("%-13s rc=%s %3ds fired=%s tree_same=%s 留下的副本=%s 上一份读数=%dB md5同=%s .part残留=%s",
          c["tag"], c["rc"], c["sec"], c["fired"], c["tree_same"], c["left"] or "-",
          c["prev_bytes"], c["prev_md5_same"], c["part_left"])
    checks = [
        ("新件：崩溃开关真接上线（不是恒不执行）", new["fired"]),
        ("新件：崩在变异窗口里，工作副本仍被 atexit 带走", not new["left"] and new["rc"] not in (0, None)),
        ("新件：真树 mtime+size 逐文件不变（臂只动 TEMP 副本）", new["tree_same"]),
        ("新件：崩掉后上一份读数一字未动（正式名只由 .part 替换）", new["prev_md5_same"]),
        ("新件：崩掉后 读数/ 里没有 .part 半截件", not new["part_left"]),
        ("负对照：旧件同样的崩法必须留下副本（否则这条自证是空的）", bool(old["left"]) and old["fired"]),
        ("负对照：旧件也没写真树（破坏面本来就只在 TEMP）", old["tree_same"]),
        ("负对照：旧件把上一份读数截成 0 字节（这条牙确实是新长的）",
         old["prev_bytes"] == 0 and not old["prev_md5_same"]),
    ]
    if mid:
        checks += [
            ("中间件（只有 atexit）：副本照样带走 ⇒ 清理与原子发布是两件事", not mid[0]["left"]),
            ("中间件（只有 atexit）：上一份读数仍被截成 0 字节 ⇒ 原子发布才是这一条的修法",
             mid[0]["prev_bytes"] == 0 and not mid[0]["prev_md5_same"]),
        ]
    else:
        w("SKIP 中间件对照：%s 不在盘上 ⇒ 「光有 atexit 保不住读数」这一条没判" % PREV2)
        checks.append(("中间件对照件在盘上（缺了就没法把 atexit 与原子发布分账）", False))
    bad = 0
    for i, (name, ok) in enumerate(checks, 1):
        w("CHECK %d/%d %-4s | %s", i, len(checks), "PASS" if ok else "FAIL", name)
        bad += 0 if ok else 1
    w("结论：%d 条不过 —— 臂检件的「打断也带走 TEMP 副本」与「打断也不毁上一份读数」%s", bad,
      "由新件、负对照与中间件三方钉住" if bad == 0 else "没钉住，别看 PASS")
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    io.open(OUT, "w", encoding="utf-8", newline="\n").write("\n".join(_lines) + "\n")
    io.open(OUT.replace(".txt", ".json"), "w", encoding="utf-8", newline="\n").write(
        json.dumps({"cases": cases, "checks": [[n, bool(o)] for n, o in checks],
                    "tree": TREE, "bad": bad}, ensure_ascii=False, indent=1))
    return 0 if bad == 0 else 3


if __name__ == "__main__":
    sys.exit(main())
