# -*- coding: utf-8 -*-
"""55188 龙头榜（``sj88.ld``）当日「变化时点」-> 独立 Markdown（每 10 分钟覆盖刷一遍）。

为什么单独一个入口
------------------
``hot_trace_timeline.py`` 是**交互式排查工具**（打印到控制台、按 5 个时段分组、top3 带
``(名称·龙N)``）。本脚本把它固化成**定时任务的产物**：一份扁平、只列变化轮、top3 只写纯代码的
Markdown，由计划任务 ``HotLdTimeline`` 每 10 分钟刷一遍。

数据来源
--------
``_hot_archive/hot_trace.jsonl``（一行 = 一次榜单内容真变化），由 ``run_hot_rank_daily.bat``
的归档步骤 ``a_archive_hot_snapshot.py`` 追加。本脚本**只读轨迹、不抓任何榜**，因此
和 ``HotRankTDX_Intraday`` 互不抢上游站点；反过来，轨迹一旦停止追加（那条管线挂了），
本表的时刻也就停在最后一次变化上 —— 这是有意为之：同一条轨迹、同一个事实来源。

产物
----
``龙头榜_变化时点_YYYY-MM-DD.md``（同目录，整份覆盖写，只留当日到目前为止的累计视角）
若轨迹里最新口径日尚无纪录，则**不写文件**并返回 0（不是错误：凌晨还没跑第一轮而已）。

用法
----
    python a_render_ld_timeline.py                 # 最新口径日 -> 龙头榜_变化时点_<日期>.md
    python a_render_ld_timeline.py --key 2026-09-24
    python a_render_ld_timeline.py --board sj88.rb --label 人气榜
"""
import argparse
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import hot_trace_timeline as tl                                            # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="某榜当日「变化时点」-> 独立 Markdown")
    ap.add_argument("--trace", default=tl.TRACE, help="轨迹文件（默认 _hot_archive/hot_trace.jsonl）")
    ap.add_argument("--key", default=None, help="口径日，默认取轨迹最后一行的 key")
    ap.add_argument("--board", default="sj88.ld", help="目标榜（默认 55188 龙头榜）")
    ap.add_argument("--label", default="龙头榜", help="榜单中文名，用于标题与文件名")
    ap.add_argument("--top", type=int, default=3, help="每轮展示的龙头条数（默认 3）")
    ap.add_argument("--out", default=None, help="输出文件，默认 <%s>_变化时点_<日期>.md" % "龙头榜")
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
    out = args.out or os.path.join(HERE, "%s_变化时点_%s.md" % (args.label, key))
    with open(out, "w", encoding="utf-8") as fh:               # 覆盖写：始终是当日累计视角
        fh.write(tl.render_md(timeline, args.board, key, args.label))

    changed = [r for r in timeline if r["changed"]]
    print("OK - %s（%s：%d 个变化时点 / 共 %d 轮抓取，只数 %s -> %s）" % (
        os.path.basename(out), args.board, len(changed), len(timeline) - 1,
        timeline[0]["n_after"], timeline[-1]["n_after"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
