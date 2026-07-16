#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""诊断工具：按当前配置实际跑一遍所有启用的爬虫，看哪些能拿到数据。

与项目自身调用方式保持一致：
    - 通过 Cfg().crawler.selection 读取启用的爬虫及其分类(normal/fc2/cid/getchu/gyutto)
    - 每个爬虫以 parser(movie) 形式调用，movie 为 javsp.datatype.MovieInfo
    - fanza(cid 分类) 使用 MovieInfo(cid=avid)，其余使用 MovieInfo(avid)

输出按「能否拿到数据」分类，帮助快速判断是「爬虫坏了」还是「代理/地区限制」导致的失败。

用法示例：
    # 用默认样例番号测试全部启用的爬虫
    python tools/test_crawlers.py

    # 只看启用了哪些爬虫（不实际抓取）
    python tools/test_crawlers.py --list

    # 自定义各分类样例番号
    python tools/test_crawlers.py --normal-avid IPX-001 --fc2-avid FC2-1000000

    # 只测部分爬虫、调整并发与单爬虫超时
    python tools/test_crawlers.py --include javbus javdb missav --workers 4 --timeout 60
"""

import os
import sys
import argparse
import logging
import concurrent.futures as cf

# 让脚本既能 `python tools/test_crawlers.py` 也能被包内调用
file_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(file_dir, '..')))

import requests
from javsp.config import Cfg
from javsp.datatype import MovieInfo
from javsp.web import exceptions as jwex


# 各分类默认样例番号（仅为探测可达性，不一定真实存在）
DEFAULT_AVIDS = {
    'normal': 'IPX-001',       # 普通有码/无码番号
    'fc2': 'FC2-1000000',      # FC2 番号
    'cid': 'c001icaxxx',       # FANZA 的 CID
    'getchu': '264014',        # Getchu 商品编号
    'gyutto': '264014',        # Gyutto 商品编号
}


# 分类用的异常优先级（数字越小越靠前展示）
STATUS_ORDER = {
    'OK': 0, 'PARTIAL': 1, 'NF': 2,
    'NET': 3, 'BLOCK': 4, 'CRED': 5, 'PERM': 6, 'WEB': 7, 'ERR': 8, 'TIMEOUT': 9,
}
STATUS_LABEL = {
    'OK': '✅ 成功获取',
    'PARTIAL': '🟡 已连通·缺字段',
    'NF': '🔗 已连通·无此番号',
    'NET': '🌐 网络/代理不通',
    'BLOCK': '🚫 站点封锁/CloudFlare',
    'CRED': '🔑 凭据缺失(需cookie)',
    'PERM': '🔒 权限/地区限制',
    'WEB': '⚠️ 网页故障(非预期状态码)',
    'ERR': '❓ 解析/其他异常',
    'TIMEOUT': '⏱ 超时',
}


def build_movie(category: str, avid: str) -> MovieInfo:
    """按分类构造 MovieInfo（fanza/cid 分类用 cid 字段）。"""
    if category == 'cid':
        return MovieInfo(cid=avid)
    return MovieInfo(avid)


def classify(exc, movie) -> tuple[str, str]:
    """把一次抓取结果归类成 (状态码, 说明)。"""
    if exc is None:
        required = [k.value if hasattr(k, 'value') else k
                    for k in Cfg().crawler.required_keys]
        missing = [k for k in required if not getattr(movie, k, None)]
        if not missing:
            return 'OK', '成功获取(含 ' + '+'.join(required) + ')'
        return 'PARTIAL', '已连通但缺字段: ' + ','.join(missing)

    etype = type(exc)
    # 1) 网络/代理层错误（与爬虫逻辑无关）
    net_errs = (
        requests.exceptions.ConnectionError,
        requests.exceptions.ProxyError,
        requests.exceptions.SSLError,
        requests.exceptions.Timeout,
        requests.exceptions.ConnectTimeout,
        requests.exceptions.ReadTimeout,
        requests.exceptions.ChunkedEncodingError,
    )
    if isinstance(exc, net_errs):
        return 'NET', '网络/代理不通'

    # 2) 项目自定义爬虫异常
    if isinstance(exc, jwex.MovieNotFoundError):
        return 'NF', '已连通·未找到该番号'
    if isinstance(exc, jwex.SiteBlocked):
        return 'BLOCK', '站点封锁/CloudFlare(403)'
    if isinstance(exc, jwex.CredentialError):
        return 'CRED', '凭据缺失(需cookie/登录态)'
    if isinstance(exc, jwex.SitePermissionError):
        return 'PERM', '权限不足/地区限制'
    if isinstance(exc, jwex.WebsiteError):
        return 'WEB', '网页故障(非预期状态码)'

    # 3) 按消息兜底（部分站点在连上后做格式/番号校验）
    msg = str(exc)
    if 'Invalid number' in msg or 'invalid' in msg.lower():
        return 'NF', '已连通·番号格式不正确'
    return 'ERR', f'{etype.__name__}: {msg[:80]}'


def run_one(name: str, category: str, avid: str, parser, timeout: int) -> dict:
    """在独立线程中跑单个爬虫，带超时保护。"""
    def _worker():
        movie = build_movie(category, avid)
        parser(movie)
        return movie

    try:
        with cf.ThreadPoolExecutor(max_workers=1) as ex:
            fut = ex.submit(_worker)
            movie = fut.result(timeout=timeout)
        status, detail = classify(None, movie)
        return {'name': name, 'category': category, 'avid': avid,
                'status': status, 'detail': detail,
                'title': getattr(movie, 'title', '') or ''}
    except cf.TimeoutError:
        return {'name': name, 'category': category, 'avid': avid,
                'status': 'TIMEOUT', 'detail': f'超过 {timeout}s 未返回', 'title': ''}
    except Exception as e:  # noqa: BLE001 - 诊断脚本需捕获一切
        status, detail = classify(e, MovieInfo(avid))
        return {'name': name, 'category': category, 'avid': avid,
                'status': status, 'detail': detail, 'title': ''}


def collect_tasks(include=None, exclude=None, avids=None):
    """根据配置构造 (分类, 爬虫名, 番号) 任务列表。"""
    avids = avids or DEFAULT_AVIDS
    tasks = []
    seen = set()
    sel = Cfg().crawler.selection
    for category, mods in sel.items():
        for mod in mods:
            name = mod.value if hasattr(mod, 'value') else str(mod)
            if name in seen:
                continue  # 同一爬虫只测一次（用其首次出现的分类番号）
            seen.add(name)
            if include and name not in include:
                continue
            if exclude and name in exclude:
                continue
            avid = avids.get(category, DEFAULT_AVIDS[category])
            tasks.append((category, name, avid))
    return tasks


def main():
    p = argparse.ArgumentParser(description='按配置实测所有启用的爬虫')
    p.add_argument('--normal-avid', default=DEFAULT_AVIDS['normal'])
    p.add_argument('--fc2-avid', default=DEFAULT_AVIDS['fc2'])
    p.add_argument('--cid-avid', default=DEFAULT_AVIDS['cid'])
    p.add_argument('--getchu-avid', default=DEFAULT_AVIDS['getchu'])
    p.add_argument('--gyutto-avid', default=DEFAULT_AVIDS['gyutto'])
    p.add_argument('--include', nargs='+', help='只测这些爬虫(按名称)')
    p.add_argument('--exclude', nargs='+', help='排除这些爬虫(按名称)')
    p.add_argument('--workers', type=int, default=8, help='并发线程数')
    p.add_argument('--timeout', type=int, default=90, help='单个爬虫超时(秒)')
    p.add_argument('--list', action='store_true', help='只列出启用的爬虫后退出')
    args = p.parse_args()

    # 安静输出：屏蔽第三方库噪音，只保留我们的结论
    logging.basicConfig(level=logging.ERROR)
    logging.getLogger('urllib3').setLevel(logging.ERROR)
    requests.packages.urllib3.disable_warnings()

    avids = {
        'normal': args.normal_avid,
        'fc2': args.fc2_avid,
        'cid': args.cid_avid,
        'getchu': args.getchu_avid,
        'gyutto': args.gyutto_avid,
    }

    include = set(args.include) if args.include else None
    exclude = set(args.exclude) if args.exclude else None
    tasks = collect_tasks(include=include, exclude=exclude, avids=avids)

    if args.list:
        print('当前配置启用的爬虫（按分类）：')
        for category, mods in Cfg().crawler.selection.items():
            print(f'  {category:8s}: {", ".join(m.value for m in mods)}')
        print(f'\n共 {len(tasks)} 个待测试爬虫（去重后）。')
        return

    print(f'代理配置 proxy_server = {Cfg().network.proxy_server}')
    print(f'待测试爬虫数 = {len(tasks)}，并发 = {args.workers}，单爬虫超时 = {args.timeout}s\n')

    # 动态导入所有任务所需的爬虫模块并取 parse_data
    parsers = {}
    for category, name, avid in tasks:
        mod = __import__('javsp.web.' + name, fromlist=['parse_data'])
        parsers[name] = getattr(mod, 'parse_data')

    results = []
    with cf.ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(run_one, name, cat, avid, parsers[name], args.timeout): name
                for cat, name, avid in tasks}
        for fut in cf.as_completed(futs):
            results.append(fut.result())

    # 排序：状态优先，再按名称
    results.sort(key=lambda r: (STATUS_ORDER.get(r['status'], 99), r['name']))

    print('=' * 78)
    print(f'{"爬虫":<14}{"分类":<9}{"状态":<22}{"说明"}')
    print('-' * 78)
    for r in results:
        line = f'{r["name"]:<14}{r["category"]:<9}{STATUS_LABEL[r["status"]]:<22}{r["detail"]}'
        print(line)
    print('=' * 78)

    # 汇总
    from collections import Counter
    cnt = Counter(r['status'] for r in results)
    print('汇总：', end='')
    parts = []
    for st in ['OK', 'PARTIAL', 'NF', 'NET', 'BLOCK', 'CRED', 'PERM', 'WEB', 'ERR', 'TIMEOUT']:
        if cnt.get(st):
            parts.append(f'{STATUS_LABEL[st].split()[0]} {cnt[st]}')
    print('  '.join(parts))
    ok = cnt.get('OK', 0)
    print(f'\n结论：{ok}/{len(results)} 个爬虫成功拿到数据。')
    print('提示：NET/Timeout 多为代理失效；BLOCK/CRED/PERM 多为地区限制或需 cookie；')
    print('      NF 表示爬虫已连通、只是样例番号不存在（换成真实番号通常即可出数）。')


if __name__ == '__main__':
    main()
