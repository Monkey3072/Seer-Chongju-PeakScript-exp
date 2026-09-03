#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把生成的 UTF-8 ini 脚本转成游戏要求的 ANSI/GBK（无 BOM、CRLF）。

用法:
    python convert_gbk.py <脚本目录>

仅处理 .ini 文件（含子目录 精灵出招/*）。已为 GBK/ANSI 的文件自动跳过，
避免重复转码。转码后再用 build-chongju-scripts/scripts/validate.py 校验。
"""

import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def to_crlf(data: bytes) -> bytes:
    data = data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return data.replace(b"\n", b"\r\n")


def convert_ini(path: Path):
    raw = path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    try:
        text = raw.decode("utf-8", errors="strict")
        encoding = "utf-8"
    except UnicodeDecodeError:
        # 已是 GBK/ANSI，仅规范化换行，保持原字节
        text = raw.decode("gb18030", errors="strict")
        encoding = "gb18030"

    if encoding == "utf-8":
        out = text.encode("gb18030")
    else:
        out = raw
    out = to_crlf(out)
    path.write_bytes(out)
    return encoding


def main():
    if len(sys.argv) != 2:
        print("用法: python convert_gbk.py <脚本目录>")
        return 2
    root = Path(sys.argv[1])
    if not root.is_dir():
        print(f"目录不存在: {root}")
        return 2

    files = sorted(root.glob("**/*.ini"))
    if not files:
        print("未找到 .ini 文件")
        return 1

    converted = skipped = 0
    for f in files:
        enc = convert_ini(f)
        if enc == "utf-8":
            converted += 1
        else:
            skipped += 1
        raw = f.read_bytes()
        ok_bom = not raw.startswith(b"\xef\xbb\xbf")
        ok_crlf = raw.count(b"\r\n") == raw.count(b"\n")
        status = "OK" if (ok_bom and ok_crlf) else "BAD"
        print(f"{status} [{enc:8s}] {f.name}")
        if status == "BAD":
            print(f"   BOM={not ok_bom} 非CRLF={not ok_crlf}")

    print(f"---- 完成: 转码 {converted} 个, 跳过(已GBK) {skipped} 个 ----")
    return 0


if __name__ == "__main__":
    sys.exit(main())
