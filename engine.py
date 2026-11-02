"""真实快照 -> 标题链 -> DTW -> 层次聚类 -> 历史前缀匹配。

排名强度使用固定尺度，不使用未来峰值归一化。热度缺失保留为 None。
"""
import hashlib
import json
import re
from collections import Counter
from difflib import SequenceMatcher
from datetime import datetime
from pathlib import Path

import numpy as np
from scipy.cluster.hierarchy import linkage, cut_tree
from scipy.spatial.distance import squareform, cdist
from sklearn.metrics import silhouette_score, calinski_harabasz_score

ROOT = Path(__file__).resolve().parent


def normalize_title(text):
    return re.sub(r'[\W_]+', '', text.casefold())


NEGATIVE_WORDS = {'争议': 20, '质疑': 15, '造假': 30, '诈骗': 30, '事故': 20, '被查': 25, '伤亡': 30, '抵制': 20, '翻车': 15, '投诉': 20, '曝光': 12, '道歉': 12, '暴雷': 25, '失败': 10, '不满': 15, '违规': 20, '谣言': 20, '辟谣': 10, '反转': 10}

def text_signal(title):
    words = [w for w in NEGATIVE_WORDS if w in title]
    return dict(negative=min(100, sum(NEGATIVE_WORDS[w] for w in words)), words=words,
                reversal=any(w in title for w in ['辟谣', '反转', '澄清']))

def title_similarity(a, b):
    a, b = normalize_title(a), normalize_title(b)
    if a == b: return 1.0
    if min(len(a), len(b)) < 6: return 0.0
    # 保守拒绝关键否定/反转词不同的标题，避免把相反事实当作改写。
    for word in ['不是', '未', '不', '辟谣', '反转', '澄清', '战胜', '不敌']:
        if (word in a) != (word in b): return 0.0
    aa = {a[i:i+2] for i in range(len(a)-1)}
    bb = {b[i:i+2] for i in range(len(b)-1)}
    overlap = len(aa & bb) / max(1, min(len(aa),len(bb)))
    ratio = SequenceMatcher(None, a, b).ratio()
    return ratio if overlap >= .65 else 0.0

def validate_snapshot(raw):
    if not isinstance(raw, dict) or not isinstance(raw.get('topics'), list):
        raise ValueError('快照必须包含 captured_at 和 topics 数组')
    stamp = datetime.fromisoformat(raw.get('captured_at', ''))
    if stamp.tzinfo is None:
        raise ValueError('captured_at 必须带时区，如 2026-11-02T14:00:00+08:00')
    if not 1 <= len(raw['topics']) <= 200:
        raise ValueError('每份快照应包含 1 至 200 条话题')
    topics = []
    for item in raw['topics']:
        title = item.get('title')
        rank = item.get('rank')
        heat = item.get('heat')
        if not isinstance(title, str) or not title.strip() or len(title) > 200:
            raise ValueError('话题标题不能为空，且不超过 200 字')
        if isinstance(rank, bool) or not isinstance(rank, int) or not 1 <= rank <= 30:
            raise ValueError('rank 必须是 1 至 30 的整数')
        if heat is not None and (isinstance(heat, bool) or not isinstance(heat, (int, float)) or not np.isfinite(heat) or heat < 0):
            raise ValueError('heat 必须是非负有限数或 null')
        topics.append(dict(title=title.strip(), rank=rank, heat=heat, url=item.get('url', '')))
    return dict(captured_at=stamp.isoformat(), topics=topics, source_url=raw.get('source_url', '用户导入'))


def dtw(a, b):
    """多维欧氏局部代价，动态规划，按两序列总长度缩放。"""
    costs = cdist(np.asarray(a), np.asarray(b))
    prev = np.full(len(b) + 1, np.inf)
    prev[0] = 0
    for row in costs:
        curr = np.full(len(b) + 1, np.inf)
        for j, cost in enumerate(row, 1):
            curr[j] = cost + min(prev[j], curr[j-1], prev[j-1])
        prev = curr
    return float(prev[-1] / (len(a) + len(b)))


def features(track, until=None):
    points = track['points'] if until is None else track['points'][:until]
    hours = np.array([p['hour'] for p in points])
    strength = np.array([(31 - p['rank']) / 30 for p in points])
    # 按真实小时重采样；长链最多 36 点，避免平方距离计算失控。
    grid = np.linspace(0, hours[-1], min(36, max(2, int(hours[-1]) + 1)))
    values = np.interp(grid, hours, strength)
    rate = np.gradient(values, grid) if grid[-1] else np.zeros_like(values)
    negative = np.interp(grid, hours, [p.get('negative', 0)/100 for p in points])
    return np.column_stack([values-values[0], .6 * rate, .2 * values, .15 * negative])


def describe(seq):
    y = seq[:, 0]
    if len(y) >= 5:
        y = np.convolve(np.pad(y, (1, 1), mode='edge'), np.ones(3)/3, mode='valid')
    diff = np.diff(y)
    significant = diff[np.abs(diff) > .035]
    turns = int(np.sum(significant[1:] * significant[:-1] < 0))
    if turns >= 3:
        return '多次波动型'
    if y[-1] - y[0] > .2:
        return '持续升温型'
    if np.argmax(y) < len(y) * .4 and max(y) - y[-1] > .25:
        return '前期高位后回落型'
    if y[0] - y[-1] > .15:
        return '逐步消退型'
    return '相对平稳型'


def warning(points):
    base = dict(level='常规观察', severity=0, stage='平稳观察', outlook='暂未出现明确的短期变化信号', reason='未触发规则。', evidence=[])
    if len(points)<3 or points[-1]['hour']<2:
        return base | dict(level='观察不足', stage='初始观察', reason='需要至少3点且覆盖2小时，不能据此预测走向。')
    a,b,c = points[-3:]
    if c['hour']-a['hour']>6:
        return base | dict(level='数据稀疏',stage='待补充观测',reason='最近3点跨度超过6小时，暂停预警。')
    gain=a['rank']-c['rank']
    rising=a['rank']>b['rank']>c['rank'] and gain>=8
    oscillating=(b['rank']-a['rank'])*(c['rank']-b['rank'])<0 and min(abs(b['rank']-a['rank']),abs(c['rank']-b['rank']))>=6
    neg=[x.get('negative',0) for x in [a,b,c]]
    evidence=list(dict.fromkeys(w for x in [a,b,c] for w in x.get('words',[])))
    base['evidence']=evidence
    if oscillating and any(x.get('reversal',False) for x in [a,b,c]):
        return base | dict(level='疑似反转振荡',severity=2,stage='波动核查',outlook='可能继续波动，建议核实反转或澄清文本',reason='排名双向变化均至少6位，且标题出现反转/辟谣/澄清词；不代表事实已反转。')
    if rising and neg[0]<neg[1]<neg[2]:
        return base | dict(level='疑似争议升级',severity=2,stage='升温核查',outlook='若排名和负面词倾向继续上升，需提高关注',reason=f'排名连续上升{gain}位，标题负面词倾向连续增加；并非公众情绪判断。')
    if rising:
        return base | dict(level='升温关注',severity=1,stage='快速升温',outlook='短期可能继续升温，需后续观测确认',reason=f'最近{c["hour"]-a["hour"]:.2f}小时排名连续提升{gain}位。')
    if oscillating:
        return base | dict(level='波动关注',severity=1,stage='往复波动',outlook='波动可能延续，当前不能判断反转',reason='最近两个变化方向相反，幅度均至少6位。')
    if a['rank']<b['rank']<c['rank'] and -gain>=6:
        return base | dict(stage='逐步回落',outlook='近期呈消退趋势，是否离榜仍需继续观测',reason=f'最近排名连续下降{-gain}位。')
    base['reason']='近期排名未达到升温或振荡阈值。'
    return base


def load_tracks(folder, include_short=False):
    snapshots, bad = {}, []
    for file in sorted(folder.glob('*.json')):
        try:
            raw = json.loads(file.read_text())
            snap = validate_snapshot(raw)
            snapshots[snap['captured_at']] = snap
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            bad.append(dict(file=file.name, error=str(exc)))
    snaps = sorted(snapshots.values(), key=lambda x: x['captured_at'])
    chains, active = [], {}
    missing = total = 0
    for snap in snaps:
        stamp = datetime.fromisoformat(snap['captured_at'])
        seen = set()
        used = set()
        current_keys = {normalize_title(p['title']) for p in snap['topics']}
        for topic in snap['topics']:
            key = normalize_title(topic['title'])
            if key in seen:
                continue
            seen.add(key)
            total += 1
            missing += topic['heat'] is None
            old = active.get(key)
            if old is not None and old['id'] in used: old = None
            if old is None or (stamp-old['_last']).total_seconds() > 3*3600:
                candidates = []
                for candidate in {v['id']:v for v in active.values()}.values():
                    if candidate['id'] in used or not 0 < (stamp-candidate['_last']).total_seconds() <= 3*3600:
                        continue
                    if normalize_title(candidate['points'][-1]['title']) in current_keys:
                        continue
                    score = title_similarity(candidate['points'][-1]['title'], topic['title'])
                    if score >= .84: candidates.append((score,candidate))
                candidates.sort(key=lambda v:v[0], reverse=True)
                if candidates and (len(candidates)==1 or candidates[0][0]-candidates[1][0]>=.04):
                    score, old = candidates[0]
                    old['links'].append(dict(time=snap['captured_at'], before=old['points'][-1]['title'], after=topic['title'], similarity=round(score,3)))
                    active[key] = old
            if old is None or (stamp - old['_last']).total_seconds() > 3 * 3600:
                old = dict(id=hashlib.sha1((key + snap['captured_at']).encode()).hexdigest()[:12], title=topic['title'], points=[], links=[], start=snap['captured_at'], _last=stamp)
                chains.append(old)
                active[key] = old
            used.add(old['id'])
            sig = text_signal(topic['title'])
            old['points'].append(dict(title=topic['title'], negative=sig['negative'], words=sig['words'], reversal=sig['reversal'], index=round((31-topic['rank'])/30*100,2), time=snap['captured_at'], hour=(stamp-datetime.fromisoformat(old['start'])).total_seconds()/3600, rank=topic['rank'], heat=topic['heat']))
            old['_last'] = stamp
    eligible = []
    for t in chains:
        t.pop('_last')
        t['end'] = t['points'][-1]['time']
        t['duration'] = t['points'][-1]['hour']
        t['eligible'] = t['duration'] >= 6 and len(t['points']) >= 4
        if t['eligible']: eligible.append(t)
    intervals = [(datetime.fromisoformat(b['captured_at'])-datetime.fromisoformat(a['captured_at'])).total_seconds()/3600 for a,b in zip(snaps, snaps[1:])]
    meta = dict(snapshots=len(snaps), records=total, chains=len(chains), eligible=len(eligible), excluded=len(chains)-len(eligible), missing_heat=missing, first=snaps[0]['captured_at'] if snaps else None, last=snaps[-1]['captured_at'] if snaps else None, median_interval_hours=float(np.median(intervals)) if intervals else None, max_gap_hours=max(intervals, default=0), invalid_files=bad)
    meta['similarity_links'] = sum(len(t['links']) for t in chains)
    return (chains if include_short else eligible), meta


class Model:
    def __init__(self, folder=None):
        self.all_tracks, self.meta = load_tracks(folder or ROOT/'data'/'raw', include_short=True)
        self.tracks = [t for t in self.all_tracks if t['eligible']]
        if len(self.tracks) < 12:
            raise ValueError('满足 6 小时、至少 4 个观测点的话题链不足 12 条，暂不能训练。')
        ordered = sorted(self.tracks, key=lambda t:t['end'])
        cutoff = ordered[int(len(ordered)*.7)]['end']
        train_pool = [t for t in ordered if t['end'] < cutoff]
        # 等距确定性抽样，最多 120 条，不把回放话题自身作为原型。
        indices = np.linspace(0, len(train_pool)-1, min(120, len(train_pool)), dtype=int)
        self.train = [train_pool[i] for i in indices]
        self.test = [t for t in ordered if t['start'] > cutoff]
        if len(self.train) < 8:
            raise ValueError('时间划分后的训练链不足 8 条。')
        self.seqs = [features(t) for t in self.train]
        n = len(self.train)
        dist = np.zeros((n,n))
        for i in range(n):
            for j in range(i):
                dist[i,j] = dist[j,i] = dtw(self.seqs[i], self.seqs[j])
        tree = linkage(squareform(dist), method='average')
        self.scores = []
        flat = np.array([np.interp(np.linspace(0,1,24), np.linspace(0,1,len(s)), s[:,0]) for s in self.seqs])
        best = None
        for k in range(2, min(7,n)):
            labels = cut_tree(tree, n_clusters=k).reshape(-1)
            score = float(silhouette_score(dist, labels, metric='precomputed'))
            sizes = list(Counter(labels).values())
            ch = float(calinski_harabasz_score(flat, labels))
            self.scores.append(dict(k=k, silhouette=score, ch=ch, min_cluster=min(sizes)))
            if min(sizes) >= 3 and (best is None or score > best[0]):
                best = (score,labels)
        if best is None:
            k = max(self.scores,key=lambda s:s['silhouette'])['k']
            best = (max(s['silhouette'] for s in self.scores),cut_tree(tree,n_clusters=k).reshape(-1))
        self.labels = best[1]
        self.clusters = []
        for label in sorted(set(self.labels)):
            members = np.where(self.labels == label)[0]
            medoid = int(members[np.argmin(dist[np.ix_(members,members)].sum(axis=1))])
            self.clusters.append(dict(id=int(label), name=describe(np.array([[(31-p['rank'])/30] for p in self.train[medoid]['points']])), count=len(members), medoid=self.train[medoid]['id'], representative=self.train[medoid]['title'], sequence=[(31-p['rank'])/30 for p in self.train[medoid]['points']]))
        train_ids = {t['id']:int(label) for t,label in zip(self.train,self.labels)}
        test_ids = {t['id'] for t in self.test}
        for t in self.all_tracks:
            t['split'] = '训练' if t['id'] in train_ids else ('回放测试' if t['id'] in test_ids else '未入模')
            t['cluster'] = train_ids.get(t['id'])
        self.meta.update(train=len(self.train), test=len(self.test), cutoff=cutoff, best_silhouette=best[0], k=len(self.clusters))
        self.by_id = {t['id']:t for t in self.all_tracks}

    def predict(self, track, count):
        points = track['points'][:count]
        alert = warning(points)
        if len(points) < 3 or points[-1]['hour'] < 2:
            return dict(cluster=None, alert=alert, status='观察不足', matches=[])
        seq = features(track,count)
        matches=[]
        for cluster in self.clusters:
            ref = self.by_id[cluster['medoid']]
            if ref['id'] == track['id']:
                continue
            prefix = [p for p in ref['points'] if p['hour'] <= points[-1]['hour']]
            if len(prefix) < 2:
                continue
            d = dtw(seq,features(ref,len(prefix)))
            matches.append(dict(cluster=cluster['id'],name=cluster['name'],distance=d,reference=ref['id'],reference_points=prefix))
        matches.sort(key=lambda x:x['distance'])
        if not matches:
            return dict(cluster=None,alert=alert,status='无可用参考',matches=[])
        uncertain = matches[0]['distance'] > .22 or (len(matches)>1 and matches[1]['distance']-matches[0]['distance'] < .015)
        return dict(cluster=matches[0]['cluster'],alert=alert,status='匹配接近，需继续观察' if uncertain else '当前最相似模式',matches=matches, uncertainty=uncertain)

    def overview(self):
        return dict(meta=self.meta, clusters=self.clusters,scores=self.scores,topics=[{k:v for k,v in t.items() if k!='points'} | dict(samples=len(t['points']), peak_rank=min(p['rank'] for p in t['points'])) for t in self.tracks])


def synthetic_cases():
    specs=[('demo-rise','模拟：某产品争议逐步升级',[29,22,12,3],['某产品体验讨论','某产品引发质疑','某产品质疑与争议','某产品质疑争议投诉']),('demo-wave','模拟：某事件反复变化',[25,5,24,4],['某事件讨论','某事件争议','某事件辟谣','某事件反转']),('demo-short','模拟：观测不足',[10,8],['测试话题','测试话题'])]
    cases=[]
    for id,title,ranks,texts in specs:
        points=[]
        for i,(rank,text) in enumerate(zip(ranks,texts)):
            sig=text_signal(text)
            points.append(dict(title=text,rank=rank,heat=None,index=(31-rank)/30*100,hour=i,time=f'2026-10-31T{12+i:02d}:00:00+08:00',**sig))
        cases.append(dict(id=id,title=title,points=points,links=[],split='模拟测试',synthetic=True,start=points[0]['time'],end=points[-1]['time']))
    return cases


def bundle(model):
    """预计算每个前缀；前端只展示当前时刻已观察的点。"""
    tracks=[]
    snapshots={}
    for track in model.all_tracks:
        item=dict(track)
        item['predictions']=[]
        for n,p in enumerate(track['points'],1):
            result=model.predict(track,n)
            result['matches']=[{k:v for k,v in match.items() if k!='reference_points'} | dict(reference_count=len(match['reference_points'])) for match in result['matches'][:2]]
            item['predictions'].append(result)
            snapshots.setdefault(p['time'],[]).append(dict(id=track['id'],count=n,rank=p['rank']))
        tracks.append(item)
    cases=synthetic_cases()
    for t in cases:
        t['predictions']=[dict(cluster=None,matches=[],status='独立规则测试，不参与聚类',alert=warning(t['points'][:n])) for n in range(1,len(t['points'])+1)]
    return dict(meta=model.meta,clusters=model.clusters,scores=model.scores,tracks=tracks,cases=cases,
                snapshots=[dict(time=tm,rows=sorted(rows,key=lambda x:x['rank'])) for tm,rows in sorted(snapshots.items())],
                dictionary=NEGATIVE_WORDS,sources=json.loads((ROOT/'data'/'provenance.json').read_text()))
