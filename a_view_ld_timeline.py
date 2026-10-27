# -*- coding: utf-8 -*-
"""55188 龙头榜（``sj88.ld``）当日「变化时点」-> 自刷新 HTML 看板（纯标准库、离线可开）。

为什么单独一个入口
------------------
``a_render_ld_timeline.py`` 的产物是**给别人读的** Markdown：只有代码没有名称，而且
文件是死的 —— 想看最新一轮就得重新打开文件。

本脚本把**同一份轨迹**（``hot_trace_timeline`` 模块，与 Markdown 一字不差地同源同序）
渲染成一张 HTML 看板：

* 顶部 KPI：口径日 / 当前只数 / 变化时点数 / 抓取轮数 / **数据最后更新**与**看板生成**
  两个时刻 —— 用来一眼判断「是不是卡住了 / 看板本身新不新」；
* 表体：``INIT`` 一行 + 每个变化时点一行（编号 1 起，未变轮不占号），列与 Markdown 一致；
* 「龙头 top3」额外带**股票名称**与**榜内名次**（Markdown 里只有代码，看盘时得再查）；
* ``<meta http-equiv="refresh">`` 自刷新 —— 配合计划任务 ``HotLdTimeline`` 每 10 分钟
  重写本文件，浏览器开一个标签页放着即可，不必手动 F5（``--refresh 0`` 可关掉）。

数据来源
--------
``_hot_archive/hot_trace.jsonl``，与 ``a_render_ld_timeline.py`` 完全相同：**只读轨迹、
不抓任何榜**，因此不会和 ``HotRankTDX_Intraday`` 抢上游站点。

产物
----
``龙头榜_变化时点_看板.html``（同目录，整份覆盖写）。若轨迹里最新口径日尚无纪录，
则**不写文件**并返回 0（凌晨还没跑第一轮而已，不是错误）。

用法
----
    python a_view_ld_timeline.py                 # 生成看板（不弹浏览器）
    python a_view_ld_timeline.py --open          # 生成后顺手打开浏览器
    python a_view_ld_timeline.py --key 2026-09-24 --board sj88.rb --label 人气榜
    python a_view_ld_timeline.py --refresh 0     # 关掉页面自刷新
"""
import argparse
import html
import os
import re
import sys
import webbrowser
from datetime import datetime

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import hot_trace_timeline as tl                                            # noqa: E402

#: ``label()`` 的产物形如 ``SZ002614(奥佳华·龙1)``（list 型榜则只有裸代码）
CHIP_RE = re.compile(r"^([A-Z]{2}\d{6})\((.+)\)$")

#: 深色主题（与 viz_renqi.py 的看板同一套配色，避免两个看板观感打架）
CSS = """
*{margin:0;padding:0;box-sizing:border-box}
body{background:#171008;color:#e8d9be;font-family:"Microsoft YaHei",sans-serif;
     padding:22px;max-width:1240px;margin:0 auto}
.hd{border-bottom:2px solid #8a6a3c;padding-bottom:14px;margin-bottom:18px}
.hd h1{font-size:22px;color:#e3ac55}
.sub{color:#a08a68;font-size:12px;margin-top:6px;line-height:1.7}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(132px,1fr));gap:12px;margin:16px 0}
.kpi{background:#241a0e;border:1px solid #4a3a26;border-radius:10px;padding:13px;text-align:center}
.kpi .v{font-size:24px;font-weight:800;color:#e3ac55;font-variant-numeric:tabular-nums}
.kpi .v.sm{font-size:16px;padding:5px 0}
.kpi .k{font-size:12px;color:#a08a68;margin-top:4px}
.card{background:#241a0e;border:1px solid #4a3a26;border-radius:10px;padding:6px 14px 14px}
table{width:100%;border-collapse:collapse;font-size:13px}
thead th{position:sticky;top:0;background:#241a0e;color:#8a6f4d;font-weight:600;
         text-align:left;font-size:12px;padding:11px 8px;border-bottom:1px solid #4a3a26;
         white-space:nowrap;z-index:2}
tbody td{padding:8px;border-bottom:1px solid #241a0e;vertical-align:middle}
tbody tr:hover{background:#2a1f12}
tr.init{background:#1d1509}
tr.init td{color:#a08a68}
.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap;color:#a08a68}
.idx{text-align:right;color:#8a6f4d;font-variant-numeric:tabular-nums;width:44px}
.tm{font-variant-numeric:tabular-nums;white-space:nowrap;color:#e8d9be}
.tm i{color:#8a6f4d;font-style:normal;font-size:11px;margin-left:4px}
.ar{color:#8a6f4d;margin:0 6px}
.bd{display:inline-block;min-width:50px;padding:2px 7px;margin-right:4px;border-radius:6px;
    font-size:12px;font-variant-numeric:tabular-nums;text-align:center}
.bd.in{background:rgba(70,168,119,.16);color:#63c99a;border:1px solid rgba(70,168,119,.45)}
.bd.out{background:rgba(201,106,90,.16);color:#d88376;border:1px solid rgba(201,106,90,.45)}
.bd.mov{background:rgba(227,172,85,.14);color:#e3ac55;border:1px solid rgba(227,172,85,.4)}
.bd.b0{background:transparent;color:#5d4d38;border:1px solid #33261a}
.chip{display:inline-block;margin:1px 5px 1px 0;padding:2px 8px;border-radius:999px;
      background:#2f2213;border:1px solid #4a3a26;white-space:nowrap;font-size:12px}
.chip b{color:#e3ac55;font-family:Consolas,monospace}
.chip i{color:#c8b596;font-style:normal;margin-left:5px}
.chip em{color:#8a6f4d;font-style:normal;margin-left:4px;font-size:11px}
.none{color:#5d4d38}
.foot{color:#8a6f4d;font-size:12px;margin-top:18px;border-top:1px solid #4a3a26;padding-top:12px;line-height:1.8}
"""


def chip(text):
    """``SZ002614(奥佳华·龙1)`` -> 代码 + 名称 + 名次 的小胶囊。"""
    m = CHIP_RE.match(text or "")
    if not m:
        return '<span class="chip"><b>%s</b></span>' % html.escape(text or "—")
    code, rest = m.groups()
    name, _, rank = rest.partition("·")
    tail = '<em>%s</em>' % html.escape(rank) if rank else ""
    return '<span class="chip"><b>%s</b><i>%s</i>%s</span>' % (
        html.escape(code), html.escape(name), tail)


def badge(kind, n):
    """形态徽章：0 值淡显，非 0 才上色（一眼看出这一轮到底动了什么）。"""
    cls = kind if n else "b0"
    return '<span class="bd %s">%s%d</span>' % (cls, {"in": "进", "out": "出", "mov": "换位"}[kind], n)


def kpi(value, label, small=False):
    return '<div class="kpi"><div class="v%s">%s</div><div class="k">%s</div></div>' % (
        " sm" if small else "", html.escape(str(value)), html.escape(label))


def render_html(timeline, board, key, label, top_n, trace_path, refresh):
    """逐轮行 -> 整份 HTML（看板 = 表体与 Markdown 同源，额外给名称/名次/自刷新）。"""
    init = timeline[0]
    changed = [r for r in timeline if r["changed"]]
    rounds = len(timeline) - 1
    flat = rounds - len(changed)
    counts = [r["n_after"] for r in timeline]
    built = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    last = timeline[-1]["generated_at"].replace("T", " ")[:19]

    tr = ['<tr class="init"><td class="idx">—</td>'
          '<td class="tm">%s<i>INIT</i></td><td class="num">%d</td>'
          '<td><span class="bd b0">初始</span></td><td>%s</td></tr>' % (
              html.escape(init["generated_at"][11:19]), init["n_after"],
              "".join(chip(t) for t in init["top"]) or '<span class="none">—</span>')]
    for i, r in enumerate(changed, 1):
        tr.append(
            '<tr><td class="idx">%d</td><td class="tm">%s</td>'
            '<td class="num"><b>%s</b><span class="ar">→</span><b>%s</b></td>'
            '<td>%s%s%s</td><td>%s</td></tr>' % (
                i, html.escape(r["generated_at"][11:19]), r["n_before"], r["n_after"],
                badge("in", r["n_in"]), badge("out", r["n_out"]), badge("mov", r["n_moved"]),
                "".join(chip(t) for t in r["top"]) or '<span class="none">—</span>'))

    meta = ('<meta http-equiv="refresh" content="%d">' % refresh) if refresh else ""
    return """<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">%s
<title>%s 变化时点 · %s</title>
<style>%s</style></head><body>
<div class="hd">
  <h1>%s · 当日变化时点看板</h1>
  <div class="sub">口径日 %s ｜ 目标榜 %s（各轮龙头 top %d）｜ 数据 %s<br>
    与 <code>%s_变化时点_%s.md</code> 同源（<code>_hot_archive/hot_trace.jsonl</code>），
    由计划任务 HotLdTimeline 每 10 分钟重刷</div>
</div>
<div class="kpis">%s</div>
<div class="card"><table>
<thead><tr><th>#</th><th>时刻</th><th>只数</th><th>形态（进/出/换位）</th><th>龙头 top%d</th></tr></thead>
<tbody>%s</tbody></table></div>
<div class="foot">
  变化时点 <b>%d</b> 个 ｜ 抓取轮 <b>%d</b>（未变 %d 轮：轨迹因别的平台变化而追加、本榜一字未动）｜
  只数 %d ~ %d<br>
  数据最后更新 <b>%s</b> ｜ 看板生成于 <b>%s</b>%s
</div>
</body></html>
""" % (meta, html.escape(label), html.escape(key), CSS, html.escape(label),
       html.escape(key), html.escape(board), top_n, html.escape(last),
       html.escape(label), html.escape(key),
       "".join([kpi(key, "口径日", True), kpi(timeline[-1]["n_after"], "当前只数"),
                kpi(len(changed), "变化时点"), kpi(rounds, "抓取轮"),
                kpi(flat, "未变轮"), kpi(last[11:], "数据最后更新", True)]),
       top_n, "".join(tr), len(changed), rounds, flat, min(counts), max(counts),
       html.escape(last), html.escape(built),
       "（页面每 %d 秒自动刷新）" % refresh if refresh else "（页面未开启自动刷新）")


def main():
    ap = argparse.ArgumentParser(description="某榜当日「变化时点」-> 自刷新 HTML 看板")
    ap.add_argument("--trace", default=tl.TRACE, help="轨迹文件（默认 _hot_archive/hot_trace.jsonl）")
    ap.add_argument("--key", default=None, help="口径日，默认取轨迹最后一行的 key")
    ap.add_argument("--board", default="sj88.ld", help="目标榜（默认 55188 龙头榜）")
    ap.add_argument("--label", default="龙头榜", help="榜单中文名，用于标题与文件名")
    ap.add_argument("--top", type=int, default=3, help="每轮展示的龙头条数（默认 3）")
    ap.add_argument("--out", default=None, help="输出文件，默认 <%s>_变化时点_看板.html" % "龙头榜")
    ap.add_argument("--refresh", type=int, default=60, help="页面自刷新秒数，0=不自刷新（默认 60）")
    ap.add_argument("--open", action="store_true", help="生成后用默认浏览器打开")
    args = ap.parse_args()

    rows = tl.load(args.trace)
    if not rows:
        print("轨迹文件为空（%s），跳过" % os.path.relpath(args.trace, HERE))
        return 0
    key = args.key or rows[-1]["key"]
    day = [r for r in rows if r.get("key") == key]
    if not day:
        print("口径日 %s 无轨迹记录，跳过" % key)
        return 0
    day.sort(key=lambda r: str(r.get("generated_at") or ""))   # 轨迹本就时序追加，防御性排序

    timeline = tl.build(day, args.board, args.top)
    out = args.out or os.path.join(HERE, "%s_变化时点_看板.html" % args.label)
    with open(out, "w", encoding="utf-8") as fh:               # 覆盖写：始终是当日累计视角
        fh.write(render_html(timeline, args.board, key, args.label, args.top,
                             args.trace, args.refresh))

    changed = [r for r in timeline if r["changed"]]
    print("OK - %s（%s：%d 个变化时点 / 共 %d 轮抓取，只数 %s -> %s，自刷新 %ss）" % (
        os.path.basename(out), args.board, len(changed), len(timeline) - 1,
        timeline[0]["n_after"], timeline[-1]["n_after"], args.refresh))
    if args.open:
        webbrowser.open("file:///" + out.replace("\\", "/"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
