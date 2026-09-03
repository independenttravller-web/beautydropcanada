const toggle=document.querySelector('.mobile-toggle');
const nav=document.querySelector('.nav');
if(toggle&&nav){toggle.addEventListener('click',()=>nav.classList.toggle('open'));}
const km=document.querySelector('[data-km]');
const svc=document.querySelector('[data-service]');
const fee=document.querySelector('[data-fee]');
function calcFee(){if(!km||!fee)return;let k=parseFloat(km.value||0),f=0;if(k<=5)f=9.99;else if(k<=10)f=12.99;else if(k<=15)f=16.99;else if(k<=20)f=21.99;else if(k<=30)f=27.99;else f=27.99+(k-30)*1.25;if(svc&&svc.value==='express')f+=7;fee.textContent='$'+f.toFixed(2);}
if(km){km.addEventListener('input',calcFee);if(svc)svc.addEventListener('change',calcFee);calcFee();}
