"""Mutation driver for the ruler's new arms 55/56/56b/56c/57 -- proves they can go red.

Mutants are written into 真端点-1023/ (so HERE/FX/TASKS still resolve), run with --selftest,
then deleted. The real piece is never touched here.
"""
import subprocess
from pathlib import Path

HERE = Path(r"C:\Users\Admin\Desktop\微内核\PDF-1022\真端点-1023")
SRC = HERE / "分析-答案数源-1023.py"
PY = r"C:/Users/Admin/sdk/py314/python.exe"
text = SRC.read_text(encoding="utf-8")

MUT = [
    ("M1 退回整串扫（不按段绑文件）",
     'for seg_kind, tool, seg, seg_rel in receipt_segments(head):',
     'for seg_kind, tool, seg, seg_rel in [("prose", "", head, None)]:'),
    ("M2 只关掉参数text这一档",
     'elif seg_kind == "receipt" and ARG_TEXT_MARK in seg.split("｜", 1)[0]:',
     'elif False and seg_kind == "receipt":'),
    ("M3 不数满400字符的行",
     "        if len(head) >= HEAD_CAP:\n            at_cap += 1",
     ""),
]

for i, (name, old, new) in enumerate(MUT):
    if old not in text:
        print('{"mutant": %s, "error": "anchor not found -- mutant never built"}' % repr(name))
        continue
    path = HERE / ("TEMP-变异-数源-%d.py" % i)
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    try:
        r = subprocess.run([PY, str(path), "--selftest"], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=900)
        lines = (r.stdout or "").splitlines()
        reds = [ln for ln in lines if '"ok": false' in ln]
        tail = [ln for ln in lines if '"selftest_fails"' in ln]
        print('{"mutant": %s, "rc": %d, "arms_red": %d, "tail": %s, "stderr_bytes": %d}'
              % (repr(name), r.returncode, len(reds), tail[-1] if tail else None,
                 len(r.stderr or "")))
        for ln in reds:
            print("    ", ln[:220])
    finally:
        path.unlink()

print('{"real_piece_bytes_after": %d, "real_piece_sha8": %s}'
      % (SRC.stat().st_size, __import__("hashlib").sha256(SRC.read_bytes()).hexdigest()[:8]))
