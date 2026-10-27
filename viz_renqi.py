# -*- coding: utf-8 -*-
"""【历史套件 · 五平台口径】基于清洗后的长表生成可视化看板（单文件 HTML，离线可开）。

本看板对应旧「五平台人气个股交叉识别」数据集（东方财富/淘股吧/同花顺/财联社/通达信），
与现行「八平台人气共振」日报管线（last_good.json -> 八平台人气共振_通达信排序指标.txt）无关；
里面的平台数与共振档位都是五平台口径，不要按八平台去读。

输入：人气交叉_清洗_fact_rank.csv / 人气交叉_清洗_dim_stock.csv
输出：人气交叉_可视化看板.html
"""
import os

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import plotly.io as pio

# 所有输入/输出都在本脚本所在目录，随目录整体搬迁无需改路径
DIR = os.path.dirname(os.path.abspath(__file__))
OUT = DIR + r"\人气交叉_可视化看板.html"

facts = pd.read_csv(DIR + r"\人气交叉_清洗_fact_rank.csv")
dim = pd.read_csv(DIR + r"\人气交叉_清洗_dim_stock.csv")
SNAP = f'{facts["日期"].iloc[0]} {facts["时间"].iloc[0]}'   # 数据快照时间，取自事实表
PLAT = ["东方财富", "淘股吧", "同花顺", "财联社", "通达信"]

# ---------- 深色主题（沿用原页面配色） ----------
pio.templates["renqi"] = go.layout.Template(
    layout=go.Layout(
        paper_bgcolor="#171008",
        plot_bgcolor="#1d1409",
        font=dict(color="#e8d9be", family="Microsoft YaHei, PingFang SC, sans-serif", size=12),
        title=dict(font=dict(color="#e3ac55", size=17), x=0.01, xanchor="left"),
        colorway=["#e3ac55", "#c96a5a", "#46a877", "#6a9fd8", "#b98ad8",
                  "#d8a06a", "#7fd8c0", "#d87fa0", "#a0b06a", "#8a9fd8"],
        xaxis=dict(gridcolor="#332618", zerolinecolor="#4a3a26", linecolor="#4a3a26"),
        yaxis=dict(gridcolor="#332618", zerolinecolor="#4a3a26", linecolor="#4a3a26"),
        legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(size=11)),
        margin=dict(l=10, r=10, t=50, b=10),
    )
)
pio.templates.default = "renqi"

CHARTS = []


def add(title, fig, height=520):
    fig.update_layout(title=title, height=height)
    CHARTS.append(fig)


# ==================== 1. 共振热力矩阵 ====================
best = facts.groupby(["代码", "平台"])["名次"].min().reset_index()
order = dim.sort_values(["覆盖平台数", "代码"], ascending=[False, True])["代码"].tolist()
names = dim.set_index("代码")["名称"].to_dict()

mat = best.pivot(index="代码", columns="平台", values="名次").reindex(index=order, columns=PLAT)
z = mat.where(mat.notna(), 21).values
txt = mat.apply(lambda s: s.map(lambda v: "" if pd.isna(v) else str(int(v)))).values

fig = go.Figure(go.Heatmap(
    z=z, x=PLAT, y=[names[c] for c in order], text=txt, texttemplate="%{text}",
    textfont=dict(color="#171008", size=11),
    zmin=1, zmax=21,
    colorscale=[[0.0, "#f2d18a"], [0.35, "#c99a4a"], [0.7, "#6d5433"], [0.97, "#4a3a26"], [1.0, "#241a0e"]],
    xgap=2, ygap=2, hoverongaps=False,
    hovertemplate="%{y} · %{x}<br>最佳名次：%{z}<extra></extra>",
    colorbar=dict(title="名次", tickvals=[1, 10, 20, 21], ticktext=["1", "10", "20", "未上榜"],
                  outlinewidth=0),
))
fig.update_yaxes(autorange="reversed", tickfont=dict(size=10), ticksuffix="  ")
fig.update_xaxes(side="top", tickfont=dict(size=12))
add("① 共振热力矩阵 · 各股在五平台的最佳名次（颜色越亮名次越前，深灰=未上榜）", fig, height=1080)

# ==================== 2. 热度 × 人气气泡图 ====================
hs = facts[(facts["平台"] == "同花顺") & (facts["指标名"] == "热度")]
hot = (hs.sort_values("榜单", ascending=False)          # 24h 优先于 1h
         .drop_duplicates("代码").set_index("代码")["指标值"])
pop = (facts[(facts["平台"] == "通达信") & (facts["指标名"] == "人气值")]
       .drop_duplicates("代码").set_index("代码")["指标值"])

bub = dim.set_index("代码").copy()
bub["同花顺热度"] = hot.reindex(bub.index)
bub["通达信人气"] = pop.reindex(bub.index)
bub = bub.dropna(subset=["同花顺热度", "通达信人气"]).reset_index()

fig = px.scatter(
    bub, x="同花顺热度", y="通达信人气", size="覆盖平台数", color="主标签",
    text="名称", hover_name="名称", hover_data={"行业": True, "覆盖平台": True, "共振级别": True},
    size_max=42,
)
fig.update_traces(textposition="top center", textfont=dict(size=10))
fig.update_xaxes(title="同花顺热度（万，24h 优先）")
fig.update_yaxes(title="通达信人气值（万）")
fig.update_layout(legend=dict(orientation="v", x=1.01, y=1))
add(f"② 热度 × 人气气泡图 · 气泡大小=覆盖平台数（共 {len(bub)} 只同时上榜同花顺与通达信）", fig, height=620)

# ==================== 3. 平台组合交集 ====================
combos = (dim.groupby("覆盖平台").agg(股票数=("代码", "count"))
          .reset_index().sort_values("股票数", ascending=False))
single = combos[combos["覆盖平台"].str.count("/") == 0]["股票数"].sum()
combos = combos[combos["覆盖平台"].str.count("/") > 0].copy()
combos["平台组合"] = combos["覆盖平台"].str.replace("/", " ＋ ", regex=False)
combos.loc[len(combos)] = ["—", single, "仅单平台上榜"]
combos = combos.sort_values("股票数", ascending=True)

fig = px.bar(combos, x="股票数", y="平台组合", orientation="h", text="股票数",
             color="股票数", color_continuous_scale=["#2a2016", "#8a6a3c", "#f2d18a"])
fig.update_traces(textposition="outside", cliponaxis=False)
fig.update_layout(coloraxis_showscale=False, yaxis_title="", xaxis_title="个股数")
fig.update_yaxes(tickfont=dict(size=11))
add("③ 平台共振组合分布 · 哪些平台组合最容易同时上榜", fig, height=460)

# ==================== 4. 行业 / 标签 分布 ====================
ind = dim.groupby("行业").size().reset_index(name="个股数").sort_values("个股数", ascending=False)
fig = px.treemap(ind, path=["行业"], values="个股数", color="个股数",
                 color_continuous_scale=["#241a0e", "#8a6a3c", "#f2d18a"])
fig.update_traces(textfont=dict(color="#171008"), marker=dict(cornerradius=4))
fig.update_layout(coloraxis_showscale=False)
add("④ 行业分布 · 题材集中度", fig, height=430)

tag = dim["主标签"].value_counts().head(14).reset_index()
tag.columns = ["主标签", "个股数"]
fig = px.bar(tag.sort_values("个股数"), x="个股数", y="主标签", orientation="h", text="个股数",
             color="个股数", color_continuous_scale=["#2a2016", "#8a6a3c", "#e3ac55"])
fig.update_traces(textposition="outside", cliponaxis=False)
fig.update_layout(coloraxis_showscale=False, yaxis_title="", xaxis_title="个股数")
add("⑤ 主标签频次 Top14 · 当日主线", fig, height=470)

# ==================== 5. 名次变化与涨跌幅 ====================
d = facts[facts["较昨日名次变化"].notna() & (facts["较昨日名次变化"] != 0)].copy()
d["颜色"] = d["较昨日名次变化"].apply(lambda v: "#c96a5a" if v > 0 else "#46a877")
d["方向"] = d["较昨日名次变化"].apply(lambda v: f"↑{int(v)}" if v > 0 else f"↓{int(-v)}")
d = d.sort_values("较昨日名次变化")
fig = go.Figure(go.Bar(
    x=d["较昨日名次变化"], y=d["名称"], orientation="h", marker_color=d["颜色"],
    text=d["方向"], textposition="outside", cliponaxis=False,
    hovertemplate="%{y}：较昨日 %{text} 名<extra></extra>",
))
fig.update_layout(
    title=f"⑥ 东方财富人气榜 · 较昨日名次变化（{len(d)} 只有变动，红=上升 绿=下降）",
    height=470, xaxis_title="名次变化（正=上升）", yaxis_title="")
CHARTS.append(fig)

ch = facts[(facts["平台"] == "财联社") & facts["涨跌幅"].notna()].copy()
ch["颜色"] = ch["涨跌幅"].apply(lambda v: "#c96a5a" if v >= 0 else "#46a877")
ch = ch.sort_values("涨跌幅")
fig = go.Figure(go.Bar(
    x=ch["涨跌幅"], y=ch["名称"], orientation="h", marker_color=ch["颜色"],
    text=ch["涨跌幅"].apply(lambda v: f"{v:+.2f}%"), textposition="outside", cliponaxis=False,
    hovertemplate="%{y}：%{text}<extra></extra>",
))
fig.update_layout(title=f"⑦ 财联社热榜 · 涨跌幅（{len(ch)} 只，红=上涨 绿=下跌）",
                  height=560, xaxis_title="涨跌幅（%）", yaxis_title="")
CHARTS.append(fig)

# ==================== KPI ====================
kpi = [
    ("个股总数", len(dim)),
    ("上榜记录", len(facts)),
    ("顶级共振（≥4 平台）", int((dim["覆盖平台数"] >= 4).sum())),
    ("三平台共振", int((dim["覆盖平台数"] == 3).sum())),
    ("双平台共振", int((dim["覆盖平台数"] == 2).sum())),
    ("单平台", int((dim["覆盖平台数"] == 1).sum())),
]
kpi_html = "".join(
    f'<div class="kpi"><div class="v">{v}</div><div class="k">{k}</div></div>' for k, v in kpi
)

# ==================== 组装 HTML ====================
parts = []
for i, fig in enumerate(CHARTS):
    parts.append(
        fig.to_html(full_html=False, include_plotlyjs=("inline" if i == 0 else False),
                    config={"displaylogo": False, "responsive": True})
    )

html = f"""<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>人气交叉 · 可视化看板</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{background:#171008;color:#e8d9be;font-family:"Microsoft YaHei",sans-serif;padding:22px;max-width:1240px;margin:0 auto}}
.hd{{border-bottom:2px solid #8a6a3c;padding-bottom:14px;margin-bottom:18px}}
.hd h1{{font-size:22px;color:#e3ac55}}
.sub{{color:#a08a68;font-size:12px;margin-top:6px}}
.kpis{{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:12px;margin:16px 0 6px}}
.kpi{{background:#241a0e;border:1px solid #4a3a26;border-radius:10px;padding:14px;text-align:center}}
.kpi .v{{font-size:26px;font-weight:800;color:#e3ac55}}
.kpi .k{{font-size:12px;color:#a08a68;margin-top:4px}}
.card{{background:#241a0e;border:1px solid #4a3a26;border-radius:10px;padding:14px;margin:16px 0}}
.foot{{color:#8a6f4d;font-size:12px;margin-top:20px;border-top:1px solid #4a3a26;padding-top:12px}}
</style></head><body>
<div class="hd">
  <h1>五平台人气个股交叉识别 · 可视化看板（历史套件）</h1>
  <div class="sub">东财 × 淘股吧 × 同花顺 × 财联社 × 通达信（各榜前 20）｜数据时间 {SNAP}｜历史套件 · 与八平台日报管线无关</div>
</div>
<div class="kpis">{kpi_html}</div>
{"".join(f'<div class="card">{p}</div>' for p in parts)}
<div class="foot">数据源：人气交叉_清洗_fact_rank.csv / 人气交叉_清洗_dim_stock.csv ｜ 图表可交互：滚轮缩放、点击图例筛选、悬停查看明细</div>
</body></html>"""

with open(OUT, "w", encoding="utf-8") as f:
    f.write(html)

print("图表数:", len(CHARTS))
print("气泡图样本:", len(bub), "只")
print("输出:", OUT)
