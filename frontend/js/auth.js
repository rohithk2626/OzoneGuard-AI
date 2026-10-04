/* Client-side validation only. Real authentication must be done by the FastAPI backend. */
const form=document.querySelector('form[data-mode]');
if(form){form.addEventListener('submit',async e=>{
 e.preventDefault();const m=form.dataset.mode,v=Object.fromEntries(new FormData(form)),er={};
 if(m==='register'&&!(v.name||'').trim())er.name='Enter your full name.';
 if(!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(v.email||''))er.email='Enter a valid email address.';
 if((v.password||'').length<8)er.password='Password must be at least 8 characters.';
 if(m==='register'&&v.password!==v.confirm)er.confirm='Passwords do not match.';
 form.querySelectorAll('.e').forEach(x=>x.textContent=er[x.dataset.f]||'');
 const msg=form.querySelector('.msg');if(Object.keys(er).length)return;
 if(API_CONFIG.USE_MOCK){msg.style.color='#6b5200';msg.textContent='Form is valid. Backend not connected yet – no account was created or session started.';return}
 try{await API[m==='login'?'login':'register']({email:v.email,password:v.password,name:v.name});msg.style.color='#2ea043';msg.textContent='Success.'}
 catch(x){msg.style.color='#b42318';msg.textContent=x.message}
})}
