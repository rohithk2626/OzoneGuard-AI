/* Centralized API layer. Set USE_MOCK=false and BASE_URL to connect FastAPI. */
const API_CONFIG={BASE_URL:'http://localhost:8000',USE_MOCK:true};
const MOCK_NOTE='Demo mode: values are sample (mock) data, not live NASA, satellite or API observations.';
// name, lat, lon, ozone(DU), uv, temp, humidity, cloud, wind
const MOCK_LOCS=[['Hyderabad',17.385,78.487,262,9,31,55,40,12],['Delhi',28.614,77.209,278,7,29,48,25,9],['Mumbai',19.076,72.878,255,8,32,72,50,15],['Chennai',13.083,80.271,250,10,33,68,35,14],['Bengaluru',12.972,77.595,258,8,27,60,45,10],['Kolkata',22.573,88.364,265,7,30,78,55,11],['Pune',18.52,73.857,257,8,28,52,30,13],['Jaipur',26.912,75.787,272,9,34,35,15,10],['Visakhapatnam',17.687,83.219,254,8,31,70,45,16]]
 .map(a=>({name:a[0],lat:a[1],lon:a[2],ozone:a[3],uv:a[4],temp:a[5],humidity:a[6],cloud:a[7],wind:a[8]}));
const rnd=s=>{const x=Math.sin(s*12.9898)*43758.5453;return x-Math.floor(x)};
const wait=ms=>new Promise(r=>setTimeout(r,ms));
async function request(path,opts){const r=await fetch(API_CONFIG.BASE_URL+path,{headers:{'Content-Type':'application/json'},...opts});if(!r.ok)throw new Error('Request failed ('+r.status+')');return r.json()}
const find=n=>MOCK_LOCS.find(l=>l.name===n)||MOCK_LOCS[0];
const API={
 async getLocations(){if(!API_CONFIG.USE_MOCK)return request('/api/locations');await wait(200);return MOCK_LOCS},
 async getCurrent(n){if(!API_CONFIG.USE_MOCK)return request('/api/environment/current?location='+encodeURIComponent(n));await wait(300);return{...find(n),source:'mock',updated:new Date().toISOString()}},
 async getHistory(n,days=30,end=new Date()){if(!API_CONFIG.USE_MOCK)return request(`/api/environment/history?location=${encodeURIComponent(n)}&days=${days}`);await wait(300);const l=find(n),s=l.lat*7;
  return Array.from({length:days},(_,i)=>{const d=new Date(end);d.setDate(d.getDate()-(days-1-i));const o=l.ozone+Math.round((rnd(s+i)-.5)*30),u=Math.max(1,+(l.uv+(rnd(s+i+99)-.5)*5-(o-l.ozone)*.03).toFixed(1));
   return{date:d.toISOString().slice(0,10),ozone:o,uv:u,temp:+(l.temp+(rnd(s+i+5)-.5)*8).toFixed(1),humidity:Math.round(l.humidity+(rnd(s+i+7)-.5)*30),cloud:Math.round(Math.min(100,Math.max(0,l.cloud+(rnd(s+i+3)-.5)*60)))}})},
 async getPredictions(n,hours=24){if(!API_CONFIG.USE_MOCK)return request(`/api/predictions?location=${encodeURIComponent(n)}&hours=${hours}`);await wait(400);const l=find(n),s=l.lat;
  return Array.from({length:hours},(_,i)=>{const h=i%24,uv=+(l.uv*Math.max(0,Math.sin(Math.PI*(h-6)/12))*(1.05-l.cloud/250)*(.9+.2*rnd(s+i))).toFixed(1),u=.1+i*.004;
   return{hour:h,label:(hours>24?'D'+(Math.floor(i/24)+1)+' ':'')+String(h).padStart(2,'0')+':00',uv,lo:+Math.max(0,uv*(1-u)).toFixed(1),hi:+(uv*(1+u)).toFixed(1)}})},
 getAnalytics(n,days,end){return API_CONFIG.USE_MOCK?this.getHistory(n,days,end):request(`/api/analytics?location=${encodeURIComponent(n)}&days=${days}`)},
 register(p){return request('/api/auth/register',{method:'POST',body:JSON.stringify(p)})},
 login(p){return request('/api/auth/login',{method:'POST',body:JSON.stringify(p)})}
};
