async function run(){
 const n=$('#sel').value,h=+$('#period').value,out=$('#ov');state(out,'Running prediction…');
 try{const p=await API.getPredictions(n,h),cur=await API.getCurrent(n),mx=p.reduce((a,b)=>b.uv>a.uv?b:a),c=uvCat(mx.uv),now=new Date().getHours();
  out.innerHTML=[['Location',n],['Prediction date',new Date().toLocaleDateString()],['Current UV (sample)',cur.uv],['Predicted max UV',mx.uv],['Expected peak time',mx.label],['Predicted risk',`<span class="badge" style="--c:${c.color}">${c.label}</span>`]].map(x=>`<div class="card stat"><div class="v" style="font-size:1.4rem">${x[1]}</div><div class="l">${x[0]}</div></div>`).join('');
  chart('ch','line',p.map(x=>x.label),[ds('Upper bound (illustrative)',p.map(x=>x.hi),'#94a3b8',{borderDash:[2,3],pointRadius:0,fill:false}),ds('Lower bound',p.map(x=>x.lo),'#94a3b8',{borderDash:[2,3],pointRadius:0,fill:'-1',backgroundColor:'#94a3b833'}),
   ds('UV Index – past hours solid, future dashed (mock)',p.map(x=>x.uv),'#0b2545',{fill:false,segment:{borderDash:ctx=>ctx.p0DataIndex>=now?[6,4]:undefined}})],'UV Index',{x:'Time (hour)'});
  $('#tb').innerHTML=p.map(x=>{const k=uvCat(x.uv);return`<tr><td>${x.label}</td><td>${x.uv}</td><td>${x.lo}–${x.hi}</td><td><span class="badge" style="--c:${k.color}">${k.label}</span></td></tr>`}).join('');
 }catch(e){state(out,'Prediction failed: '+e.message,1)}
}
document.addEventListener('DOMContentLoaded',async()=>{await fillSelect($('#sel'),run);$('#period').onchange=run;$('#refresh').onclick=run;run()});
