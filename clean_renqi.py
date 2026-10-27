# -*- coding: utf-8 -*-
"""【历史套件 · 五平台口径】人气交叉页面数据清洗：解析解码后的 HTML，输出标准化长表事实表 + 维度表 + 校验报告。

面向旧「五平台人气个股交叉识别」数据集（东方财富/淘股吧/同花顺/财联社/通达信），
与现行「八平台人气共振」日报管线（last_good.json -> 八平台人气共振_通达信排序指标.txt）无关；
平台列表与覆盖档位都是五平台口径，不随八平台升级调整。

产出：
  人气交叉_清洗_fact_rank.csv / .json   长表事实表（一行 = 一股票在一平台一榜单的一条记录）
  人气交叉_清洗_dim_stock.csv           个股维度表（含计算出的平台覆盖数）
  人气交叉_清洗_校验报告.md             数据校验结果
"""
import csv
import html as H
import json
import os
import re

# 所有输入/输出都在本脚本所在目录，随目录整体搬迁无需改路径
DIR = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(DIR, "_renqi_decoded.html")
OUT_DIR = DIR
PLATFORMS = ["东方财富", "淘股吧", "同花顺", "财联社", "通达信"]

# (平台, 榜单) -> 备注/指标列的语义
BOARD_SPEC = {
    ("东方财富", "人气榜"): "delta",
    ("淘股吧", "实时热搜"): "搜索",
    ("淘股吧", "24h热搜"): "搜索",
    ("同花顺", "1h热股"): "热度",
    ("同花顺", "24h热股"): "热度",
    ("财联社", "热榜"): "change",
    ("通达信", "人气榜"): "人气",
}
# 独立热点表中，各平台的默认榜单（名次列的归属）
DEFAULT_BOARD = {"东方财富": "人气榜", "财联社": "热榜", "通达信": "人气榜"}

# 标签别名归一（原文 -> 规范名）
TAG_ALIAS = {
    "CPO": "共封装光学(CPO)",
    "算力": "东数西算(算力)",
    "AIDC": "数据中心(AIDC)",
    "字节概念": "抖音概念(字节概念)",
}


def text(s):
    return re.sub(r"\s+", " ", H.unescape(re.sub(r"<[^>]+>", "", s))).strip()


def split_board(raw):
    """'淘股吧实时热搜' -> ('淘股吧', '实时热搜')"""
    for p in PLATFORMS:
        if raw.startswith(p):
            board = raw[len(p):].strip()
            return p, {"人气": "人气榜"}.get(board, board)
    return raw, ""


def parse_signed(s):
    """↑2/↓3/+1.75/-4.06 → float；'—'/'' → 0.0；其余 → None（并 round 消除浮点误差）"""
    s = s.strip()
    if s in ("", "—"):
        return 0.0
    m = re.match(r"^([↑↓+\-])\s*([\d.]+)$", s)
    if m:
        sign = -1 if m.group(1) in "↓-" else 1
        return round(sign * float(m.group(2)), 2)
    return None


def parse_metric(s):
    """'今日搜索 9 次' / '今日 26 次 / 7日 120 次' / '热度 88.0 万' / '人气 90 万' → (名称, 值, 单位, 附加)"""
    s = s.strip().lstrip("·").strip()
    if not s or s == "—":
        return None
    extra = ""
    m7 = re.search(r"7日\s*([\d.]+)\s*次", s)
    if m7:
        extra = f"7日 {m7.group(1)} 次"
    for pat, name, unit in (
        (r"^今日搜索\s*([\d.]+)\s*次", "搜索次数", "次"),
        (r"^今日\s*([\d.]+)\s*次", "搜索次数", "次"),
        (r"^热度\s*([\d.]+)\s*万", "热度", "万"),
        (r"^人气\s*([\d.]+)\s*万", "人气值", "万"),
        (r"^([\d.]+)\s*次$", "搜索次数", "次"),
    ):
        m = re.match(pat, s)
        if m:
            return name, float(m.group(1)), unit, extra
    return None


def parse_tag_cell(s):
    """'通信设备 共封装光学(CPO) 芯片概念' → (行业, 主标签, 辅标签)"""
    parts = [p for p in re.split(r"\s+", s.strip()) if p]
    parts += [""] * (3 - len(parts))
    return parts[0], parts[1], parts[2], (len(parts) if len(parts) > 3 else 0)


def norm_tag(t):
    return TAG_ALIAS.get(t, t)


# ============================ 解析 ============================
src = open(SRC, encoding="utf-8").read()
body = src.split("<body>", 1)[1]

head = {
    "title": text(re.search(r"<h1>(.*?)</h1>", body, re.S).group(1)),
    "subtitle": text(re.search(r'class="sub">(.*?)</div>', body, re.S).group(1)),
    "data_time": text(re.search(r"数据时间 <b>(.*?)</b>", body).group(1)),
}
DATE = head["data_time"].split()[0]
TIME = head["data_time"].split()[-1]

metrics = dict(
    (k, v) for v, k in re.findall(r'<div class="v">(.*?)</div><div class="k">(.*?)</div>', body)
)

facts = []
stocks = {}  # code -> dim
warnings = []


def add_fact(rec):
    facts.append(rec)


def upsert_stock(code, exchange, name, industry, ptag, atag, group, level):
    d = stocks.setdefault(
        code,
        {
            "代码": code,
            "交易所": exchange,
            "名称": name,
            "行业": industry or "",
            "主标签": ptag or "",
            "辅标签": atag or "",
            "分组": group,
            "共振级别": level or "",
        },
    )
    for k, v in (("行业", industry), ("主标签", ptag), ("辅标签", atag), ("名称", name)):
        if v and not d[k]:
            d[k] = v


# --- A. 共振股（spot 卡片） ---
for sec in re.finditer(
    r'<h([23])>([^<]*)</h\1>\s*<div class="cmt">(.*?)</div>(.*?)(?=<h[23]>|<div class="card"|<div class="note|</body>)',
    body,
    re.S,
):
    group = text(sec.group(2))
    for blk in re.split(r'(?=<div class="spot3?">)', sec.group(4))[1:]:
        nm = re.search(r'class="lk"[^>]*>([^<]+)</a>', blk)
        if not nm:
            continue
        name = text(nm.group(1))
        code_raw = re.search(r'class="spot-code">(\w+)<', blk).group(1)
        exchange, code = code_raw[:2], code_raw[2:]
        level = text(re.search(r'class="(?:top|tri|duo)">([^<]+)<', blk).group(1))
        pills = dict(re.findall(r'class="pill (\w+)">([^<]+)<', blk))
        industry, ptag, atag = pills.get("ind", ""), pills.get("main", ""), pills.get("aux", "")
        upsert_stock(code, exchange, name, industry, ptag, atag, group, level)

        for row in re.findall(r'class="ck">(.*?)</div>(?=<div class="ck">|</div>)', blk, re.S):
            m = re.search(r"</i>(.*?)<b>(.*?)</b>(.*)", row, re.S)
            if not m:
                continue
            platform, board = split_board(text(m.group(1)))
            rank = int(re.search(r"(\d+)", text(m.group(2))).group(1))
            note = text(m.group(3))
            spec = BOARD_SPEC.get((platform, board))
            rec = {
                "日期": DATE, "时间": TIME, "代码": code, "交易所": exchange, "名称": name,
                "平台": platform, "榜单": board, "名次": rank,
                "指标名": "", "指标值": "", "指标单位": "", "指标附加": "",
                "涨跌幅": "", "较昨日名次变化": "",
                "分组": group, "共振级别": level, "行业": industry,
                "主标签": ptag, "辅标签": atag,
                "主标签_规范": norm_tag(ptag), "辅标签_规范": norm_tag(atag),
                "来源": "共振",
            }
            if spec == "delta":
                rec["较昨日名次变化"] = parse_signed(note)
            elif spec == "change":
                rec["涨跌幅"] = parse_signed(note)
            else:
                pm = parse_metric(note)
                if pm:
                    rec["指标名"], rec["指标值"], rec["指标单位"], rec["指标附加"] = pm
                elif note and note != "—":
                    warnings.append(f"未识别的备注：{name} {platform}{board} = {note!r}")
                    rec["指标附加"] = note
            add_fact(rec)

# --- B. 独立热点（表格） ---
for card in re.findall(r'<div class="card"><h2>([^<]*)</h2>\s*<table>(.*?)</table>', body, re.S):
    title, table = card
    group = text(title)
    platform = next((p for p in PLATFORMS if p in group), None)
    cols = [text(x) for x in re.findall(r"<th[^>]*>(.*?)</th>", table, re.S)]
    for tr in re.findall(r"<tr>(?!<th)(.*?)</tr>", table, re.S):
        tds = [text(td) for td in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)]
        if not tds:
            continue
        cell = dict(zip(cols, tds))
        name = cell.get("个股", "")
        code_raw = cell.get("代码", "")
        exchange, code = (code_raw[:2], code_raw[2:]) if len(code_raw) > 6 else ("", code_raw)
        industry, ptag, atag, overflow = parse_tag_cell(cell.get("行业 · 主标签 · 辅标签", ""))
        if overflow:
            warnings.append(f"标签列拆分超出 3 段：{name} = {cell.get('行业 · 主标签 · 辅标签')!r}")
        upsert_stock(code, exchange, name, industry, ptag, atag, group, "独立热点")

        def base(board, rank):
            return {
                "日期": DATE, "时间": TIME, "代码": code, "交易所": exchange, "名称": name,
                "平台": platform, "榜单": board, "名次": rank,
                "指标名": "", "指标值": "", "指标单位": "", "指标附加": "",
                "涨跌幅": "", "较昨日名次变化": "",
                "分组": group, "共振级别": "独立热点", "行业": industry,
                "主标签": ptag, "辅标签": atag,
                "主标签_规范": norm_tag(ptag), "辅标签_规范": norm_tag(atag),
                "来源": "独立热点",
            }

        # 带榜单前缀的单元（实时/24h/1h）
        for col in ("实时热搜", "24h热搜", "1h热股", "24h热股"):
            v = cell.get(col, "")
            if not v or v == "—":
                continue
            m = re.match(r"^(实时|24h|1h)\s*第\s*(\d+)\s*名(?:\s*·\s*(.*))?$", v)
            if not m:
                warnings.append(f"未识别的榜单单元：{name} {col} = {v!r}")
                continue
            board = {"实时": "实时热搜", "24h": "24h热搜", "1h": "1h热股"}[m.group(1)]
            rec = base(board, int(m.group(2)))
            pm = parse_metric(m.group(3) or "")
            if pm:
                rec["指标名"], rec["指标值"], rec["指标单位"], rec["指标附加"] = pm
            add_fact(rec)

        # 纯名次列（东财/财联社/通达信）
        if cell.get("名次", "").isdigit():
            board = DEFAULT_BOARD[platform]
            rec = base(board, int(cell["名次"]))
            if "涨幅" in cell:
                rec["涨跌幅"] = parse_signed(cell["涨幅"])
            if "较昨日" in cell:
                rec["较昨日名次变化"] = parse_signed(cell["较昨日"])
            if "人气值" in cell:
                pm = parse_metric(cell["人气值"])
                if pm:
                    rec["指标名"], rec["指标值"], rec["指标单位"], rec["指标附加"] = pm
            add_fact(rec)

# --- 维度表补充：平台覆盖数 ---
for code, d in stocks.items():
    rows = [f for f in facts if f["代码"] == code]
    d["覆盖平台数"] = len(set(r["平台"] for r in rows))
    d["上榜条数"] = len(rows)
    d["覆盖平台"] = "/".join(sorted(set(r["平台"] for r in rows)))

# ============================ 校验 ============================
V = []
key_seen, dup = set(), []
for f in facts:
    k = (f["日期"], f["时间"], f["代码"], f["平台"], f["榜单"])
    if k in key_seen:
        dup.append(k)
    key_seen.add(k)

bad_rank = [f for f in facts if not (1 <= f["名次"] <= 20)]
bad_plat = [f for f in facts if f["平台"] not in PLATFORMS]
bad_code = [c for c in stocks if not re.fullmatch(r"\d{6}", c)]
SEG = {"SH": ("60", "68", "90"), "SZ": ("00", "30", "20", "15"), "BJ": ("43", "83", "87", "88", "92")}
bad_seg = [c for c, d in stocks.items() if not any(c.startswith(p) for p in SEG.get(d["交易所"], ()))]
bad_chg = [f for f in facts if f["涨跌幅"] != "" and not (-30 <= f["涨跌幅"] <= 30)]
no_tag = [c for c, d in stocks.items() if not d["行业"] or not d["主标签"]]

# 平台覆盖数 vs 指标卡
metric_map = {"东方财富": "东财人气", "淘股吧": "淘股吧上榜", "同花顺": "同花顺上榜",
              "财联社": "财联社热榜", "通达信": "通达信人气"}
cover_cmp = []
for p in PLATFORMS:
    calc = len(set(f["代码"] for f in facts if f["平台"] == p))
    declared = metrics.get(metric_map[p], "?")
    cover_cmp.append((p, calc, declared, "OK" if str(calc) == str(declared) else "不一致"))

# 共振级别声明 vs 计算
level_cmp = []
for code, d in stocks.items():
    decl = re.match(r"(\d+)", d["共振级别"])
    if decl:
        calc = d["覆盖平台数"]
        if int(decl.group(1)) != calc:
            level_cmp.append((d["名称"], d["共振级别"], calc))

L = ["# 人气交叉 · 数据清洗校验报告\n",
     f"- 源文件：`_renqi_decoded.html`（数据时间 {DATE} {TIME}）",
     f"- 事实表：**{len(facts)}** 条 ｜ 个股维度：**{len(stocks)}** 只 ｜ 校验告警：**{len(warnings)}** 条\n",
     "## 一、硬校验\n",
     "| 校验项 | 结果 |", "| --- | --- |",
     f"| 主键 (日期,时间,代码,平台,榜单) 唯一 | {'通过' if not dup else f'失败 {len(dup)} 条重复'} |",
     f"| 名次范围 1–20 | {'通过' if not bad_rank else f'越界 {len(bad_rank)} 条'} |",
     f"| 平台命中白名单 | {'通过' if not bad_plat else f'越界 {len(bad_plat)} 条'} |",
     f"| 代码为 6 位数字 | {'通过' if not bad_code else f'异常 {bad_code}'} |",
     f"| 交易所前缀与号段一致 | {'通过' if not bad_seg else f'异常 {bad_seg}'} |",
     f"| 涨跌幅 ∈ [-30,30] | {'通过' if not bad_chg else f'越界 {len(bad_chg)} 条'} |",
     f"| {len(stocks)} 只均有行业+主标签 | {'通过' if not no_tag else f'缺失 {no_tag}'} |",
     "\n## 二、平台覆盖数 vs 页面指标卡\n",
     "| 平台 | 计算值 | 指标卡 | 结论 |", "| --- | --- | --- | --- |"]
L += [f"| {p} | {c} | {d} | {s} |" for p, c, d, s in cover_cmp]
L += ["\n## 三、共振级别重算（声明平台数 vs 实际覆盖平台数）\n"]
if level_cmp:
    L += ["| 个股 | 页面声明 | 实际覆盖 |", "| --- | --- | --- |"]
    L += [f"| {n} | {d} | {c} |" for n, d, c in level_cmp]
    L.append("\n> 差异源于同平台多榜单重复计数（淘股吧实时+24h、同花顺1h+24h 各算 2 条），清洗后以**去重平台数**为准。")
else:
    L.append("全部一致，无差异。")

L += ["\n## 四、清洗告警\n"]
if warnings:
    seen = sorted(set(warnings))
    L += [f"- {w}" for w in seen]
else:
    L.append("无。")

L += ["\n## 五、字段口径\n",
      "| 字段 | 说明 |", "| --- | --- |",
      "| 名次 | 该榜单内名次，1–20 |",
      "| 指标名/值/单位 | 该榜指标（搜索次数·次 / 热度·万 / 人气值·万），空 = 该榜无此指标 |",
      "| 指标附加 | 次要时间窗指标，如 `7日 120 次` |",
      "| 涨跌幅 | 仅财联社热榜、通达信人气榜存在；`—`→0 |",
      "| 较昨日名次变化 | 仅东方财富人气榜存在；`↑x`→+x、`↓x`→-x、`—`→0 |",
      "| 主/辅标签_规范 | 别名归一（CPO→共封装光学(CPO) 等） |",
      "| 覆盖平台数 | 该股去重后的平台覆盖数（维度表） |"]

# ============================ 输出 ============================
COLS = ["日期", "时间", "代码", "交易所", "名称", "平台", "榜单", "名次",
        "指标名", "指标值", "指标单位", "指标附加", "涨跌幅", "较昨日名次变化",
        "分组", "共振级别", "行业", "主标签", "辅标签", "主标签_规范", "辅标签_规范", "来源"]

with open(os.path.join(OUT_DIR, "人气交叉_清洗_fact_rank.csv"), "w", encoding="utf-8-sig", newline="") as f:
    w = csv.DictWriter(f, fieldnames=COLS)
    w.writeheader()
    w.writerows(sorted(facts, key=lambda r: (r["代码"], r["平台"], r["榜单"])))

with open(os.path.join(OUT_DIR, "人气交叉_清洗_fact_rank.json"), "w", encoding="utf-8") as f:
    json.dump(facts, f, ensure_ascii=False, indent=2)

DIM = ["代码", "交易所", "名称", "行业", "主标签", "辅标签", "分组", "共振级别",
       "覆盖平台数", "覆盖平台", "上榜条数"]
with open(os.path.join(OUT_DIR, "人气交叉_清洗_dim_stock.csv"), "w", encoding="utf-8-sig", newline="") as f:
    w = csv.DictWriter(f, fieldnames=DIM)
    w.writeheader()
    w.writerows(sorted(stocks.values(), key=lambda d: (-d["覆盖平台数"], d["代码"])))

with open(os.path.join(OUT_DIR, "人气交叉_清洗_校验报告.md"), "w", encoding="utf-8") as f:
    f.write("\n".join(L))

print(f"事实表 {len(facts)} 条 | 个股 {len(stocks)} 只 | 告警 {len(set(warnings))} 条")
print("平台覆盖:", [(p, c, d, s) for p, c, d, s in cover_cmp])
print("共振级别差异:", level_cmp)
print("硬校验: 主键重复", len(dup), "| 名次越界", len(bad_rank), "| 代码异常", bad_code,
      "| 号段异常", bad_seg, "| 涨跌幅越界", len(bad_chg), "| 无标签", no_tag)
for w_ in sorted(set(warnings)):
    print("告警:", w_)
