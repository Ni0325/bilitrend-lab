"""B站热搜采集；失败时不写入伪造或历史替代记录。"""
import argparse
import json
import time
from datetime import datetime
from zoneinfo import ZoneInfo
from urllib.parse import quote
import requests
from engine import ROOT, validate_snapshot

URL = 'https://app.bilibili.com/x/v2/search/trending/ranking'

def collect():
    response = requests.get(URL, params={'limit':30}, timeout=(5,10), headers={'User-Agent':'Mozilla/5.0', 'Referer':'https://www.bilibili.com/'})
    response.raise_for_status()
    raw = response.json()
    if raw.get('code') != 0:
        raise ValueError(f"平台返回错误：{raw.get('code')}")
    items = raw.get('data',{}).get('list',[])
    if not items:
        raise ValueError('平台返回空榜单，未保存')
    now = datetime.now(ZoneInfo('Asia/Shanghai'))
    topics = []
    for i,p in enumerate(items[:30],1):
        title = p.get('show_name') or p.get('keyword')
        topics.append(dict(title=title,rank=i,heat=None,url='https://search.bilibili.com/all?keyword='+quote(title or '')))
    snap = validate_snapshot(dict(captured_at=now.isoformat(),topics=topics,source_url=URL))
    folder = ROOT/'data'/'live';folder.mkdir(exist_ok=True)
    path=folder/(now.strftime('%Y-%m-%d_%H-%M-%S')+'.json')
    path.write_text(json.dumps(snap,ensure_ascii=False,indent=2))
    return snap

if __name__ == '__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--loop',action='store_true');args=parser.parse_args()
    while True:
        try:
            snap=collect();print('已采集',snap['captured_at'],len(snap['topics']),flush=True)
        except (requests.RequestException,ValueError) as exc:
            print('采集失败，未写入数据：',str(exc),flush=True)
        if not args.loop:break
        time.sleep(1800)
