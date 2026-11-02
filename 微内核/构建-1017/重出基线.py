"""按上一份基线的**精确路径集**重生成一份新基线（不从扩展名重新捞 —— 那条坑记过：
按扩展名筛会把 go.mod 之类漏掉，账面从 66 掉到 65 还没人发现）。
格式对齐上一份：`<sha256> *<路径>`、CRLF；写完自验并**分母与 OK 并排印**。"""
import datetime
import hashlib
import io
import os
import re

SRC = r"C:\Users\Admin\Desktop\微内核\微内核\微内核"
PREV = os.path.join(SRC, "报告", "回滚基线-1017al.txt")
NEW = os.path.join(SRC, "报告", "回滚基线-1017am.txt")
LINE = re.compile(r"^([0-9a-f]{64})\s+\*?(\S+)\s*$")


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for blk in iter(lambda: f.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


paths = []
with io.open(PREV, encoding="utf-8") as f:
    for raw in f:
        m = LINE.match(raw.rstrip("\r\n"))
        if m:
            paths.append(m.group(2))
assert len(paths) == 87, "从上一份取到的路径数不是 87，是 %d —— 先别看新的" % len(paths)
missing = [p for p in paths if not os.path.exists(os.path.join(SRC, p.replace("/", os.sep)))]
assert not missing, "上一份点名的文件现在不在了：%r" % missing[:5]

stamp = datetime.datetime.now().strftime("%m-%d %H:%M")
body = ["# 回滚基线 · 全部代码文件 · %s（由 %s 的精确路径集重生成，%d 条路径一条不多一条不少）" % (stamp, os.path.basename(PREV), len(paths)),
        "# 计数先数分母再吹 OK/FAILED；读这份件的人应当同时看到两个数"]
changed = []
for p in paths:
    h = sha256(os.path.join(SRC, p.replace("/", os.sep)))
    body.append("%s *%s" % (h, p))
with io.open(NEW, "w", encoding="utf-8", newline="\r\n") as f:
    f.write("\n".join(body) + "\n")

# 自验：重新读回来逐条重算，分母/OK/FAILED 并排印；顺带点名与上一份比哪几件字节变了
prev_hash = {}
with io.open(PREV, encoding="utf-8") as f:
    for raw in f:
        m = LINE.match(raw.rstrip("\r\n"))
        if m:
            prev_hash[m.group(2)] = m.group(1)
moved = [p for p in paths if prev_hash[p] != sha256(os.path.join(SRC, p.replace("/", os.sep)))]
total = ok = 0
bad = []
with io.open(NEW, encoding="utf-8") as f:
    for raw in f:
        m = LINE.match(raw.rstrip("\r\n"))
        if not m:
            continue
        total += 1
        cur = sha256(os.path.join(SRC, m.group(2).replace("/", os.sep)))
        ok += 1 if cur == m.group(1) else 0
        if cur != m.group(1):
            bad.append(m.group(2))
print("新基线 %s ｜ 分母 %d ｜ 对上 %d ｜ 没对上 %d ｜ 与上一份比字节变过的 %d 件：%s"
      % (os.path.basename(NEW), total, ok, len(bad), len(moved), moved))
print("行数核对（含抬头）：新件 %d 行 ｜ 上一件 %d 行"
      % (sum(1 for _ in io.open(NEW, encoding="utf-8")), sum(1 for _ in io.open(PREV, encoding="utf-8"))))
assert total == 87 and ok == 87 and not bad, "新基线自验没过"
