# -*- coding: utf-8 -*-
"""AIStudio 常驻定时任务：每天固定时刻把明细表去重后落库并提交因子。

沿用 ``定时任务案列演示.txt`` 的 ``wait_until`` 范式——**进程必须一直开着**：
关闭 AIStudio 会话或停止本进程后，任务不再执行。

每次触发都调一次 ``a_duopingtai_hot_factor.py``：

* 缺省（``--from-csv``）：直接用已落盘的明细表 -> 重复日期数据检查（同一
  ``(date, instrument)`` 只保留一行，多余行删除）-> 落库 ``alpha_duopingtai_hot_factor_data``
  -> 提交因子 ``alpha_duopingtai_hot_factor``
* 加 ``--from-snapshot``：改成读快照 ``last_good.json`` 走完整流程——先把当日明细
  **追加**进 CSV（同口径日整日以本次为准，其余日期保留）-> 去重 -> 落库 -> 提交

用法
----
    python a_daily_schedule.py                      # 每天 16:30 执行（收盘后，口径日=当天）
    python a_daily_schedule.py --time 09:30         # 改成每天 09:30
    python a_daily_schedule.py --run-now            # 启动先立刻跑一次，再进入定时循环
    python a_daily_schedule.py --from-snapshot      # 先追加读快照，再落库提交
    python a_daily_schedule.py --csv /path/x.csv --snapshot /path/y.json   # 自定义路径
"""

import argparse
import datetime as dt
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
FACTOR_SCRIPT = os.path.join(HERE, "a_duopingtai_hot_factor.py")

#: 常驻脚本要把日志实时刷出来（否则重定向时被块缓冲，看不到进展）
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)


def now_str():
    """当前时刻字符串（打印用）。"""
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def run_task(args):
    """调一次因子脚本：追加/去重明细表 -> 落库数据源 -> 提交因子。"""
    cmd = [sys.executable, FACTOR_SCRIPT]
    if args.from_snapshot:
        if args.snapshot:
            cmd += ["--snapshot", args.snapshot]
    else:
        cmd.append("--from-csv")
    if args.csv:
        cmd += ["--out", args.csv]

    print("[%s] 开始执行：%s" % (now_str(), " ".join(cmd)))
    proc = subprocess.run(cmd, cwd=HERE, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    for stream in (proc.stdout, proc.stderr):
        if stream and stream.strip():
            print(stream.strip())
    if proc.returncode != 0:
        raise RuntimeError("因子脚本退出码 %d" % proc.returncode)
    print("[%s] 执行完成" % now_str())


def wait_until(target_time):
    """等待到每天指定的时间（范例同款：睡到目标时刻后返回）。"""
    while True:
        now = dt.datetime.now()
        target = dt.datetime.combine(now.date(), target_time)
        # 今天的目标时间已过，则等到明天
        if target <= now:
            target += dt.timedelta(days=1)
        seconds = (target - now).total_seconds()
        print("[%s] 下一次运行时间：%s" % (now_str(), target.strftime("%Y-%m-%d %H:%M:%S")))
        time.sleep(seconds)
        return


def parse_time(text):
    """``HH:MM`` -> datetime.time。"""
    try:
        hour, minute = (int(x) for x in text.split(":"))
        return dt.time(hour, minute)
    except Exception:                              # noqa: BLE001
        raise argparse.ArgumentTypeError("时间格式应为 HH:MM，例如 16:30")


def main():
    ap = argparse.ArgumentParser(description="多平台热门股票因子 · AIStudio 常驻定时任务")
    ap.add_argument("--time", type=parse_time, default=dt.time(16, 30),
                    help="每天执行时刻 HH:MM，默认 16:30（收盘后，口径日=当天）")
    ap.add_argument("--run-now", action="store_true", help="启动时先立即执行一次")
    ap.add_argument("--from-snapshot", action="store_true",
                    help="读快照追加明细（缺省则用 --from-csv 只消费已落盘明细）")
    ap.add_argument("--csv", default=None, help="明细 CSV 路径；缺省用脚本内默认值")
    ap.add_argument("--snapshot", default=None, help="快照 JSON 路径；缺省用脚本内默认值")
    args = ap.parse_args()

    if args.run_now:
        try:
            run_task(args)
        except Exception as exc:                    # noqa: BLE001 - 单次失败不退出常驻进程
            print("[%s] 任务执行失败：%s" % (now_str(), exc))

    while True:
        wait_until(args.time)
        try:
            run_task(args)
        except Exception as exc:                    # noqa: BLE001
            print("[%s] 任务执行失败：%s" % (now_str(), exc))
        # 防止任务执行时间跨过下一次调度时间
        time.sleep(1)


if __name__ == "__main__":
    main()
