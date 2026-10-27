# -*- coding: utf-8 -*-
"""韭研公社「异动图」红股抓取（人气共振第 7 平台 · 只贡献覆盖平台数）。

数据来源：韭研公社异动页 https://www.jiuyangongshe.com/action/<日期> 的「异动图」
          （diagram-url 接口返回的 PNG）；图中**红色**股票 = 当日强势异动股。
          接口需登录态，cookie 从本机 Chrome/Edge 解密读出（浏览器 v80+ AES-GCM）。

口径
----
韭研红股**没有 1~20 名次**，故只贡献「覆盖平台数 +1」，rank_score 记 0
（快照里的 jygs 条目不带 rank 字段，不虚报名次）。

缓存
----
按口径日缓存 ``jygs_red_cache.json``：当日首次抓取 + OCR 后写入，之后同一口径日
直接复用（近零开销）。抓取/识别失败时沿用该口径日已有缓存，**从不抛异常**
（绝不阻塞其他 6 个平台）。

用法
----
    python a_fetch_jygs_red.py                    # 抓今天（带缓存复用）
    python a_fetch_jygs_red.py --date 2026-09-22  # 指定口径日
    python a_fetch_jygs_red.py --force            # 忽略缓存强制重抓
    python a_fetch_jygs_red.py --show             # 只打印缓存内容，不抓取

依赖：requests / playwright / opencv-python / numpy / rapidocr-onnxruntime / cryptography
（重库均为惰性导入，``--show`` 与命中缓存时不会加载）
"""
import argparse
import base64
import ctypes
import ctypes.wintypes as wt
import datetime as dt
import json
import os
import re
import sqlite3
import sys
import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_NAME = "jygs_red_cache.json"
CACHE_PATH = os.path.join(_DIR, CACHE_NAME)
DIAGRAM_NAME = "jygs_diagram.png"

ACTION_URL = "https://www.jiuyangongshe.com/action"
API_HOST = "web-api.jiuyangongshe.com"
UUID_PNG = re.compile(r"https://cdn\.jiuyangongshe\.com/[0-9A-F-]{36}\.png", re.I)
#: 从目标日起往前回退探测的天数（非交易日/无图日自动跳过）
LOOKBACK_DAYS = 10
#: 异动页的「涨停简图」页签。该页签在盘中（9:00~19:59）不是默认页签，
#: 页面在此时段**不会**请求 diagram-url，必须显式点开才会触发。
DIAGRAM_TAB = "text=涨停简图"

# ------------------------------ 登录态（本机浏览器 cookie 解密） ------------------------------

DOMAIN_FILTER = "jiuyangongshe"
BROWSERS = {
    "chrome": ("LOCALAPPDATA", r"Google\Chrome\User Data"),
    "edge": ("LOCALAPPDATA", r"Microsoft\Edge\User Data"),
}
SAME_SITE = {0: "None", 1: "Lax", 2: "Strict"}
#: Chrome cookie 过期时间是 1601-01-01 起的微秒数
_EPOCH_OFFSET_US = 11644473600 * 1_000_000


class _DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wt.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _dpapi_unprotect(data):
    buf = ctypes.create_string_buffer(data, len(data))
    blob_in = _DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    blob_out = _DATA_BLOB()
    if not ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)
    ):
        raise OSError("CryptUnprotectData failed (err=%d)" % ctypes.GetLastError())
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(blob_out.pbData)


def _master_key(user_data_dir):
    with open(os.path.join(user_data_dir, "Local State"), encoding="utf-8") as fh:
        state = json.load(fh)
    blob = base64.b64decode(state["os_crypt"]["encrypted_key"])
    if blob[:5] != b"DPAPI":
        raise ValueError("unexpected encrypted_key prefix: %r" % blob[:5])
    return _dpapi_unprotect(blob[5:])


def _decrypt(enc, key):
    if not enc:
        return ""
    prefix = enc[:3]
    if prefix in (b"v10", b"v11"):
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        return AESGCM(key).decrypt(enc[3:15], enc[15:], None).decode("utf-8", "replace")
    if prefix == b"v20":
        raise RuntimeError("cookie 使用 App-Bound Encryption (v20)，暂不支持")
    return _dpapi_unprotect(enc).decode("utf-8", "replace")


def _snapshot_db(path, dest, tries=10):
    """浏览器独占 Cookies 数据库时重试拷贝一份出来。"""
    last = None
    for _ in range(tries):
        try:
            with open(path, "rb") as src, open(dest, "wb") as dst:
                dst.write(src.read())
            return
        except OSError as exc:
            last = exc
            time.sleep(0.5)
    raise RuntimeError("cannot snapshot %s: %s" % (path, last))


def _read_browser(name, user_data_dir, tmp_dir):
    db = os.path.join(user_data_dir, r"Default\Network\Cookies")
    if not os.path.exists(db):
        return []
    snap = os.path.join(tmp_dir, "%s_cookies.db" % name)
    _snapshot_db(db, snap)

    con = sqlite3.connect(snap)
    try:
        rows = con.execute(
            """SELECT host_key, name, value, encrypted_value, path, expires_utc,
                      is_secure, is_httponly, samesite
               FROM cookies WHERE host_key LIKE ?""",
            ("%%%s%%" % DOMAIN_FILTER,),
        ).fetchall()
    finally:
        con.close()

    key = _master_key(user_data_dir)
    cookies = []
    for host, cname, val, enc, path, expires, secure, httponly, samesite in rows:
        value = val or _decrypt(enc, key)
        if not value:
            continue
        cookie = {
            "name": cname,
            "value": value,
            "domain": host,
            "path": path or "/",
            "secure": bool(secure),
            "httpOnly": bool(httponly),
            "sameSite": SAME_SITE.get(samesite, "Lax"),
        }
        if expires and expires > _EPOCH_OFFSET_US:
            cookie["expires"] = expires / 1_000_000 - 11644473600
        cookies.append(cookie)
    return cookies


def read_session_cookies(tmp_dir=None):
    """读本机浏览器里 jiuyangongshe.com 的全部 cookie（含解密后的值）。"""
    tmp_dir = tmp_dir or os.path.join(os.environ.get("TEMP", "."), "jygs_ck")
    os.makedirs(tmp_dir, exist_ok=True)
    for name, (env_key, rel) in BROWSERS.items():
        base = os.environ.get(env_key)
        if not base:
            continue
        user_data_dir = os.path.join(base, rel)
        if not os.path.exists(os.path.join(user_data_dir, "Local State")):
            continue
        cookies = _read_browser(name, user_data_dir, tmp_dir)
        if any(c["name"] == "SESSION" for c in cookies):
            return cookies
    return []


def _dedup_cookie_header(raw, real_session):
    """同名 cookie 只保留最后一个（后写入的是注入的真实 SESSION）。

    页面自身会写一个匿名 SESSION，与真实 SESSION 同名会让服务端取错值，
    故每个请求的 Cookie 头都重写一遍。
    """
    seen = {}
    order = []
    for part in raw.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        cname = part.split("=", 1)[0].strip()
        if cname not in seen:
            order.append(cname)
        seen[cname] = part
    if "SESSION" in seen and real_session:
        seen["SESSION"] = "SESSION=%s" % real_session
    return "; ".join(seen[n] for n in order)


# ------------------------------ 异动图（Playwright） ------------------------------

def _grab_diagram_url(dates, headless=False):
    """逐日渲染异动页，取第一个有图的交易日的 diagram-url；返回 {"date", "url"}。"""
    from playwright.sync_api import sync_playwright

    cookies = read_session_cookies()
    real = [c for c in cookies if c.get("name") == "SESSION"]
    if not real:
        raise RuntimeError("本机 Chrome/Edge 未找到 jiuyangongshe 的 SESSION 登录态")
    real_session = real[0]["value"]

    hit = {"date": "", "url": ""}
    with sync_playwright() as p:
        browser = p.chromium.launch(
            channel="chrome",
            headless=headless,
            args=["--disable-blink-features=AutomationControlled"],
        )
        try:
            ctx = browser.new_context(viewport={"width": 1600, "height": 1200},
                                      device_scale_factor=2)
            ctx.add_cookies(cookies)

            def on_route(route):
                req = route.request
                headers = dict(req.headers)
                if API_HOST in req.url and "cookie" in headers:
                    headers["cookie"] = _dedup_cookie_header(headers["cookie"], real_session)
                route.continue_(headers=headers)

            current = {}

            def on_response(resp):
                if API_HOST in resp.url and "diagram-url" in resp.url:
                    try:
                        data = resp.json().get("data")
                    except Exception:                  # noqa: BLE001 - 非 JSON 响应直接跳过
                        return
                    for u in [data] if isinstance(data, str) else (data or []):
                        if isinstance(u, str) and u.startswith("http"):
                            current.setdefault("diagram-url", u)

            ctx.route("**/*", on_route)
            page = ctx.new_page()
            page.on("response", on_response)

            for day in dates:
                current.clear()
                page.goto("%s/%s" % (ACTION_URL, day),
                          wait_until="domcontentloaded", timeout=60000)
                try:
                    page.wait_for_load_state("networkidle", timeout=20000)
                except Exception:                      # noqa: BLE001 - 长连接页面等不到 idle
                    pass
                page.wait_for_timeout(1500)
                # 点开「涨停简图」页签（盘中非默认页签，不点则不会发 diagram-url 请求）
                try:
                    page.click(DIAGRAM_TAB, timeout=5000)
                except Exception:                      # noqa: BLE001 - 页签已是选中态时点击可能超时
                    pass
                page.wait_for_timeout(3000)
                got = current.get("diagram-url")
                if not got:                            # 兜底：页面里直接挂的 UUID PNG
                    imgs = page.evaluate(
                        "() => [...document.querySelectorAll('img')]"
                        ".map(i => i.currentSrc || i.src)")
                    got = next((u for u in imgs if UUID_PNG.match(u or "")), None)
                print("[韭研公社] %s 异动图 %s" % (day, "OK" if got else "空"))
                if got:
                    hit["date"], hit["url"] = day, got
                    break
        finally:
            browser.close()
    return hit


def _download(url, dest):
    import requests

    resp = requests.get(url, timeout=60, headers={"User-Agent": "Mozilla/5.0"})
    resp.raise_for_status()
    with open(dest, "wb") as fh:
        fh.write(resp.content)
    return len(resp.content)


# ------------------------------ 红字识别（OpenCV + OCR） ------------------------------

#: 代码列 / 名称列在异动图里的横向中心范围（表头：板数 | 代码 | 个股 | 涨停时间）
ROW_X0_MIN, ROW_X0_MAX = 200, 640
CODE_X1 = 420                       # cx < CODE_X1 视为代码列
NAME_X0 = 420                       # NAME_X0 <= cx < ROW_X0_MAX 视为名称列
CODE_LOOSE = re.compile(r"[0-9]{6}")
#: 红墨比例阈值：框内「强红」笔画像素 / 全部笔画像素（真红字 0.65~0.89，黑字 0.01~0.05）
RED_INK_THRESHOLD = 0.35
#: 判定「强红」的饱和度下限，低于它的偏灰/偏粉像素不算红
RED_S_MIN = 120

_OCR = None


def _get_ocr():
    global _OCR
    if _OCR is None:
        from rapidocr_onnxruntime import RapidOCR

        _OCR = RapidOCR()
    return _OCR


def _mask_red(img):
    """量测用：不做膨胀，只统计真正饱和的红像素，避免把黑字抗锯齿边缘误算成红。"""
    import cv2
    import numpy as np

    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    h, s, v = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    return (((h <= 10) | (h >= 170)) & (s > RED_S_MIN) & (v > 90)).astype(np.uint8)


def _mask_ink(img):
    import cv2
    import numpy as np

    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    v, s = hsv[:, :, 2], hsv[:, :, 1]
    return ((v < 200) | (s > 80)).astype(np.uint8)


def to_instrument(raw):
    """OCR 代码文本 -> 统一 instrument（``603636.SH``）；识别不了返回 None。"""
    s = re.sub(r"[^0-9A-Za-z]", "", str(raw or "")).upper()
    m = re.match(r"^(?:(SH|SZ|BJ))?(\d{6})(?:(SH|SZ|BJ))?$", s)
    if not m:
        return None
    mkt = m.group(1) or m.group(3)
    num = m.group(2)
    if not mkt:
        if num[0] in "48":
            mkt = "BJ"
        elif num[0] in "69":
            mkt = "SH"
        else:
            mkt = "SZ"
    return "%s.%s" % (num, mkt)


def _imread(path):
    """读图：Windows 下 cv2.imread 打不开含中文的路径（本项目目录即是），故走 imdecode。"""
    import cv2
    import numpy as np

    with open(path, "rb") as fh:
        buf = fh.read()
    img = cv2.imdecode(np.frombuffer(buf, dtype=np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise RuntimeError("无法解码异动图（%d 字节）: %s" % (len(buf), path))
    return img


def extract_red_stocks(image_path):
    """异动图 -> [(instrument, 名称, 红墨比)]（只保留红色行）。"""
    import numpy as np

    img = _imread(image_path)
    rm = _mask_red(img)
    im = _mask_ink(img)

    res_all, _ = _get_ocr()(img)
    boxes = []
    for box, text, _score in (res_all or []):
        pts = np.array(box, dtype=np.int32)
        x0, y0 = int(pts[:, 0].min()), int(pts[:, 1].min())
        x1, y1 = int(pts[:, 0].max()), int(pts[:, 1].max())
        ink = int(im[y0:y1 + 1, x0:x1 + 1].sum())
        red = int(rm[y0:y1 + 1, x0:x1 + 1].sum())
        ratio = red / ink if ink else 0.0
        boxes.append({"x0": x0, "cx": (x0 + x1) // 2, "cy": (y0 + y1) // 2,
                      "text": str(text or ""), "ratio": ratio,
                      "is_red": ratio >= RED_INK_THRESHOLD})

    # 按行（y）聚同一行的框，再在行内把「代码列」与「名称列」配对。
    # 判列用框中心 cx：各列宽度不同，用左边 x0 会把「个股」列错判成代码列、
    # 把「涨停时间」列错判成名称列。
    rows = {}
    for b in boxes:
        if b["cx"] < ROW_X0_MIN or b["cx"] > ROW_X0_MAX:
            continue
        rows.setdefault(round(b["cy"] / 28), []).append(b)

    out = []
    for key in sorted(rows):
        cells = sorted(rows[key], key=lambda z: z["cx"])
        code = next((c for c in cells
                     if c["cx"] < CODE_X1 and CODE_LOOSE.search(c["text"])), None)
        name = next((c for c in cells if NAME_X0 <= c["cx"] < ROW_X0_MAX), None)
        if code is None or name is None or not any(c["is_red"] for c in cells):
            continue
        inst = to_instrument(code["text"])
        name_text = name["text"].strip()
        if inst and name_text:
            out.append((inst, name_text, max(c["ratio"] for c in cells)))
    return out


# ------------------------------ 缓存 ------------------------------

def load_cache():
    """读 jygs_red_cache.json；不存在/损坏返回空表。"""
    if not os.path.exists(CACHE_PATH):
        return {}
    try:
        with open(CACHE_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception as exc:                           # noqa: BLE001 - 缓存损坏不该中断抓取
        print("[韭研公社] 缓存读取失败(%s)，本次不使用缓存" % exc)
        return {}


def save_cache(cache):
    """原子落盘（先写临时文件再替换）。"""
    tmp = CACHE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(cache, fh, ensure_ascii=False, indent=0)
    os.replace(tmp, CACHE_PATH)


# ------------------------------ 主流程 ------------------------------

def _crawl(date, headless=False):
    """抓取 + 识别指定口径日的红股；返回 (源日期, {instrument: 名称})。"""
    base = dt.date.fromisoformat(date)
    dates = [(base - dt.timedelta(days=i)).isoformat() for i in range(LOOKBACK_DAYS)]
    hit = _grab_diagram_url(dates, headless=headless)
    if not hit["url"]:
        raise RuntimeError("近 %d 天都没取到异动图 URL" % LOOKBACK_DAYS)

    dest = os.path.join(_DIR, DIAGRAM_NAME)
    size = _download(hit["url"], dest)
    stocks = {}
    for inst, name, _ratio in extract_red_stocks(dest):
        stocks.setdefault(inst, name)
    print("[韭研公社] 异动图 %s（%d 字节，源日期 %s）-> 红股 %d 只"
          % (os.path.basename(dest), size, hit["date"], len(stocks)))
    return hit["date"], stocks


def fetch_red_stocks(date=None, force=False, headless=False):
    """取指定口径日的韭研红股 {instrument: 名称}；任何失败都返回已有缓存（不抛异常）。"""
    date = date or dt.date.today().isoformat()
    cache = load_cache()
    rec = cache.get(date) or {}
    cached = dict(rec.get("stocks") or {})
    if cached and not force:
        print("[韭研公社] 命中口径日 %s 缓存：%d 只红股（抓取于 %s）"
              % (date, len(cached), rec.get("fetched_at") or "-"))
        return cached

    try:
        source_date, stocks = _crawl(date, headless=headless)
    except Exception as exc:                           # noqa: BLE001 - 单平台失败不拖垮整份快照
        print("[韭研公社] 抓取失败（%s）%s"
              % (exc, "，沿用缓存 %d 只" % len(cached) if cached else "，且无缓存可回退"))
        return cached

    if not stocks:
        print("[韭研公社] 未识别到红色股票%s"
              % ("，沿用缓存 %d 只" % len(cached) if cached else ""))
        return cached

    cache[date] = {"fetched_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                   "source_date": source_date,
                   "diagram": DIAGRAM_NAME,
                   "stocks": stocks}
    try:
        save_cache(cache)
    except Exception as exc:                           # noqa: BLE001
        print("[韭研公社] 缓存写回失败(%s)，本次仍返回结果" % exc)
    return dict(stocks)


def main():
    ap = argparse.ArgumentParser(
        description="韭研公社异动图红股抓取（第 7 平台 · 只贡献覆盖平台数）")
    ap.add_argument("--date", default=None, help="口径日 YYYY-MM-DD（默认今天）")
    ap.add_argument("--force", action="store_true", help="忽略当日缓存强制重抓")
    ap.add_argument("--headless", action="store_true", help="无头模式（默认有头，登录态更稳）")
    ap.add_argument("--show", action="store_true", help="只打印缓存内容，不抓取")
    args = ap.parse_args()

    if args.show:
        cache = load_cache()
        if not cache:
            print("缓存为空：%s" % CACHE_PATH)
            return 0
        for day in sorted(cache, reverse=True):
            rec = cache.get(day) or {}
            print("%s  抓取于 %s  源日期 %s  %d 只"
                  % (day, rec.get("fetched_at") or "-", rec.get("source_date") or "-",
                     len(rec.get("stocks") or {})))
            for inst, name in (rec.get("stocks") or {}).items():
                print("  %-12s %s" % (inst, name))
        return 0

    stocks = fetch_red_stocks(args.date, force=args.force, headless=args.headless)
    return 0 if stocks else 3


if __name__ == "__main__":
    sys.exit(main())
