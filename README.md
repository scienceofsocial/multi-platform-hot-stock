# 多平台热门股票 · 五平台人气共振数据管线

抓取多平台（东方财富 / 淘股吧 / 韭研公社 / 55188 / 通达信等）的人气榜、龙头榜、涨停池，
合成共振分并落地到通达信自定义数据，附每日日报与变化时点分析。

> 本仓库为**代码与文档**托管。数据、日志、运行时 cookie 一律不入库（见 `.gitignore`）。

## 结构

| 文件 | 作用 |
|---|---|
| `a_fetch_hot_snapshot.py` | 主抓取：各平台榜单 -> 快照 `last_good.json` |
| `a_archive_hot_snapshot.py` | 按口径日归档快照 + 变化即追加 `hot_trace.jsonl` |
| `a_duopingtai_hot_factor.py` | 五平台共振分因子面板 |
| `a_export_tdx_hot_rank.py` | 导出通达信自定义数据 `.dat` + 公式 |
| `a_report_daily.py` | 每日日报 |
| `hot_trace_timeline.py` | 龙头榜全天变化时点明细表 |
| `ld_timeline_stats.py` | 变化时点统计（节奏/形态/龙头/只数/选股） |
| `em_cookie.py` | 东方财富 cookie 提取/注入（Playwright） |

## 运行

Windows 计划任务驱动，入口 `run_hot_rank_daily.bat`。详见 `多平台热门股票数据说明.md`。

## 环境

- Python 3.11+（numpy / pandas / playwright / requests）
- 行情数据源：本机通达信 `C:\new_tdx`

## 移植须知（重要）

本仓库的 `.bat` / `.ps1` 里带有**原机器的绝对路径**（Python 解释器、项目目录、通达信目录），
换机器运行前必须改：

| 需要修改 | 原值形式 |
|---|---|
| `.bat` 里的 `set "PY=..."` | `C:\Users\<用户名>\AppData\Local\Programs\Python\Python3xx\python.exe` |
| `.ps1` 里的任务路径 | `$PSScriptRoot` 派生，通常无需改 |
| 通达信数据目录 | 代码常量 `C:\new_tdx\vipdoc` |

计划任务注册：`register_*.ps1`，用 PowerShell `-ExecutionPolicy Bypass -File` 执行。

## 安全说明

- 本仓库**不包含**任何运行时凭证：东财 cookie（`em_cookie.json`，含 `JSESSIONID` 等真实会话）已在 `.gitignore` 中排除。
- 本仓库**不包含** Winlogon 自动登录配置的实际值（文档中以 `<明文密码>` / `<本机域名>` 占位）。
- 抓取脚本里有 `ut=7eea3edc...` 之类参数，那是东方财富**公开 API 的通用参数**（出现在 URL 中），不是会话凭证/密钥。
- 请勿把 `_hot_archive/`（行情轨迹，体积大且含抓取明细）、`out/`、`*.log`、`*.jsonl` 提交进库。

