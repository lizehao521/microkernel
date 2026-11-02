#!/usr/bin/env python3
"""Build the non-author trial zip from the pilot sample pack.

Read-only on sources; writes only 交付-1020/<zip> and SHA256SUMS-交付.txt.
No network, no model calls.
"""
import hashlib
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "交付-1020"
ZIP_NAME = "非作者试读包-SAMPLE-491-539-2026-10-20.zip"
FIXED_DATE = (2026, 10, 20, 0, 0, 0)

FILES = [
    ("非作者试读-交接说明.md", "00-交接说明.md"),
    ("工具包/03-复核工作台.md", "01-复核工作台.md"),
    ("工具包/02-证据包清单.md", "02-证据包清单.md"),
    ("样本包-491-539/复核记录-空白.md", "03-复核记录-空白.md"),
    ("样本包-491-539/证据包.md", "样本包/证据包.md"),
    ("样本包-491-539/链切片-491-539.jsonl", "样本包/链切片-491-539.jsonl"),
    ("样本包-491-539/链校验-491-539.json", "样本包/链校验-491-539.json"),
    ("样本包-491-539/锚点-490.json", "样本包/锚点-490.json"),
    ("样本包-491-539/受控副本/README.md", "样本包/受控副本/README.md"),
    ("样本包-491-539/受控副本/账本-前缀-1-539.jsonl", "样本包/受控副本/账本-前缀-1-539.jsonl"),
    ("样本包-491-539/受控副本/链切片-491-539.jsonl", "样本包/受控副本/链切片-491-539.jsonl"),
    ("样本包-491-539/受控副本/链校验-491-539.json", "样本包/受控副本/链校验-491-539.json"),
    ("样本包-491-539/受控副本/锚点-490.json", "样本包/受控副本/锚点-490.json"),
    ("工具/切片与校验.js", "工具/切片与校验.js"),
]

SECRET_RE = re.compile(rb"sk-[A-Za-z0-9_-]{20,}")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def add_entry(zf: zipfile.ZipFile, arcname: str, data: bytes) -> None:
    info = zipfile.ZipInfo(arcname, date_time=FIXED_DATE)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o644 << 16
    info.flag_bits |= 0x800  # UTF-8 names
    zf.writestr(info, data)


def main() -> int:
    missing = [src for src, _ in FILES if not (ROOT / src).is_file()]
    if missing:
        print("FAIL missing sources:")
        for src in missing:
            print("  " + src)
        return 1

    payloads = []
    for src, arc in FILES:
        data = (ROOT / src).read_bytes()
        hit = SECRET_RE.search(data)
        if hit:
            print(f"FAIL secret pattern in {src}: {hit.group(0)[:8]}...")
            return 1
        payloads.append((src, arc, data))

    manifest = "".join(f"{sha256(data)} *{arc}\n" for _, arc, data in payloads).encode("utf-8")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    zip_path = OUT_DIR / ZIP_NAME
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for _, arc, data in payloads:
            add_entry(zf, arc, data)
        add_entry(zf, "SHA256SUMS", manifest)

    zip_hash = sha256(zip_path.read_bytes())
    (OUT_DIR / "SHA256SUMS-交付.txt").write_text(
        f"{zip_hash} *{ZIP_NAME}\n", encoding="utf-8", newline="\n"
    )

    print(f"files={len(payloads)}")
    print(f"zip={zip_path}")
    print(f"zip_bytes={zip_path.stat().st_size}")
    print(f"zip_sha256={zip_hash}")
    print("secret_pattern=0")
    return 0


if __name__ == "__main__":
    sys.exit(main())
