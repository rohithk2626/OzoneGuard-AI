const agg=(rows,k)=>{if(k===1)return rows;const o=[];for(let i=0;i<rows.length;i+=k){const s=rows.slice(i,i+k),m=f=>+(s.reduce((a,b)=>a+b[f],0)/s.length).toFixed(1);o.push({date:s[0].date,ozone:m('ozone'),uv:m('uv'),temp:m('temp'),humidity:m('humidity'),cloud:m('cloud')})}return o};
async function run(){
 const n=$('#sel').value,to=new Date($('#to').value),from=new Date($('#from').value),days=Math.round((to-from)/864e5)+1,box=$('#st');
 if(!(days>0&&days<=365)){state(box,'Choose a valid date range (1–365 days).',1);return}
 state(box,'Loading history…');
 try{const full=await API.getAnalytics(n,days,to);if(!full.length){state(box,'No data for this range.');return}
  const top=full.reduce((a,b)=>b.uv>a.uv?b:a),avg=f=>(full.reduce((a,b)=>a+b[f],0)/full.length).toFixed(1);
  box.innerHTML=[['Avg ozone (DU)',avg('ozone')],['Avg UV Index',avg('uv')],['Max UV Index',top.uv],['Min UV Index',Math.min(...full.map(x=>x.uv))],['Highest UV period',top.date]].map(x=>`<div class="card stat"><div class="v" style="font-size:1.5rem">${x[1]}</div><div class="l">${x[0]}</div></div>`).join('');
  const r=agg(full,{Daily:1,Weekly:7,Monthly:30}[$('#per').value]),L=r.map(x=>x.date);
  [['c1','Ozone (DU)','ozone','#14b8a6'],['c2','UV Index','uv','#e8801a'],['c3','Temperature (°C)','temp','#dc3545'],['c4','Humidity (%)','humidity','#38bdf8'],['c5','Cloud cover (%)','cloud','#64748b']].forEach(c=>chart(c[0],'line',L,[ds(c[1],r.map(x=>x[c[2]]),c[3],{fill:true})],c[1],{x:'Date'}));
  chart('c6','scatter',undefined,[{label:'Ozone vs UV (daily)',data:full.map(x=>({x:x.ozone,y:x.uv})),backgroundColor:'#0b2545aa'}],'UV Index',{o:{scales:{x:{type:'linear',title:{display:true,text:'Total column ozone (DU)'}},y:{beginAtZero:true,title:{display:true,text:'UV Index'}}}}});
 }catch(e){state(box,'Failed to load analytics: '+e.message,1)}
}
document.addEventListener('DOMContentLoaded',async()=>{
 const t=new Date(),f=new Date();f.setDate(t.getDate()-29);$('#to').value=t.toISOString().slice(0,10);$('#from').value=f.toISOString().slice(0,10);
 $('#grid').innerHTML=[['c1','Historical ozone'],['c2','Historical UV Index'],['c3','Temperature trend'],['c4','Humidity trend'],['c5','Cloud cover trend'],['c6','Ozone and UV relationship']].map(c=>`<div class="card"><h3>${c[1]}</h3><div class="chartbox"><canvas id="${c[0]}"></canvas></div></div>`).join('');
 await fillSelect($('#sel'),run);['from','to','per'].forEach(i=>$('#'+i).onchange=run);run();
});
