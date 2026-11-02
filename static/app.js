'use strict';
// 各子页共用渲染器：未包含的面板使用脱离文档的节点，不显示在页面中。
const absent=new Map();
const $=id=>{const found=document.getElementById(id);if(found)return found;if(!absent.has(id)){const node=document.createElement('div');node.value=id==='alert-filter'?'all':'';absent.set(id,node);}return absent.get(id);}, esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmt=s=>s?.replace('T',' ').slice(0,16)||'—';
let data,tracks,frames,frame,selected,metric='rank',timer,rows=[],online=typeof EMBED==='undefined';
const names={rank:'真实排名',index:'排名热度指数',negative:'标题负面词倾向'};
async function api(path,body){const r=await fetch(path,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const d=await r.json();if(!r.ok)throw Error(d.error||'请求失败');return d;}
function stop(){clearInterval(timer);timer=null;$('play').textContent='播放回放';}
function curve(target,lines,key='rank',small=false){
 const w=680,h=small?140:250,L=40,R=15,T=16,B=32,max=Math.max(1,...lines.flatMap(l=>l.points.map(p=>p.hour))),x=v=>L+v/max*(w-L-R),y=v=>T+(key==='rank'?(v-1)/29:1-v/100)*(h-T-B);
 let svg=`<svg viewBox="0 0 ${w} ${h}" role="img" aria-label="${names[key]}随时间的变化">`;
 for(const v of key==='rank'?[1,10,20,30]:[0,50,100])svg+=`<line x1="${L}" y1="${y(v)}" x2="${w-R}" y2="${y(v)}" stroke="#e2e8ed"/><text x="5" y="${y(v)+4}" font-size="11" fill="#778591">${v}</text>`;
 for(let i=0;i<=4;i++)svg+=`<text x="${x(max*i/4)}" y="${h-6}" font-size="11" fill="#778591" text-anchor="middle">${(max*i/4).toFixed(1)}h</text>`;
 for(const l of lines){svg+=`<polyline points="${l.points.map(p=>`${x(p.hour)},${y(p[key])}`).join(' ')}" stroke="${l.color}" fill="none" stroke-width="2.5" ${l.dash?'stroke-dasharray="6 5"':''}/>`;if(!small)for(const p of l.points)svg+=`<circle cx="${x(p.hour)}" cy="${y(p[key])}" r="3" fill="${l.color}"><title>${esc(p.title)} / ${fmt(p.time)} / ${p[key]}</title></circle>`;}
 target.innerHTML=svg+'</svg>';
}
function mode(p){return p.cluster===null?'观察不足 / 无匹配':`C${p.cluster+1} · ${data.clusters.find(c=>c.id===p.cluster)?.name||''}${p.uncertainty?'（暂定）':''}`;}
function changeFrame(){
 frame=frames[+$('timeline').value];
 rows=frame.rows.map(r=>{const t=tracks.get(r.id);return {...r,track:t,point:t.points[r.count-1],prediction:t.predictions[r.count-1]};});
 $('clock-label').textContent=fmt(frame.time);$('clock-note').textContent=`${+$('timeline').value+1} / ${frames.length} 个回放时刻 · 采样时间不规则 · 训练截止 ${fmt(data.meta.cutoff)} · 所有曲线仅显示已观察前缀`;
 const alerted=rows.filter(r=>r.prediction.alert.severity>0),matched=rows.filter(r=>r.prediction.cluster!==null);
 $('stats').innerHTML=[[rows.length,'当前快照在榜话题'],[alerted.length,'当前关注信号'],[matched.length,'已匹配模式（含暂定）'],[data.meta.similarity_links,'全月相似标题关联']].map(([n,s])=>`<div class="stat"><b>${n}</b><span>${s}</span></div>`).join('');
 renderAlerts();renderDistribution();
 if(!rows.some(r=>r.id===selected))selected=(alerted[0]||rows[0])?.id;
 renderList();renderDetail();
 document.querySelectorAll('a[data-page]').forEach(a=>{const u=new URL(a.href);u.searchParams.set('time',frame.time);a.href=u.href;});
}
function pageHref(page,extra={}){const a=document.querySelector('a[data-page="'+page+'"]');const u=new URL(a.href);if(frame)u.searchParams.set('time',frame.time);for(const [k,v] of Object.entries(extra))u.searchParams.set(k,v);return u.href;}
function choose(id){selected=id;renderList();renderDetail();}
function renderAlerts(){const level=$('alert-filter').value;const rs=rows.filter(r=>r.prediction.alert.severity>0&&(level==='all'||r.prediction.alert.severity===+level)).sort((a,b)=>b.prediction.alert.severity-a.prediction.alert.severity||a.rank-b.rank);
 $('alerts').innerHTML=rs.length?'<table><thead><tr><th>等级 / 信号</th><th>话题</th><th>阶段与原因</th><th>可能走向</th></tr></thead><tbody>'+rs.map(r=>{const a=r.prediction.alert;return `<tr><td><span class="badge severity-${a.severity}">${a.severity}级 · ${esc(a.level)}</span></td><td><button data-topic="${r.id}">${esc(r.point.title)}</button><br><small>${fmt(frame.time)} · 第${r.rank}名</small></td><td>${esc(a.stage)}<br>${esc(a.reason)}</td><td>${esc(a.outlook)}</td></tr>`;}).join('')+'</tbody></table>':'<div class="empty">当前时刻没有符合筛选条件的预警。可以拖动时间轴查看其他时刻。</div>';
 $('alerts').querySelectorAll('[data-topic]').forEach(b=>b.onclick=()=>{if(!document.getElementById('explore')){location.href=pageHref('explore',{topic:b.dataset.topic});return;}choose(b.dataset.topic);$('explore').scrollIntoView({behavior:'smooth'});});
}
function renderList(){const q=$('search').value.trim().toLowerCase(),c=$('cluster-filter').value;const visible=rows.filter(r=>r.point.title.toLowerCase().includes(q)&&(c===''||String(r.prediction.cluster)===c));
 $('list-count').textContent=`当前在榜 ${rows.length} 条 · 筛选后 ${visible.length} 条`;
 $('topic-list').innerHTML=visible.length?visible.map(r=>`<button class="topic ${selected===r.id?'active':''}" data-id="${r.id}"><b>${r.rank}.</b> <span${r.count>3?' class="observed-title"':''}>${esc(r.point.title)}</span><small>${r.count}次观测 · ${r.point.hour.toFixed(1)}h · ${esc(r.prediction.alert.level)}</small></button>`).join(''):'<p class="empty">没有匹配话题</p>';
 $('topic-list').querySelectorAll('[data-id]').forEach(b=>b.onclick=()=>choose(b.dataset.id));
}
function renderDetail(){const r=rows.find(r=>r.id===selected);if(!r)return;const t=r.track,p=r.prediction,a=p.alert,observed=t.points.slice(0,r.count),match=p.matches[0];
 $('topic-title').textContent=r.point.title;$('topic-meta').textContent=`已观测 ${observed.length} 点 / ${r.point.hour.toFixed(1)} 小时 / 起点 ${fmt(t.start)}`;
 const lines=[{points:observed,color:'#147bba'}];if(match){const ref=tracks.get(match.reference);lines.push({points:ref.points.slice(0,match.reference_count),color:'#ed789c',dash:true});}
 curve($('chart'),lines,metric);$('chart-note').textContent=metric==='rank'?'真实名次，纵轴越靠上排名越高。横轴为各话题首次观测后的小时数。':metric==='index'?'由名次线性换算，不是平台热度；它与排名并非独立证据。':'按每次观测标题的词典命中计分；平线表示标题措辞未变，不表示公众情绪不变。';
 $('prediction').textContent=mode(p);$('match-detail').textContent=match?`${p.status}；距离 ${match.distance.toFixed(3)}（非概率）。参考：${tracks.get(match.reference).title}`:p.status;
 $('alert').textContent=`${a.severity?`${a.severity}级 · `:''}${a.level} / ${a.stage}`;$('alert').style.color=a.severity>0?'#b04a70':'#147bba';$('alert-reason').textContent=a.reason;$('outlook').textContent='可能走向：'+a.outlook;$('evidence').textContent='最近标题证据词：'+(a.evidence.join('、')||'无命中');
 $('mini-charts').innerHTML=Object.keys(names).filter(k=>k!==metric).map(k=>`<div><p>${names[k]}</p><div class="small" id="small-${k}"></div></div>`).join('');Object.keys(names).filter(k=>k!==metric).forEach(k=>curve($('small-'+k),lines,k,true));
 document.querySelectorAll('[data-metric]').forEach(b=>b.classList.toggle('active',b.dataset.metric===metric));
 const links=t.links.filter(l=>l.time<=frame.time);$('links').innerHTML=links.length?links.map(l=>`<p>${fmt(l.time)}：${esc(l.before)} → ${esc(l.after)} · 相似度 ${l.similarity}</p>`).join(''):'<p>当前已观察片段没有相似标题合并，使用规范化标题精确匹配。</p>';
 $('records').innerHTML='<table><tr><th>时间</th><th>原始标题</th><th>名次</th><th>指数</th><th>负面词分</th></tr>'+observed.map(v=>`<tr><td>${fmt(v.time)}</td><td>${esc(v.title)}</td><td>${v.rank}</td><td>${v.index.toFixed(1)}</td><td>${v.negative}</td></tr>`).join('')+'</table>';
}
function renderDistribution(){const buckets=[...data.clusters.map(c=>({value:String(c.id),label:`C${c.id+1} ${c.name}`})),{value:'null',label:'观察不足 / 无匹配'}];$('distribution').innerHTML=buckets.map(b=>{const n=rows.filter(r=>String(r.prediction.cluster)===b.value).length;return `<button class="bar-row" data-filter="${b.value}"><span>${esc(b.label)}</span><div class="bar-bg"><div class="bar-fill" style="width:${n/Math.max(rows.length,1)*100}%"></div></div><b>${n}</b></button>`;}).join('');$('distribution').querySelectorAll('[data-filter]').forEach(b=>b.onclick=()=>{if(!document.getElementById('explore')){location.href=pageHref('explore',{cluster:b.dataset.filter});return;}$('cluster-filter').value=b.dataset.filter;renderList();$('explore').scrollIntoView({behavior:'smooth'});});}
function renderStatic(){const m=data.meta;
 $('cluster-filter').innerHTML='<option value="">全部模式</option>'+data.clusters.map(c=>`<option value="${c.id}">C${c.id+1} ${esc(c.name)}</option>`).join('')+'<option value="null">观察不足 / 无匹配</option>';
 $('scores').innerHTML='<table><tr><th>簇数</th><th>轮廓系数</th><th>CH指数</th><th>最小簇</th></tr>'+data.scores.map(s=>`<tr class="${s.k===m.k?'chosen':''}"><td>${s.k}${s.k===m.k?' · 选定':''}</td><td>${s.silhouette.toFixed(3)}</td><td>${s.ch.toFixed(2)}</td><td>${s.min_cluster}</td></tr>`).join('')+'</table>';
 $('cluster-list').innerHTML=data.clusters.map(c=>`<div class="cluster"><p>C${c.id+1} · ${c.count}条训练轨迹</p><h3>${esc(c.name)}</h3><div class="mini" id="cluster-${c.id}"></div><p>代表：${esc(c.representative)}</p></div>`).join('');data.clusters.forEach(c=>curve($('cluster-'+c.id),[{points:tracks.get(c.medoid).points,color:'#147bba'}],'rank',true));
 $('data-summary').textContent=`${fmt(m.first)} 至 ${fmt(m.last)}：${m.snapshots}份快照，${m.records.toLocaleString()}条记录，${m.chains}条链，其中${m.eligible}条满足入模长度。确定性抽样训练${m.train}条，后段独立测试长链${m.test}条；短链保留展示。时间间隔中位数${m.median_interval_hours.toFixed(2)}h、最大${m.max_gap_hours.toFixed(2)}h，未达到固定半小时采样。真实热度缺失${m.missing_heat}条。`;
 $('dictionary').textContent=Object.entries(data.dictionary).map(([w,v])=>`${w}: ${v}`).join('；')+'。各词命中一次计分，总分最高100；不处理复杂语义或讽刺。';
 $('case').innerHTML=data.cases.map((t,i)=>`<option value="${i}">${esc(t.title)}</option>`).join('');renderCase(true);
}
function renderCase(reset=false){const t=data.cases[+$('case').value||0];$('case-time').max=t.points.length;if(reset)$('case-time').value=t.points.length;const n=+$('case-time').value,a=t.predictions[n-1].alert;curve($('case-chart'),[{points:t.points.slice(0,n),color:'#ed789c'}],'rank');$('case-title').textContent=`${a.level} · ${a.severity}级 / ${a.stage}`;$('case-result').textContent=a.reason+' '+a.outlook;$('case-words').textContent=`模拟标题：${t.points[n-1].title}；命中词：${t.points[n-1].words.join('、')||'无'}。仅验证规则，不验证模型在真实舆情上的准确率。`;}
function install(d){data=d;tracks=new Map(d.tracks.map(t=>[t.id,t]));frames=d.snapshots.filter(f=>f.time>d.meta.cutoff);if(!frames.length)throw Error('没有训练截止后的回放记录');$('timeline').max=frames.length-1;const query=new URLSearchParams(location.search);const wanted=query.get('time');let initial=frames.findIndex(f=>f.time===wanted);$('timeline').value=initial<0?frames.length-1:initial;selected=query.get('topic');renderStatic();$('cluster-filter').value=query.get('cluster')||'';changeFrame();$('mode').textContent=online?'本地服务 · 历史回放':'独立 HTML · 离线回放';}
function example(good){$('json-input').value=JSON.stringify({captured_at:'2026-11-02T14:00:00+08:00',topics:[{title:good?'测试输入（非真实热搜）':'',rank:good?5:-1,heat:null}]},null,2);}
function validateLocal(d){if(!d||!Array.isArray(d.topics)||!d.topics.length||d.topics.length>200)throw Error('topics必须包含1至200条话题');if(typeof d.captured_at!=='string'||!/(Z|[+-]\d\d:\d\d)$/.test(d.captured_at)||!Number.isFinite(Date.parse(d.captured_at)))throw Error('时间无效或缺少时区');for(const t of d.topics){if(!t||typeof t.title!=='string'||!t.title.trim()||t.title.length>200)throw Error('标题不能为空且不超过200字');if(!Number.isInteger(t.rank)||t.rank<1||t.rank>30)throw Error('排名必须为1至30的整数');if(t.heat!=null&&(typeof t.heat!=='number'||!Number.isFinite(t.heat)||t.heat<0))throw Error('热度必须是非负有限数或null');}return '校验通过；单个快照不足以形成轨迹。本测试不写入数据。';}
async function collection(path){try{$('collect-status').textContent='请求处理中…';const d=await api(path,{});showStatus(d);}catch(e){$('collect-status').textContent=e.message;}}
function showStatus(d){$('collect-status').textContent=`定时采集：${d.running?'运行中（30分钟间隔）':'已停止'}。${d.message||''}${d.last_attempt?' 最近尝试：'+fmt(d.last_attempt):''}`;const s=d.snapshot;$('live-list').innerHTML=s?`<p>上次成功：${fmt(s.captured_at)}（独立于历史回放）</p>`+s.topics.map(t=>`<div>${t.rank}. ${esc(t.title)}</div>`).join(''):'';}
$('timeline').oninput=()=>{stop();changeFrame();};$('latest').onclick=()=>{stop();$('timeline').value=frames.length-1;changeFrame();};$('play').onclick=()=>{if(timer){stop();return;}if(+$('timeline').value===frames.length-1)$('timeline').value=0;changeFrame();$('play').textContent='暂停回放';timer=setInterval(()=>{if(+$('timeline').value>=frames.length-1){stop();return;}$('timeline').value=+$('timeline').value+1;changeFrame();},+$('speed').value);};$('speed').onchange=stop;
$('search').oninput=renderList;$('cluster-filter').onchange=renderList;$('alert-filter').onchange=renderAlerts;document.querySelectorAll('[data-metric]').forEach(b=>b.onclick=()=>{metric=b.dataset.metric;renderDetail();});$('case').onchange=()=>renderCase(true);$('case-time').oninput=()=>renderCase();$('valid').onclick=()=>example(true);$('invalid').onclick=()=>example(false);
$('validate').onclick=async()=>{try{const d=JSON.parse($('json-input').value);const message=online?(await api('/api/validate',d)).message:validateLocal(d);$('validation').textContent=message;}catch(e){$('validation').textContent='校验失败：'+e.message;}};
$('collect').onclick=()=>collection('/api/collect');$('auto-start').onclick=()=>collection('/api/collector/start');$('auto-stop').onclick=()=>collection('/api/collector/stop');
$('train').onclick=async()=>{stop();$('train').disabled=true;$('train').textContent='重新计算中…';try{install(await api('/api/train',{}));}catch(e){$('error').textContent=e.message;}finally{$('train').disabled=false;$('train').textContent='重新训练';}};
$('export').onclick=()=>{const clean=v=>'"'+String(v??'').replace(/^[=+@-]/,"'$&").replace(/"/g,'""')+'"';const output=[['回放时间','话题','排名','等级','信号','阶段','原因','可能走向'],...rows.filter(r=>r.prediction.alert.severity>0).map(r=>{const a=r.prediction.alert;return [frame.time,r.point.title,r.rank,a.severity,a.level,a.stage,a.reason,a.outlook];})];const url=URL.createObjectURL(new Blob(['\ufeff'+output.map(r=>r.map(clean).join(',')).join('\r\n')],{type:'text/csv;charset=utf-8'}));const a=document.createElement('a');a.href=url;a.download='bili_alerts_'+frame.time.slice(0,16).replace(/:/g,'-')+'.csv';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};
example(true);if(!online){for(const id of ['collect','auto-start','auto-stop','train'])$(id).disabled=true;$('collect-status').textContent='离线HTML不执行网络采集或训练；这些功能请启动Python项目使用。';$('train').textContent='已内嵌训练结果';}
(async()=>{try{install(online?await api('/api/bundle'):EMBED);if(online){showStatus(await api('/api/collector/status'));setInterval(()=>api('/api/collector/status').then(showStatus).catch(()=>{}),15000);}}catch(e){$('error').textContent=e.message;}})();
