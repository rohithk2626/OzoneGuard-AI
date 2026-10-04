document.addEventListener('DOMContentLoaded',async()=>{
 const n=getLoc(),box=$('#sum');$('#loc').textContent=n;state(box,'Loading…');
 try{const [d,p,h]=await Promise.all([API.getCurrent(n),API.getPredictions(n,24),API.getHistory(n,14)]),c=uvCat(d.uv);
  box.innerHTML=`<div class="card stat"><div class="v" style="font-size:1.3rem">${ozoneState(d.ozone)}</div><div class="l">Ozone condition (${d.ozone} DU)</div></div><div class="card stat"><div class="v">${d.uv}</div><div class="l">Current UV Index</div></div><div class="card stat"><span class="badge" style="--c:${c.color}">${c.label}</span><div class="l">Risk classification</div></div><div class="card stat"><div class="v" style="font-size:1.3rem">${d.temp} °C · ${d.humidity}% · ${d.cloud}% cloud</div><div class="l">Weather summary</div></div>`;
  chart('f','line',p.map(x=>x.label),[ds('Predicted UV (mock)',p.map(x=>x.uv),'#14b8a6',{fill:true})],'UV Index',{x:'Hour'});
  chart('h','line',h.map(x=>x.date),[ds('Daily UV (sample)',h.map(x=>x.uv),'#e8801a',{fill:true})],'UV Index',{x:'Date'});
 }catch(e){state(box,'Could not load dashboard: '+e.message,1)}
});
