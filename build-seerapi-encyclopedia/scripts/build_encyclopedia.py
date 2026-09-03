# -*- coding: utf-8 -*-
"""
从 SeerAPI 官方 SQLite 数据库构建《赛尔号》精灵文本图鉴。

用法:
    python build_encyclopedia.py --db <sqlite路径> --filter <清单txt路径> --output <输出txt路径>

数据来源: https://github.com/SeerAPI/api-data (MIT License)
输出字段: 名称、ID、属性、性别、种族值、魂印、技能(含技能ID)与技能描述
（不含"图鉴"与"简介"条目）
"""

import argparse
import re
import sqlite3
from datetime import datetime
from pathlib import Path


# 数据库中性别名为英文，转换为中文
GENDER_MAP = {
    "genderless": "无性别",
    "male": "雄性",
    "female": "雌性",
}

# 神谕/觉醒关键词：同名精灵查重时优先保留的形态
AWAKEN_KEYWORDS = ("神谕", "觉醒")


def parse_args():
    parser = argparse.ArgumentParser(description="构建赛尔号精灵文本图鉴")
    parser.add_argument("--db", required=True, help="seerapi-data.sqlite 路径")
    parser.add_argument("--filter", required=True, help="筛选清单 txt 路径（ID-名称，按行）")
    parser.add_argument("--output", required=True, help="输出 txt 路径")
    parser.add_argument("--max-level", type=int, default=15, help="低级技能解锁等级上限（默认15）")
    parser.add_argument("--min-power", type=int, default=30, help="低级技能威力下限（默认30）")
    parser.add_argument("--max-power", type=int, default=70, help="低级技能威力上限（默认70）")
    return parser.parse_args()


def parse_filter_list(text: str):
    """解析筛选清单，返回 (分组列表, 精灵列表)。

    文件格式: "ID-名称" 为精灵条目；其余非空行为分组标题。
    """
    groups = []          # [(标题, [(id, 名称), ...]), ...]
    pets = []            # 扁平列表 [(id, 名称)]
    current_title = "未分组"
    current_pets = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = re.match(r"^(\d+)\s*-\s*(.+)$", line)
        if match:
            pid = int(match.group(1))
            name = match.group(2).strip()
            current_pets.append((pid, name))
            pets.append((pid, name))
        else:
            if current_pets:
                groups.append((current_title, current_pets))
            current_title = line
            current_pets = []
    if current_pets:
        groups.append((current_title, current_pets))
    return groups, pets


class EncyclopediaBuilder:
    """从 SQLite 读取精灵图鉴数据并格式化为文本。"""

    def __init__(self, db_path: Path, max_level: int, min_power: int, max_power: int):
        self.con = sqlite3.connect(str(db_path))
        self.con.row_factory = sqlite3.Row
        self.cur = self.con.cursor()
        self.max_level = max_level
        self.min_power = min_power
        self.max_power = max_power
        self.removed_skill_names = set()
        self.removed_skill_count = 0
        self.empty_after_filter = []

    def close(self):
        self.con.close()

    def get_pet_base(self, pid: int):
        """精灵基础信息：名称、属性、性别。"""
        return self.cur.execute(
            """
            SELECT p.id, p.name, ec.name AS type_name, g.name AS gender_name
            FROM pet p
            JOIN element_type_combination ec ON ec.id = p.type_id
            JOIN pet_gender g ON g.id = p.gender_id
            WHERE p.id = ?
            """,
            (pid,),
        ).fetchone()

    def get_base_stats(self, pid: int):
        """种族值六维。"""
        return self.cur.execute(
            """
            SELECT hp, atk, def, sp_atk, sp_def, spd
            FROM pet_base_stats WHERE id = ?
            """,
            (pid,),
        ).fetchone()

    def get_soulmarks(self, pid: int):
        """魂印：直接关联 + 进化/超进化关联，按 id 去重。"""
        rows = self.cur.execute(
            """
            SELECT sm.id, sm.desc
            FROM petsoulmarklink l JOIN soulmark sm ON sm.id = l.soulmark_id
            WHERE l.pet_id = ?
            """,
            (pid,),
        ).fetchall()
        soulmark_ids = {row["id"]: row["desc"] for row in rows}
        adv_rows = self.cur.execute(
            "SELECT soulmark_id FROM pet_advance WHERE pet_id = ?",
            (pid,),
        ).fetchall()
        for adv in adv_rows:
            sid = adv["soulmark_id"]
            if sid is not None and sid not in soulmark_ids:
                row = self.cur.execute(
                    "SELECT id, desc FROM soulmark WHERE id = ?", (sid,)
                ).fetchone()
                if row:
                    soulmark_ids[row["id"]] = row["desc"]
        return soulmark_ids.values()

    def get_skills(self, pid: int):
        """精灵的全部技能：等级、名称、分类、属性、数值与效果描述（已过滤低级技能）。"""
        rows = self.cur.execute(
            """
            SELECT sp.learning_level, sp.is_special, sp.is_advanced, sp.is_fifth,
                   s.id, s.name, s.power, s.max_pp, s.accuracy, s.priority,
                   s.crit_rate, s.must_hit, s.info, s.category_id,
                   sc.name AS category_name, ec.name AS type_name
            FROM skillinpetorm sp
            JOIN skill s ON s.id = sp.skill_id
            JOIN skill_category sc ON sc.id = s.category_id
            JOIN element_type_combination ec ON ec.id = s.type_id
            WHERE sp.pet_id = ?
            ORDER BY sp.learning_level, sp.skill_id
            """,
            (pid,),
        ).fetchall()

        skills = []
        for row in rows:
            effects = self.get_skill_effects(row["id"])
            if self.is_low_level_skill(row, effects):
                self.removed_skill_count += 1
                self.removed_skill_names.add(row["name"])
                continue
            skills.append({"row": row, "effects": effects})
        return skills

    def is_low_level_skill(self, row, effects):
        """保守判断"低级技能"：同时满足以下条件才删除，否则保留。

        - 解锁等级 <= max_level
        - 无先制等级
        - 没有任何效果描述（技能自身说明 + 效果表均为空）
        - 是普通攻击技能（物理/特殊，排除属性技能）
        - 威力在 min_power~max_power 之间
        - 非必中，且不是特训/神谕/第五技能
        """
        return (
            row["learning_level"] <= self.max_level
            and row["priority"] == 0
            and not row["info"]
            and len(effects) == 0
            and row["category_id"] in (1, 2)
            and self.min_power <= (row["power"] or 0) <= self.max_power
            and not row["must_hit"]
            and not row["is_special"]
            and not row["is_advanced"]
            and not row["is_fifth"]
        )

    def get_skill_effects(self, skill_id: int):
        """技能效果描述（按效果顺序、去重）。"""
        rows = self.cur.execute(
            """
            SELECT DISTINCT e.info
            FROM skilleffectlink l
            JOIN skill_effect_in_use e ON e.id = l.effect_in_use_id
            WHERE l.skill_id = ?
              AND e.info IS NOT NULL AND e.info != ''
            ORDER BY l.effect_in_use_id
            """,
            (skill_id,),
        ).fetchall()
        return [row["info"] for row in rows]

    @staticmethod
    def format_stats(stats):
        if stats is None:
            return "无数据"
        values = [
            stats["hp"], stats["atk"], stats["def"],
            stats["sp_atk"], stats["sp_def"], stats["spd"],
        ]
        total = sum(v for v in values if v is not None)
        return (
            f"体力 {stats['hp']} ／ 攻击 {stats['atk']} ／ 防御 {stats['def']} ／ "
            f"特攻 {stats['sp_atk']} ／ 特防 {stats['sp_def']} ／ 速度 {stats['spd']} ／ "
            f"总和 {total}"
        )

    @staticmethod
    def format_skill(skill):
        row = skill["row"]
        parts = [f"{row['category_name']}·{row['type_name']}"]
        if row["power"] is not None:
            parts.append(f"威力 {row['power']}")
        if row["max_pp"] is not None:
            parts.append(f"PP {row['max_pp']}")
        if row["accuracy"] is not None:
            parts.append(f"命中 {row['accuracy']}%")
        if row["priority"]:
            parts.append(f"先制+{row['priority']}" if row["priority"] > 0 else f"先制{row['priority']}")
        if row["must_hit"]:
            parts.append("必中")
        if row["crit_rate"]:
            parts.append(f"暴击率 {row['crit_rate']}")

        marks = []
        if row["is_fifth"]:
            marks.append("第五技能")
        if row["is_special"]:
            marks.append("特训")
        if row["is_advanced"]:
            marks.append("神谕")

        desc_parts = []
        if row["info"]:
            desc_parts.append(row["info"])
        desc_parts.extend(skill["effects"])

        line = f"{row['learning_level']}级 {row['name']}-{row['id']}（{', '.join(parts)}）"
        if marks:
            line += f"【{'/'.join(marks)}】"
        for desc in desc_parts:
            line += f"\n      描述：{desc}"
        return line

    @staticmethod
    def format_soulmark(desc_text: str):
        """魂印描述按 | 分段输出为多行。"""
        if not desc_text:
            return None
        parts = [p.strip() for p in desc_text.split("|") if p.strip()]
        return "\n".join(f"      · {p}" for p in parts)

    def build_pet(self, pid: int, listed_name: str):
        """生成单只精灵的图鉴文本；返回 None 表示未在数据库中找到。"""
        base = self.get_pet_base(pid)
        if base is None:
            return None

        stats = self.get_base_stats(pid)
        soulmarks = list(self.get_soulmarks(pid))
        skills = self.get_skills(pid)

        lines = []
        name_part = base["name"]
        if listed_name != base["name"]:
            name_part += f"（清单名：{listed_name}）"
        lines.append(f"\n【{base['id']}】{name_part}")
        lines.append(f"  属性：{base['type_name']}")
        lines.append(f"  性别：{GENDER_MAP.get(base['gender_name'], base['gender_name'])}")
        lines.append(f"  种族值：{self.format_stats(stats)}")

        if soulmarks:
            lines.append("  魂印：")
            for sm in soulmarks:
                formatted = self.format_soulmark(sm)
                if formatted:
                    lines.append(formatted)
        else:
            lines.append("  魂印：无")

        if skills:
            lines.append("  技能：")
            for skill in skills:
                lines.append("    " + self.format_skill(skill))
        else:
            original_count = self.cur.execute(
                "SELECT COUNT(*) FROM skillinpetorm WHERE pet_id = ?", (pid,)
            ).fetchone()[0]
            if original_count:
                self.empty_after_filter.append((pid, base["name"]))
            lines.append("  技能：无")

        return "\n".join(lines)


def resolve_duplicates(builder: EncyclopediaBuilder, all_pets):
    """同名精灵查重：仅保留神谕/觉醒后的词条，否则保留 ID 较大者。

    返回 (保留的 pid 集合, 被丢弃的 [(pid, 名称)] 列表)。
    """
    name_to_ids = {}
    for pid, _ in all_pets:
        base = builder.get_pet_base(pid)
        if base is not None:
            name_to_ids.setdefault(base["name"], []).append((pid, base["name"]))

    keep = set()
    dropped = []
    for name, entries in name_to_ids.items():
        if len(entries) == 1:
            keep.add(entries[0][0])
            continue
        # 优先保留名称含"神谕/觉醒"的形态，否则保留 ID 最大者
        awakened = [e for e in entries if any(k in e[1] for k in AWAKEN_KEYWORDS)]
        chosen = max(awakened or entries, key=lambda e: e[0])
        keep.add(chosen[0])
        dropped.extend(e for e in entries if e[0] != chosen[0])
    return keep, dropped


def main():
    args = parse_args()
    filter_path = Path(args.filter)
    output_path = Path(args.output)

    filter_text = filter_path.read_text(encoding="utf-8")
    groups, all_pets = parse_filter_list(filter_text)

    builder = EncyclopediaBuilder(Path(args.db), args.max_level, args.min_power, args.max_power)
    try:
        keep_ids, dropped = resolve_duplicates(builder, all_pets)

        output_lines = []
        output_lines.append("=" * 60)
        output_lines.append("赛尔号 精灵文本图鉴")
        output_lines.append("数据来源：SeerAPI 官方数据库（github.com/SeerAPI/api-data，MIT License）")
        output_lines.append(f"筛选清单：{filter_path.name}")
        output_lines.append(f"提取时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}")
        output_lines.append(
            f"技能过滤：仅删除解锁<={args.max_level}级、无先制、无效果描述、威力"
            f"{args.min_power}~{args.max_power}的普通攻击技能（保守策略，无法确认的技能保留）"
        )

        found = 0
        missing = []
        for title, pet_list in groups:
            lines = [f"\n[ {title} ]", "=" * 60]
            for pid, listed_name in pet_list:
                if pid not in keep_ids:
                    continue
                text = builder.build_pet(pid, listed_name)
                if text is not None:
                    lines.append(text)
                    found += 1
                else:
                    missing.append((pid, listed_name))
            if len(lines) > 2:
                output_lines.extend(lines)

        output_lines.append("\n" + "=" * 60)
        output_lines.append(f"统计：清单精灵 {len(all_pets)} 只，成功提取 {found} 只，未找到 {len(missing)} 只。")
        removed_names = sorted(builder.removed_skill_names)
        output_lines.append(
            f"低级技能过滤：共删除 {builder.removed_skill_count} 个技能（{len(removed_names)} 种），"
            f"例如：{'、'.join(removed_names[:20])}"
        )
        if dropped:
            output_lines.append(f"查重：同名精灵仅保留神谕/觉醒后词条，丢弃 {len(dropped)} 条：")
            output_lines.extend(f"  {pid}-{name}" for pid, name in dropped)
        if missing:
            output_lines.append("未找到的精灵：")
            output_lines.extend(f"  {pid}-{name}" for pid, name in missing)
        if builder.empty_after_filter:
            output_lines.append("警告：以下精灵过滤后技能为空（原始有技能）：")
            output_lines.extend(f"  {pid}-{name}" for pid, name in builder.empty_after_filter)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("\n".join(output_lines) + "\n", encoding="utf-8")

        # 输出后校验：精灵数与种族值/魂印行数一致、ID 无重复
        text = output_path.read_text(encoding="utf-8")
        pet_count = len(re.findall(r"^【\d+】", text, flags=re.M))
        stat_count = len(re.findall(r"^\s+种族值：", text, flags=re.M))
        soul_count = len(re.findall(r"^\s+魂印：", text, flags=re.M))
        ids = re.findall(r"^【(\d+)】", text, flags=re.M)
        id_dup = len(ids) != len(set(ids))

        print(f"输出完成: {output_path}")
        print(f"清单精灵: {len(all_pets)}，成功: {found}，未找到: {len(missing)}")
        print(f"低级技能过滤: 删除 {builder.removed_skill_count} 个（{len(removed_names)} 种）")
        if dropped:
            print(f"查重丢弃: {len(dropped)} 条")
        print(f"校验: 精灵 {pet_count} | 种族值行 {stat_count} | 魂印行 {soul_count} | ID重复 {id_dup}")
        if pet_count != stat_count or pet_count != soul_count or id_dup:
            print("警告: 输出校验未通过，请检查!")
        if builder.empty_after_filter:
            print(f"警告: {len(builder.empty_after_filter)} 只精灵过滤后技能为空")
        for pid, name in missing:
            print(f"  缺失: {pid}-{name}")
    finally:
        builder.close()


if __name__ == "__main__":
    main()
