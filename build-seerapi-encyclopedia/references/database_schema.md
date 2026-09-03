# SeerAPI 数据库核心表结构

数据源：`seerapi-data.sqlite`（github.com/SeerAPI/api-data，MIT License，112 张表）。
本文件仅列出构建精灵图鉴所需的核心表；字段与关联关系已逐项对照数据库核实。调整输出字段时以此为据。

## 精灵本体

### pet（精灵主表）

| 字段 | 说明 |
|---|---|
| id | 精灵 ID（即图鉴 ID） |
| name | 精灵名称 |
| type_id | 属性组合 id → element_type_combination |
| gender_id | 性别 id → pet_gender |
| pet_class_id | 精灵分类 id → pet_class |
| base_stats_id | 种族值 id → pet_base_stats（= pet.id） |
| yielding_ev_id | 努力值 id → pet_yielding_ev |
| resource_id / enemy_resource_id | 客户端资源 ID |

### pet_base_stats（种族值）

`hp, atk, def, sp_atk, sp_def, spd, percent`，`id` 与 `pet.id` 一致。
总和 = 六维之和。

### pet_encyclopedia_entry（图鉴条目，默认不使用）

`id`（= pet.id）、`name`、`has_sound`、`height`、`weight`、`foundin`、`food`、`introduction`。
按需求生成文本图鉴时默认**不输出**图鉴与简介条目。

### pet_class（精灵分类）

`is_variant_pet`（异能）、`is_dark_pet`（暗黑）、`is_shine_pet`（闪光）、
`is_rare_pet`（稀有）、`is_breeding_pet`（繁殖）、`is_fusion_pet`（融合）。

## 属性与性别

### element_type_combination（属性组合）

`id, name, name_en, primary_id, secondary_id`。精灵的 `type_id` 指向此表，`name` 即显示属性。

### element_type（单属性）

`id, name, name_en`。单属性名；技能的类型**实际指向 `element_type_combination`**（`skill.type_id → element_type_combination.id`），
`element_type` 仅作为组合表 `primary_id/secondary_id` 指向的单属性字典，勿直接用于技能取类型。

### pet_gender（性别）

`id, name`（`0=genderless`/`1=male`/`2=female`，脚本中已映射为中文）。

## 魂印

### soulmark

`id, desc, analyze_desc, pve_effective, intensified, is_adv, intensified_to_id`。
`desc` 为干净文本，多个效果用 `|` 分段；`analyze_desc` 含颜色/sprite 标记，勿直接输出。

### petsoulmarklink（精灵-魂印关联）

`pet_id, soulmark_id`。一只精灵可有多个魂印。

### pet_advance（进化/超进化附加）

`id, pet_id, soulmark_id`。某些精灵的魂印经由进化/超进化关联，提取时应合并去重。

## 技能

### skill（技能主表）

| 字段 | 说明 |
|---|---|
| id | 技能 ID（输出为"技能名-ID"） |
| name | 技能名 |
| power | 威力（属性技能为 0） |
| max_pp | PP 上限 |
| accuracy | 命中率（%） |
| priority | 先制等级（正为先制+，负为先制-） |
| crit_rate | 暴击率（%） |
| must_hit | 是否必中 |
| info | 技能自带文字说明（可为空） |
| category_id | 分类 → skill_category（1=物理攻击, 2=特殊攻击, 4=属性技能） |
| type_id | 属性 → element_type |

### skillinpetorm（精灵-技能关联）

`pet_id, skill_id, learning_level, is_special, is_advanced, is_fifth, skill_activation_item_id`。
神谕技能 `learning_level=0`。`is_fifth`=第五技能，`is_special`=特训，`is_advanced`=神谕。

### skill_category（技能分类）

`1=物理攻击, 2=特殊攻击, 4=属性技能`。

### skilleffectlink + skill_effect_in_use（技能效果）

`skilleffectlink(skill_id, effect_in_use_id)` → `skill_effect_in_use(id, info, analyze_info, args, effect_id)`。
效果描述取 `info`（干净文本，按 effect_in_use_id 排序去重）。

## 常用关联关系速查

- 精灵属性：`pet.type_id → element_type_combination.id`
- 精灵种族值：`pet.base_stats_id → pet_base_stats.id`（数值上等于 pet.id）
- 精灵魂印：`petsoulmarklink.pet_id → soulmark.id`，另查 `pet_advance.pet_id → soulmark.id`
- 精灵技能：`skillinpetorm.pet_id → skill.id`，按 `learning_level, skill_id` 排序
- 技能描述：`skill.info` + `skilleffectlink → skill_effect_in_use.info`
