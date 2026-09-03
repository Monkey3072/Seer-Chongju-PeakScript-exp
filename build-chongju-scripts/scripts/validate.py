#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""重聚巅峰脚本三件套校验器。

用法:
    python validate.py <脚本目录>

脚本目录需包含: BP.ini(或 banpick.ini)、切换.ini、精灵出招/ 文件夹。
退出码: 0 = 无 ERROR; 1 = 存在 ERROR; 2 = 用法错误。
"""

import re
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

PET_SECTIONS = {"循环", "登场", "中切登场", "死切登场", "击杀", "中切特判登场"}
SWITCH_GLOBAL = {"死亡切换", "击杀切走", "切走"}
ACTION_WORDS = {"切走", "特判切走", "hp", "pp"}
ACTION_CODES = {"5", "0", "1000001"}  # 样本实测出现、手册未定义的动作码
SWITCH_LIKE = {"切走", "特判切走"}
ID4 = re.compile(r"^\d{4}$")
ID5 = re.compile(r"^\d{5}$")
NAME = re.compile(r"^[\u4e00-\u9fffA-Za-z0-9·]+$")


def decode_ini(path):
    raw = path.read_bytes()
    problems = []
    if raw[:3] == b"\xef\xbb\xbf":
        problems.append("ERROR: 带 UTF-8 BOM")
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        problems.append("ERROR: 带 UTF-16 BOM")
    try:
        raw.decode("utf-8", errors="strict")
        if any(b >= 0x80 for b in raw):
            problems.append("ERROR: 疑似 UTF-8 编码（规范为 ANSI/GBK）")
    except UnicodeDecodeError:
        pass
    text = raw.decode("gb18030", errors="replace")
    if "\ufffd" in text:
        problems.append("ERROR: 存在无法用 ANSI/GBK 解码的字符")
    crlf = raw.count(b"\r\n")
    lf = raw.count(b"\n") - crlf
    if lf:
        problems.append(f"WARNING: 存在 {lf} 个仅 LF 换行（规范为 CRLF）")
    return text, problems


def parse_ini(text):
    sections = {}
    problems = []
    cur = None
    for lineno, line in enumerate(text.splitlines(), 1):
        s = line.strip()
        if not s:
            continue
        m = re.match(r"^\[(.+)\]$", s)
        if m:
            cur = m.group(1).strip()
            sections.setdefault(cur, [])
            continue
        if "=" not in s:
            problems.append(f"ERROR: 行 {lineno} 缺少 '=' : {s}")
            continue
        if cur is None:
            problems.append(f"ERROR: 行 {lineno} 键值出现在区块外 : {s}")
            continue
        k, v = (x.strip() for x in s.split("=", 1))
        sections[cur].append((lineno, k, v))
    return sections, problems


def tokens(value):
    return value.split()


def warn_dup(seq, where, problems):
    seen = set()
    for t in seq:
        if t in seen:
            problems.append(f"WARNING: {where} 出现重复项 {t}")
        seen.add(t)


def check_pet_key(k, where, problems):
    if k in ("技能", "默认") or ID4.match(k):
        return
    if NAME.match(k):
        problems.append(f"WARNING: {where} 名称作特判键未在手册确认（建议用 4 位精灵 ID）")
    else:
        problems.append(f"ERROR: {where} 键格式错误 {k}")


def check_switch_key(k, where, problems):
    if k == "默认" or ID4.match(k):
        return
    if NAME.match(k):
        problems.append(f"WARNING: {where} 名称作键未在手册确认（建议用 4 位精灵 ID）")
    else:
        problems.append(f"ERROR: {where} 键格式错误 {k}")


def check_action_tokens(seq, where, problems):
    for t in seq:
        if t in ACTION_WORDS or t in ACTION_CODES or ID5.match(t):
            continue
        if t in ("HP", "PP"):
            problems.append(f"ERROR: {where} 吃药必须小写 hp/pp，收到 {t}")
            continue
        if ID4.match(t):
            problems.append(f"ERROR: {where} 动作序列出现 4 位精灵 ID {t}（此处应为 5 位技能 ID）")
        elif re.fullmatch(r"\d+", t):
            problems.append(f"ERROR: {where} 非法数字 token {t}")
        else:
            problems.append(f"ERROR: {where} 未知动作 {t}")


def check_switch_value_tokens(value, where, problems):
    for t in tokens(value):
        if ID4.match(t):
            continue
        if ID5.match(t):
            problems.append(f"ERROR: {where} 切换队列出现 5 位技能 ID {t}（此处应为精灵 ID）")
        elif NAME.match(t) or t == "默认":
            continue
        else:
            problems.append(f"WARNING: {where} 无法识别的精灵标识 {t}")


def check_sequence_rules(seq, section, where, problems, default_key=False):
    if len(seq) <= 1:
        if section == "循环" and seq and seq[0] in SWITCH_LIKE:
            if default_key:
                problems.append(f"ERROR: {where} 循环默认行单独一个切换动作会空过")
            else:
                problems.append(f"WARNING: {where} 循环特判行只有切换动作，切换失败可能空过")
        return
    for i in range(len(seq) - 1):
        if seq[i] in SWITCH_LIKE and seq[i + 1] in SWITCH_LIKE:
            problems.append(f"ERROR: {where} 切换动作相邻")
    if section == "循环" and seq[0] in SWITCH_LIKE and seq[-1] in SWITCH_LIKE:
        problems.append(f"ERROR: {where} 循环首尾均为切换动作（首尾相接）")


def validate_bp(sections, problems):
    if "BP" not in sections:
        problems.append("ERROR: 缺少 [BP] 区块")
        return
    keys = {k for _, k, _ in sections["BP"]}
    for need in ("首发", "出战"):
        if need not in keys:
            problems.append(f"ERROR: [BP] 缺少 {need}=")
    first = None
    team = None
    for _, k, v in sections["BP"]:
        if k == "首发":
            first = tokens(v)
            warn_dup(first, "[BP] 首发", problems)
        elif k == "出战":
            team = set(tokens(v))
            warn_dup(tokens(v), "[BP] 出战", problems)
        elif k == "禁用":
            continue
        else:
            problems.append(f"ERROR: [BP] 出现未知键 {k}")
    if first is not None and team is not None:
        for pid in first:
            if ID4.match(pid) and pid not in team:
                problems.append(f"WARNING: 首发 {pid} 不在出战列表中")
    cond_order = []
    for sec_name in sections:
        if sec_name == "BP":
            continue
        parts = sec_name.split("/")
        if not (1 <= len(parts) <= 3):
            problems.append(f"ERROR: 条件节 {sec_name} 条件数必须为 1~3")
            continue
        cond_order.append((sec_name, len(parts)))
        keys = {k for _, k, _ in sections[sec_name]}
        if "首发" not in keys or "出战" not in keys:
            problems.append(f"WARNING: 条件节 {sec_name} 建议同时写 首发 与 出战")
        for _, k, _ in sections[sec_name]:
            if k not in ("首发", "出战"):
                problems.append(f"ERROR: 条件节 {sec_name} 出现未知键 {k}")
    if cond_order:
        counts = [n for _, n in cond_order]
        if counts != sorted(counts, reverse=True):
            problems.append("WARNING: 条件节建议按 3→2→1 条件数从多到少排列")


def validate_switch(sections, problems):
    for sec_name in sections:
        if sec_name in SWITCH_GLOBAL or re.fullmatch(r"[ST]\d{4}", sec_name) or ID4.match(sec_name):
            continue
        problems.append(f"ERROR: 切换.ini 出现未知区块 [{sec_name}]")

    if "切走" not in sections:
        problems.append("ERROR: 切换.ini 缺少 [切走]")
    else:
        if not any(k == "默认" for _, k, _ in sections["切走"]):
            problems.append("ERROR: [切走] 缺少 默认=")
        for _, k, v in sections["切走"]:
            check_switch_key(k, f"[切走] {k}", problems)
            check_switch_value_tokens(v, f"[切走] {k}", problems)

    if "死亡切换" not in sections:
        problems.append("ERROR: 切换.ini 缺少 [死亡切换]")
    else:
        if not any(k == "默认" for _, k, _ in sections["死亡切换"]):
            problems.append("ERROR: [死亡切换] 缺少 默认=")
        for _, k, v in sections["死亡切换"]:
            check_switch_key(k, f"[死亡切换] {k}", problems)
            check_switch_value_tokens(v, f"[死亡切换] {k}", problems)

    if "击杀切走" in sections:
        keys = [k for _, k, _ in sections["击杀切走"]]
        if "默认>默认" not in keys:
            problems.append("ERROR: [击杀切走] 缺少 默认>默认=（可能卡出招）")
        for _, k, v in sections["击杀切走"]:
            m = re.match(r"^(默认|[^>=\s]+)>(默认|[^>=\s]+)$", k)
            if not m:
                problems.append(f"ERROR: [击杀切走] 键格式错误 {k}")
                continue
            for side in m.groups():
                if side != "默认" and not ID4.match(side) and NAME.match(side):
                    problems.append(f"WARNING: [击杀切走] {k} 名称作键未在手册确认（建议用 ID）")
            check_switch_value_tokens(v, f"[击杀切走] {k}", problems)

    for sec_name in sections:
        if re.fullmatch(r"[ST]\d{4}", sec_name) or ID4.match(sec_name):
            for _, k, v in sections[sec_name]:
                check_switch_key(k, f"[{sec_name}] {k}", problems)
                check_switch_value_tokens(v, f"[{sec_name}] {k}", problems)


def validate_pet_file(pet_path, problems):
    text, dp = decode_ini(pet_path)
    problems.extend(f"{pet_path.name}: {p}" for p in dp)
    if any(p.startswith("ERROR") for p in dp):
        return
    sections, pp = parse_ini(text)
    problems.extend(f"{pet_path.name}: {p}" for p in pp)
    for sec_name in sections:
        if sec_name not in PET_SECTIONS:
            problems.append(f"ERROR: {pet_path.name} 出现未知区块 [{sec_name}]")
            continue
        for lineno, k, v in sections[sec_name]:
            where = f"{pet_path.name}:{lineno} [{sec_name}] {k}"
            check_pet_key(k, where, problems)
            seq = tokens(v)
            if not seq:
                problems.append(f"WARNING: {where} 值为空")
                continue
            check_action_tokens(seq, where, problems)
            check_sequence_rules(seq, sec_name, where, problems, default_key=(k in ("技能", "默认")))
            if sec_name == "击杀" and len(seq) > 1:
                problems.append(f"ERROR: {where} 击杀技只能写一招")


def validate(root):
    root = Path(root)
    if not root.is_dir():
        print(f"ERROR: 目录不存在 {root}")
        return 1
    bp = root / "BP.ini"
    if not bp.exists():
        bp = root / "banpick.ini"
    switch = root / "切换.ini"
    pet_dir = root / "精灵出招"
    problems = []
    if not bp.exists():
        problems.append("ERROR: 缺少 BP.ini 或 banpick.ini")
    if not switch.exists():
        problems.append("ERROR: 缺少 切换.ini")
    if not pet_dir.is_dir():
        problems.append("ERROR: 缺少 精灵出招 文件夹")

    if bp.exists():
        text, dp = decode_ini(bp)
        problems.extend(f"BP.ini: {p}" for p in dp)
        if not any(p.startswith("ERROR") for p in dp):
            sections, pp = parse_ini(text)
            problems.extend(f"BP.ini: {p}" for p in pp)
            validate_bp(sections, problems)

    if switch.exists():
        text, dp = decode_ini(switch)
        problems.extend(f"切换.ini: {p}" for p in dp)
        if not any(p.startswith("ERROR") for p in dp):
            sections, pp = parse_ini(text)
            problems.extend(f"切换.ini: {p}" for p in pp)
            validate_switch(sections, problems)

    if pet_dir.is_dir():
        files = sorted(pet_dir.glob("*.ini"))
        if not files:
            problems.append("WARNING: 精灵出招 文件夹为空")
        for f in files:
            validate_pet_file(f, problems)

    errors = [p for p in problems if "ERROR:" in p]
    warnings = [p for p in problems if "WARNING:" in p]
    for p in problems:
        print(p)
    print(f"---- 结果: ERROR {len(errors)} 个, WARNING {len(warnings)} 个 ----")
    return 1 if errors else 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("用法: python validate.py <脚本目录>")
        sys.exit(2)
    sys.exit(validate(sys.argv[1]))
