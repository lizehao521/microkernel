#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""出表：由 数据/*.json 生成正文里的两个 GEN 块，落盘后**重读**并数行数。

这是本族唯一被授权写 HTML 的件。写的是生成区，手写的正文句子一个字都不动
（GEN 注释之间的内容会被整段替换）。

用法（工作目录 垂类报告-1026）：
    C:/Users/Admin/sdk/py314/python.exe 工具/出表.py            # 生成并落盘
    C:/Users/Admin/sdk/py314/python.exe 工具/出表.py --check    # 只算不写（dry-run）
退出码：0 写出且落盘行数对得上 ｜ 2 dry-run 通过但没写 ｜ 3 评分表自身不合法（拒绝出分）
        ｜ 1 本件错（文件读不到 / GEN 区间缺失 / 重读对不上）

stdout 只印 ASCII（GBK 控制台下 `✓`/`⇒` 会崩，崩掉的是退出码契约）；
完整读数走 UTF-8 句柄写进 读数/出表.txt。
"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import 模型  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = os.path.join(ROOT, "src")
SCORE_HTML = os.path.join(SRC, "04-scoring.html")
APPX_HTML = os.path.join(SRC, "07-appendix.html")
DRY = "--check" in sys.argv[1:]


def count_tr(text):
    return text.count("<tr")


def main():
    o = io.StringIO()

    def w(f, *a):
        o.write((f % a if a else f) + "\n")

    try:
        score, closed, refs = 模型.load_all()
    except FileNotFoundError as e:
        print("E1 INPUT_MISSING ascii-only: see stderr file")
        sys.stderr.write("出表：读不到输入件 %s\n" % e)
        return 1
    except Exception as e:  # noqa: BLE001
        sys.stderr.write("出表：输入件读不出来：%r\n" % (e,))
        return 1

    bad, res = 模型.validate(score, closed, refs)
    sens = 模型.sensitivity(score)
    w("出表 · 评分表 schema=%s decided_at=%s", score.get("schema"), score.get("decided_at"))
    w("垂类 %d ｜ 计分维 %d ｜ 格子 %d 个（其中未判定 %d）",
      len(score.get("verticals", [])), len(score.get("dimensions", [])),
      len(score.get("verticals", [])) * len(score.get("dimensions", [])),
      sum(len(r["unknown"]) for r in res.get("rows", [])) if not res.get("error") else -1)
    if refs is None:
        w("引用登记件：不存在（波 1 未起）—— public 凭据一律无法核对")
    else:
        cnt = 模型.status_counts(refs)
        w("引用登记：%d 条 ｜ %s", len(refs.get("entries", [])),
          " ".join("%s=%d" % (s, cnt[s]) for s in 模型.STATUSES))

    if bad:
        w("")
        w("评分表不合法，拒绝出分（%d 条）：", len(bad))
        for x in bad:
            w("  - %s", x)
        w("")
        w("结论：rc=3。修数据或补凭据，不要求着出一个赢家。")
        _emit(o)
        return 3

    w("")
    w("重算赢家：%s ｜ 名次 %s", res["winner"], " → ".join(res["ranking"]))
    for r in res["rows"]:
        w("  %s %-24s 加权好度 %.4f（已知权重和 %.2f，未判定 %s）",
          r["id"], r["name"][:12], r["total"], r["weight_known"],
          ",".join(r["unknown"]) or "—")
    w("敏感性 ±%.0f%%：%s", sens["pct"] * 100,
      "全部不翻" if not sens["flips"] else "会翻 → " + "、".join(sens["flips"]))

    score_block = 模型.gen_score_html(score, res, sens)
    expected_score = 1 + len(score.get("verticals", []))  # fig3 表头 + 每垂类一行
    expected_score += 1 + len(sens.get("rows", []))       # 敏感性表头 + 每扰动一行

    if refs is None:
        appx_block = 模型.block("REFS", '<p class="small">波 1 未起：引用登记件不存在，本块待生成。</p>')
        expected_refs = 0
    else:
        appx_block = 模型.gen_refs_html(refs)
        expected_refs = 1 + len(refs.get("entries", []))

    if DRY:
        w("")
        w("dry-run：没写盘。SCORE 块应含 %d 行表，REFS 块应含 %d 行表。",
          expected_score, expected_refs)
        _emit(o)
        return 2

    rc = 0
    for path, blk, exp, name in ((SCORE_HTML, score_block, expected_score, "SCORE"),
                                 (APPX_HTML, appx_block, expected_refs, "REFS")):
        if not os.path.isfile(path):
            w("落地失败：%s 不存在（正文段要先写好 GEN 标记）", path)
            rc = 1
            continue
        text = open(path, encoding="utf-8").read()
        try:
            new = 模型.splice(text, name, blk)
        except RuntimeError as e:
            w("落地失败：%s", e)
            rc = 1
            continue
        if new == text:
            w("%s 块内容与盘上已一致（没改动）", name)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(new)
        # 落盘后重读，从落盘那份重数——件自己印的行数不算证据
        back = open(path, encoding="utf-8").read()
        got = 模型.rendered_blocks(back).get(name, "")
        n = count_tr(got)
        ok = (n == exp)
        w("  %s → %s：落盘重读 <tr>=%d，期望 %d ｜ %s",
          name, os.path.basename(path), n, exp, "OK" if ok else "MISMATCH")
        if not ok:
            rc = 1

    w("")
    filled = sum(r["n_known"] for r in res["rows"])
    cells = len(score.get("verticals", [])) * len(score.get("dimensions", []))
    if rc == 0:
        w("landing check: %d/%d rows OK", expected_score + expected_refs,
          expected_score + expected_refs)
    else:
        w("landing check: FAILED（上面点名哪一块对不上）")
    w("score_cells_filled=%d/%d ｜ score_winner=%s ｜ score_flip_count=%d",
      filled, cells, res["winner"] or "TIE", len(sens["flips"]))
    w("结论：%s", "已写出" if rc == 0 else "本件错（rc=1）")
    _emit(o)
    return rc


def _emit(buf):
    """读数落盘为权威件（UTF-8）；stdout 走原始字节，绕开 GBK 编码崩溃——
    崩掉的是退出码契约，不是显示。（同一手法见 研究-1022/话术闸.py）"""
    text = buf.getvalue()
    out_dir = os.path.join(ROOT, "读数")
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "出表.txt"), "w", encoding="utf-8") as f:
        f.write(text)
    sys.stdout.buffer.write(text.encode("utf-8", errors="replace"))


if __name__ == "__main__":
    sys.exit(main())
