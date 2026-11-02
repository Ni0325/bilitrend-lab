const fs=require('fs'),vm=require('vm'),assert=require('assert');
(async()=>{for(const page of ['BiliTrend','BiliTrend_monitor','BiliTrend_explore','BiliTrend_clusters','BiliTrend_data']){
 const html=fs.readFileSync(require('path').join(__dirname,page+'.html'),'utf8'),ids=new Set([...html.matchAll(/id="([^"]+)"/g)].map(m=>m[1])),els=new Map();
 const node=()=>({value:'',innerHTML:'',textContent:'',style:{},dataset:{},querySelectorAll:()=>[],scrollIntoView:()=>{},classList:{toggle:()=>{}}});
 const links=[...html.matchAll(/data-page="([^"]+)" href="([^"]+)"/g)].map(m=>({dataset:{page:m[1]},href:new URL(m[2],'file:///outputs/'+page+'.html').href}));
 const get=id=>{if(!ids.has(id))return null;if(!els.has(id)){const e=node();e.value=id==='alert-filter'?'all':id==='speed'?'1500':'';els.set(id,e);}return els.get(id);};
 const ctx={document:{getElementById:get,createElement:node,querySelectorAll:s=>s==='a[data-page]'?links:[],querySelector:s=>links.find(a=>s.includes('"'+a.dataset.page+'"'))},location:{search:'?time=2026-10-31T23%3A40%3A00%2B08%3A00'},URL,URLSearchParams,console,Blob,setTimeout,setInterval,clearInterval,fetch:()=>{throw Error('offline network')}};
 vm.createContext(ctx);vm.runInContext(html.match(/<script>([\s\S]*)<\/script>/)[1],ctx);await new Promise(r=>setTimeout(r,0));assert.equal(get('error').textContent,'');if(get('mode'))assert(get('mode').textContent.includes('离线'));assert(get('stats').innerHTML.includes('30'));assert(links.every(a=>a.href.includes('time=')));
 if(page.endsWith('data')){get('invalid').onclick();await get('validate').onclick();assert(get('validation').textContent.includes('校验失败'));}
 if(page.endsWith('explore'))assert(get('chart').innerHTML.includes('<svg'));
 console.log(page+' OK');
}})();
