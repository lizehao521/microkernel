#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""补丁第二轮：让引擎 CLI 在安全路径解释器下也能导入同目录兄弟模块，并让演示文案不再说谎"""
from __future__ import annotations

import hashlib
import os
import py_compile
import shutil
import sys
import tempfile
import time
from pathlib import Path

SKILL = Path(r"C:/Users/Admin/.qoder-cn/skills/loudong-wajue-jinhua-yinqing")
TARGET = SKILL / "evolution_enhancer.py"
FIXED = Path(__file__).resolve().parent / "修复副本" / "evolution_enhancer.py"
BACKUP_DIR = Path(__file__).resolve().parent / "备份"

PATCHES = [
    (
        "P11 显式把脚本目录放进 sys.path（安全路径解释器不会自动加）",
        '''import hashlib
import json
import random''',
        '''import hashlib
import json
import os
import random''',
    ),
    (
        "P11b 兄弟模块导入前补 sys.path",
        '''from typing import Callable, Dict, List, Optional, Tuple

# ── 复用内核能力 ──''',
        '''from typing import Callable, Dict, List, Optional, Tuple

# 嵌入解释器/安全路径不会把脚本目录放进 sys.path；显式补上，保证同目录兄弟模块可导入
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ── 复用内核能力 ──''',
    ),
    (
        "P12 未接元基因库时把异常原因印出来，不静默",
        '''    except Exception:
        mgl = None
        print("=== 未接入元基因库（开环演示）===")''',
        '''    except Exception as exc:
        mgl = None
        print(f"=== 未接入元基因库（开环演示）：{exc} ===")''',
    ),
    (
        "P13 演示文案只在真写回时说自己已写回",
        '''    print(f"第1次 best_fitness={eh1.best.fitness}, 已写回 L4 基因")

    print("\\n--- 第 2 次进化（读回 L4 先验，偏置策略选择）---")
    eh2 = EvolutionEnhancer(population_size=24, meta_gene=mgl, vuln_type="sqli")
    eh2.evolve(demo_seeds, "sqli", generations=6)
    print(f"第2次 best_fitness={eh2.best.fitness}, L4 先验权重={eh2._strategy_weights}")''',
        '''    if mgl is not None:
        print(f"第1次 best_fitness={eh1.best.fitness}, 已写回 L4 基因")
    else:
        print(f"第1次 best_fitness={eh1.best.fitness}, 未接元基因库：这一轮没有写回")

    print("\\n--- 第 2 次进化（" + ("读回 L4 先验，偏置策略选择" if mgl is not None else "未接元基因库，开环") + "）---")
    eh2 = EvolutionEnhancer(population_size=24, meta_gene=mgl, vuln_type="sqli")
    eh2.evolve(demo_seeds, "sqli", generations=6)
    if mgl is not None:
        print(f"第2次 best_fitness={eh2.best.fitness}, L4 先验权重={eh2._strategy_weights}")
    else:
        print(f"第2次 best_fitness={eh2.best.fitness}, 未接元基因库：无先验可读")''',
    ),
]


def apply_to(text: str) -> tuple[str, list[str]]:
    log = []
    out = text
    for label, old, new in PATCHES:
        n = out.count(old)
        log.append(f"  [{'OK' if n == 1 else 'BAD'}] {label} ｜ 命中 {n}")
        if n != 1:
            return out, log + ["尺子坏：替换目标不唯一"]
        out = out.replace(old, new, 1)
    return out, log


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    out: list[str] = []

    def say(s: str = "") -> None:
        print(s)
        out.append(s)

    raw = TARGET.read_bytes()
    crlf = b"\r\n" in raw
    text = TARGET.read_text(encoding="utf-8")
    say("=" * 72)
    say("补丁第二轮：CLI 自持 + 演示文案诚实")
    say("=" * 72)
    say(f"目标 = {TARGET}")
    say(f"改前 sha256 = {hashlib.sha256(raw).hexdigest()} ｜ CRLF = {crlf}")

    fixed_text, log = apply_to(text)
    for line in log:
        say(line)
    if any("BAD" in line or "尺子坏" in line for line in log):
        return 3

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    backup = BACKUP_DIR / f"evolution_enhancer.py.patch1-{time.strftime('%Y%m%d-%H%M%S')}"
    shutil.copy2(TARGET, backup)
    say(f"第二轮前备份 = {backup}")

    fd, tmp_name = tempfile.mkstemp(prefix="ee2-", suffix=".py", dir=str(SKILL))
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        with tmp.open("w", encoding="utf-8", newline="\r\n" if crlf else "\n") as fh:
            fh.write(fixed_text)
        py_compile.compile(str(tmp), doraise=True)
        os.replace(tmp, TARGET)
    finally:
        if tmp.exists():
            tmp.unlink()

    after = TARGET.read_bytes()
    say(f"改后 sha256 = {hashlib.sha256(after).hexdigest()} ｜ 字节 = {len(after)}")

    FIXED.write_text(TARGET.read_text(encoding="utf-8"), encoding="utf-8")
    say(f"修复副本已同步 = {FIXED} ｜ sha256 = {hashlib.sha256(FIXED.read_bytes()).hexdigest()}")
    say("改动范围仍只有 evolution_enhancer.py")
    (Path(__file__).resolve().parent / "应用补丁2-读数.txt").write_text(
        "\n".join(out) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
