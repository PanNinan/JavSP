# -*- coding: utf-8 -*-
"""
搜索 missav.ai 并缓存目标详情页
注意事项：无法从主程序获取代理（我不会）；所以必须自行添加DEFAULT_PROXY值保证连接。
这个脚本可以独立运行，输入番号即可缓存相应影片番号的搜索页面和影片的详细页面。

改动概要：
1) keyword 兼容两种来源：
   - 其它脚本唤起时通过命令行参数传入（full_id）
   - 若未传，则在本脚本里手动输入
2) 代理使用脚本内的默认设置 DEFAULT_PROXY，无需输入

依赖:
    pip install playwright beautifulsoup4 lxml curl_cffi requests
    python -m playwright install chromium
"""

import os
import pathlib
import re
import sys
import time
import traceback
from typing import List, Optional
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from javsp.config import Cfg

# 可选模块，按可用性启用
try:
    from playwright.sync_api import sync_playwright

    PLAYWRIGHT_AVAILABLE = True
except Exception:
    PLAYWRIGHT_AVAILABLE = False

try:
    from curl_cffi import requests as curl_requests

    CURL_CFFI_AVAILABLE = True
except Exception:
    CURL_CFFI_AVAILABLE = False

import requests

# 标记上一次 curl_cffi 请求是否命中 Cloudflare 挑战，供 main() 决定是否回退 playwright
LAST_CURL_WAS_CF = False

# ===================== 配置区 =====================
MISSAV_HOST = "https://missav.ai"
SEARCH_TEMPLATE = "https://missav.ai/ja/search/{keyword}"

# ✅ 默认代理：改成你的实际代理地址；若不想用代理，留空字符串""即可
DEFAULT_PROXY = Cfg().network.proxy_server  # ←←← 修改这里

# （暂时无效）如果你想优先使用系统环境变量代理，把下方开关设为 True
USE_ENV_PROXY_IF_SET = True
# =================================================

CACHE_DIR = pathlib.Path("./cache")
LOG_FILE = CACHE_DIR / "missav_run.log"
CACHE_DIR.mkdir(parents=True, exist_ok=True)


def log(msg: str):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    try:
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def _ua() -> str:
    return ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/121.0.0.0 Safari/537.36")


def build_proxies() -> Optional[dict]:
    """
    使用默认代理，无需输入。
    若 USE_ENV_PROXY_IF_SET=True 且环境变量存在，则优先用环境变量。
    """
    if USE_ENV_PROXY_IF_SET:
        http_env = os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy")
        https_env = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
        if http_env or https_env:
            proxies = {"http": http_env or https_env, "https": https_env or http_env}
            log(f"使用环境变量代理：{proxies}")
            return proxies

    if DEFAULT_PROXY:
        proxies = {"http": DEFAULT_PROXY, "https": DEFAULT_PROXY}
        log(f"使用默认代理：{proxies}")
        return proxies

    log("未设置代理。")
    return None


def is_target_link(href: str, keyword: str) -> bool:
    if not href:
        return False
    # 绝对化
    if href.startswith("//"):
        href = "https:" + href
    elif href.startswith("/"):
        href = urljoin(MISSAV_HOST, href)

    try:
        u = urlparse(href)
    except Exception:
        return False

    # 仅 missav.ai 域名
    if u.netloc and u.netloc.lower() not in ("missav.ai", "www.missav.ai"):
        return False

    path_lower = (u.path or "").lower()
    # 必须包含关键词，且不含 /search/
    if keyword.lower() not in path_lower:
        return False
    if "/search/" in path_lower:
        return False
    return True


def to_abs(href: str) -> str:
    if href.startswith("//"):
        return "https:" + href
    if href.startswith("/"):
        return urljoin(MISSAV_HOST, href)
    return href


def pick_first_target(links: List[str], keyword: str) -> Optional[str]:
    for href in links:
        if is_target_link(href, keyword):
            return to_abs(href)
    return None


def is_cloudflare_challenge(html: str) -> bool:
    """判断页面是否是 Cloudflare 的「Just a moment...」托管式 JS 挑战页。"""
    if not html:
        return False
    t = html.lower()
    markers = [
        "just a moment",
        "cf-mitigated",
        "challenge-platform",
        "verify you are human",
        "attention required",
        "why am i seeing this",
    ]
    return any(m in t for m in markers)


def extract_links_from_html(html: str) -> List[str]:
    soup = BeautifulSoup(html, "lxml")
    links = [a.get("href", "").strip() for a in soup.select("a[href]")]
    return [h for h in links if h]


def save_cache(html: str, keyword: str, suffix: str) -> pathlib.Path:
    ts = time.strftime("%Y%m%d_%H%M%S")
    safe_kw = re.sub(r"[^\w\-]+", "_", keyword.strip())
    out = CACHE_DIR / f"{safe_kw}_{suffix}_{ts}.html"
    out.write_text(html, encoding="utf-8", errors="ignore")
    log(f"缓存文件已保存：{out}")
    return out


def _goto_with_retry(page, url: str, retries: int = 3, wait: str = "domcontentloaded", timeout: int = 60000):
    """带重试的页面跳转。代理偶发 RST（ERR_CONNECTION_CLOSED）时自动重试，提升在抖动网络下的成功率。"""
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            page.goto(url, wait_until=wait, timeout=timeout)
            return True
        except Exception as e:
            last_err = e
            log(f"[PW] goto 第 {attempt}/{retries} 次失败：{e}")
            if attempt < retries:
                time.sleep(2)
    if last_err:
        raise last_err
    return False


# ---------------- 方案一：Playwright（真浏览器，用于绕过 Cloudflare JS 挑战） ----------------
def fetch_with_playwright(search_url: str, keyword: str, proxies: Optional[dict]) -> Optional[str]:
    if not PLAYWRIGHT_AVAILABLE:
        log("Playwright 不可用，跳过方案一。")
        return None

    pw_proxy = None
    if proxies and (proxies.get("https") or proxies.get("http")):
        pw_proxy = {"server": proxies.get("https") or proxies.get("http")}

    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            # 反 headless 检测：去掉 AutomationControlled 特征，禁用 /dev/shm 共享内存（容器环境更稳定）
            browser = p.chromium.launch(
                headless=True,
                proxy=pw_proxy,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-infobars",
                ],
            )
            context = browser.new_context(
                locale="ja-JP",
                user_agent=_ua(),
                ignore_https_errors=True,
            )
            # 覆盖 navigator.webdriver，进一步规避 Cloudflare 的 headless 指纹
            context.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
            )
            page = context.new_page()
            page.set_extra_http_headers({
                "Accept-Language": "ja,en;q=0.9,zh;q=0.8",
                "Cache-Control": "no-cache",
                "Pragma": "no-cache",
            })

            log(f"[PW] 打开搜索页：{search_url}")
            _goto_with_retry(page, search_url, retries=3, wait="domcontentloaded", timeout=60000)

            # 关键：等待 Cloudflare 的「Just a moment...」挑战解完（标题不再是挑战页）
            # 挑战页标题为 "Just a moment..."，解出后会跳转到真实页面，标题随之改变
            try:
                page.wait_for_function(
                    "() => { const t = document.title; return !t || t.toLowerCase().indexOf('just a moment') === -1; }",
                    timeout=30000,
                )
                log("[PW] Cloudflare 挑战已通过，等待页面稳定。")
            except Exception as e:
                log(f"[PW] 等待 CF 挑战超时（仍可能是挑战页）：{e}")
            page.wait_for_timeout(1500)

            search_html = page.content()
            save_cache(search_html, keyword, "search")

            # 若仍是挑战页，则本次未成功绕过
            if is_cloudflare_challenge(search_html):
                log("[PW] 警告：缓存的搜索页仍是 Cloudflare 挑战页，可能无法取到有效链接。")
                context.close()
                browser.close()
                return None

            links = extract_links_from_html(search_html)
            # 兜底：文本里再扫一轮直链
            links += re.findall(r'https?://(?:www\.)?missav\.ai/[^\s"\'<>]+', search_html, flags=re.I)
            target = pick_first_target(links, keyword)

            if not target:
                log("[PW] 未找到符合规则的详情链接（包含关键词且不含 /search/）。")
                context.close()
                browser.close()
                return None

            log(f"[PW] 发现目标链接：{target}")
            _goto_with_retry(page, target, retries=3, wait="domcontentloaded", timeout=60000)
            try:
                page.wait_for_function(
                    "() => { const t = document.title; return !t || t.toLowerCase().indexOf('just a moment') === -1; }",
                    timeout=30000,
                )
            except Exception:
                pass
            page.wait_for_timeout(1500)
            detail_html = page.content()
            save_cache(detail_html, keyword, "detail")

            context.close()
            browser.close()
            return target

    except Exception as e:
        log(f"[PW] 失败：{e}")
        traceback.print_exc()
        return None


# --------------- 方案二：curl_cffi（模拟 Chrome TLS 指纹绕过 Cloudflare） ---------------
def fetch_with_curl(search_url: str, keyword: str, proxies: Optional[dict]) -> Optional[str]:
    global LAST_CURL_WAS_CF
    if CURL_CFFI_AVAILABLE:
        # impersonate="chrome" 让 curl_cffi 复刻 Chrome 的 TLS/JA3 指纹（含扩展、曲线、ALPN 顺序），
        # 相比 cloudscraper 更接近真实浏览器，能更稳地通过 Cloudflare 的 TLS 指纹检测
        sess = curl_requests.Session(impersonate="chrome")
        log("[REQ] 使用 curl_cffi（模拟 Chrome TLS 指纹）。")
    else:
        sess = requests.Session()
        log("[REQ] 使用 requests（未检测到 curl_cffi）。")

    if proxies:
        sess.proxies.update(proxies)

    sess.headers.update({
        "User-Agent": _ua(),
        "Accept-Language": "ja,en;q=0.9,zh;q=0.8",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    })

    try:
        log(f"[REQ] 打开搜索页：{search_url}")
        r = sess.get(search_url, timeout=60)
        # 命中 Cloudflare 挑战（403 或挑战页正文）：标记后回退 playwright，不在此硬解
        if r.status_code == 403 or is_cloudflare_challenge(r.text):
            LAST_CURL_WAS_CF = True
            log("[REQ] 命中 Cloudflare 挑战，将回退 playwright 解挑战。")
            return None
        r.raise_for_status()
        search_html = r.text
        save_cache(search_html, keyword, "search")

        links = extract_links_from_html(search_html)
        links += re.findall(r'href=["\']([^"\']+)["\']', search_html, flags=re.I)
        links += re.findall(r'https?://(?:www\.)?missav\.ai/[^\s"\'<>]+', search_html, flags=re.I)
        target = pick_first_target(links, keyword)

        if not target:
            log("[REQ] 未找到符合规则的详情链接（包含关键词且不含 /search/）。")
            return None

        log(f"[REQ] 发现目标链接：{target}")
        r2 = sess.get(target, timeout=60)
        if r2.status_code == 403 or is_cloudflare_challenge(r2.text):
            LAST_CURL_WAS_CF = True
            log("[REQ] 详情页也命中 Cloudflare 挑战，将回退 playwright。")
            return None
        r2.raise_for_status()
        detail_html = r2.text
        save_cache(detail_html, keyword, "detail")
        return target

    except Exception as e:
        log(f"[REQ] 失败：{e}")
        traceback.print_exc()
        return None


def get_keyword_from_argv_or_input() -> Optional[str]:
    """
    优先从命令行参数读取（供其它脚本唤起，传 full_id）。
    若无参数，则在本脚本里手动输入。
    """
    if len(sys.argv) >= 2:
        kw = sys.argv[1].strip()
        if kw:
            log(f"收到命令行参数 keyword：{kw}")
            return kw

    print("请输入搜索关键词（例如：zuko-118）：")
    kw = input("> ").strip()
    if kw:
        return kw
    return None


def main():
    global LAST_CURL_WAS_CF
    try:
        keyword = get_keyword_from_argv_or_input()
        if not keyword:
            print("未提供关键词，退出。")
            return

        search_url = SEARCH_TEMPLATE.format(keyword=keyword)
        log(f"搜索URL：{search_url}")

        proxies = build_proxies()

        # 首选 curl_cffi（模拟 Chrome TLS 指纹，速度快）；任何原因失败时（含 Cloudflare 挑战、TLS 异常）
        # 一律回退 playwright 真浏览器解挑战，作为可靠兜底
        LAST_CURL_WAS_CF = False
        target_url = fetch_with_curl(search_url, keyword, proxies)

        if (target_url is None) and PLAYWRIGHT_AVAILABLE:
            reason = "命中 Cloudflare 挑战" if LAST_CURL_WAS_CF else "curl_cffi 请求失败"
            log(f"[MAIN] {reason}，回退 playwright 真浏览器解挑战。")
            target_url = fetch_with_playwright(search_url, keyword, proxies)

        if target_url:
            log(f"完成。目标链接：{target_url}")
            print(f"\n完成 ✅ 目标链接：{target_url}\n缓存目录：{CACHE_DIR.resolve()}")
        else:
            log("未能获取目标链接或缓存详情页。")
            print("\n未能获取目标链接或缓存详情页。详见日志：", LOG_FILE.resolve())

    except Exception as e:
        log(f"[FATAL] {e}")
        traceback.print_exc()
        print("\n发生致命错误，详见日志：", LOG_FILE.resolve())


if __name__ == "__main__":
    main()
