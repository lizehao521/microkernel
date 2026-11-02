"""两把尺子对账：窗口对比件印的 p，必须等于自检过的那件的 p。"""
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location(
    "pw", str(HERE / "分析-配对检验-1023.py"))
pw = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pw)

spec2 = importlib.util.spec_from_file_location(
    "wc", str(HERE / "分析-窗口对比-1023.py"))
wc = importlib.util.module_from_spec(spec2)
spec2.loader.exec_module(wc)

CASES = [("B01", 4, 5, 17, 18), ("B02", 4, 5, 17, 19), ("B09", 4, 5, 19, 19),
         ("overall", 60, 64, 53, 56)]
bad = []
for name, k1, n1, k2, n2 in CASES:
    a = pw.fisher_2x2(k1, n1, k2, n2)
    b = wc.fisher_exact(k1, n1 - k1, k2, n2 - k2)
    b = None if b is None else round(b, 4)
    same = (a == b)
    if not same:
        bad.append(name)
    print(json.dumps({"case": name, "counts": "%d/%d vs %d/%d" % (k1, n1, k2, n2),
                      "p_selftested": a, "p_window_tool": b, "agree": same},
                     ensure_ascii=True))
print(json.dumps({"cases": len(CASES), "disagree": bad, "all_agree": not bad},
                 ensure_ascii=True))
raise SystemExit(0 if not bad else 1)
