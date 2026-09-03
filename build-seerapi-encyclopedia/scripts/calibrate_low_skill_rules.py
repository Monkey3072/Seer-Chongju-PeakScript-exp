# -*- coding: utf-8 -*-
"""
分析精灵技能分布，用于校准"低级技能"过滤阈值。

用法:
    python calibrate_low_skill_rules.py --db <sqlite路径> --filter <清单txt路径>

会输出不同解锁等级下的技能数量统计，以及按候选规则命中的技能清单，
便于人工确认过滤规则是否过严/过松。
"""

import argparse
import re
import sqlite3
from pathlib import Path


def parse_args():
    parser = argparse.ArgumentParser(description="分析低级技能分布")
    parser.add_argument("--db", required=True, help="seerapi-data.sqlite 路径")
    parser.add_argument("--filter", required=True, help="筛选清单 txt 路径")
    parser.add_argument("--max-level", type=int, default=15, help="候选规则的解锁等级上限（默认15）")
    return parser.parse_args()


def load_pet_ids(filter_path: Path):
    text = filter_path.read_text(encoding="utf-8")
    ids = []
    for line in text.splitlines():
        m = re.match(r"^(\d+)\s*-\s*(.+)$", line.strip())
        if m:
            ids.append(int(m.group(1)))
    return ids


def main():
    args = parse_args()
    con = sqlite3.connect(args.db)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    def effect_lines(skill_id):
        info = cur.execute("SELECT info FROM skill WHERE id = ?", (skill_id,)).fetchone()["info"]
        cnt = cur.execute(
            """
            SELECT COUNT(*) FROM skilleffectlink l
            JOIN skill_effect_in_use e ON e.id = l.effect_in_use_id
            WHERE l.skill_id = ? AND e.info IS NOT NULL AND e.info != ''
            """,
            (skill_id,),
        ).fetchone()[0]
        return (1 if info else 0) + cnt

    rows = []
    for pid in load_pet_ids(Path(args.filter)):
        skill_rows = cur.execute(
            """
            SELECT sp.pet_id, sp.learning_level, sp.is_special, sp.is_advanced, sp.is_fifth,
                   s.id, s.name, s.power, s.max_pp, s.accuracy, s.priority, s.must_hit,
                   s.category_id
            FROM skillinpetorm sp JOIN skill s ON s.id = sp.skill_id
            WHERE sp.pet_id = ?
            """,
            (pid,),
        ).fetchall()
        for r in skill_rows:
            row = dict(r)
            row["effect_lines"] = effect_lines(r["id"])
            rows.append(row)

    print(f"技能总数: {len(rows)}")
    for lvl in (5, 10, 15, 20, 25, 30):
        sub = [r for r in rows if r["learning_level"] <= lvl]
        print(
            f"解锁等级<={lvl}: {len(sub)} | 先制=0: {sum(1 for r in sub if r['priority']==0)} | "
            f"效果行=0: {sum(1 for r in sub if r['effect_lines']==0)}"
        )

    def is_low_level(r):
        return (
            r["learning_level"] <= args.max_level
            and r["priority"] == 0
            and r["effect_lines"] == 0
            and r["category_id"] in (1, 2)
            and 30 <= (r["power"] or 0) <= 70
            and not r["must_hit"]
            and not r["is_special"]
            and not r["is_advanced"]
            and not r["is_fifth"]
        )

    cand = [r for r in rows if is_low_level(r)]
    cand.sort(key=lambda r: (r["learning_level"], r["name"]))
    print(
        f"\n规则命中: {len(cand)} 个技能，涉及 {len(set(r['pet_id'] for r in cand))} 只精灵"
    )
    for r in cand[:60]:
        print(
            f"  L{r['learning_level']:>3} {r['name']:<14} 威力{r['power']} "
            f"命中{r['accuracy']} 必中{int(r['must_hit'])}"
        )
    names = sorted(set(r["name"] for r in cand))
    print(f"\n命中技能名共 {len(names)} 种: {', '.join(names)}")
    con.close()


if __name__ == "__main__":
    main()
