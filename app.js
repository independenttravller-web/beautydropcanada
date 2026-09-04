const toggle=document.querySelector('.mobile-toggle');
const nav=document.querySelector('.nav');
if(toggle&&nav){toggle.addEventListener('click',()=>nav.classList.toggle('open'));}

function money(v){return '$'+Number(v||0).toFixed(2)}
function estimate(k,service,cfg){
  k=Math.max(0,Number(k||0));
  const base=Number(cfg.base||0), included=Number(cfg.included||0), perkm=Number(cfg.perkm||0), minimum=Number(cfg.minimum||0), taxRate=Number(cfg.tax||0), rush=Number(cfg.rush||0);
  let fee=base+Math.max(0,k-included)*perkm;
  fee=Math.max(minimum,fee);
  if(service==='express')fee+=rush;
  const tax=fee*taxRate;
  const low=Math.max(20,Math.floor(20+k*1.6));
  const high=Math.max(low+10,Math.floor(35+k*2));
  return {fee,tax,total:fee+tax,low,high};
}

const calc=document.querySelector('[data-calculator]');
if(calc){
  const range=calc.querySelector('[data-home-km]');
  const dist=calc.querySelector('[data-home-km-value]');
  const total=calc.querySelector('[data-home-total]');
  const fee=calc.querySelector('[data-home-fee]');
  const tax=calc.querySelector('[data-home-tax]');
  const eta=calc.querySelector('[data-home-eta]');
  const radios=calc.querySelectorAll('[data-home-service]');
  const cfg={base:calc.dataset.base,included:calc.dataset.included,perkm:calc.dataset.perkm,minimum:calc.dataset.minimum,tax:calc.dataset.tax,rush:calc.dataset.rush};
  function update(){const svc=[...radios].find(r=>r.checked)?.value||'standard';const e=estimate(range.value,svc,cfg);dist.textContent=Number(range.value).toFixed(1)+' km';fee.textContent=money(e.fee);tax.textContent=money(e.tax);total.textContent=money(e.total);eta.textContent=e.low+'–'+e.high+' min';}
  range.addEventListener('input',update);radios.forEach(r=>r.addEventListener('change',update));update();
}

const form=document.querySelector('[data-delivery-form]');
if(form){
  const km=form.querySelector('[data-form-km]'), svc=form.querySelector('[data-form-service]');
  const fee=form.querySelector('[data-form-fee]'), tax=form.querySelector('[data-form-tax]'), total=form.querySelector('[data-form-total]'), eta=form.querySelector('[data-form-eta]');
  const cfg={base:form.dataset.base,included:form.dataset.included,perkm:form.dataset.perkm,minimum:form.dataset.minimum,tax:form.dataset.tax,rush:form.dataset.rush};
  function update(){const e=estimate(km.value,svc.value,cfg);fee.textContent=money(e.fee);tax.textContent=money(e.tax);total.textContent=money(e.total);eta.textContent=e.low+'–'+e.high+' min';}
  km.addEventListener('input',update);svc.addEventListener('change',update);update();
  const timing=form.querySelectorAll('[data-timing]'), fields=form.querySelector('[data-schedule-fields]');
  function timingUpdate(){const scheduled=[...timing].find(r=>r.checked)?.value==='scheduled';fields.hidden=!scheduled;fields.querySelectorAll('input').forEach(i=>i.required=scheduled);}
  timing.forEach(r=>r.addEventListener('change',timingUpdate));timingUpdate();
}
