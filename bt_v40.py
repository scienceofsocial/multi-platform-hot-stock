# -*- coding: utf-8 -*-
"""V4.0 盘后选股 · 一周回测。

信号日取最近 N 个交易日（默认 5，且必须有次日行情）。每日用「截至该日
收盘」的K线跑 tdx_paixu.f_v40（强度分 0~150）与 f_v40x（选股 选中=1），
再按次日真实行情评估收益——公式只用 upto 截断后的K线，无未来函数。

评估口径（盘后选股 → 次日执行）
-------------------------------
* 开盘买→收盘卖 : (次日收盘/次日开盘-1)*100    ← 主口径（可执行）
* 昨收→次收     : (次日收盘/信号日收盘-1)*100   （含跳空，参考）
* 开盘买→次高   : (次日最高/次日开盘-1)*100    （日内理论上限）

可交易类目：全部命中样本一律算「可交易」——开盘涨停 / 一字板也不例外。
它们只作标注（能否挂单成交由使用者自行判断），不再剔除、不再单独降级统计。

一字板判定（买入日）：最低价 == 收盘价 才算一字板（全天未曾低于收盘价）。
若最低价与收盘价不是一个数字，说明盘中价格离开过收盘价（涨停价），
判定为「可以被买入」，不作为一字板处理。

用法
----
    python bt_v40.py                 # 最近 5 个可评估交易日
    python bt_v40.py --days 10
    python bt_v40.py --limit 300     # 调试
"""
import argparse
import os
import time

import numpy as np
import pandas as pd

import tdx_paixu as P
from tdx_engine import TdxData, StockSeries

DIR = os.path.dirname(os.path.abspath(__file__))


def zt_line(code):
    """涨停线 %：与 V4.0 公式口径一致（创业/科创19.5、北交所29.5、其余9.5）。"""
    if code.startswith(("300", "301", "302", "688", "689")):
        return 19.5
    if code.startswith("8"):
        return 29.5
    return 9.5


def main():
    ap = argparse.ArgumentParser(description="V4.0 盘后选股 一周回测")
    ap.add_argument("--days", type=int, default=5, help="回测信号日数（默认5）")
    ap.add_argument("--limit", type=int, default=0, help="只跑前 N 只（调试用）")
    ap.add_argument("--out", default=None, help="输出 CSV；缺省自动命名")
    args = ap.parse_args()

    data = TdxData(use_cache=False)
    data.connect()
    try:
        dates = list(data.index_df(1)["date"])
        dates = dates[-args.days - 1:]
        sig_days = dates[:-1]
        next_of = {d: dates[i + 1] for i, d in enumerate(dates[:-1])}
        print(f"信号日 {sig_days[0]} ~ {sig_days[-1]}（{len(sig_days)} 天）"
              f"；末日 {dates[-1]} 仅作次日行情", flush=True)

        stocks = data.stocks()
        if args.limit:
            stocks = stocks[:args.limit]

        recs, t0, fail = [], time.time(), 0
        for i, (mkt, code, name) in enumerate(stocks, 1):
            if i % 200 == 0 or i == len(stocks):
                print(f"  {i}/{len(stocks)}  {time.time() - t0:.0f}s", flush=True)
            try:
                df = data.bars(mkt, code)
                if len(df) < StockSeries.MIN_BARS:
                    continue
                ltg = data.ltg(mkt, code)
                idf = data.index_df(mkt)
            except Exception:
                fail += 1
                continue
            pos = {d: j for j, d in enumerate(df["date"])}
            zt = zt_line(code)
            for d in sig_days:
                j = pos.get(d)
                if j is None or j + 1 >= len(df):
                    continue
                sub = df.iloc[:j + 1]
                if len(sub) < StockSeries.MIN_BARS:
                    continue
                s = StockSeries(code, name, sub, ltg, idf)
                try:
                    sc, _ = P.f_v40(s)
                    _, det = P.f_v40x(s)
                except Exception:
                    continue
                if not det.get("选中"):
                    continue
                c0 = float(df["close"].iloc[j])
                nx = df.iloc[j + 1]
                o1, h1, l1, c1 = (float(nx["open"]), float(nx["high"]),
                                  float(nx["low"]), float(nx["close"]))
                if c0 <= 0 or o1 <= 0:
                    continue
                gap = (o1 / c0 - 1.0) * 100.0
                recs.append({
                    "信号日": d, "代码": code, "名称": name,
                    "强度分": sc, "信号日连板": det.get("连板"),
                    "次日日期": next_of[d],
                    "开盘涨幅%": round(gap, 3),
                    "开盘买→收盘卖%": round((c1 / o1 - 1.0) * 100.0, 3),
                    "昨收→次收%": round((c1 / c0 - 1.0) * 100.0, 3),
                    "开盘买→次高%": round((h1 / o1 - 1.0) * 100.0, 3),
                    "开盘涨停": int(gap >= zt - 0.3),
                    # 最低价 != 收盘价 = 盘中离开过收盘价(涨停价) = 可买入
                    "一字板": int(gap >= zt - 0.3 and l1 == c1),
                })

        if not recs:
            print("  无入选记录")
            return
        df = pd.DataFrame(recs).sort_values(
            ["信号日", "强度分"], ascending=[True, False]).reset_index(drop=True)
        out = args.out or os.path.join(
            DIR, f"回测_V4.0_一周_{sig_days[-1]}_{len(df)}笔.csv")
        df.to_csv(out, index=False, encoding="utf-8-sig")

        pd.set_option("display.width", 220)
        pd.set_option("display.unicode.east_asian_width", True)
        for d, g in df.groupby("信号日"):
            print(f"\n=== {d} 入选 {len(g)} 只 → 次日 {g['次日日期'].iloc[0]} ===")
            print(g[["代码", "名称", "强度分", "信号日连板", "开盘涨幅%",
                     "开盘买→收盘卖%", "昨收→次收%"]].to_string(index=False))
            r = g["开盘买→收盘卖%"]
            print(f"  等权均值 {r.mean():+.2f}%  胜率 {(r > 0).mean() * 100:.0f}%"
                  f"  最好 {r.max():+.2f}%  最差 {r.min():+.2f}%"
                  f"  | 可交易类目（全部计入；其中开盘涨停 {int(g['开盘涨停'].sum())} "
                  f"只 / 一字板 {int(g['一字板'].sum())} 只）")

        print("\n================ 汇总 ================")
        print(f"可交易类目 {len(df):>4}笔  （含开盘涨停 {int(df['开盘涨停'].sum())} 只 / "
              f"一字板 {int(df['一字板'].sum())} 只，均计入统计）")
        for lab, sub in (("选股名单", df),
                         ("强度分Top5/日", df.groupby("信号日", group_keys=False)
                          .apply(lambda g: g.nlargest(5, "强度分")))):
            if sub.empty:
                continue
            r = sub["开盘买→收盘卖%"]
            print(f"{lab:<14} {len(sub):>4}笔  均值 {r.mean():+.2f}%  "
                  f"胜率 {(r > 0).mean() * 100:.0f}%  最好 {r.max():+.2f}%  "
                  f"最差 {r.min():+.2f}%  昨收→次收均值 {sub['昨收→次收%'].mean():+.2f}%")
        print(f"\n已输出 {out}")
    finally:
        data.disconnect()


if __name__ == "__main__":
    main()
