/* Shared helpers: nav, footer, UV categories, location state, charts. */
const $=(s,r=document)=>r.querySelector(s);
const UVC=[[2,'Low','#2ea043','Safe for most people. Sunglasses on bright days.'],[5,'Moderate','#d4a72c','Wear sunscreen and sunglasses; seek shade around midday.'],[7,'High','#e8801a','Use SPF 30+, a hat and sunglasses; limit sun 10am–4pm.'],[10,'Very High','#dc3545','Avoid midday sun; cover up and use SPF 50+, reapply often.'],[99,'Extreme','#8b5cf6','Stay indoors at midday; unprotected skin can burn in minutes.']];
const uvCat=v=>{const r=Math.round(v),c=UVC.find(x=>r<=x[0]);return{label:c[1],color:c[2],tip:c[3]}};
const getLoc=()=>localStorage.getItem('og_loc')||'Hyderabad';
const setLoc=n=>localStorage.setItem('og_loc',n);
const ozoneState=d=>d<220?'Depleted (ozone-hole range, <220 DU)':d<250?'Below typical':d<=300?'Typical for the region':'Above typical';
const fmt=iso=>new Date(iso).toLocaleString();
function layout(){
 const P=[['index.html','Home'],['locations.html','Location'],['predictions.html','Predictions'],['analytics.html','Analytics'],['dashboard.html','Dashboard'],['about.html','About']];
 const cur=location.pathname.split('/').pop()||'index.html';
 const a=p=>`<a href="${p[0]}" class="${cur===p[0]?'on':''}">${p[1]}</a>`;
 $('#nav').outerHTML=`<header class="nav"><div class="wrap"><a class="logo" href="index.html"><i data-lucide="shield-check"></i>OzoneGuard AI</a><button class="burger" aria-label="Menu" onclick="document.querySelector('.links').classList.toggle('open')"><i data-lucide="menu"></i></button><nav class="links">${a(P[0])}<span class="grp">${a(P[1])}${a(P[2])}${a(P[3])}</span>${a(P[4])}${a(P[5])}<a class="btn" href="login.html" style="color:#fff;opacity:1">Login / Sign Up</a></nav></div></header>`;
 $('#foot').outerHTML=`<footer><div class="wrap"><b style="color:#fff">OzoneGuard AI</b> – B.Tech CSE-AIML final-year project<p style="margin:10px 0">${P.map(a).join('')}</p><p>Data sources (planned): satellite total column ozone (e.g. NASA OMI/TROPOMI), weather and UV APIs. ${MOCK_NOTE}</p><p style="margin-top:8px">© ${new Date().getFullYear()} OzoneGuard AI</p></div></footer>`;
 window.lucide&&lucide.createIcons();
}
const state=(el,msg,err)=>el.innerHTML=`<div class="state ${err?'err':''}">${msg}</div>`;
/* Fill a <select> with locations and keep selection in sync with stored location. */
async function fillSelect(sel,onChange){
 try{const L=await API.getLocations();sel.innerHTML=L.map(l=>`<option>${l.name}</option>`).join('');sel.value=getLoc();sel.onchange=()=>{setLoc(sel.value);onChange(sel.value)};return L}
 catch(e){sel.innerHTML='<option>Unavailable</option>'}
}
function statCards(d){
 const c=[['Total Column Ozone',d.ozone,' DU','layers'],['UV Index',d.uv,'','sun'],['Temperature',d.temp,' °C','thermometer'],['Humidity',d.humidity,' %','droplets'],['Cloud Cover',d.cloud,' %','cloud'],['Wind Speed',d.wind,' km/h','wind']];
 return c.map(x=>`<div class="card stat"><i data-lucide="${x[3]}"></i><div class="v">${x[1]}<small>${x[2]}</small></div><div class="l">${x[0]}</div></div>`).join('');
}
function uvCard(uv){const c=uvCat(uv);return`<div class="card uvcard" style="--c:${c.color}"><span class="badge">${c.label}</span><div class="stat"><div class="v" style="font-size:3rem">${uv}</div><div class="l">UV Index (0–2 Low · 3–5 Moderate · 6–7 High · 8–10 Very High · 11+ Extreme)</div></div><p style="margin-top:8px"><b>Precautions:</b> ${c.tip}</p></div>`}
const charts={};
function chart(id,type,labels,datasets,y,opts={}){
 charts[id]&&charts[id].destroy();
 charts[id]=new Chart(document.getElementById(id),{type,data:{labels,datasets},options:{responsive:true,maintainAspectRatio:false,interaction:{mode:'index',intersect:false},
  scales:{y:{title:{display:true,text:y},beginAtZero:true},x:{title:{display:!!opts.x,text:opts.x||''},ticks:{maxTicksLimit:12}}},...opts.o}});
}
const ds=(label,data,color,extra)=>({label,data,borderColor:color,backgroundColor:color+'33',tension:.35,pointRadius:2,...extra});
document.addEventListener('DOMContentLoaded',layout);
