# -*- coding: utf-8 -*-
"""临时脚本（非管线）：百度热搜「命中 vs 未命中」前瞻收益粗看。

窗口 = 百度真榜可回补的 7 个交易日（2026-09-15 ~ 09-23）。
命中组 = 当日百度热搜 A 股前 10；对照组 = 当日全市场未命中个股。
前瞻收益 = 当日收盘 -> 后 1/3/5 个交易日收盘涨跌幅%（与 tdx_backtest.fwd_return 同口径）。

仅为定性粗看，不做统计检验。右侧缺失（窗口末端无未来K线）一律记 NaN。
"""
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from a_fetch_hot_snapshot import BAIDU_URL, BAIDU_HEADERS, BAIDU_TOP_N, norm_code  # noqa: E402
from tdx_engine import TdxData                                                      # noqa: E402

DAYS = ["2026-09-15", "2026-09-16", "2026-09-17", "2026-09-18",
        "2026-09-21", "2026-09-22", "2026-09-23"]
HOLDS = [1, 3, 5]
#: 次新股阈值：命中日时该股本地K线不足此数则视为次新（其涨跌幅不受涨跌停约束，单独看一版）
NEW_BARS = 20


def fetch_baidu(day):
    """按口径日回补百度热搜前 10 -> {统一代码: 名次}。"""
    from curl_cffi import requests as cr
    url = BAIDU_URL.format(day=day.replace("-", ""))
    resp = cr.get(url, headers=BAIDU_HEADERS, impersonate="chrome", timeout=20)
    resp.raise_for_status()
    data = resp.json() or {}
    body = ((data.get("Result") or {}).get("list") or {}).get("body") or []
    out = {}
    for idx, item in enumerate(body[:BAIDU_TOP_N]):
        item = item or {}
        code = norm_code(item.get("code"), item.get("exchange"))
        if code:
            out[code] = {"rank": idx + 1, "name": str(item.get("name") or "").strip()}
    return out


def fwd(df, day, holds):
    """当日收盘 -> 后 N 交易日收盘涨跌幅%；缺当日/越界记 None/NaN。"""
    dates = df["date"].astype(str).to_numpy()
    pos = int(np.searchsorted(dates, day))
    if pos >= len(dates) or dates[pos] != day:
        return None, pos
    c0 = float(df["close"].iloc[pos])
    if c0 <= 0:
        return None, pos
    out = {}
    for h in holds:
        j = pos + h
        out[h] = ((float(df["close"].iloc[j]) / c0 - 1.0) * 100.0
                  if j < len(dates) else np.nan)
    return out, pos


def stat(vals):
    s = pd.Series(vals, dtype=float).dropna()
    if s.empty:
        return None
    return {"n": len(s), "mean": s.mean(), "median": s.median(),
            "win": (s > 0).mean() * 100.0}


def fmt(tag, h, st):
    if st is None:
        return f"  {tag:<8}{h}日{'':<4}{'-':>6}{'-':>10}{'-':>10}{'-':>10}"
    return (f"  {tag:<8}{h}日{'':<4}{st['n']:>6}{st['mean']:>10.2f}"
            f"{st['median']:>10.2f}{st['win']:>9.1f}%")


def main():
    print("=" * 78)
    print("百度热搜命中/未命中 · 前瞻收益粗看（定性，非统计检验）")
    print("=" * 78, flush=True)

    print("\n[1/3] 回补百度热搜前 10 …", flush=True)
    hits_by_day = {}
    for d in DAYS:
        try:
            hits_by_day[d] = fetch_baidu(d)
            names = "/".join(v["name"] for v in hits_by_day[d].values())
            print(f"  {d}  {len(hits_by_day[d])} 只：{names}", flush=True)
        except Exception as exc:                            # noqa: BLE001
            print(f"  {d}  抓取失败：{exc}", flush=True)
            hits_by_day[d] = {}

    # 交叉校验 09-23 与 last_good.json
    try:
        import json
        with open(os.path.join(HERE, "last_good.json"), "r", encoding="utf-8") as fh:
            snap = json.load(fh)
        if str(snap.get("date")) == "2026-09-23" and snap.get("baidu"):
            same = set(snap["baidu"]) == set(hits_by_day.get("2026-09-23", {}))
            print(f"  [校验] 09-23 与 last_good.json 命中集合一致：{same}", flush=True)
    except Exception as exc:                                # noqa: BLE001
        print(f"  [校验] 跳过：{exc}", flush=True)

    print("\n[2/3] 加载本地行情 …", flush=True)
    data = TdxData(use_cache=True)
    data.connect()
    try:
        stocks = data.stocks()
        by_code = {code: (mkt, name) for mkt, code, name in stocks}
        print(f"  股票池 {len(stocks)} 只", flush=True)

        # hit[day][h] / miss[day][h]；new_* 为剔除次新后的同一统计
        acc = {k: {d: {h: [] for h in HOLDS} for d in DAYS}
               for k in ("hit", "miss", "hit_nn", "miss_nn")}
        hit_detail = []

        print("\n[3/3] 逐股计算前瞻收益 …", flush=True)
        for i, (mkt, code, name) in enumerate(stocks, 1):
            if i % 1000 == 0:
                print(f"    {i}/{len(stocks)}", flush=True)
            try:
                df = data.bars(mkt, code, 0)
            except Exception:                               # noqa: BLE001
                continue
            if df is None or len(df) < 2:
                continue
            fcode = ("SH" if mkt == 1 else "SZ") + code
            for d in DAYS:
                fr, pos = fwd(df, d, HOLDS)
                if fr is None:
                    continue
                fresh = pos + 1 < NEW_BARS        # 截至该日K线不足 20 根 -> 次新
                hid = fcode in hits_by_day.get(d, {})
                grp = "hit" if hid else "miss"
                for h in HOLDS:
                    acc[grp][d][h].append(fr[h])
                    if not fresh:
                        acc[grp + "_nn"][d][h].append(fr[h])
                if hid:
                    hit_detail.append({"日期": d, "代码": fcode, "名称": name,
                                       "百度名次": hits_by_day[d][fcode]["rank"],
                                       "次新": "是" if fresh else ""} |
                                      {f"{h}日%": (None if np.isnan(fr[h]) else round(fr[h], 2))
                                       for h in HOLDS})
    finally:
        data.disconnect()

    # ---------------- 输出 ----------------
    print("\n" + "=" * 78)
    print("A. 汇总（全部命中日合并；'未命中' = 全市场非前10；'剔除次新' = 该日K线>=20根）")
    print("=" * 78)
    for label, hk, mk in (("全部个股", "hit", "miss"),
                          ("剔除次新", "hit_nn", "miss_nn")):
        print(f"\n[{label}]")
        print(f"  {'组':<8}{'期':<5}{'样本':>6}{'均值':>10}{'中位数':>10}{'胜率':>10}")
        print("  " + "-" * 49)
        for h in HOLDS:
            hv = [v for d in DAYS for v in acc[hk][d][h]]
            mv = [v for d in DAYS for v in acc[mk][d][h]]
            print(fmt("命中", h, stat(hv)))
            print(fmt("未命中", h, stat(mv)))
        print("  【命中 - 未命中 均值差（pct）】" +
              "  ".join(
                  f"{h}日:{((stat([v for d in DAYS for v in acc[hk][d][h]]) or {}).get('mean', float('nan')) - (stat([v for d in DAYS for v in acc[mk][d][h]]) or {}).get('mean', float('nan'))):+.2f}"
                  for h in HOLDS))

    print("\n" + "=" * 78)
    print("B. 逐日（命中组 vs 未命中组，均值%）")
    print("=" * 78)
    print(f"  {'日期':<12}{'命中n':>6}" +
          "".join(f"{f'命中{h}日':>10}{f'未命中{h}日':>11}" for h in HOLDS))
    print("  " + "-" * 72)
    for d in DAYS:
        hs = stat([v for h in HOLDS for v in acc["hit"][d][h]])  # 仅用于取 n
        n_hit = len(pd.Series(acc["hit"][d][HOLDS[0]], dtype=float).dropna())
        line = f"  {d:<12}{n_hit:>6}"
        for h in HOLDS:
            hs = stat(acc["hit"][d][h])
            ms = stat(acc["miss"][d][h])
            line += (f"{(hs['mean'] if hs else float('nan')):>10.2f}"
                     f"{(ms['mean'] if ms else float('nan')):>11.2f}")
        print(line)

    if hit_detail:
        out = os.path.join(HERE, f"百度命中_前瞻收益粗看_{DAYS[0]}_{DAYS[-1]}.csv")
        pd.DataFrame(hit_detail).to_csv(out, index=False, encoding="utf-8-sig")
        print(f"\n已输出命中明细 {out}（{len(hit_detail)} 条）")

    print("\n提示：09-23 无未来K线，1/3/5 日前瞻均为 NaN；样本极小，仅供方向性参考。")


if __name__ == "__main__":
    main()
