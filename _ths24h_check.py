# -*- coding: utf-8 -*-
"""临时脚本（非管线）：同花顺 24h 热股在「八平台人气共振」里的边际影响。

结构背景：24h 不单独成榜，与 1h 合并进「同花顺」平台键并取最好名次（ths_rank）。
本脚本量化「若剔除 24h 榜」，cover_platforms / 共振分 / 排名 会怎样变。
"""
import copy
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.chdir(HERE)

import a_duopingtai_hot_factor as hot7      # noqa: E402
import a_export_tdx_hot_rank as tx          # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

with open(os.path.join(HERE, "last_good.json"), "r", encoding="utf-8") as fh:
    snap = json.load(fh)


def line(ch="=", n=78):
    print(ch * n)


def main():
    line()
    print("同花顺 1h / 24h 热股 —— 结构性贡献与边际影响")
    print("口径日 %s  抓取时刻 %s" % (snap.get("date"), snap.get("fetched_at")))
    line()

    ths = snap.get("ths") or {}
    h1 = {c: (v or {}).get("hour_rank") for c, v in ths.items()}
    d24 = {c: (v or {}).get("day_rank") for c, v in ths.items()}
    nm = {c: (v or {}).get("name") for c, v in ths.items()}
    h1v = {c: r for c, r in h1.items() if r is not None}
    d24v = {c: r for c, r in d24.items() if r is not None}

    print("\n[1] 两榜重合度")
    print("  ths 键总数 %d ｜ 1h 有值 %d ｜ 24h 有值 %d" % (len(ths), len(h1v), len(d24v)))
    print("  交集 %d ｜ 仅 24h %d ｜ 仅 1h %d ｜ 并集 %d"
          % (len(set(h1v) & set(d24v)), len(set(d24v) - set(h1v)),
             len(set(h1v) - set(d24v)), len(set(h1v) | set(d24v))))

    both = sorted(set(h1v) & set(d24v))
    wins = [(c, h1v[c], d24v[c]) for c in both if d24v[c] < h1v[c]]
    print("  重合 %d 只中，24h 名次优于 1h（真正抬高 ths_rank）的：%d 只"
          % (len(both), len(wins)))
    for c, a, b in sorted(wins, key=lambda t: t[2])[:20]:
        print("    %-8s %-8s 1h=%2d 24h=%2d  名次分 +%d"
              % (c, (nm.get(c) or "")[:8], a, b,
                 max(0, 21 - b) - max(0, 21 - a)))

    poi = set((snap.get("ths_poi") or {}).keys())
    recs = hot7.collect_best_ranks(snap)

    print("\n[2] 仅 24h 上榜的股票（24h 的全部增量来源，共 %d 只）"
          % len(set(d24v) - set(h1v)))
    print("  %-8s %-9s %-8s %-9s %s"
          % ("代码", "名称", "24h名次", "在指标平台", "其它上榜平台"))
    for c in sorted(set(d24v) - set(h1v), key=lambda x: d24v[x]):
        inst = hot7.to_instrument(c)
        rec = recs.get(inst) or {}
        others = [b for b in hot7.PLATFORM_FIELD
                  if b not in ("同花顺",) and rec.get(b) is not None]
        print("  %-8s %-9s %-9d %-11s %s"
              % (c, (nm.get(c) or "")[:8], d24v[c],
                 "是" if c in poi else "否",
                 "、".join(others) if others else "（无）"))

    print("\n[2b] 三组价格特征（截至 09-23 收盘，本地日线；C/N 前缀 = 次新）")
    try:
        import numpy as np
        sys.path.insert(0, os.path.dirname(HERE))
        from tdx_engine import TdxData
        data = TdxData(use_cache=True)
        data.connect()
    except Exception as exc:                                # noqa: BLE001
        print("  跳过：行情层不可用（%s）" % exc)
    else:
        MJ = {"SH": 1, "SZ": 0, "BJ": 2}
        groups = [("仅24h(退潮)", sorted(set(d24v) - set(h1v))),
                  ("仅1h(升温)", sorted(set(h1v) - set(d24v))),
                  ("两榜都有", sorted(set(h1v) & set(d24v)))]
        print("  %-11s %-9s %-6s %-8s %-8s %-8s %-8s %s"
              % ("组", "代码", "K线数", "今涨%", "5日%", "20日%", "24h名次", "1h名次"))
        summ = {}
        skipped = []
        for gname, cs in groups:
            vals = []
            for c in cs:
                inst = hot7.to_instrument(c)
                code, _, suf = inst.partition(".")
                mkt = MJ.get(suf)
                if mkt is None:
                    skipped.append((gname, c, "市场后缀 %s 不在 MJ" % suf))
                    continue
                try:
                    df = data.bars(mkt, code, 0)
                except Exception as exc:                    # noqa: BLE001
                    skipped.append((gname, c, "bars 异常 %s" % exc))
                    continue
                if df is None or len(df) == 0:
                    skipped.append((gname, c, "无日线"))
                    continue
                dts = df["date"].astype(str).to_numpy()
                pos = int(np.searchsorted(dts, "2026-09-23"))
                if pos >= len(dts) or dts[pos] != "2026-09-23":
                    pos = len(dts) - 1
                cl = df["close"].astype(float).to_numpy()

                def r(k, pos=pos, cl=cl):
                    j = pos - k
                    return (cl[pos] / cl[j] - 1) * 100 if j >= 0 and cl[j] > 0 else float("nan")

                row = (c, (nm.get(c) or "")[:8], pos + 1, r(1), r(5), r(20),
                       d24v.get(c), h1v.get(c))
                vals.append(row)
                print("  %-11s %-9s %-6d %-8.2f %-8.2f %-8.2f %-9s %s"
                      % (gname, row[1], row[2], row[3], row[4], row[5],
                         row[6] if row[6] else "-", row[7] if row[7] else "-"))
            if vals:
                arr = np.array([[v[3], v[4], v[5]] for v in vals], dtype=float)
                summ[gname] = (len(vals), np.nanmean(arr[:, 0]), np.nanmean(arr[:, 1]),
                               np.nanmean(arr[:, 2]),
                               sum(1 for v in vals if v[2] < 20))
        print("  " + "-" * 74)
        print("  %-11s %-6s %-8s %-9s %-9s %s"
              % ("组均值", "只数", "今涨%", "5日%", "20日%", "其中次新(<20根K线)"))
        for gname, s in summ.items():
            print("  %-11s %-6d %-8.2f %-9.2f %-9.2f %d 只"
                  % (gname, s[0], s[1], s[2], s[3], s[4]))
        if skipped:
            print("  [跳过 %d 只]" % len(skipped))
            for gname, c, why in skipped:
                print("    %-11s %-8s %s" % (gname, c, why))

    print("\n[3] 模拟「剔除 24h 榜」后的共振分变化（COVER_WEIGHT=1000）")
    full = tx.score_all(snap)
    snap2 = copy.deepcopy(snap)
    for c, v in (snap2.get("ths") or {}).items():
        if isinstance(v, dict):
            v["day_rank"] = None
    cut = tx.score_all(snap2)
    m0 = {it["code"]: it for it in full}
    m1 = {it["code"]: it for it in cut}
    r0 = {it["code"]: i + 1 for i, it in enumerate(full)}
    r1 = {it["code"]: i + 1 for i, it in enumerate(cut)}

    rows = []
    for c, it in m0.items():
        jt = m1.get(c)
        d_score = it["score"] - (jt["score"] if jt else 0)
        d_cov = it["cover"] - (jt["cover"] if jt else 0)
        drk = r0[c] - (r1[c] if c in r1 else len(cut) + 1)
        if d_score or d_cov or drk:
            rows.append((c, it, jt, d_cov, d_score, r0[c], r1.get(c), drk))
    rows.sort(key=lambda r: (-r[4], r[5]))

    print("  受影响股票 %d 只 / 全池 %d 只" % (len(rows), len(m0)))
    lost = [r for r in rows if r[3] > 0]
    print("  其中「丢掉 1 个覆盖平台」的 %d 只（完全靠 24h 才拿到同花顺这 1 个平台）"
          % len(lost))
    print("  %-8s %-9s %-7s %-7s %-9s %s"
          % ("代码", "名称", "原cover", "新cover", "共振分-Δ", "名次 原->新"))
    for c, it, jt, d_cov, d_score, a, b, drk in rows[:30]:
        print("  %-8s %-9s %-8d %-8d %-10d %d->%s (%+d)"
              % (c, (it["name"] or "")[:8], it["cover"],
                 jt["cover"] if jt else 0, -d_score, a, b if b else "出榜",
                 -(b - a) if b else 0))
    if not rows:
        print("  （剔除 24h 对任何股票都没有影响）")

    line()
    print("[4] 口径提示：24h 不单独成榜，只经「同花顺平台去重 + 取最好名次」生效；")
    print("    边际作用 = ① 给『仅 24h』股票 +1 平台  ② 名次优于 1h 时抬高 ths_rank。")
    line()


if __name__ == "__main__":
    main()
