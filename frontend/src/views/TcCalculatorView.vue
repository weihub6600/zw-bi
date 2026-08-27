<script setup>
import { onMounted, onBeforeUnmount } from 'vue'
import { useAuthStore } from '../stores/auth'

const $=id=>document.getElementById(id)
const auth=useAuthStore()
const DATA_URL='/tc-data.json'
let csrf='', origins=[], destinations=[], originMap={}, routeTables={}, lastResult=null, quickTransportMin=false, destinationRequest=0
const DEFAULTS={originProvince:'河北',originCity:'廊坊',destinationProvince:'安徽',destinationCity:'合肥'}
const apiUrl=file=>String(file||'')
const normalizeRegion=s=>String(s||'').trim().replace(/\s+/g,'').replace(/(壮族自治区|回族自治区|维吾尔自治区|特别行政区|自治区|自治州|地区|省|市|盟|州)$/,'')
const uniqueSorted=a=>[...new Set(a)].sort((x,y)=>String(x).localeCompare(String(y),'zh-CN'))
const num=n=>Number(n).toLocaleString('zh-CN',{maximumFractionDigits:6})
const money=n=>Number(n).toLocaleString('zh-CN',{minimumFractionDigits:2,maximumFractionDigits:2})
const percent=n=>Number(n*100).toLocaleString('zh-CN',{minimumFractionDigits:2,maximumFractionDigits:4})+'%'

function escapeHtml(v){return String(v).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
function displayProvince(p){const map={北京:'北京市',上海:'上海市',天津:'天津市',重庆:'重庆市',内蒙古:'内蒙古自治区',广西:'广西壮族自治区',西藏:'西藏自治区',宁夏:'宁夏回族自治区',新疆:'新疆维吾尔自治区',香港:'香港特别行政区',澳门:'澳门特别行政区'};return map[p]||(/(?:省|市|自治区|特别行政区)$/.test(p)?p:`${p}省`);}
function displayCity(c){return /(?:市|地区|盟|州|自治州)$/.test(c)?c:`${c}市`;}
function pairText(pair){return `${displayCity(pair.city)}`;}
function canonicalProvince(value,pairs){const n=normalizeRegion(String(value||'').split('｜').pop());if(!n)return'';return uniqueSorted(pairs.map(x=>x.province)).find(x=>normalizeRegion(x)===n)||'';}
function canonicalCity(value,pairs,province=''){
  const raw=String(value||'').trim();if(!raw)return null;
  const parts=raw.split(/[｜|]/);const cityN=normalizeRegion(parts[0]);const typedProvince=parts[1]?normalizeRegion(parts[1]):'';const selectedProvince=normalizeRegion(province);
  let matches=pairs.filter(x=>normalizeRegion(x.city)===cityN);
  if(typedProvince){const exact=matches.find(x=>normalizeRegion(x.province)===typedProvince);if(exact)return exact;}
  if(selectedProvince){const exact=matches.find(x=>normalizeRegion(x.province)===selectedProvince);if(exact)return exact;}
  return matches.length===1?matches[0]:null;
}
function showError(msg){$('errorBox').textContent=msg;$('errorBox').style.display='block';}
function clearError(){$('errorBox').style.display='none';for(const id of['op','oc','dp','dc']){$(id).removeAttribute('aria-invalid');$(id).classList.remove('combo-unresolved');}}
async function fetchBootstrap(){
  if(!origins.length){
    const res=await fetch(DATA_URL,{cache:'no-store'});
    const data=await res.json();
    if(!data||!Array.isArray(data.origins)||!data.originMap||!data.routes) throw new Error('运价数据格式无效。');
    origins=data.origins.map(x=>({province:x[0],city:x[1]}));
    originMap=data.originMap;
    routeTables=data.routes;
    Object.assign(DEFAULTS,data.defaults||{});
  }
  csrf='local';
  return {csrf,origins,defaults:DEFAULTS};
}
function api(path,options={}){
  const name=String(path);
  let payload={};
  try{payload=options.body?JSON.parse(options.body):{};}catch{throw new Error('请求参数格式无效。');}
  if(name.endsWith('destinations.php')) return Promise.resolve(localDestinations(payload));
  if(name.endsWith('quote.php')) return Promise.resolve(localQuote(payload));
  return Promise.reject(new Error('未知计算器接口。'));
}
function localDestinations(payload){
  const key=`${payload.originProvince||''}|${payload.originCity||''}`;
  const oid=originMap[key];
  const routes=oid?routeTables[oid]:null;
  if(!routes) throw new Error('未找到该始发地线路。');
  const list=Object.keys(routes).map(key=>{const parts=key.split('|');return {province:parts[0],city:parts[1]};});
  list.sort((a,b)=>(a.province+a.city).localeCompare(b.province+b.city,'zh-CN'));
  return {success:true,destinations:list};
}
function localQuote(data){
  const op=String(data.originProvince||'').trim(), oc=String(data.originCity||'').trim();
  const dp=String(data.destinationProvince||'').trim(), dc=String(data.destinationCity||'').trim();
  const mode=String(data.mode||'estimate'); if(!['estimate','review'].includes(mode)) throw new Error('计算模式无效。');
  const season=String(data.season||'off'); if(!['off','peak'].includes(season)) throw new Error('淡旺季参数无效。');
  const number=(value,name,min,max)=>{const n=Number(value);if(!Number.isFinite(n)||n<min||n>max) throw new Error(`${name}超出允许范围。`);return n;};
  const detailKg=number(data.weight,'重量',0.001,10000000), detailVol=number(data.volume,'体积',0.000001,100000);
  const review=mode==='review';
  const ticketKg=review?number(data.ticketWeight,'整票总重量',0.001,10000000):detailKg;
  const ticketVol=review?number(data.ticketVolume,'整票总体积',0.000001,100000):detailVol;
  if(review&&detailKg>ticketKg+1e-9) throw new Error('当前明细重量不能大于整票总重量。');
  if(review&&detailVol>ticketVol+1e-9) throw new Error('当前明细体积不能大于整票总体积。');
  const pickup=Boolean(data.pickup);
  const applyTransportMinimum=review?true:Boolean(data.applyTransportMinimum);
  const transportSettle=number(data.transportSettle??40,'运输结算比例',0,1000)/100;
  const pickupSettle=number(data.pickupSettle??80,'提货结算比例',0,1000)/100;
  const oid=originMap[`${op}|${oc}`], routes=oid?routeTables[oid]:null, row=routes?.[`${dp}|${dc}`];
  if(!Array.isArray(row)||row.length<13) throw new Error('价格本未收录该线路。');
  const minFee=Number(row[0]);
  const offV=row.slice(1,6).map(Number), offWCents=row.slice(6,11).map(Number);
  const pickupVOff=Number(row[11]), pickupWCentsOff=Number(row[12]);
  const peakInt=n=>Math.floor(n*1.1+0.500000001), peakCent=c=>Math.floor(c*1.1+0.500000001)/100;
  const volumeRates=season==='peak'?offV.map(peakInt):offV;
  const weightRates=season==='peak'?offWCents.map(peakCent):offWCents.map(x=>x/100);
  const pickupVolumeRate=season==='peak'?peakInt(pickupVOff):pickupVOff;
  const pickupWeightRate=season==='peak'?peakCent(pickupWCentsOff):pickupWCentsOff/100;
  const ratio=ticketVol/(ticketKg/1000), light=ratio>=3;
  const volumeTier=v=>v<=5?0:v<=10?1:v<=20?2:v<=50?3:4;
  const weightTier=kg=>{const t=kg/1000;return t<=1?0:t<=2?1:t<=5?2:t<=10?3:4;};
  const tier=light?volumeTier(ticketVol):weightTier(ticketKg);
  const rate=light?volumeRates[tier]:weightRates[tier], ticketQty=light?ticketVol:ticketKg, detailQty=light?detailVol:detailKg;
  const share=review?detailQty/ticketQty:1; if(!(share>0&&share<=1+1e-9)) throw new Error('明细分摊比例无效。');
  const rawTicketFreight=ticketQty*rate, ticketFreightOriginal=applyTransportMinimum?Math.max(rawTicketFreight,minFee):rawTicketFreight;
  const transportMinimumApplied=applyTransportMinimum&&ticketFreightOriginal>rawTicketFreight+1e-9;
  const round2=n=>Math.round((n+Number.EPSILON)*100)/100;
  const freightOriginal=review?round2(ticketFreightOriginal*share):ticketFreightOriginal;
  const pickupRate=light?pickupVolumeRate:pickupWeightRate, rawTicketPickup=ticketQty*pickupRate;
  const ticketPickupOriginal=pickup?Math.max(rawTicketPickup,40):0, pickupMinimumApplied=pickup&&ticketPickupOriginal>rawTicketPickup+1e-9;
  const pickupOriginal=review?round2(ticketPickupOriginal*share):(pickup?ticketPickupOriginal:0);
  const originalTotal=freightOriginal+pickupOriginal, settledFreight=freightOriginal*transportSettle, settledPickup=pickupOriginal*pickupSettle, settledTotal=settledFreight+settledPickup;
  const tierNames=light?['0–5方','5–10方','10–20方','20–50方','50方以上']:['0–1吨','1–2吨','2–5吨','5–10吨','10吨以上'];
  return {success:true,route:{originProvince:op,originCity:oc,destinationProvince:dp,destinationCity:dc},context:{mode,season,detailKg,detailVol,ticketKg,ticketVol,ratio,light,cargoType:light?'泡货（轻货）':'重货',tier,tierName:tierNames[tier],share,pickup,applyTransportMinimum},pricing:{minimumFee:minFee,rate,pickupRate,rawTicketFreight,ticketFreightOriginal,transportMinimumApplied,freightOriginal,rawTicketPickup,ticketPickupOriginal,pickupMinimumApplied,pickupOriginal,originalTotal,transportSettle,pickupSettle,settledFreight,settledPickup,settledTotal},selectedRate:{type:light?'volume':'weight',tier,value:rate}};
}
const comboState={op:{active:-1},oc:{active:-1},dp:{active:-1},dc:{active:-1}};
let loadedOriginKey='';
function pairsFor(id){return id==='op'||id==='oc'?origins:destinations;}
function provinceOptions(id,query){const pairs=pairsFor(id),q=normalizeRegion(query);return uniqueSorted(pairs.map(x=>x.province)).filter(p=>!q||normalizeRegion(p).includes(q)).map(p=>({type:'province',province:p,text:displayProvince(p),secondary:''})).slice(0,120);}
function cityOptions(id,query){
  const pairs=pairsFor(id),provinceId=id==='oc'?'op':'dp',selected=canonicalProvince($(provinceId).value,pairs),q=normalizeRegion(String(query||'').split(/[｜|]/)[0]);
  let pool=pairs;
  if(!q&&selected)pool=pairs.filter(x=>x.province===selected);
  let out=pool.filter(x=>{if(!q)return true;return normalizeRegion(x.city).includes(q)||normalizeRegion(x.province).includes(q)||normalizeRegion(`${x.city}${x.province}`).includes(q);});
  if(q&&selected&&!out.some(x=>x.province===selected)){out=pairs.filter(x=>normalizeRegion(x.city).includes(q)||normalizeRegion(x.province).includes(q)||normalizeRegion(`${x.city}${x.province}`).includes(q));}
  return out.slice(0,160).map(x=>({type:'city',province:x.province,city:x.city,text:displayCity(x.city),secondary:displayProvince(x.province)}));
}
function optionsFor(id,showAll=false){const query=showAll?'':$(id).value;return id==='op'||id==='dp'?provinceOptions(id,query):cityOptions(id,query);}
function closeCombo(id){const root=document.querySelector(`.combo[data-combo="${id}"]`);if(root)root.classList.remove('open');$(id).setAttribute('aria-expanded','false');comboState[id].active=-1;}
function closeAllCombos(except=''){for(const id of Object.keys(comboState))if(id!==except)closeCombo(id);}
function renderCombo(id,forceOpen=true,showAll=false){
  const root=document.querySelector(`.combo[data-combo="${id}"]`),menu=$(`${id}Menu`),items=optionsFor(id,showAll);comboState[id].items=items;comboState[id].active=-1;
  if(!items.length){menu.innerHTML=`<div class="combo-empty">${(id==='dp'||id==='dc')&&!destinations.length?'请先选择始发城市':'没有匹配结果'}</div>`;}
  else menu.innerHTML=items.map((item,i)=>`<button type="button" class="combo-option" data-index="${i}" role="option"><span>${escapeHtml(item.text)}</span>${item.secondary?`<span class="secondary">${escapeHtml(item.secondary)}</span>`:''}</button>`).join('');
  if(forceOpen){closeAllCombos(id);root.classList.add('open');$(id).setAttribute('aria-expanded','true');}
}
async function chooseOption(id,index){const item=(comboState[id].items||[])[index];if(!item)return;
  if(item.type==='province'){
    $(id).value=displayProvince(item.province);$(id).dataset.value=item.province;$(id).classList.add('combo-resolved');
    if(id==='op'){$('oc').value='';$('oc').dataset.value='';loadedOriginKey='';destinations=[];$('dp').value='';$('dc').value='';}
    else $('dc').value='';
  }else{
    const pid=id==='oc'?'op':'dp';$(pid).value=displayProvince(item.province);$(pid).dataset.value=item.province;$(id).value=pairText(item);$(id).dataset.province=item.province;$(id).dataset.city=item.city;$(id).classList.add('combo-resolved');$(pid).classList.add('combo-resolved');
    if(id==='oc'){$('dp').value='';$('dc').value='';await loadDestinations(true,false);}
  }
  closeCombo(id);
}
function markUnresolved(id){$(id).classList.remove('combo-resolved');$(id).classList.add('combo-unresolved');$(id).setAttribute('aria-invalid','true');}
function resolveProvinceInput(side,quiet=false){const pairs=side==='origin'?origins:destinations,id=side==='origin'?'op':'dp',p=canonicalProvince($(id).value,pairs);if(p){$(id).value=displayProvince(p);$(id).dataset.value=p;$(id).classList.add('combo-resolved');$(id).classList.remove('combo-unresolved');return p;}if(!quiet&&$(id).value.trim())markUnresolved(id);return'';}
function resolveCityInput(side,quiet=false){const pairs=side==='origin'?origins:destinations,pid=side==='origin'?'op':'dp',cid=side==='origin'?'oc':'dc';const p=canonicalProvince($(pid).value,pairs),found=canonicalCity($(cid).value,pairs,p);if(found){$(pid).value=displayProvince(found.province);$(pid).dataset.value=found.province;$(cid).value=pairText(found);$(cid).dataset.province=found.province;$(cid).dataset.city=found.city;$(pid).classList.add('combo-resolved');$(cid).classList.add('combo-resolved');$(pid).classList.remove('combo-unresolved');$(cid).classList.remove('combo-unresolved');return found;}if(!quiet&&$(cid).value.trim())markUnresolved(cid);return null;}
async function loadDestinations(useDefault=false,showLoading=true){
  const seq=++destinationRequest,origin=resolveCityInput('origin',true);if(!origin)return;
  const key=`${origin.province}|${origin.city}`;if(key===loadedOriginKey&&destinations.length){if(useDefault)selectDefaultDestination();return;}
  loadedOriginKey='';destinations=[];$('dp').value='';$('dc').value='';if(showLoading){$ ('dpMenu').innerHTML='<div class="combo-loading">正在加载可达省市…</div>';$ ('dcMenu').innerHTML='<div class="combo-loading">正在加载可达城市…</div>';}
  try{const data=await api(apiUrl('destinations.php'),{method:'POST',body:JSON.stringify({csrf,originProvince:origin.province,originCity:origin.city})});if(seq!==destinationRequest)return;destinations=data.destinations||[];loadedOriginKey=key;if(useDefault)selectDefaultDestination();}
  catch(e){showError(e.message);}
}
function selectDefaultDestination(){const d=destinations.find(x=>normalizeRegion(x.province)===normalizeRegion(DEFAULTS.destinationProvince)&&normalizeRegion(x.city)===normalizeRegion(DEFAULTS.destinationCity));if(d){$('dp').value=displayProvince(d.province);$('dp').dataset.value=d.province;$('dc').value=pairText(d);$('dc').dataset.province=d.province;$('dc').dataset.city=d.city;$('dp').classList.add('combo-resolved');$('dc').classList.add('combo-resolved');}}
function moveCombo(id,delta){const items=comboState[id].items||[];if(!items.length)return;let next=comboState[id].active+delta;if(next<0)next=items.length-1;if(next>=items.length)next=0;comboState[id].active=next;const buttons=[...$(`${id}Menu`).querySelectorAll('.combo-option')];buttons.forEach((b,i)=>b.classList.toggle('active',i===next));buttons[next]?.scrollIntoView({block:'nearest'});}
function bindCombo(id){const input=$(id),root=document.querySelector(`.combo[data-combo="${id}"]`),toggle=root.querySelector('.combo-toggle'),menu=$(`${id}Menu`);
  input.addEventListener('focus',()=>renderCombo(id,true,input.classList.contains('combo-resolved')));
  input.addEventListener('click',()=>renderCombo(id,true,input.classList.contains('combo-resolved')));
  input.addEventListener('input',()=>{input.dataset.value='';input.dataset.city='';input.classList.remove('combo-resolved','combo-unresolved');if(id==='op'||id==='oc'){loadedOriginKey='';destinations=[];$('dp').value='';$('dc').value='';}renderCombo(id,true);});
  toggle.addEventListener('click',()=>{if(root.classList.contains('open'))closeCombo(id);else{input.focus();renderCombo(id,true,true);}});
  menu.addEventListener('mousedown',e=>e.preventDefault());
  menu.addEventListener('click',e=>{const btn=e.target.closest('.combo-option');if(btn)chooseOption(id,Number(btn.dataset.index));});
  input.addEventListener('keydown',async e=>{if(e.key==='ArrowDown'){e.preventDefault();if(!root.classList.contains('open'))renderCombo(id,true);moveCombo(id,1);}else if(e.key==='ArrowUp'){e.preventDefault();moveCombo(id,-1);}else if(e.key==='Enter'){e.preventDefault();if(root.classList.contains('open')&&comboState[id].active>=0)await chooseOption(id,comboState[id].active);else if(id==='op'||id==='dp'){resolveProvinceInput(id==='op'?'origin':'destination');closeCombo(id);}else{const found=resolveCityInput(id==='oc'?'origin':'destination');closeCombo(id);if(found&&id==='oc')await loadDestinations(false,false);}}else if(e.key==='Escape')closeCombo(id);});
  input.addEventListener('blur',()=>setTimeout(async()=>{if(document.activeElement&&root.contains(document.activeElement))return;if(id==='op'||id==='dp')resolveProvinceInput(id==='op'?'origin':'destination',true);else{const found=resolveCityInput(id==='oc'?'origin':'destination',true);if(found&&id==='oc')await loadDestinations(false,false);}closeCombo(id);},120));
}
function getMode(){return document.querySelector('input[name="calcMode"]:checked')?.value||'estimate';}
function updateMode(){const review=getMode()==='review',minInput=$('transportMin');$('.app').classList.toggle('review-mode',review);$('cargoHint').textContent=review?'输入当前明细及其所属整票汇总数据':'按票输入总重量和总体积';$('weightLabel').textContent=review?'当前明细重量（kg）':'实际重量（kg）';$('volumeLabel').textContent=review?'当前明细体积（m³）':'总体积（m³）';$('modeNote').textContent=review?'适用于复核合单账单：先按整票判断重泡、阶梯和最低收费，再分摊至当前明细。':'适用于单票报价或成本快速测算。';$('originalLabel').textContent=review?'当前明细原始费用':'承运商原始费用';$('settledLabel').textContent=review?'账单结算成本（当前明细）':'账单结算成本';$('cargoTypeLabel').textContent=review?'整票重泡判定':'重泡判定';if(review){if(!minInput.disabled)quickTransportMin=minInput.checked;minInput.checked=true;minInput.disabled=true;$('transportMinRow').classList.add('is-disabled');$('transportMinText').textContent='是，按整票最低收费（复核固定）';$('calcNotice').innerHTML='<strong>计算口径：</strong>账单复核模式按整票总重量、总体积判断重泡货及阶梯价；运输原始费按整票执行线路最低收费，提货原始费按整票最低 40 元，随后按当前明细计费依据占比分摊。';}else{minInput.disabled=false;minInput.checked=quickTransportMin;$('transportMinRow').classList.remove('is-disabled');$('transportMinText').textContent=minInput.checked?'是，按线路最低收费':'否，不按最低收费';$('calcNotice').innerHTML='<strong>计算口径：</strong>账单结算成本默认按 6 月账单中的运输 40%、提货 80%计算。运输费用默认无最低收费，提货原始费用最低40元';}}
function validateRoute(){const origin=resolveCityInput('origin');if(!origin){markUnresolved('oc');return null;}const dest=resolveCityInput('destination');if(!dest){markUnresolved('dc');return null;}return{origin,dest};}
function renderCargoSummary(c){const review=c.mode==='review',items=review?[['计算模式','账单复核'],['计费季节',c.season==='peak'?'旺季（1、2、5、6、10、11、12月）':'淡季（3、4、7、8、9月）'],['当前明细重量',`${num(c.detailKg)} kg`],['当前明细体积',`${num(c.detailVol)} m³`],['整票总重量',`${num(c.ticketKg)} kg`],['整票总体积',`${num(c.ticketVol)} m³`],['整票重泡比',num(c.ratio)],['整票货物类型',c.cargoType],['明细分摊比例',percent(c.share)],['提货方式',c.pickup?'上门提货':'自送到仓'],['运输最低收费','按整票执行']]:[['计算模式','快速估算'],['计费季节',c.season==='peak'?'旺季（1、2、5、6、10、11、12月）':'淡季（3、4、7、8、9月）'],['实际重量',`${num(c.detailKg)} kg`],['总体积',`${num(c.detailVol)} m³`],['重泡比',num(c.ratio)],['货物类型',c.cargoType],['提货方式',c.pickup?'上门提货':'自送到仓'],['运输最低收费',c.applyTransportMinimum?'启用':'不启用']];$('cargoSummary').innerHTML=items.map(([k,v])=>`<div class="cargo-item"><div class="k">${escapeHtml(k)}</div><div class="v">${escapeHtml(v)}</div></div>`).join('');}
function renderResult(d){lastResult=d;const c=d.context,p=d.pricing,r=d.route,review=c.mode==='review';$('emptyState').style.display='none';$('resultWrap').style.display='block';$('routeTitle').textContent=`${r.originProvince} ${r.originCity} → ${r.destinationProvince} ${r.destinationCity}`;$('routeSub').innerHTML=`${c.season==='peak'?'旺季':'淡季'} · ${review?'账单复核，整票计价后分摊':'快速估算'} · ${escapeHtml(c.tierName)} · 线路最低收费 ${money(p.minimumFee)} 元 <span class="tag ${review?'mode-badge':''}">${review?'整票计价后分摊':(c.applyTransportMinimum?'运输最低收费开启':'运输最低收费关闭')}</span>`;renderCargoSummary(c);$('originalTotal').innerHTML=`${money(p.originalTotal)}<span class="unit">元</span>`;$('settledTotal').innerHTML=`${money(p.settledTotal)}<span class="unit">元</span>`;$('cargoType').textContent=c.cargoType;const rows=[['采用运输单价',`${money(p.rate)} 元/${c.light?'m³':'kg'}`],['线路最低收费',`${money(p.minimumFee)} 元`],['运输原始费',`${money(p.freightOriginal)} 元${p.transportMinimumApplied?'（已触发最低收费）':''}`],['运输结算成本',`${money(p.settledFreight)} 元（${money(p.transportSettle*100)}%）`],['提货单价',`${money(p.pickupRate)} 元/${c.light?'m³':'kg'}`],['提货原始费',c.pickup?`${money(p.pickupOriginal)} 元${p.pickupMinimumApplied?'（已触发最低 40 元）':''}`:'0.00 元（自送）'],['提货结算成本',`${money(p.settledPickup)} 元（${money(p.pickupSettle*100)}%）`]];if(review){rows.unshift(['整票运输原始费',`${money(p.ticketFreightOriginal)} 元`],['整票提货原始费',`${money(p.ticketPickupOriginal)} 元`],['明细分摊比例',percent(c.share)]);}$('details').innerHTML=rows.map(([k,v])=>`<div class="detail-row"><span>${escapeHtml(k)}</span><strong>${escapeHtml(v)}</strong></div>`).join('');const qty=c.light?(review?c.ticketVol:c.detailVol):(review?c.ticketKg:c.detailKg),unit=c.light?'m³':'kg';$('formula').innerHTML=review?`整票计费：${num(qty)} ${unit} × ${money(p.rate)} 元/${unit}${c.applyTransportMinimum?`，与最低收费 ${money(p.minimumFee)} 元取高值`:''}；当前明细按 ${percent(c.share)} 分摊。<br>账单成本：运输 ${money(p.freightOriginal)} × ${money(p.transportSettle*100)}% + 提货 ${money(p.pickupOriginal)} × ${money(p.pickupSettle*100)}% = <strong>${money(p.settledTotal)} 元</strong>`:`运输：${num(qty)} ${unit} × ${money(p.rate)} 元/${unit}${c.applyTransportMinimum?`，与最低收费 ${money(p.minimumFee)} 元取高值`:''}。<br>账单成本：运输 ${money(p.freightOriginal)} × ${money(p.transportSettle*100)}% + 提货 ${money(p.pickupOriginal)} × ${money(p.pickupSettle*100)}% = <strong>${money(p.settledTotal)} 元</strong>`;const tiers=c.light?['0–5 方','5–10 方','10–20 方','20–50 方','50 方以上']:['0–1 吨','1–2 吨','2–5 吨','5–10 吨','10 吨以上'];const cells=tiers.map((label,i)=>`<div class="rate-cell ${i===c.tier?'active':''}"><span class="rate-cell-label">${label}</span><strong>${i===c.tier?`${money(p.rate)} 元/${unit}`:'—'}</strong></div>`).join('');$('rateBody').innerHTML=`<div class="rate-type">${c.light?'泡货体积价':'重货重量价'}</div><div class="rate-cells">${cells}</div>`;}
async function calculate(){clearError();const origin=resolveCityInput('origin');if(!origin)return showError('请输入或选择有效的始发城市。');const originKey=`${origin.province}|${origin.city}`;if(originKey!==loadedOriginKey||!destinations.length)await loadDestinations(false,false);const route=validateRoute();if(!route)return showError('请输入或选择该始发地可达的目的城市。');const payload={csrf,originProvince:route.origin.province,originCity:route.origin.city,destinationProvince:route.dest.province,destinationCity:route.dest.city,mode:getMode(),season:$('season').value,weight:$('weight').value,volume:$('volume').value,ticketWeight:$('ticketWeight').value,ticketVolume:$('ticketVolume').value,pickup:$('pickup').checked,applyTransportMinimum:$('transportMin').checked,transportSettle:$('transportSettle').value,pickupSettle:$('pickupSettle').value};$('calcBtn').disabled=true;$('calcBtn').textContent='计算中…';try{const d=await api(apiUrl('quote.php'),{method:'POST',body:JSON.stringify(payload)});renderResult(d);}catch(e){showError(e.message);}finally{$('calcBtn').disabled=false;$('calcBtn').textContent='计算运费';}}
function reset(){clearError();closeAllCombos();lastResult=null;$('modeEstimate').checked=true;quickTransportMin=false;$('season').value='off';$('weight').value='';$('volume').value='';$('ticketWeight').value='';$('ticketVolume').value='';$('pickup').checked=false;$('transportMin').checked=false;$('transportSettle').value='40';$('pickupSettle').value='80';$('pickupText').textContent='否，自送到仓';$('op').value=displayProvince(DEFAULTS.originProvince);$('oc').value=displayCity(DEFAULTS.originCity);$('op').classList.add('combo-resolved');$('oc').classList.add('combo-resolved');$('dp').value='';$('dc').value='';loadedOriginKey='';destinations=[];$('resultWrap').style.display='none';$('emptyState').style.display='flex';$('seasonBadge').textContent='淡季价格';updateMode();loadDestinations(true,false);}
async function copyResult(){if(!lastResult)return showError('请先完成一次计算。');const d=lastResult,c=d.context,p=d.pricing,r=d.route;const text=[`线路：${r.originProvince}${r.originCity} → ${r.destinationProvince}${r.destinationCity}`,`模式：${c.mode==='review'?'账单复核':'快速估算'}`,`季节：${c.season==='peak'?'旺季':'淡季'}`,`货物类型：${c.cargoType}`,`采用阶梯：${c.tierName}`,`原始费用：${money(p.originalTotal)} 元`,`账单结算成本：${money(p.settledTotal)} 元`].join('\n');try{await navigator.clipboard.writeText(text);$('copyBtn').textContent='已复制';setTimeout(()=>$('copyBtn').textContent='复制结果',1200);}catch{showError('浏览器未允许复制，请手动选择结果。');}}
function onDocumentMouseDown(e){if(!e.target.closest('.combo'))closeAllCombos();}
function bind(){for(const id of['op','oc','dp','dc'])bindCombo(id);document.addEventListener('mousedown',onDocumentMouseDown);for(const id of['modeEstimate','modeReview'])$(id).addEventListener('change',updateMode);$('season').addEventListener('change',()=>{$('seasonBadge').textContent=$('season').value==='peak'?'旺季价格':'淡季价格';});$('pickup').addEventListener('change',()=>{$('pickupText').textContent=$('pickup').checked?'是，上门提货':'否，自送到仓';});$('transportMin').addEventListener('change',()=>{if(!$('transportMin').disabled){quickTransportMin=$('transportMin').checked;$('transportMinText').textContent=quickTransportMin?'是，按线路最低收费':'否，不按最低收费';}});$('calcBtn').addEventListener('click',calculate);$('resetBtn').addEventListener('click',reset);$('copyBtn').addEventListener('click',copyResult);$('printBtn').addEventListener('click',()=>window.print());}
async function init(){bind();try{const data=await fetchBootstrap();origins=data.origins||[];Object.assign(DEFAULTS,data.defaults||{});$('op').value=displayProvince(DEFAULTS.originProvince);$('oc').value=displayCity(DEFAULTS.originCity);$('op').classList.add('combo-resolved');$('oc').classList.add('combo-resolved');await loadDestinations(true,false);$('loading').style.display='none';$('seasonBadge').classList.add('online');}catch(e){$('spinner').style.display='none';$('loadingTitle').textContent='计算器初始化失败';$('loadingHint').className='loading-error';$('loadingHint').textContent=`${e.message} 请确认前端已正确发布 tc-data.json。`;}}
onMounted(init);
onBeforeUnmount(()=>document.removeEventListener('mousedown',onDocumentMouseDown));
</script>

<template>
<div class="loading" id="loading"><div class="loader-card"><div class="spinner" id="spinner"></div><strong id="loadingTitle">正在建立安全连接</strong><div class="hint" id="loadingHint">价格库保存在服务器端，浏览器不下载完整数据</div></div></div>
<div class="app">
  <div class="hero">
    <div><h1>TC物流运费特快到仓计算器<span v-if="auth.departmentName && auth.departmentName !== '—'"> · {{ auth.departmentName }}</span></h1><p>支持淡旺季、重泡货、阶梯价、最低收费和上门提货，结果仅供参考</p></div>
    <div class="status" id="seasonBadge">淡季价格</div>
  </div>
  <div class="error" id="errorBox"></div>
  <div class="grid">
    <div class="card input-card">
      <h2>计算参数</h2>
      <div class="section">
        <div class="section-title"><h3>1. 线路选择</h3><span class="hint">可下拉选择或输入关键词搜索</span></div>
        <div class="form-grid four route-grid">
          <div class="field"><label for="op">始发省</label><div class="combo" data-combo="op"><input id="op" autocomplete="off" placeholder="输入或下拉选择省份" role="combobox" aria-autocomplete="list" aria-expanded="false" aria-controls="opMenu"><button class="combo-toggle" type="button" aria-label="展开始发省列表">▾</button><div class="combo-menu" id="opMenu" role="listbox"></div></div></div>
          <div class="field"><label for="oc">始发市</label><div class="combo" data-combo="oc"><input id="oc" autocomplete="off" placeholder="可直接输入城市搜索" role="combobox" aria-autocomplete="list" aria-expanded="false" aria-controls="ocMenu"><button class="combo-toggle" type="button" aria-label="展开始发市列表">▾</button><div class="combo-menu" id="ocMenu" role="listbox"></div></div></div>
          <div class="field"><label for="dp">目的省</label><div class="combo" data-combo="dp"><input id="dp" autocomplete="off" placeholder="输入或下拉选择省份" role="combobox" aria-autocomplete="list" aria-expanded="false" aria-controls="dpMenu"><button class="combo-toggle" type="button" aria-label="展开目的省列表">▾</button><div class="combo-menu" id="dpMenu" role="listbox"></div></div></div>
          <div class="field"><label for="dc">目的市</label><div class="combo" data-combo="dc"><input id="dc" autocomplete="off" placeholder="可直接输入城市搜索" role="combobox" aria-autocomplete="list" aria-expanded="false" aria-controls="dcMenu"><button class="combo-toggle" type="button" aria-label="展开目的市列表">▾</button><div class="combo-menu" id="dcMenu" role="listbox"></div></div></div>
        </div>
        <div class="search-note search-note-spaced">点击输入框或右侧按钮即可展开；支持直接搜索省份或城市。选择城市后会自动补全所属省份。</div>
      </div>
      <div class="section">
        <div class="section-title"><h3>2. 货物信息</h3><span class="hint" id="cargoHint">按票输入总重量和总体积</span></div>
        <div class="form-grid cargo-grid">
          <div class="field full">
            <label>计算模式</label>
            <div class="mode-switch" role="radiogroup" aria-label="计算模式">
              <label class="mode-option"><input id="modeEstimate" type="radio" name="calcMode" value="estimate" checked><span><strong>快速估算</strong><small>按当前输入货物直接判断重泡、阶梯和费用</small></span></label>
              <label class="mode-option"><input id="modeReview" type="radio" name="calcMode" value="review"><span><strong>账单复核</strong><small>按整票计价，再按计费依据分摊到当前明细</small></span></label>
            </div>
            <div class="mode-note" id="modeNote">适用于单票报价或成本快速测算。</div>
          </div>
          <div class="field"><label for="season">淡旺季</label><select id="season"><option value="off">淡季（3月、4月、7月、8月、9月）</option><option value="peak">旺季（1月、2月、5月、6月、10月、11月、12月）</option></select></div>
          <div class="field"><label for="weight" id="weightLabel">实际重量（kg）</label><input id="weight" type="number" min="0.001" step="0.001" placeholder="例如 125.4"></div>
          <div class="field"><label for="volume" id="volumeLabel">总体积（m³）</label><input id="volume" type="number" min="0.000001" step="0.000001" placeholder="例如 0.21"></div>
          <div class="field review-field"><label for="ticketWeight">整票总重量（kg）</label><input id="ticketWeight" type="number" min="0.001" step="0.001" placeholder="同一托运单汇总重量"></div>
          <div class="field review-field"><label for="ticketVolume">整票总体积（m³）</label><input id="ticketVolume" type="number" min="0.000001" step="0.000001" placeholder="同一托运单汇总体积"></div>
          <div class="field review-field"><label>复核分摊规则</label><div class="switch-row"><span class="hint">整票按重货则按重量占比分摊；整票按泡货则按体积占比分摊</span></div></div>
          <div class="toggle-pair">
            <div class="field"><label>上门提货</label><div class="switch-row"><label class="switch"><input id="pickup" type="checkbox"><span class="slider"></span></label><span id="pickupText">否，自送到仓</span></div></div>
            <div class="field" id="transportMinField"><label>原始运输费是否按最低收费</label><div class="switch-row" id="transportMinRow"><label class="switch"><input id="transportMin" type="checkbox"><span class="slider"></span></label><span id="transportMinText">否，不按最低收费</span></div></div>
          </div>
        </div>
      </div>
      <div class="section advanced">
        <details>
          <summary>高级参数（可按合同调整）</summary>
          <div class="small-grid">
            <div class="field"><label for="transportSettle">运输结算比例（%）</label><input id="transportSettle" type="number" value="40" min="0" max="1000" step="0.1"></div>
            <div class="field"><label for="pickupSettle">提货结算比例（%）</label><input id="pickupSettle" type="number" value="80" min="0" max="1000" step="0.1"></div>
          </div>
        </details>
      </div>
      <div class="buttons">
        <button class="btn primary" id="calcBtn">计算运费</button>
        <button class="btn secondary" id="resetBtn">重置</button>
        <button class="btn ghost" id="copyBtn">复制结果</button>
        <button class="btn ghost" id="printBtn">打印</button>
      </div>
      <div class="notice" id="calcNotice"><strong>计算口径：</strong>账单结算成本默认按 6 月账单中的运输 40%、提货 80%计算。运输费用默认无最低收费，提货原始费用最低40元</div>
      <div class="security-note">安全说明：完整价格库和计算规则保存在服务器端；页面仅获取当前线路及本次计算结果。</div>
    </div>
    <div class="card">
      <div class="result-empty" id="emptyState"><div><strong>等待计算</strong>选择线路并输入重量、体积后，点击“计算运费”。</div></div>
      <div class="result-wrap" id="resultWrap">
        <div class="route-line" id="routeTitle"></div><div class="subline" id="routeSub"></div>
        <div class="cargo-summary" id="cargoSummary"></div>
        <div class="metric-grid">
          <div class="metric"><div class="label" id="originalLabel">承运商原始费用</div><div class="value" id="originalTotal">0.00<span class="unit">元</span></div></div>
          <div class="metric primary"><div class="label" id="settledLabel">账单结算成本</div><div class="value" id="settledTotal">0.00<span class="unit">元</span></div></div>
          <div class="metric amber"><div class="label" id="cargoTypeLabel">重泡判定</div><div class="value cargo-type-value" id="cargoType">—</div></div>
        </div>
        <div class="detail" id="details"></div>
        <div class="formula" id="formula"></div>
        <div class="rate-table-wrap" aria-label="阶梯区间"><div class="rate-heading"><span>阶梯区间</span><small>自动命中当前货物对应价格</small></div><div id="rateBody" class="rate-body"></div></div>
      </div>
    </div>
  </div>
  <div class="footer"><a href="https://517zhe.com" target="_blank" rel="noopener noreferrer">Powered by ZhangWei</a></div>
</div>
</template>

<style scoped>
.app{--bg:#f4f7fb;--card:#fff;--ink:#172033;--muted:#6a7487;--line:#dce3ee;--blue:#2563eb;--blue2:#eff6ff;--green:#059669;--green2:#ecfdf5;--amber:#d97706;--amber2:#fffbeb;--red:#dc2626;--shadow:0 10px 30px rgba(34,53,84,.08);--radius:16px}
*{box-sizing:border-box}html{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Hiragino Sans GB","Microsoft YaHei",Arial,sans-serif;color:var(--ink);background:var(--bg)}body{margin:0;min-width:320px}.app{max-width:1260px;margin:0 auto;padding:24px}.hero{display:flex;justify-content:space-between;align-items:flex-end;gap:20px;margin-bottom:18px}.hero h1{font-size:28px;margin:0 0 6px;letter-spacing:.01em}.hero p{margin:0;color:var(--muted);font-size:14px;line-height:1.6}.status{padding:8px 12px;border-radius:999px;background:var(--blue2);color:var(--blue);font-weight:700;font-size:13px;white-space:nowrap}.grid{display:grid;grid-template-columns:minmax(0,1.12fr) minmax(360px,.88fr);gap:18px}.card{background:var(--card);border:1px solid var(--line);border-radius:var(--radius);box-shadow:var(--shadow);padding:20px}.card h2{font-size:18px;margin:0 0 16px}.section{padding-top:18px;margin-top:18px;border-top:1px solid var(--line)}.section:first-of-type{padding-top:0;margin-top:0;border-top:0}.section-title{display:flex;justify-content:space-between;align-items:center;margin-bottom:12px}.section-title h3{font-size:15px;margin:0}.hint{font-size:12px;color:var(--muted);font-weight:600}.form-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:13px}.form-grid.four{grid-template-columns:repeat(4,minmax(0,1fr))}.form-grid.cargo-grid{grid-template-columns:repeat(3,minmax(0,1fr))}.toggle-pair{grid-column:1/-1;display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:13px}.field{display:flex;flex-direction:column;gap:7px}.field.full{grid-column:1/-1}.field label{font-size:13px;font-weight:650;color:#39445a}.field input,.field select{width:100%;height:42px;border:1px solid #cfd8e6;border-radius:10px;padding:0 11px;background:#fff;color:var(--ink);font-size:14px;outline:none;transition:.15s}.field input:focus,.field select:focus{border-color:#7aa2f8;box-shadow:0 0 0 3px rgba(37,99,235,.10)}.field input[aria-invalid="true"]{border-color:#ef4444;box-shadow:0 0 0 3px rgba(239,68,68,.08)}.route-grid{gap:14px}.route-grid .field{padding:12px;border:1px solid #e2eaf5;border-radius:14px;background:linear-gradient(180deg,#fbfdff 0%,#f6f9fd 100%);box-shadow:inset 0 1px 0 rgba(255,255,255,.92);transition:.16s}.route-grid .field:focus-within{border-color:#b9cffb;box-shadow:0 0 0 4px rgba(37,99,235,.08),inset 0 1px 0 rgba(255,255,255,.92)}.route-grid .field label{font-size:12px;font-weight:800;color:#4e5b72;letter-spacing:.02em}.route-grid .field input{height:44px;border-radius:12px;font-weight:650;background:#fff}.route-grid .field input::placeholder{font-weight:500;color:#98a3b8}.route-grid .combo-menu{top:calc(100% + 10px)}.search-note-spaced{margin-top:12px}.search-note{font-size:11px;color:#8a94a6;line-height:1.4}.switch-row{display:flex;align-items:center;gap:10px;min-height:42px}.switch{position:relative;width:46px;height:26px;display:inline-block}.switch input{opacity:0;width:0;height:0}.slider{position:absolute;inset:0;background:#cbd5e1;border-radius:999px;cursor:pointer;transition:.2s}.slider:before{content:"";position:absolute;width:20px;height:20px;left:3px;top:3px;background:#fff;border-radius:50%;box-shadow:0 1px 4px rgba(0,0,0,.2);transition:.2s}.switch input:checked+.slider{background:var(--blue)}.switch input:checked+.slider:before{transform:translateX(20px)}.buttons{display:flex;gap:10px;margin-top:18px;flex-wrap:wrap}.btn{height:42px;border:0;border-radius:10px;padding:0 18px;font-weight:700;font-size:14px;cursor:pointer;transition:.15s}.btn:hover{transform:translateY(-1px)}.btn.primary{background:var(--blue);color:#fff}.btn.secondary{background:#eef2f7;color:#354157}.btn.ghost{background:#fff;border:1px solid var(--line);color:#354157}.result-empty{min-height:370px;display:flex;align-items:center;justify-content:center;text-align:center;color:var(--muted);padding:40px}.result-empty strong{display:block;color:#3d485c;margin-bottom:6px}.result-wrap{display:none}.route-line{font-weight:800;font-size:18px;margin-bottom:4px}.subline{font-size:13px;color:var(--muted);margin-bottom:14px}.cargo-summary{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;margin-bottom:12px}.cargo-item{border:1px solid var(--line);background:#fafcff;border-radius:10px;padding:9px 10px}.cargo-item .k{font-size:11px;color:var(--muted);margin-bottom:4px}.cargo-item .v{font-size:13px;font-weight:750;word-break:break-word}.metric-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}.metric{border:1px solid var(--line);border-radius:12px;padding:13px;background:#fafcff}.metric.primary{background:linear-gradient(135deg,#0b57d0 0%,#2563eb 58%,#1e40af 100%);border:2px solid #1e3a8a;color:#fff;box-shadow:0 12px 26px rgba(37,99,235,.30);transform:translateY(-2px)}.metric.amber{background:var(--amber2);border-color:#f5d89a}.metric .label{font-size:12px;color:var(--muted);margin-bottom:6px}.metric .value{font-size:24px;font-weight:800;letter-spacing:-.02em}.metric .unit{font-size:13px;font-weight:600;color:var(--muted);margin-left:2px}.metric.primary .label{color:rgba(255,255,255,.88);font-weight:750}.metric.primary .value{font-size:30px;color:#fff;text-shadow:0 1px 2px rgba(0,0,0,.16)}.metric.primary .unit{color:rgba(255,255,255,.92)}.detail{margin-top:14px;border:1px solid var(--line);border-radius:12px;overflow:hidden}.detail-row{display:grid;grid-template-columns:1fr auto;gap:14px;padding:10px 12px;border-top:1px solid var(--line);font-size:13px;align-items:start}.detail-row:first-child{border-top:0}.detail-row span:first-child{color:var(--muted)}.detail-row strong{text-align:right;max-width:340px}.formula{margin-top:14px;background:#f6f8fb;border-radius:12px;padding:12px 14px;font-size:12px;line-height:1.7;color:#4c576b}.rate-table-wrap{margin-top:18px;overflow:auto;border:1px solid var(--line);border-radius:12px}.rate-table{width:100%;border-collapse:collapse;font-size:12px;min-width:650px}.rate-table th,.rate-table td{padding:9px 10px;text-align:center;border-right:1px solid var(--line);border-bottom:1px solid var(--line)}.rate-table th:last-child,.rate-table td:last-child{border-right:0}.rate-table tr:last-child td{border-bottom:0}.rate-table th{background:#f5f7fb;color:#4a5568}.rate-table td.active{background:#dbeafe;color:#1d4ed8;font-weight:800}.notice{margin-top:18px;padding:13px 15px;border-radius:12px;background:#fff7ed;border:1px solid #fed7aa;color:#9a4b0e;font-size:12px;line-height:1.7}.advanced summary{cursor:pointer;font-weight:700;font-size:14px;color:#364258}.advanced[open] summary{margin-bottom:14px}.small-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}.small-grid input{height:38px}.loading{position:fixed;inset:0;background:rgba(244,247,251,.94);z-index:10;display:flex;align-items:center;justify-content:center}.loader-card{background:#fff;border:1px solid var(--line);border-radius:16px;padding:24px 30px;box-shadow:var(--shadow);text-align:center}.spinner{width:30px;height:30px;border:3px solid #dbe5f5;border-top-color:var(--blue);border-radius:50%;animation:spin .8s linear infinite;margin:0 auto 12px}@keyframes spin{to{transform:rotate(360deg)}}.error{display:none;background:#fef2f2;border:1px solid #fecaca;color:#991b1b;padding:12px;border-radius:10px;margin-bottom:16px;font-size:13px}.footer{margin:18px 0 4px;display:flex;align-items:center;justify-content:space-between;gap:16px;color:#8993a5;font-size:12px}.footer a{margin-left:auto;color:#65738a;text-decoration:none;font-weight:650}.footer a:hover{color:var(--blue);text-decoration:underline}.tag{display:inline-flex;align-items:center;padding:3px 7px;border-radius:999px;font-size:11px;font-weight:700;background:#eef2ff;color:#4338ca;margin-left:6px}
.mode-switch{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}.mode-option{position:relative;cursor:pointer}.mode-option input{position:absolute;opacity:0;pointer-events:none}.mode-option>span{display:flex;flex-direction:column;gap:3px;min-height:58px;padding:11px 13px;border:1px solid #cfd8e6;border-radius:11px;background:#fff;transition:.16s}.mode-option strong{font-size:14px;color:#354157}.mode-option small{font-size:11px;color:var(--muted);line-height:1.4}.mode-option input:checked+span{border-color:#4f7fe8;background:#eff6ff;box-shadow:0 0 0 3px rgba(37,99,235,.09)}.mode-option input:checked+span strong{color:#1d4ed8}.mode-note{margin-top:7px;font-size:11px;color:#7b8799;line-height:1.55}.review-field{display:none}.review-mode .review-field{display:flex}.switch input:disabled+.slider{cursor:not-allowed;background:#60a5fa}.switch input:disabled+.slider:before{box-shadow:none}.switch-row.is-disabled{opacity:.82}.mode-badge{background:#ecfdf5;color:#047857}.allocation{font-variant-numeric:tabular-nums}

@media(max-width:900px){.grid{grid-template-columns:1fr}.form-grid.four,.form-grid.cargo-grid,.small-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.hero{align-items:flex-start;flex-direction:column}.status{align-self:flex-start}.metric-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.metric.amber{grid-column:1/-1}.cargo-summary{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:560px){.app{padding:14px}.card{padding:16px}.form-grid,.form-grid.four,.form-grid.cargo-grid,.toggle-pair,.small-grid,.metric-grid,.cargo-summary,.mode-switch{grid-template-columns:1fr}.metric.amber{grid-column:auto}.hero h1{font-size:23px}.metric .value{font-size:22px}.footer{align-items:flex-end;flex-direction:column}.footer a{margin-left:0}}
@media print{.app{background:#fff;-webkit-print-color-adjust:exact;print-color-adjust:exact;max-width:none;padding:0 0 28px}.hero{margin-bottom:10px}.hero p,.hero .status,.buttons,.advanced,.notice,.error{display:none!important}.grid{grid-template-columns:1fr}.card{box-shadow:none;border-color:#bfc7d4;break-inside:avoid}.input-card{display:none}.result-wrap{display:block!important}.result-empty{display:none!important}.cargo-summary{grid-template-columns:repeat(3,minmax(0,1fr))}.metric-grid{grid-template-columns:repeat(3,minmax(0,1fr))}.metric.amber{grid-column:auto}.rate-table-wrap{overflow:visible}.footer{display:flex!important;position:fixed;left:0;right:0;bottom:0;margin:0;padding:7px 0;background:#fff;border-top:1px solid #e5e7eb}.footer a{margin-left:auto;color:#555;text-decoration:none}}

.search-note-spaced{margin-top:8px}.cargo-type-value{font-size:21px!important}.loading-error{color:#991b1b;max-width:460px;line-height:1.6}.status.online{background:#ecfdf5;color:#047857}.status.offline{background:#fef2f2;color:#b91c1c}.btn[disabled]{opacity:.55;cursor:not-allowed;transform:none}.security-note{font-size:11px;color:#64748b;margin-top:7px;line-height:1.55}
.combo{position:relative}.combo input{padding-right:50px;cursor:text}.combo-toggle{position:absolute;right:8px;top:50%;transform:translateY(-50%);width:30px;height:30px;border:1px solid #d6dfeb;border-radius:999px;background:linear-gradient(180deg,#fff 0%,#f3f7fd 100%);color:#5f6f86;font-size:14px;font-weight:800;line-height:1;display:flex;align-items:center;justify-content:center;cursor:pointer;box-shadow:0 2px 6px rgba(15,23,42,.08);transition:.16s}.combo-toggle:hover{background:linear-gradient(180deg,#f8fbff 0%,#eaf2ff 100%);border-color:#a9c2fb;color:var(--blue);box-shadow:0 4px 12px rgba(37,99,235,.16)}.combo.open .combo-toggle{border-color:#8db0fb;color:var(--blue);background:#eef4ff;transform:translateY(-50%) rotate(180deg)}.combo-menu{display:none;position:absolute;z-index:50;left:0;right:0;top:calc(100% + 8px);max-height:280px;overflow:auto;background:#fff;border:1px solid #d7e1ee;border-radius:14px;box-shadow:0 18px 40px rgba(25,42,70,.16);padding:6px}.combo.open .combo-menu{display:block}.combo-option{display:grid;grid-template-columns:minmax(0,1fr) auto;align-items:center;gap:10px;width:100%;padding:10px 12px;border:1px solid transparent;border-radius:10px;background:#fff;color:#273246;text-align:left;font-size:13px;cursor:pointer;transition:.14s}.combo-option:hover,.combo-option.active{background:#eff6ff;border-color:#d8e7ff;color:#174ea6}.combo-option .secondary{font-size:11px;color:#8390a5;white-space:nowrap;padding-left:8px}.combo-option:hover .secondary,.combo-option.active .secondary{color:#4f6f9f}.combo-empty{padding:14px 10px;color:#8a94a6;font-size:12px;text-align:center}.combo-loading{padding:14px 10px;color:#2563eb;font-size:12px;text-align:center}.field input.combo-resolved{border-color:#86b7a7;background:linear-gradient(180deg,#fff 0%,#fbfffd 100%)}.field input.combo-unresolved{border-color:#ef4444;background:#fffafa}

/* Match the host BI theme, including dark mode, while keeping the calculator visually distinct. */
.app{--tc-bg:var(--bg);--tc-panel:var(--panel);--tc-panel2:var(--panel2);--tc-text:var(--text);--tc-muted:var(--muted);--tc-line:var(--line);--tc-primary:var(--primary);--tc-green:var(--green);--tc-orange:var(--orange);--tc-red:var(--red);color:var(--tc-text);background:transparent}
.app,.app *{font-family:inherit}
.hero{padding:18px 20px;border:1px solid var(--tc-line);border-radius:16px;background:linear-gradient(135deg,color-mix(in srgb,var(--tc-primary) 10%,var(--tc-panel)),var(--tc-panel));box-shadow:var(--shadow)}
.hero h1{color:var(--tc-text);letter-spacing:0}
.hero p,.hint,.search-note,.mode-note,.security-note,.subline,.footer{color:var(--tc-muted)}
.status{background:color-mix(in srgb,var(--tc-primary) 12%,var(--tc-panel2));color:var(--tc-primary);border:1px solid color-mix(in srgb,var(--tc-primary) 24%,var(--tc-line))}
.status.online{background:color-mix(in srgb,var(--tc-green) 13%,var(--tc-panel));color:var(--tc-green);border-color:color-mix(in srgb,var(--tc-green) 25%,var(--tc-line))}
.card{background:var(--tc-panel);border-color:var(--tc-line);box-shadow:var(--shadow)}
.section{border-color:var(--tc-line)}
.section-title h3,.field label{color:var(--tc-text)}
.route-grid .field{border-color:var(--tc-line);background:color-mix(in srgb,var(--tc-primary) 3%,var(--tc-panel2));box-shadow:inset 0 1px 0 color-mix(in srgb,#fff 18%,transparent)}
.route-grid .field:hover{border-color:color-mix(in srgb,var(--tc-primary) 32%,var(--tc-line));transform:translateY(-1px)}
.field input,.field select{border-color:var(--tc-line);background:var(--tc-panel2);color:var(--tc-text)}
.field input::placeholder{color:var(--tc-muted)}
.field input:focus,.field select:focus{border-color:var(--tc-primary);box-shadow:0 0 0 3px color-mix(in srgb,var(--tc-primary) 18%,transparent)}
.combo-toggle{border-color:var(--tc-line);background:var(--tc-panel2);color:var(--tc-muted);box-shadow:none}
.combo-toggle:hover,.combo.open .combo-toggle{background:color-mix(in srgb,var(--tc-primary) 12%,var(--tc-panel2));border-color:color-mix(in srgb,var(--tc-primary) 42%,var(--tc-line));color:var(--tc-primary);box-shadow:0 4px 12px color-mix(in srgb,var(--tc-primary) 16%,transparent)}
.combo-menu{background:var(--tc-panel);border-color:var(--tc-line);box-shadow:0 18px 40px rgba(0,0,0,.24)}
.combo-option{background:var(--tc-panel);color:var(--tc-text)}
.combo-option:hover,.combo-option.active{background:color-mix(in srgb,var(--tc-primary) 14%,var(--tc-panel));border-color:color-mix(in srgb,var(--tc-primary) 28%,var(--tc-line));color:var(--tc-primary)}
.combo-option .secondary{color:var(--tc-muted)}
.combo-empty,.combo-loading{color:var(--tc-muted)}
.field input.combo-resolved{border-color:color-mix(in srgb,var(--tc-green) 52%,var(--tc-line));background:color-mix(in srgb,var(--tc-green) 7%,var(--tc-panel2))}
.field input.combo-unresolved{border-color:var(--tc-red);background:color-mix(in srgb,var(--tc-red) 7%,var(--tc-panel2))}
.mode-option>span{border-color:var(--tc-line);background:var(--tc-panel2)}
.mode-option:hover>span{border-color:color-mix(in srgb,var(--tc-primary) 35%,var(--tc-line));transform:translateY(-1px)}
.mode-option strong{color:var(--tc-text)}
.mode-option input:checked+span{border-color:var(--tc-primary);background:color-mix(in srgb,var(--tc-primary) 12%,var(--tc-panel2));box-shadow:0 0 0 3px color-mix(in srgb,var(--tc-primary) 16%,transparent)}
.mode-option input:checked+span strong{color:var(--tc-primary)}
.slider{background:color-mix(in srgb,var(--tc-text) 22%,var(--tc-panel2))}
.switch input:checked+.slider{background:var(--tc-primary)}
.btn{border:1px solid transparent;box-shadow:none}
.btn:hover{transform:translateY(-1px);filter:brightness(1.04)}
.btn:active{transform:translateY(0);filter:brightness(.98)}
.btn:focus-visible,.combo-toggle:focus-visible,.mode-option span:focus-visible{outline:3px solid color-mix(in srgb,var(--tc-primary) 28%,transparent);outline-offset:2px}
.btn.primary{background:var(--tc-primary)}
.btn.secondary,.btn.ghost{background:var(--tc-panel2);border-color:var(--tc-line);color:var(--tc-text)}
.btn.ghost:hover,.btn.secondary:hover{border-color:color-mix(in srgb,var(--tc-primary) 34%,var(--tc-line));color:var(--tc-primary)}
.notice{background:color-mix(in srgb,var(--tc-orange) 11%,var(--tc-panel));border-color:color-mix(in srgb,var(--tc-orange) 30%,var(--tc-line));color:var(--tc-orange)}
.error{background:color-mix(in srgb,var(--tc-red) 11%,var(--tc-panel));border-color:color-mix(in srgb,var(--tc-red) 30%,var(--tc-line));color:var(--tc-red)}
.result-empty{color:var(--tc-muted)}
.result-empty strong,.route-line{color:var(--tc-text)}
.cargo-item,.metric{border-color:var(--tc-line);background:var(--tc-panel2)}
.cargo-item .k,.metric .label,.detail-row span:first-child{color:var(--tc-muted)}
.metric.primary{background:linear-gradient(135deg,color-mix(in srgb,var(--tc-primary) 88%,#000),var(--tc-primary));border-color:color-mix(in srgb,var(--tc-primary) 72%,#000)}
.metric.amber{background:color-mix(in srgb,var(--tc-orange) 10%,var(--tc-panel));border-color:color-mix(in srgb,var(--tc-orange) 32%,var(--tc-line))}
.detail,.rate-table-wrap{border-color:var(--tc-line)}
.detail-row,.rate-table th,.rate-table td{border-color:var(--tc-line)}
.detail-row strong{color:var(--tc-text)}
.formula{background:color-mix(in srgb,var(--tc-primary) 5%,var(--tc-panel2));color:var(--tc-muted)}
.rate-table th{background:color-mix(in srgb,var(--tc-primary) 8%,var(--tc-panel2));color:var(--tc-muted)}
.rate-table td{color:var(--tc-text)}
.rate-table td.active{background:color-mix(in srgb,var(--tc-primary) 18%,var(--tc-panel));color:var(--tc-primary)}
.loading{background:color-mix(in srgb,var(--tc-bg) 92%,transparent)}
.loader-card{background:var(--tc-panel);border-color:var(--tc-line);box-shadow:var(--shadow);color:var(--tc-text)}
.footer a{color:var(--tc-muted)}
.footer a:hover{color:var(--tc-primary)}
@media(max-width:700px){.hero{padding:16px}.hero h1{font-size:22px}.card{padding:16px}.buttons .btn{flex:1;min-width:120px}}

/* Reference visual: warm ivory surface with coral actions and mint resolved fields. */
.app{--tc-bg:#fff7f3;--tc-panel:#fffefd;--tc-panel2:#fffaf8;--tc-text:#2a2430;--tc-muted:#806f7c;--tc-line:#f2d8d0;--tc-primary:#ff5b61;--tc-green:#43b89c;--tc-orange:#f29a53;--tc-red:#d95761;background:var(--tc-bg);border-radius:0;padding:18px 22px 10px;max-width:none}
.app :where(.hero,.card){border-color:var(--tc-line)}
.hero{padding:0 6px 16px;background:transparent;border:0;box-shadow:none;align-items:center}
.hero h1{font-size:28px;color:var(--tc-text);font-weight:850}
.hero p{color:var(--tc-muted);font-size:13px}
.status{padding:8px 14px;border-radius:999px;background:#fff0f0;color:var(--tc-primary);border:1px solid #ffd5d2}
.status.online{background:#fff0f0;color:var(--tc-primary);border-color:#ffd5d2}
.grid{grid-template-columns:minmax(0,1.12fr) minmax(390px,.88fr);gap:18px}
.card{border-radius:18px;padding:20px;background:var(--tc-panel);box-shadow:0 10px 26px rgba(194,108,96,.07)}
.card h2{font-size:18px;color:var(--tc-text)}
.section{border-color:var(--tc-line)}
.section-title h3,.field label{color:var(--tc-text)}
.route-grid .field{border-color:#f6d6cf;background:linear-gradient(180deg,#fffefe 0%,#fff9f7 100%);border-radius:15px;padding:12px}
.route-grid .field:hover,.route-grid .field:focus-within{border-color:#ffaaa0;box-shadow:0 0 0 3px rgba(255,91,97,.09);transform:none}
.field input,.field select{height:42px;border-radius:11px;border-color:#f0d3cc;background:#fff;color:var(--tc-text)}
.route-grid .field input{height:42px;border-radius:12px}
.field input:focus,.field select:focus{border-color:var(--tc-primary);box-shadow:0 0 0 3px rgba(255,91,97,.12)}
.field input.combo-resolved{border-color:#62bfa8;background:#f4fffb}
.combo-toggle{width:30px;height:30px;border-radius:999px;border-color:#dfe5eb;background:#f8fbfd;color:#708092}
.combo-toggle:hover,.combo.open .combo-toggle{color:var(--tc-primary);border-color:#ffb2aa;background:#fff2ef;box-shadow:none}
.combo-menu{border-color:#f0d3cc;border-radius:13px;background:var(--tc-panel);box-shadow:0 18px 36px rgba(126,76,72,.18)}
.combo-menu{min-width:180px;max-width:min(260px,calc(100vw - 32px));left:0;right:auto}
.combo-option{min-height:38px;white-space:nowrap}
.combo-option{background:var(--tc-panel);color:var(--tc-text)}
.combo-option:hover,.combo-option.active{background:#fff0ed;border-color:#ffd5ce;color:#d94650}
.mode-option>span{min-height:62px;border-radius:12px;border-color:#d6dce9;background:#fff}
.mode-option:hover>span{border-color:#ffb1a7;background:#fff9f7}
.mode-option input:checked+span{border-color:#ff8d83;background:#fff1ee;box-shadow:0 0 0 3px rgba(255,91,97,.10)}
.mode-option input:checked+span strong{color:var(--tc-primary)}
.slider{background:#c9d1df}.switch input:checked+.slider{background:var(--tc-green)}
.btn{height:42px;border-radius:10px;padding:0 17px}
.btn.primary{background:var(--tc-primary);box-shadow:0 8px 16px rgba(255,91,97,.20)}
.btn.secondary,.btn.ghost{background:#fff;border-color:#f0d3cc;color:#6d5962}
.btn.secondary:hover,.btn.ghost:hover{color:var(--tc-primary);border-color:#ffaaa0;background:#fff8f6}
.notice{background:#fff6e9;border-color:#ffd59e;color:#b25d18}
.error{background:#fff0f1;border-color:#ffc8cd;color:#b63e49}
.result-empty{min-height:370px;color:var(--tc-muted)}
.result-empty strong,.route-line{color:var(--tc-text)}
.cargo-item,.metric{border-color:#f0d8d2;background:#fffdfc;border-radius:11px}
.cargo-item .k,.metric .label,.detail-row span:first-child{color:#907b87}
.metric.primary{background:linear-gradient(135deg,#ff6b62 0%,#ff535d 100%);border-color:#ff665f;box-shadow:0 12px 24px rgba(255,91,97,.24)}
.metric.amber{background:#fff5e7;border-color:#ffd29a}
.metric .value{color:var(--tc-text)}
.metric.primary .value{color:#fff}
.metric .value,.metric .unit{white-space:nowrap}
.metric .value{font-size:23px;letter-spacing:-.02em}
.metric.primary .value{font-size:29px}
.metric .unit{font-size:12px;margin-left:3px}
.detail{border-color:#f0d8d2}
.detail-row{grid-template-columns:minmax(0,1fr) auto;padding:10px 12px;border-color:#f3dfda;white-space:nowrap}
.detail-row strong{color:var(--tc-text);max-width:none}
.formula{background:#fff6f5;color:#7d6c77;border:1px solid #f5dfda}
.rate-table-wrap{border-color:#f0d8d2}
.rate-table th{background:#fff2ef;color:#8b6871;border-color:#f0d8d2}
.rate-table td{color:var(--tc-text);border-color:#f0d8d2}
.rate-table td.active{background:#ffe3dd;color:#e6494f}
.security-note{color:#8e7e88}
.loading{background:rgba(255,247,243,.95)}
.loader-card{border-color:#f0d8d2;background:#fffefd;color:var(--tc-text)}
.footer a{color:#9b7f86}
@media(max-width:900px){.app{padding:14px}.grid{grid-template-columns:1fr}.hero{padding-bottom:12px}.hero h1{font-size:23px}.card{padding:16px}}
@media(max-width:560px){.app{padding:12px 10px 8px}.hero h1{font-size:21px}.hero p{font-size:12px}.status{padding:6px 10px;font-size:12px}.detail-row{white-space:normal}.detail-row strong{text-align:right}}

:global(:root[data-theme="dark"]) .app{--tc-bg:#1a1720;--tc-panel:#211d29;--tc-panel2:#272230;--tc-text:#f6edf2;--tc-muted:#b9a7b2;--tc-line:#443543;--tc-primary:#ff7775;--tc-green:#61d1ad;--tc-orange:#f6b36a;--tc-red:#ff8b92}
:global(:root[data-theme="dark"]) .hero{background:transparent}
:global(:root[data-theme="dark"]) .status,:global(:root[data-theme="dark"]) .status.online{background:#35232d;border-color:#68414c;color:#ffaaa0}
:global(:root[data-theme="dark"]) .route-grid .field{background:#241f2b;border-color:#443543}
:global(:root[data-theme="dark"]) .field input,:global(:root[data-theme="dark"]) .field select,:global(:root[data-theme="dark"]) .mode-option>span,:global(:root[data-theme="dark"]) .btn.secondary,:global(:root[data-theme="dark"]) .btn.ghost{background:var(--tc-panel2);color:var(--tc-text);border-color:var(--tc-line)}
:global(:root[data-theme="dark"]) .combo-menu,:global(:root[data-theme="dark"]) .combo-option{background:var(--tc-panel)}
:global(:root[data-theme="dark"]) .combo-option:hover,:global(:root[data-theme="dark"]) .combo-option.active,:global(:root[data-theme="dark"]) .mode-option input:checked+span{background:#382631;border-color:#80505b;color:#ffaaa0}
:global(:root[data-theme="dark"]) .field input.combo-resolved{background:#20352f;border-color:#4eae94}
:global(:root[data-theme="dark"]) .notice{background:#382b20;border-color:#76512f;color:#f5bc75}
:global(:root[data-theme="dark"]) .error{background:#3b242b;border-color:#75414d;color:#ff9aa0}
:global(:root[data-theme="dark"]) .cargo-item,:global(:root[data-theme="dark"]) .metric{background:var(--tc-panel2);border-color:var(--tc-line)}
:global(:root[data-theme="dark"]) .metric.amber{background:#382b20;border-color:#76512f}
:global(:root[data-theme="dark"]) .formula{background:#2b232c;border-color:#4b3540;color:#c8b7c0}
:global(:root[data-theme="dark"]) .rate-table th{background:#382631;color:#d9b5bf}
:global(:root[data-theme="dark"]) .rate-table td.active{background:#53323b;color:#ffaaa0}
.app{max-width:1180px;margin:0 auto}
.grid{align-items:start}
.result-wrap{min-width:0}
.detail{overflow:hidden;background:var(--tc-panel)}
.detail-row{display:flex;justify-content:space-between;align-items:center;gap:18px;min-height:40px;white-space:normal}
.detail-row span{font-size:12px;color:var(--tc-muted);flex:1;min-width:0}
.detail-row strong{font-size:13px;text-align:right;white-space:nowrap}
.detail-row:nth-child(even){background:color-mix(in srgb,var(--tc-primary) 2%,var(--tc-panel))}
.rate-table-wrap{padding:12px;background:var(--tc-panel);overflow:visible}
.rate-heading{display:flex;align-items:baseline;justify-content:space-between;gap:12px;margin-bottom:10px}
.rate-heading span{font-size:13px;font-weight:800;color:var(--tc-text)}
.rate-heading small{font-size:11px;color:var(--tc-muted)}
.rate-body{display:grid;grid-template-columns:92px repeat(5,minmax(0,1fr));border:1px solid var(--tc-line);border-radius:11px;overflow:hidden}
.rate-type,.rate-cell{min-height:76px;padding:10px 8px;display:flex;flex-direction:column;justify-content:center;align-items:center;text-align:center;border-right:1px solid var(--tc-line)}
.rate-type{font-size:12px;font-weight:700;color:var(--tc-muted);background:color-mix(in srgb,var(--tc-primary) 5%,var(--tc-panel2))}
.rate-cell:last-child{border-right:0}
.rate-cell-label{font-size:11px;color:var(--tc-muted);line-height:1.35}
.rate-cell strong{margin-top:7px;font-size:12px;color:var(--tc-text);white-space:nowrap}
.rate-cell em{margin-top:5px;padding:2px 6px;border-radius:999px;background:#ffe3dd;color:#e6494f;font-size:10px;font-style:normal;font-weight:800}
.rate-cell.active{background:#fff0ed;box-shadow:inset 0 -3px 0 var(--tc-primary)}
.rate-cell.active .rate-cell-label,.rate-cell.active strong{color:#df4f53}
:global(:root[data-theme="dark"]) .rate-cell.active{background:#432831}
:global(:root[data-theme="dark"]) .rate-cell em{background:#5b3039;color:#ffaaa0}
@media(max-width:760px){.app{max-width:none}.rate-body{grid-template-columns:76px minmax(0,1fr);overflow:hidden}.rate-cells{grid-template-columns:repeat(5,116px);overflow:auto}.rate-heading{display:block}.rate-heading small{display:block;margin-top:3px}.rate-table-wrap{overflow:hidden}.detail-row strong{font-size:12px}}

/* Dynamic result rows are inserted with innerHTML, so they need deep selectors under scoped CSS. */
:deep(.detail-row){display:flex;justify-content:space-between;align-items:center;gap:18px;min-height:40px;padding:10px 12px;border-top:1px solid var(--tc-line);font-size:13px;white-space:normal}
:deep(.detail-row:first-child){border-top:0}
:deep(.detail-row:nth-child(even)){background:color-mix(in srgb,var(--tc-primary) 2%,var(--tc-panel))}
:deep(.detail-row span){flex:1;min-width:0;font-size:12px;color:var(--tc-muted)}
:deep(.detail-row strong){max-width:none;color:var(--tc-text);font-size:13px;text-align:right;white-space:nowrap}
:deep(.cargo-summary){display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;margin-bottom:12px}
:deep(.cargo-item){border:1px solid var(--tc-line);background:var(--tc-panel2);border-radius:10px;padding:9px 10px;min-width:0}
:deep(.cargo-item .k){font-size:11px;color:var(--tc-muted);margin-bottom:4px}
:deep(.cargo-item .v){font-size:13px;font-weight:750;color:var(--tc-text);word-break:break-word;line-height:1.35}
:deep(.rate-body){display:grid;grid-template-columns:92px repeat(5,minmax(0,1fr));border:1px solid var(--tc-line);border-radius:11px;overflow:hidden}
:deep(.rate-body){grid-template-columns:92px minmax(0,1fr)}
:deep(.rate-cells){display:grid;grid-template-columns:repeat(5,minmax(0,1fr));min-width:0}
:deep(.rate-type),:deep(.rate-cell){min-height:76px;padding:10px 8px;display:flex;flex-direction:column;justify-content:center;align-items:center;text-align:center;border-right:1px solid var(--tc-line)}
:deep(.rate-type){font-size:12px;font-weight:700;color:var(--tc-muted);background:color-mix(in srgb,var(--tc-primary) 5%,var(--tc-panel2))}
:deep(.rate-cell:last-child){border-right:0}
:deep(.rate-cell-label){font-size:11px;color:var(--tc-muted);line-height:1.35}
:deep(.rate-cell strong){margin-top:7px;font-size:12px;color:var(--tc-text);white-space:nowrap}
:deep(.rate-cell em){margin-top:5px;padding:2px 6px;border-radius:999px;background:#ffe3dd;color:#e6494f;font-size:10px;font-style:normal;font-weight:800}
:deep(.rate-cell.active){background:#fff0ed;box-shadow:inset 0 -3px 0 var(--tc-primary)}
:deep(.rate-cell.active .rate-cell-label),:deep(.rate-cell.active strong){color:#df4f53}
:global(:root[data-theme="dark"]) :deep(.rate-cell.active){background:#432831}
:global(:root[data-theme="dark"]) :deep(.rate-cell em){background:#5b3039;color:#ffaaa0}
@media(max-width:760px){:deep(.rate-body){grid-template-columns:76px minmax(0,1fr);overflow:hidden}:deep(.rate-cells){grid-template-columns:repeat(5,116px);overflow:auto}.rate-table-wrap{overflow:hidden}}
@media(max-width:700px){:deep(.cargo-summary){grid-template-columns:repeat(2,minmax(0,1fr))}}
@media(max-width:560px){:deep(.cargo-summary){grid-template-columns:1fr}}
</style>
