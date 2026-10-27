# -*- coding: utf-8 -*-
"""【仅测试 · 勿用于日常选股】8 指标交集命中票的「止盈 + 止损」出场模拟。

输入：bt_intersect8.py 的输出 CSV（8 指标交集命中名单，任意信号日数）
      —— 只关心 信号日/次日日期，不重跑选股。
      * T+1 买入日 = 信号日的次日（市场交易日历，取 CSV 的「次日日期」列）
      * T+2 卖出日 = 买入日之后该票自身的下一根日K
      持有时长恒为「T+1 开盘买 → T+2 收盘卖」，不依赖 CSV 里可能过期的
      买入日/卖出日/持有到T+2收盘% 列（一律自算，保证新旧样本口径一致）。

出场模型（T+1 开盘买入 → 最晚 T+2 收盘卖出）
--------------------------------------------
* 止损：任一时点价格 <= 买入价*(1-止损%) → 以该价卖出；
        若为跳空低开（开盘价已低于止损线）则以开盘价卖出（更差）。
* 止盈：自买入后累计涨幅先达到「激活%」，之后自峰值回撤「回撤%」→ 卖出。
        卖出价取触发线 峰值*(1-回撤%)。
* 未触发任何条件 → T+2 收盘卖出。

一字板标注（买入日）：最低价 == 收盘价 才算一字板；最低价与收盘价不是一个数字
即视为盘中离开过收盘价（涨停价），判定「可以被买入」，不作一字板处理。仅标注，不剔除。

日K无法还原日内先后顺序，按「开盘→最高→最低→收盘」假定（先冲高后回落），
故同一根K内同时满足止盈/止损时按先触发止盈处理（较乐观）。

用法
----
    python bt_exit_sim.py                  # 默认场景对比 + 止损-5% 网格
    python bt_exit_sim.py --act 4 --retr 1 --sl 5   # 单场景明细
"""
import argparse
import os

import numpy as np
import pandas as pd

from tdx_engine import TdxData

DIR = os.path.dirname(os.path.abspath(__file__))


def pick_input():
    """自动挑选样本 CSV：优先大样本（22 日），其次一周样本。"""
    for fn in ("回测_交集8指标_22日_仅测试.csv",
               "回测_交集8指标_一周_2026-09-11_22笔_仅测试.csv"):
        p = os.path.join(DIR, fn)
        if os.path.exists(p):
            return p
    raise SystemExit("未找到样本 CSV，请用 --in 指定")


def mkt_of(code):
    return 1 if code.startswith(("60", "68")) else 0


def zt_line(code):
    """涨停线 %：与 V4.0 公式口径一致（创业/科创19.5、北交所29.5、其余9.5）。"""
    if code.startswith(("300", "301", "302", "688", "689")):
        return 19.5
    if code.startswith("8"):
        return 29.5
    return 9.5


def load_cases(src, data):
    """读样本 CSV → 逐笔装配 (信号日, T+1买入日, T+2卖出日, 日K路径)。

    返回 (recs, skip)。recs 每笔含 path=[(o,h,l,c), (o,h,l,c)]，
    t2 = 持到 T+2 收盘的收益%（基准口径），gapzt/yz 由信号日收盘价重算。
    """
    df = pd.read_csv(src, encoding="utf-8-sig", dtype={"代码": str})
    df = df.rename(columns={"代码": "code", "名称": "name", "信号日": "sig",
                            "次日日期": "nextbuy"})
    recs, skip = [], []
    for row in df.itertuples(index=False):
        code = str(row.code).strip()
        if not (code.isdigit() and len(code) == 6):
            code = code.zfill(6)
        name = str(getattr(row, "name", ""))
        sig = str(row.sig)[:10]
        buy = str(row.nextbuy)[:10]
        try:
            bars = data.bars(mkt_of(code), code)
        except Exception:
            skip.append((code, name, "取不到日K"))
            continue
        pos = {d: j for j, d in enumerate(bars["date"])}
        k, i = pos.get(sig), pos.get(buy)
        if i is None or i + 1 >= len(bars):
            skip.append((code, name, f"缺 {buy} 或其后行情"))
            continue
        j = i + 1                                    # T+2 = 买入日的下一根K
        path = [(float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"]))
                for _, r in bars.iloc[i:j + 1].iterrows()]
        buy_px = path[0][0]
        if not buy_px > 0:
            skip.append((code, name, "买入价无效"))
            continue
        t2 = (path[-1][3] / buy_px - 1.0) * 100.0
        gapzt, yz = 0, 0                             # 开盘涨停/一字板（仅标注，不剔除）
        if k is not None and i == k + 1:
            c0 = float(bars["close"].iloc[k])
            if c0 > 0 and (buy_px / c0 - 1.0) * 100.0 >= zt_line(code) - 0.3:
                # 一字板 = 买入日 最低价 == 收盘价（全天未离开收盘价=涨停价）；
                # 最低价 != 收盘价 说明盘中离开过，判定「可以被买入」，不作一字板。
                gapzt, yz = 1, int(path[0][2] == path[0][3])
        recs.append({"code": code, "name": name, "sig": sig, "buy": buy,
                     "gapzt": gapzt, "yz": yz, "t2": t2, "path": path})
    return recs, skip


def simulate(path, act, retr, sl):
    """逐日出场模拟。

    path: [(o,h,l,c), ...] 自买入日到 T+2；返回 (收益%, 出场日序号, 方式)。
    act/retr/sl 单位均为 %；act>=999 表示不启用止盈，sl<=0 表示不启用止损。
    """
    buy = float(path[0][0])
    if not buy > 0:
        return None
    peak = buy
    act_price = buy * (1.0 + act / 100.0)
    tp_keep = 1.0 - retr / 100.0
    sl_price = buy * (1.0 - sl / 100.0) if sl and sl > 0 else None

    for k, (o, h, l, c) in enumerate(path):
        for tag, p in (("o", o), ("h", h), ("l", l), ("c", c)):
            if p is None or np.isnan(p):
                continue
            if p > peak:
                peak = p
            if peak >= act_price and p <= peak * tp_keep:
                return (peak * tp_keep / buy - 1.0) * 100.0, k, "止盈"
            if sl_price is not None and p <= sl_price:
                fill = float(o) if (tag == "o" and k > 0) else sl_price
                return (fill / buy - 1.0) * 100.0, k, "止损"
    c_last = float(path[-1][3])
    return (c_last / buy - 1.0) * 100.0, len(path) - 1, "T+2收盘"


def summarize(tag, rets, n_all, n_trade):
    r = np.asarray(rets, dtype=float)
    if r.size == 0:
        return
    print(f"{tag:<26} {r.size:>3}笔  均值 {r.mean():+7.2f}%  "
          f"胜率 {(r > 0).mean() * 100:>3.0f}%  中位 {np.median(r):+7.2f}%  "
          f"最好 {r.max():+7.2f}%  最差 {r.min():+7.2f}%")


def main():
    ap = argparse.ArgumentParser(description="【仅测试】8指标交集 止盈/止损 出场模拟")
    ap.add_argument("--in", dest="src", default=None, help="输入 CSV；缺省自动挑选")
    ap.add_argument("--act", type=float, default=None, help="激活%")
    ap.add_argument("--retr", type=float, default=None, help="回撤%")
    ap.add_argument("--sl", type=float, default=None, help="止损%")
    ap.add_argument("--grid", action="store_true", help="跑 激活x回撤 网格（止损固定）")
    args = ap.parse_args()

    src = args.src or pick_input()
    print("=" * 78)
    print("【仅测试】8 指标交集命中票 出场模拟｜⚠ 结果不得用于日常选股")
    print(f"输入 {os.path.basename(src)}")
    print("=" * 78)

    data = TdxData(use_cache=False)
    data.connect()
    try:
        recs, skip = load_cases(src, data)
        if skip:
            head = "、".join(f"{c} {n}({w})" for c, n, w in skip[:6])
            print(f"  跳过 {len(skip)} 笔：{head}{' …' if len(skip) > 6 else ''}")
        print(f"可交易类目 {len(recs)} 笔（其中开盘涨停 {sum(r['gapzt'] for r in recs)} 笔、"
              f"一字板 {sum(r['yz'] for r in recs)} 笔——仅标注，能否成交由使用者自行判断，"
              f"全部计入统计）")

        trade = list(recs)                           # 可交易类目 = 全部命中样本
        print(f"\n可交易类目 {len(trade)} 笔（开盘涨停/一字板一律计入，不再剔除）\n")

        # ---------------- 场景对比 ----------------
        scenes = [
            ("持到T+2收盘(基准)", 999, 0.0, 0.0),
            ("止损-5%", 999, 0.0, 5.0),
            ("止盈+4%/1%", 4.0, 1.0, 0.0),
            ("止盈+4%/1% + 止损-5%", 4.0, 1.0, 5.0),
            ("止盈+3%/0.5%", 3.0, 0.5, 0.0),
            ("止盈+3%/0.5% + 止损-5%", 3.0, 0.5, 5.0),
            ("止盈+2%/0.5% + 止损-5%", 2.0, 0.5, 5.0),
        ]
        print("------ 场景对比（可交易类目） ------")
        for tag, a, rt, s in scenes:
            summarize(tag, [simulate(r["path"], a, rt, s)[0] for r in trade],
                      len(recs), len(trade))

        # ---------------- 分信号日：检验是否单日驱动 ----------------
        best_scene = ("止盈+2%/0.5% + 止损-5%", 2.0, 0.5, 5.0)
        bys = {}
        for r in trade:
            bys.setdefault(r["sig"], []).append(r)
        print(f"\n------ 分信号日：基准(持到T+2收盘) vs {best_scene[0]} ------")
        print(f"{'信号日':<12}{'笔数':>5}{'基准均值':>10}{'规则均值':>10}{'差值':>9}")
        wins = 0
        for d in sorted(bys):
            g = bys[d]
            b = np.mean([simulate(r["path"], 999, 0.0, 0.0)[0] for r in g])
            v = np.mean([simulate(r["path"], *best_scene[1:])[0] for r in g])
            wins += int(v > b)
            print(f"{d:<12}{len(g):>5}{b:>10.2f}{v:>10.2f}{v - b:>9.2f}")
        print(f"  规则优于基准的信号日：{wins}/{len(bys)}")

        # ---------------- 单场景明细 ----------------
        if args.act is not None:
            a, rt, s = args.act, args.retr or 0.0, args.sl or 0.0
            print(f"\n------ 明细：激活{a}% / 回撤{rt}% / 止损{s or '无'}% ------")
            print(f"{'代码':<7}{'名称':<10}{'信号日':<11}{'出场日':<11}"
                  f"{'方式':<10}{'收益%':>8}{'T+2收盘%':>10}")
            for r in recs:
                ret, k, why = simulate(r["path"], a, rt, s)
                exit_day = ["T+1(买入)", "T+2"][k] if k < 2 else f"+{k}"
                print(f"{r['code']:<7}{r['name']:<10}{r['sig']:<11}{exit_day:<11}"
                      f"{why:<10}{ret:>8.2f}{r['t2']:>10.2f}")
            return

        # ---------------- 网格（止损固定 -5%） ----------------
        sl = args.sl if args.sl is not None else 5.0
        print(f"\n------ 参数网格：止损固定 -{sl:g}%（可交易类目 {len(trade)} 笔） ------")
        hdr = "激活/回撤"
        print(f"{hdr:<10}" + "".join(f"{rt:>8.1f}%" for rt in
              (0.5, 0.8, 1.0, 1.5, 2.0, 3.0)))
        print("-" * 62)
        best = None
        for a in (2.0, 3.0, 4.0, 5.0, 6.0, 7.0):
            cells = []
            for rt in (0.5, 0.8, 1.0, 1.5, 2.0, 3.0):
                rr = np.array([simulate(r["path"], a, rt, sl)[0] for r in trade])
                cells.append(rr.mean())
                if best is None or rr.mean() > best[0]:
                    best = (rr.mean(), a, rt, (rr > 0).mean() * 100,
                            rr.min(), rr.max())
            print(f"{a:>7.0f}%  " + "".join(f"{v:>9.2f}" for v in cells))
        m, a, rt, wr, mn, mx = best
        print(f"\n最优：激活 +{a:g}% / 回撤 {rt:g}% / 止损 -{sl:g}% → "
              f"均值 {m:+.2f}%、胜率 {wr:.0f}%、最差 {mn:+.2f}%、最好 {mx:+.2f}%")

        # 出场方式分布（最优参数）
        ways = {}
        for r in trade:
            _, _, why = simulate(r["path"], a, rt, sl)
            ways[why] = ways.get(why, 0) + 1
        print("出场方式分布：" + "、".join(f"{k} {v}笔" for k, v in ways.items()))
        print("\n⚠ 仅本次测试，日常选股请用 tdx_paixu.py 的 9 指标交集。")
    finally:
        data.disconnect()


if __name__ == "__main__":
    main()
