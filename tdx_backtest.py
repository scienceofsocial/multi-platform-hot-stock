# -*- coding: utf-8 -*-
"""【历史套件 · 五平台口径】本次回测专用 · 严禁作为日常选股依据

本脚本对应旧「五平台人气个股交叉识别」数据集（东方财富/淘股吧/同花顺/财联社/通达信），
与现行「七平台人气共振」日报管线（last_good.json -> 七平台人气共振_通达信排序指标.txt）
不是同一条链路，里面的平台数都是五平台口径。

去掉「五平台人气共振(renqi)」的 8 指标交集回测版。

为什么单独做一个
----------------
五平台人气榜（人气交叉_通达信排序指标.txt）是盘中每 10 分钟刷新的动态
快照，历史日期无法复现，所以含 renqi 的 9 指标交集不可回测。本脚本固定
剔除 renqi，只保留 8 个纯日线、可复现的指标：

    v40x 接力选股V4.0 / v61 多指标共振选股V6.1 / v32 接力选股V3.2
    jz 综合接力分 / qsm 趋势动量 / v40 接力强度V4.0
    v42 多指标共振V4.2 / v34 接力强度V3.4

命中规则与 tdx_paixu 一致：选股类(v32/v40x/v61) score==1；其余 score>0。

通道说明
--------
人气通道现已升级为八平台口径（通达信公式名 RENQI8，见
八平台人气共振_通达信排序指标.txt）。本回测「renqi 不可回测」的结论只取决于
「该通道是盘中动态刷新的快照」，与平台数由 5 增至 8 无关，结论继续成立。

！！ 警 告 ！！
本脚本产出的任何信号 **仅用于本次回测验证**，严禁作为今后的日常选股
依据。日常选股请用：python tdx_paixu.py --formula intersect（含人气）。

用法
----
    python tdx_backtest.py --start 2026-09-08 --end 2026-09-14
    python tdx_backtest.py --start 2026-09-01 --end 2026-09-14 --hold 1,3,5,10

输出
----
    回测_8指标_no人气_{start}_{end}_{N}条.csv
    每行 = 某日命中的一只票；列含 8 个指标值 + 各持有期后验收益%。
"""
import argparse
import os
import time

import numpy as np
import pandas as pd

from tdx_engine import TdxData
from tdx_paixu import FORMULAS, build_series, _hit

DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(DIR, "_cache")

#: 回测参与指标（已剔除 renqi）；顺序=最严格优先，未命中即提前终止
BT_KEYS = ["v40x", "v61", "v32", "jz", "qsm", "v40", "v42", "v34"]

BANNER = ("=" * 70 +
          "\n【回测专用 · 已剔除人气指标 · 严禁用于日常选股】\n"
          "本结果仅用于本次回测验证，不得作为日常交易 / 选股依据。\n" +
          "=" * 70)


def _today():
    return time.strftime("%Y-%m-%d")


def _newest_cache():
    """最新一个 _cache/mkt_*.pkl 的日期标签；无则 None。"""
    if not os.path.isdir(CACHE_DIR):
        return None
    names = sorted(f for f in os.listdir(CACHE_DIR)
                   if f.startswith("mkt_") and f.endswith(".pkl"))
    return names[-1][4:-4] if names else None


def prepare(data):
    """优先复用最新磁盘缓存；无缓存则联网全市场预取并落盘。"""
    key = _newest_cache()
    if key and os.path.exists(os.path.join(CACHE_DIR, f"mkt_{key}.pkl")):
        data.load_cache(key)
        print(f"[数据] 复用磁盘缓存 _cache/mkt_{key}.pkl（不再联网取数）", flush=True)
        return

    print("[数据] 无可用缓存，联网全市场预取（较慢）…", flush=True)
    data.load_cache(_today())            # 仅用于设置落盘路径
    t0 = time.time()
    stocks = data.stocks()
    for i, (mkt, code, _name) in enumerate(stocks, 1):
        if i % 500 == 0 or i == len(stocks):
            print(f"  预取 {i}/{len(stocks)}  {time.time() - t0:.0f}s", flush=True)
        try:
            data.bars(mkt, code)
            data.ltg(mkt, code)
        except Exception:
            pass
    data.index_df(1)
    data.index_df(0)
    data.save_cache()


def trading_days(data, start, end):
    """用上证指数K线日期作交易日历，取 [start, end] 内的交易日。"""
    idx = data.index_df(1)
    return [d for d in idx["date"].astype(str).tolist() if start <= d <= end]


def scan_day(data, day, stocks):
    """当日在 8 指标上全部命中的 [(mkt, code, name, scores), ...]。"""
    hits = []
    for mkt, code, name in stocks:
        try:
            s = build_series(data, mkt, code, name, day)
        except Exception:
            continue
        if s is None:
            continue
        scores, ok = {}, True
        try:
            for k in BT_KEYS:
                score, _ = FORMULAS[k][1](s)
                scores[k] = score
                if not _hit(k, score):
                    ok = False
                    break
        except Exception:
            continue
        if ok:
            hits.append((mkt, code, name, scores))
    return hits


def fwd_return(data, mkt, code, day, holds):
    """命中日收盘 → 后 N 个交易日收盘的涨跌幅%；缺数据返回 None。"""
    df = data.bars(mkt, code)
    dates = df["date"].astype(str).to_numpy()
    pos = int(np.searchsorted(dates, day))
    if pos >= len(dates) or dates[pos] != day:
        return None                       # 当日停牌 / 无K线
    c0 = float(df["close"].iloc[pos])
    if c0 <= 0:
        return None
    out = {}
    for h in holds:
        j = pos + h
        out[h] = ((float(df["close"].iloc[j]) / c0 - 1.0) * 100.0
                  if j < len(df) else np.nan)
    return out


def main():
    ap = argparse.ArgumentParser(
        description="8 指标（去人气）交集回测 —— 仅限本次测试，严禁日常选股")
    ap.add_argument("--start", required=True, help="起始交易日 YYYY-MM-DD")
    ap.add_argument("--end", default=None, help="结束交易日 YYYY-MM-DD；缺省=start")
    ap.add_argument("--hold", default="1,3,5",
                    help="持有期（交易日），逗号分隔；留空=不算后验收益")
    ap.add_argument("--limit", type=int, default=0, help="只跑前 N 只（调试用）")
    ap.add_argument("--out", default=None, help="输出 CSV 路径；缺省自动命名")
    args = ap.parse_args()

    print(BANNER, flush=True)
    end = args.end or args.start
    holds = [int(x) for x in args.hold.split(",") if x.strip().isdigit()]

    data = TdxData(use_cache=True)
    data.connect()
    try:
        prepare(data)
        days = trading_days(data, args.start, end)
        if not days:
            print(f"  [无交易日] {args.start} ~ {end} 不在指数K线范围内", flush=True)
            return
        stocks = data.stocks()
        if args.limit:
            stocks = stocks[:args.limit]
        print(f"回测区间 {days[0]} ~ {days[-1]}（{len(days)} 个交易日）｜"
              f"股票池 {len(stocks)} 只｜持有期 {holds or '不计算'}\n", flush=True)

        rows, t0 = [], time.time()
        for di, day in enumerate(days, 1):
            hits = scan_day(data, day, stocks)
            print(f"  [{di}/{len(days)}] {day}  命中 {len(hits)} 只  "
                  f"{time.time() - t0:.0f}s", flush=True)
            for mkt, code, name, scores in hits:
                row = {"日期": day, "代码": code, "名称": name}
                for k in BT_KEYS:
                    row[FORMULAS[k][0]] = scores.get(k)
                fr = fwd_return(data, mkt, code, day, holds) if holds else None
                for h in holds:
                    v = fr.get(h) if fr else None
                    row[f"{h}日%"] = (None if v is None or np.isnan(v)
                                      else round(v, 2))
                rows.append(row)
    finally:
        data.disconnect()

    if not rows:
        print("\n  回测区间内无任何命中", flush=True)
        return

    df = pd.DataFrame(rows).sort_values(["日期", "代码"]).reset_index(drop=True)
    out = args.out or os.path.join(
        DIR, f"回测_8指标_no人气_{days[0]}_{days[-1]}_{len(df)}条.csv")
    df.to_csv(out, index=False, encoding="utf-8-sig")
    print(f"\n已输出 {out}（{len(df)} 条命中）", flush=True)

    print("\n每日命中数：")
    print(df.groupby("日期").size().to_string())

    if holds:
        print("\n后验收益（%，命中日收盘买入）：")
        print(f"{'持有期':<8}{'样本':>6}{'均值':>9}{'中位数':>9}{'胜率':>9}")
        print("-" * 41)
        for h in holds:
            c = df[f"{h}日%"].dropna()
            if c.empty:
                print(f"{h}日{'':<6}{0:>6}")
                continue
            print(f"{h}日{'':<6}{len(c):>6}{c.mean():>9.2f}"
                  f"{c.median():>9.2f}{(c > 0).mean() * 100:>8.1f}%")


if __name__ == "__main__":
    main()
