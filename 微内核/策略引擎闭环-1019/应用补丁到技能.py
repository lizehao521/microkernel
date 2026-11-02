#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把已验证的修复副本落到已安装技能（先备份，编译通过才替换）

只动 evolution_enhancer.py；不动 meta_gene.py / vuln_hunter_kernel.py / SKILL.md。
"""
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


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


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
    fixed_text = FIXED.read_text(encoding="utf-8")
    say("=" * 72)
    say("把修复副本落到已安装技能")
    say("=" * 72)
    say(f"目标 = {TARGET}")
    say(f"目标原 sha256 = {sha(raw)} ｜ 原字节 = {len(raw)} ｜ CRLF = {crlf}")
    say(f"来源 = {FIXED}")
    say(f"来源 sha256 = {sha(FIXED.read_bytes())}")

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup = BACKUP_DIR / f"evolution_enhancer.py.orig-{stamp}"
    shutil.copy2(TARGET, backup)
    if sha(backup.read_bytes()) != sha(raw):
        say("尺子坏：备份字节与原件不一致，未替换")
        return 3
    say(f"备份 = {backup} ｜ sha256 = {sha(backup.read_bytes())}")

    fd, tmp_name = tempfile.mkstemp(prefix="ee-", suffix=".py", dir=str(SKILL))
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        with tmp.open("w", encoding="utf-8", newline="\r\n" if crlf else "\n") as fh:
            fh.write(fixed_text)
        try:
            py_compile.compile(str(tmp), doraise=True)
        except py_compile.PyCompileError as exc:
            say(f"尺子坏：补丁后编译失败，未替换：{exc}")
            return 3
        before = TARGET.read_bytes()
        os.replace(tmp, TARGET)
        after = TARGET.read_bytes()
    finally:
        if tmp.exists():
            tmp.unlink()

    say(f"替换后 sha256 = {sha(after)} ｜ 后字节 = {len(after)}")
    say(f"替换前后不同 = {before != after}")
    say("改动范围 = evolution_enhancer.py 一个文件；meta_gene.py / vuln_hunter_kernel.py / SKILL.md 未动")

    # 归一化行尾后确认内容就是修复副本
    same_text = TARGET.read_text(encoding="utf-8") == fixed_text
    say(f"归一化行尾后与修复副本逐字相同 = {same_text}")
    (Path(__file__).resolve().parent / "应用补丁-读数.txt").write_text(
        "\n".join(out) + "\n", encoding="utf-8"
    )
    return 0 if same_text else 3


if __name__ == "__main__":
    sys.exit(main())
