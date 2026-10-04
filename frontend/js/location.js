let map,marker,LOCS=[];
async function show(n){
 setLoc(n);$('#search').value=n;$('#sel').value=n;const out=$('#out');state(out,'Loading environmental data…');
 try{const d=await API.getCurrent(n);
  if(map){map.setView([d.lat,d.lon],7);marker.setLatLng([d.lat,d.lon]).bindPopup(n)}
  out.innerHTML=`<h2>${n}</h2><div class="note">${MOCK_NOTE}</div><div class="grid">${statCards(d)}</div><div class="grid two" style="margin-top:18px">${uvCard(d.uv)}
  <div class="card"><h3>Additional information</h3><p><b>Ozone condition:</b> ${ozoneState(d.ozone)}</p><p><b>Weather:</b> ${d.temp} °C, humidity ${d.humidity}%, cloud ${d.cloud}%, wind ${d.wind} km/h</p><p><b>Last updated:</b> ${fmt(d.updated)}</p><p><b>Data source:</b> ${d.source==='mock'?'Sample/mock data (not live)':'Backend API'}</p></div></div>`;
  lucide.createIcons();
 }catch(e){state(out,'Could not load data: '+e.message,1)}
}
const nearest=(la,lo)=>LOCS.map(l=>[l,Math.hypot(l.lat-la,l.lon-lo)]).sort((a,b)=>a[1]-b[1])[0][0];
document.addEventListener('DOMContentLoaded',async()=>{
 map=L.map('map').setView([22.5,79],5);L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{attribution:'© OpenStreetMap'}).addTo(map);marker=L.marker([22.5,79]).addTo(map);
 LOCS=await fillSelect($('#sel'),show)||[];$('#dl').innerHTML=LOCS.map(l=>`<option value="${l.name}">`).join('');
 $('#search').onchange=e=>{const l=LOCS.find(x=>x.name.toLowerCase()===e.target.value.trim().toLowerCase());l?show(l.name):state($('#out'),'No sample location matches “'+e.target.value+'”. Try a listed city.',1)};
 map.on('click',e=>show(nearest(e.latlng.lat,e.latlng.lng).name));
 $('#gps').onclick=()=>{if(!navigator.geolocation)return state($('#out'),'Geolocation is not supported.',1);
  navigator.geolocation.getCurrentPosition(p=>show(nearest(p.coords.latitude,p.coords.longitude).name),()=>state($('#out'),'Location permission denied. Select a city instead.',1))};
 show(getLoc());
});
