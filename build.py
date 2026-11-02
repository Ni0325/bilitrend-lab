"""生成首页与4个独立子页面。--cached仅更新页面，不重训。"""
import argparse
import json
import re
from pathlib import Path
from engine import ROOT, Model, bundle

PAGES = {'monitor':'预警中心','explore':'话题详情','clusters':'聚类实验','data':'数据与测试'}

def render_pages(packed, destination=None):
    template=(ROOT/'static'/'page_template.html').read_text()
    css=(ROOT/'static'/'style.css').read_text()
    js=(ROOT/'static'/'app.js').read_text()
    sections={}
    for name in PAGES:
        start=template.index('<section id="'+name+'">')
        end=template.index('</section>',start)+len('</section>')
        sections[name]=template[start:end]
    first=template.index('<section id="monitor">')
    prefix=template[:first]
    footer=template[template.index('<footer>'):]
    hero=re.search(r'<section class="hero">.*?</section>',prefix,re.S).group()
    target=Path(destination) if destination else ROOT/'BiliTrend.html'
    encoded=json.dumps(packed,ensure_ascii=False,separators=(',',':'),allow_nan=False).replace('<','\\u003c')
    for offline in (False,True):
        def link(key):
            if offline:return target.name if key=='home' else target.stem+'_'+key+'.html'
            return '/' if key=='home' else '/static/'+key+'.html'
        for key in ('home',*PAGES):
            heading='首页' if key=='home' else PAGES[key]
            nav='<nav aria-label="主导航">'+''.join(f'<a data-page="{p}" href="{link(p)}"'+(' aria-current="page"' if p==key else '')+'>'+label+'</a>' for p,label in PAGES.items())+'</nav>'
            head=re.sub(r'<nav>.*?</nav>',lambda _:nav,prefix)
            head=head.replace('class="brand" href="#"',f'class="brand" data-page="home" href="{link("home")}"')
            head=head.replace('<title>潮汐 · B站热搜演化实验室</title>',f'<title>{heading} · 潮汐热搜实验室</title>')
            if key!='home':
                sub=f'<section class="subhero"><a data-page="home" href="{link("home")}">← 返回首页</a><p class="eyebrow">TREND LAB / {key.upper()}</p><h1>{heading}</h1><p>2026 年 10 月 B站热搜</p></section>'
                head=head.replace(hero,sub)
            body=sections.get(key,'<section class="entry-list"><h2>选择一个功能页面</h2>'+''.join(f'<a data-page="{p}" href="{link(p)}"><span>0{i}</span><strong>{label}</strong><span>进入页面 →</span></a>' for i,(p,label) in enumerate(PAGES.items(),1))+'</section>')
            if key=='explore':
                clock=re.search(r'<section class="clock">.*?</section>',head,re.S).group()
                note=re.search(r'<p id="clock-note".*?</p>',head,re.S).group()
                head=head.replace(clock,'').replace(note,'').replace('<body>','<body class="page-explore">')
                body=body.replace('<div class="workspace">','<div class="explorer-shell"><div class="workspace">',1)
                body=body.rsplit('</section>',1)[0]+'<div class="explorer-controls">'+clock+note+'</div></div></section>'
            html=head+body+footer
            if offline:
                html=html.replace('<link rel="stylesheet" href="/static/style.css">','<style>'+css+'</style>')
                html=html.replace('<script src="/static/app.js"></script>','<script>const EMBED='+encoded+';\n'+js+'</script>')
                name=target.name if key=='home' else target.stem+'_'+key+'.html'
                (target.parent/name).write_text(html)
                (ROOT/'static'/name).write_text(html)
            else:
                (ROOT/'static'/('index.html' if key=='home' else key+'.html')).write_text(html)
    return packed

def build(destination=None,cached=False):
    if cached: packed=json.loads((ROOT/'data'/'bundle.json').read_text())
    else:
        packed=bundle(Model())
        (ROOT/'data'/'bundle.json').write_text(json.dumps(packed,ensure_ascii=False,separators=(',',':'),allow_nan=False))
        (ROOT/'data'/'results.json').write_text(json.dumps({k:packed[k] for k in ['meta','clusters','scores']},ensure_ascii=False,indent=2))
    render_pages(packed,destination)
    print('已生成首页与4个独立子页面')
    return packed

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--cached',action='store_true');args=parser.parse_args();build(cached=args.cached)
