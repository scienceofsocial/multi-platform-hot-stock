# -*- coding: utf-8 -*-
"""解析解码后的 _renqi_decoded.html，输出结构化数据（JSON/CSV）与 Markdown 报告。"""
import csv
import html as htmllib
import json
import os
import re

# 所有输入/输出都在本脚本所在目录，随目录整体搬迁无需改路径
DIR = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(DIR, "_renqi_decoded.html")
OUT_JSON = os.path.join(DIR, "人气交叉_结构化数据.json")
OUT_CSV = os.path.join(DIR, "人气交叉_结构化数据.csv")
OUT_MD = os.path.join(DIR, "人气交叉_报告.md")

src = open(SRC, encoding="utf-8").read()
body = src.split("<body>", 1)[1]


def text(s):
    s = re.sub(r"<[^>]+>", "", s)
    return re.sub(r"\s+", " ", htmllib.unescape(s)).strip()


def clean_num(s):
    """财联社/东财的涨跌幅浮点尾数修正：↓4.0600004 -> -4.06"""
    m = re.match(r"↑(-?[\d.]+)", s)
    if m:
        return f"{float(m.group(1)):+.2f}"
    m = re.match(r"↓(-?[\d.]+)", s)
    if m:
        return f"-{abs(float(m.group(1))):.2f}"
    return s or "—"


# ---------- 1. 头部信息 ----------
head = {}
head["标题"] = text(re.search(r"<h1>(.*?)</h1>", body, re.S).group(1))
head["副标题"] = text(re.search(r'class="sub">(.*?)</div>', body, re.S).group(1))
head["数据时间"] = text(re.search(r'数据时间 <b>(.*?)</b>', body).group(1))
head["刷新说明"] = text(re.search(r"</b><br>(.*?)</div>", body).group(1))

# ---------- 2. 指标卡 ----------
metrics = [
    {"名称": k, "数值": v}
    for v, k in re.findall(r'<div class="v">(.*?)</div><div class="k">(.*?)</div>', body)
]

# ---------- 3. 共振分组（点评 + 个股） ----------
overall = text(re.search(r'<h2>整体结构点评</h2>\s*<div class="cmt">(.*?)</div>', body, re.S).group(1))

resonance = []
for sec in re.finditer(
    r'<h([23])>([^<]*)</h\1>\s*<div class="cmt">(.*?)</div>(.*?)'
    r'(?=<h[23]>|<div class="card"|<div class="note|</body>)',
    body,
    re.S,
):
    title, comment, blob = sec.group(2), sec.group(3), sec.group(4)
    stocks = []
    for blk in re.split(r'(?=<div class="spot3?">)', blob)[1:]:
        name = re.search(r'class="lk"[^>]*>([^<]+)</a>', blk)
        if not name:
            continue
        code = re.search(r'class="spot-code">(\w+)<', blk)
        level = re.search(r'class="(?:top|tri|duo)">([^<]+)<', blk)
        pills = dict(
            (klass, val)
            for klass, val in re.findall(r'class="pill (\w+)">([^<]+)<', blk)
        )
        ranks = []
        for row in re.findall(r'class="ck">(.*?)</div>(?=<div class="ck">|</div>)', blk, re.S):
            m = re.search(r"</i>(.*?)<b>(.*?)</b>(.*)", row, re.S)
            if not m:
                continue
            ranks.append(
                {
                    "榜": text(m.group(1)),
                    "名次": text(m.group(2)),
                    "备注": clean_num(text(m.group(3))),
                }
            )
        stocks.append(
            {
                "名称": text(name.group(1)),
                "代码": code.group(1) if code else "",
                "共振级别": text(level.group(1)) if level else "",
                "行业": pills.get("ind", ""),
                "主标签": pills.get("main", ""),
                "辅标签": pills.get("aux", ""),
                "上榜": ranks,
            }
        )
    if stocks:
        resonance.append(
            {"分组": text(title), "点评": text(comment), "个股数": len(stocks), "个股": stocks}
        )

# ---------- 4. 各平台独立热点表格 ----------
indep = []
for card in re.findall(r'<div class="card"><h2>([^<]*)</h2>\s*<table>(.*?)</table>', body, re.S):
    title, table = card
    header = [text(x) for x in re.findall(r"<th[^>]*>(.*?)</th>", table, re.S)]
    rows = []
    for tr in re.findall(r"<tr>(?!<th)(.*?)</tr>", table, re.S):
        tds = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)
        if not tds:
            continue
        vals = [text(td) or "—" for td in tds]
        rows.append(dict(zip(header, vals)))
    indep.append({"平台": text(title), "列": header, "个股数": len(rows), "个股": rows})

report = {
    "头部信息": head,
    "指标卡": metrics,
    "整体结构点评": overall,
    "共振分组": resonance,
    "平台独立热点": indep,
}

with open(OUT_JSON, "w", encoding="utf-8") as f:
    json.dump(report, f, ensure_ascii=False, indent=2)

# ---------- CSV：全量个股 ----------
csv_rows = []
for grp in resonance:
    for s in grp["个股"]:
        row = {
            "分组": grp["分组"],
            "共振级别": s["共振级别"],
            "名称": s["名称"],
            "代码": s["代码"],
            "行业": s["行业"],
            "主标签": s["主标签"],
            "辅标签": s["辅标签"],
        }
        for r in s["上榜"]:
            row[r["榜"]] = f"{r['名次']} {r['备注']}".strip()
        csv_rows.append(row)
for blk in indep:
    for s in blk["个股"]:
        row = {
            "分组": blk["平台"],
            "共振级别": "独立热点",
            "名称": s.get("个股", ""),
            "代码": s.get("代码", ""),
            "行业": "",
            "主标签": "",
            "辅标签": "",
        }
        row.update({k: v for k, v in s.items() if k not in ("个股", "代码")})
        csv_rows.append(row)

cols = ["分组", "共振级别", "名称", "代码", "行业", "主标签", "辅标签"]
for r in csv_rows:
    for k in r:
        if k not in cols:
            cols.append(k)
with open(OUT_CSV, "w", encoding="utf-8-sig", newline="") as f:
    w = csv.DictWriter(f, fieldnames=cols)
    w.writeheader()
    w.writerows(csv_rows)

# ---------- Markdown 报告 ----------
L = []
L.append(f"# {head['标题']}")
L.append(f"\n> {head['副标题']}\n>\n> 数据时间：**{head['数据时间']}** ｜ {head['刷新说明']}\n")

L.append("## 一、概览指标\n")
L.append("| 指标 | 数值 |")
L.append("| --- | --- |")
for m in metrics:
    L.append(f"| {m['名称']} | {m['数值']} |")

L.append("\n## 二、共振股明细\n")
L.append(f"整体结构点评：{overall}\n")
L.append("| 共振级别 | 名称 | 代码 | 行业 | 主标签 | 辅标签 | 上榜榜数 |")
L.append("| --- | --- | --- | --- | --- | --- | --- |")
for grp in resonance:
    for s in grp["个股"]:
        L.append(
            f"| {s['共振级别']} | {s['名称']} | {s['代码']} | {s['行业']} | "
            f"{s['主标签']} | {s['辅标签']} | {len(s['上榜'])} |"
        )

for grp in resonance:
    L.append(f"\n### {grp['分组']}（{grp['个股数']} 只）\n")
    L.append(f"点评：{grp['点评']}\n")
    for s in grp["个股"]:
        L.append(f"**{s['名称']}（{s['代码']}）** — {s['行业']} / {s['主标签']} / {s['辅标签']}")
        for r in s["上榜"]:
            L.append(f"- {r['榜']}：{r['名次']} {r['备注']}")
        L.append("")

L.append("## 三、各平台独立热点（单平台上榜）\n")
for blk in indep:
    L.append(f"### {blk['平台']}\n")
    L.append("| " + " | ".join(blk["列"]) + " |")
    L.append("| " + " | ".join(["---"] * len(blk["列"])) + " |")
    for s in blk["个股"]:
        L.append("| " + " | ".join(s.get(c, "—") for c in blk["列"]) + " |")
    L.append("")

with open(OUT_MD, "w", encoding="utf-8") as f:
    f.write("\n".join(L))

print("分组数:", len(resonance), "| 共振个股:", sum(g["个股数"] for g in resonance))
print("独立热点平台:", [(b["平台"], b["个股数"]) for b in indep])
print("CSV 行数:", len(csv_rows))
print("已输出:", OUT_JSON, OUT_CSV, OUT_MD, sep="\n  ")
