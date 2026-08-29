<script setup>
import { computed, ref } from 'vue'
import { ArrowLeftRight, Calculator, RotateCcw, Truck } from 'lucide-vue-next'

const groups = {
  hb: ['北京','天津','河北','山西','山东','内蒙古-呼和浩特市','内蒙古-包头市','内蒙古-乌海市','内蒙古-乌兰察布市','内蒙古-锡林郭勒盟','内蒙古-鄂尔多斯市','内蒙古-巴彦淖尔市','内蒙古-阿拉善盟'],
  db: ['辽宁','吉林','黑龙江','内蒙古-赤峰市','内蒙古-呼伦贝尔市','内蒙古-兴安盟','内蒙古-通辽市'],
  hd: ['上海','江苏','安徽','浙江'], hz: ['河南','湖北','湖南','江西'],
  xn: ['重庆','四川','贵州','云南','西藏'], xb: ['陕西','甘肃','青海','宁夏','新疆'], hn: ['福建','广东','广西','海南']
}
const regionNames = { hb:'华北区域', db:'东北区域', hd:'华东区域', hz:'华中区域', xn:'西南区域', xb:'西北区域', hn:'华南区域' }
const places = Object.entries(groups).flatMap(([region, list]) => list.map(name => ({ name, region })))
const aliases = new Map()
const normalize = value => String(value || '').trim().replace(/\s+/g, '').replace(/[省市自治区壮族回族维吾尔特别行政区]/g, '')
places.forEach(place => {
  aliases.set(normalize(place.name), place)
  if (place.name.startsWith('内蒙古-')) aliases.set(normalize(place.name.slice(5)), place)
})
const resolve = value => aliases.get(normalize(value))

const sender = ref('河北'), receiver = ref('安徽'), season = ref('off')
const weight = ref(1), quantity = ref(1), volume = ref(0), outboundTier = ref('auto'), materialMode = ref('auto'), manualMaterial = ref(0)
const result = ref(null)

const route = computed(() => {
  const from = resolve(sender.value), to = resolve(receiver.value)
  if (!from || !to) return null
  return { from, to, same: from.region === to.region, uncovered: ['西藏','甘肃','青海','新疆'].includes(to.name) }
})
const routeLabel = computed(() => {
  if (!route.value) return '待确认线路'
  if (route.value.uncovered && !route.value.same) return '跨区未覆盖'
  return route.value.same ? '同区 A 区' : '跨区 B 区'
})

function money(v) { return Number(v || 0).toFixed(2) }
function chargeableWeight() { return Math.max(Number(weight.value) || 0, (Number(volume.value) || 0) / 6000) }
function calculateExpress(zone, isPeak, kg) {
  const rates = zone === 'A' ? (isPeak ? [4,4.5,5.5,6.5] : [3.5,4,5,6]) : (isPeak ? [5.5,6,6.5,7.5] : [5,5.5,6,7])
  const extra = zone === 'A' ? 1.5 : 2.5
  if (kg <= .5) return { total: rates[0], formula: `0–0.5kg · ${money(rates[0])}元/票` }
  if (kg <= 1) return { total: rates[1], formula: `0.5–1kg · ${money(rates[1])}元/票` }
  if (kg <= 2) return { total: rates[2], formula: `1–2kg · ${money(rates[2])}元/票` }
  if (kg <= 3) return { total: rates[3], formula: `2–3kg · ${money(rates[3])}元/票` }
  const extraKg = Math.ceil(kg - 3 - 1e-9); return { total: rates[3] + extraKg * extra, formula: `首重3kg ${money(rates[3])}元 + ${extraKg}kg续重` }
}
function calculate() {
  const r = route.value, kg = Number(weight.value), qty = Number(quantity.value), vol = Number(volume.value)
  if (!r || !Number.isFinite(kg) || kg <= 0 || !Number.isInteger(qty) || qty <= 0 || !Number.isFinite(vol) || vol < 0) { result.value = null; return }
  if (r.uncovered && !r.same) { result.value = { unsupported: true, route: r }; return }
  const zone = r.same ? 'A' : 'B', express = calculateExpress(zone, season.value === 'peak', kg)
  const avg = chargeableWeight() / qty, large = outboundTier.value === 'large' || (outboundTier.value === 'auto' && avg > 2.5)
  const outbound = (large ? 1.2 : .9) + qty * .3
  let material = materialMode.value === 'none' ? 0 : materialMode.value === 'reinforce' ? .4 : materialMode.value === 'manual' ? Math.max(0, Number(manualMaterial.value) || 0) : ([.44,.48,.56,.76,.96,.4,.4,1][kg <= .5 ? 0 : kg <= 1 ? 1 : kg <= 2 ? 2 : kg <= 3 ? 3 : kg <= 5 ? 4 : kg <= 10 ? 5 : kg <= 20 ? 6 : 7])
  result.value = { route: r, zone, express, outbound, material, total: express.total + outbound + material, chargeable: chargeableWeight(), large }
}
function reset() { sender.value = '河北'; receiver.value = '安徽'; season.value = 'off'; weight.value = 1; quantity.value = 1; volume.value = 0; outboundTier.value = 'auto'; materialMode.value = 'auto'; manualMaterial.value = 0; result.value = null }
function swap() { const current = sender.value; sender.value = receiver.value; receiver.value = current; calculate() }
</script>

<template>
  <div class="page jp-page">
    <div class="page-title jp-title"><div class="jp-heading"><span class="jp-hero-icon"><Truck :size="19"/></span><div><h1>京配计算器</h1><p>京东标快月票量 3000+ 参考价，快速估算发货成本。</p></div></div><span class="jp-badge">B2C事业部 · 参考价</span></div>
    <section class="panel jp-panel">
      <div class="section-head"><div><h3>线路与货物参数</h3><span>输入基础信息，费用会随参数变化即时更新</span></div><button class="ui-btn ui-btn-ghost" type="button" @click="reset"><RotateCcw :size="14"/>重置</button></div>
      <div class="jp-form-grid">
        <label>始发地<input v-model="sender" list="jp-place-list" placeholder="如：河北" @input="calculate"/></label>
        <div class="jp-swap"><button type="button" title="交换始发地和目的地" @click="swap"><ArrowLeftRight :size="17"/></button></div>
        <label>收货地<input v-model="receiver" list="jp-place-list" placeholder="如：安徽" @input="calculate"/></label>
        <label>季节<select v-model="season" @change="calculate"><option value="off">淡季</option><option value="peak">旺季</option></select></label>
        <label>重量（kg）<input v-model.number="weight" type="number" min="0.01" step="0.01" @input="calculate"/></label>
        <label>件数<input v-model.number="quantity" type="number" min="1" step="1" @input="calculate"/></label>
        <label>体积（m³）<input v-model.number="volume" type="number" min="0" step="0.001" @input="calculate"/></label>
        <label>出库档位<select v-model="outboundTier" @change="calculate"><option value="auto">自动判断</option><option value="normal">普通件</option><option value="large">大件/特殊件</option></select></label>
        <label>耗材费<select v-model="materialMode" @change="calculate"><option value="auto">按历史中位估算</option><option value="none">无额外耗材</option><option value="reinforce">简单加固</option><option value="manual">手动输入</option></select></label>
        <label v-if="materialMode === 'manual'">实付耗材费（元）<input v-model.number="manualMaterial" type="number" min="0" step="0.01" @input="calculate"/></label>
      </div>
      <datalist id="jp-place-list"><option v-for="p in places" :key="p.name" :value="p.name"/></datalist>
      <div class="jp-route-status" :class="{ good: route && route.same, cross: route && !route.same, bad: route && route.uncovered && !route.same }"><span>{{ routeLabel }}</span><small v-if="route">{{ route.from.name }}（{{ regionNames[route.from.region] }}）→ {{ route.to.name }}（{{ regionNames[route.to.region] }}）</small><small v-else>请输入有效的省份或城市名称</small></div>
      <button class="ui-btn ui-btn-primary jp-calc" type="button" @click="calculate"><Calculator :size="15"/>计算费用</button>
    </section>

    <section class="jp-result-grid">
      <div class="jp-total" :class="{ pending: !result, unsupported: result?.unsupported }"><span>预计总费用</span><strong>{{ result && !result.unsupported ? money(result.total) : '--' }}<i>元</i></strong><small>{{ result?.unsupported ? '当前价格表未覆盖该跨区流向' : result ? `${result.zone}区 · ${season === 'peak' ? '旺季' : '淡季'}` : '等待填写参数' }}</small></div>
      <div class="panel jp-breakdown"><div class="section-head"><h3>费用组成</h3><span v-if="result">计费参考重量 {{ result.chargeable.toFixed(3) }} kg</span></div><div class="jp-kpis"><div><span>快递费</span><b>{{ result && !result.unsupported ? money(result.express.total) : '--' }}<em>元</em></b></div><div><span>销售出库费</span><b>{{ result && !result.unsupported ? money(result.outbound) : '--' }}<em>元</em></b></div><div><span>耗材费</span><b>{{ result && !result.unsupported ? money(result.material) : '--' }}<em>元</em></b></div></div><div class="jp-detail" v-if="result && !result.unsupported"><p><b>快递费：</b>{{ result.express.formula }}</p><p><b>出库费：</b>{{ result.large ? '大件/特殊件' : '普通件' }}基础费 + {{ quantity }}件 × 0.30元</p><p><b>耗材费：</b>{{ materialMode === 'auto' ? '按历史中位估算' : materialMode === 'none' ? '原箱出库' : materialMode === 'reinforce' ? '简单加固' : '手动输入' }}</p></div></div>
    </section>
    <section class="panel jp-notes"><div class="section-head"><h3>计费说明</h3><span>来源：京东标快 B2C 参考价格表</span></div><div class="jp-note-grid"><p><b>A区</b>：同区域内互发，首重价格更低，续重约 1.5 元/kg。</p><p><b>B区</b>：跨区域发送，续重约 2.5 元/kg；西藏、甘肃、青海、新疆暂未覆盖。</p><p><b>重泡判断</b>：体积 ÷ 6000 与实际重量取较大值作为计费参考。</p><p><b>旺季</b>：基础快递费按参考价格上浮，国庆、双11等高峰附加费需另行确认。</p></div></section>
  </div>
</template>

<style scoped>
.jp-page{max-width:1080px;padding-bottom:24px}.jp-title{display:flex;align-items:center;justify-content:space-between;gap:18px;margin-bottom:16px}.jp-heading{display:flex;align-items:center;gap:12px}.jp-hero-icon{width:42px;height:42px;border-radius:14px;display:grid;place-items:center;color:#fff;background:linear-gradient(145deg,#5968f5,#4ba7d8);box-shadow:0 9px 22px rgba(82,102,221,.22)}.jp-title h1{font-size:25px;letter-spacing:-.02em}.jp-title p{margin:5px 0 0;color:var(--muted);font-size:12px}.jp-badge{padding:7px 11px;border-radius:9px;border:1px solid color-mix(in srgb,var(--primary) 18%,var(--line));background:color-mix(in srgb,var(--primary) 7%,var(--panel));color:var(--primary);font-size:11px;font-weight:750;white-space:nowrap}.jp-panel{padding:20px 20px 18px;margin-bottom:14px;border-radius:18px}.jp-panel:before{content:"";display:block;width:52px;height:3px;border-radius:3px;background:var(--primary);margin-bottom:13px}.jp-form-grid{display:grid;grid-template-columns:1.15fr 38px 1.15fr repeat(3,minmax(120px,1fr));gap:12px;align-items:end}.jp-form-grid label{font-size:11px;color:var(--muted);font-weight:750}.jp-form-grid input,.jp-form-grid select{width:100%;height:43px;margin-top:6px;padding:0 11px;border:1px solid var(--line);border-radius:11px;background:var(--panel2);color:var(--text);outline:none;transition:.18s}.jp-form-grid input:hover,.jp-form-grid select:hover{border-color:color-mix(in srgb,var(--primary) 20%,var(--line))}.jp-form-grid input:focus,.jp-form-grid select:focus{border-color:var(--primary);box-shadow:0 0 0 4px color-mix(in srgb,var(--primary) 10%,transparent);background:var(--panel)}.jp-swap{display:flex;align-items:end}.jp-swap button{width:38px;height:43px;border:1px solid var(--line);border-radius:11px;background:var(--panel2);color:var(--muted);display:grid;place-items:center;cursor:pointer;transition:.18s}.jp-swap button:hover{color:var(--primary);border-color:var(--primary);background:color-mix(in srgb,var(--primary) 8%,var(--panel))}.jp-route-status{display:flex;align-items:center;gap:10px;margin-top:15px;padding:11px 13px;border:1px solid var(--line);border-radius:11px;background:color-mix(in srgb,var(--primary) 3%,var(--panel2))}.jp-route-status:before{content:"";width:7px;height:7px;border-radius:50%;background:var(--muted)}.jp-route-status.good:before{background:var(--green)}.jp-route-status.cross:before{background:var(--orange)}.jp-route-status.bad:before{background:var(--red)}.jp-route-status span{font-size:12px;font-weight:850;color:var(--muted)}.jp-route-status small{font-size:11px;color:var(--muted)}.jp-route-status.good span{color:var(--green)}.jp-route-status.cross span{color:var(--orange)}.jp-route-status.bad span{color:var(--red)}.jp-calc{margin-top:15px;min-width:118px}.jp-result-grid{display:grid;grid-template-columns:minmax(260px,.75fr) minmax(0,1.25fr);gap:14px;margin-bottom:14px}.jp-total{min-height:188px;border-radius:17px;padding:24px;background:linear-gradient(145deg,#202a3c,#354562);color:#fff;display:flex;flex-direction:column;justify-content:center;box-shadow:0 16px 34px rgba(33,47,74,.18)}.jp-total.pending{background:#68758b}.jp-total.unsupported{background:#8c4f47}.jp-total span{font-size:12px;color:#cbd5e1}.jp-total strong{font-size:43px;line-height:1.1;margin:9px 0;font-variant-numeric:tabular-nums;letter-spacing:-.03em}.jp-total strong i{font-size:15px;font-style:normal;margin-left:5px;font-weight:500}.jp-total small{font-size:11px;color:#d6dce6}.jp-breakdown{min-height:188px;padding:20px}.jp-kpis{display:grid;grid-template-columns:repeat(3,1fr);gap:9px}.jp-kpis>div{padding:13px 12px;border:1px solid var(--line);border-radius:12px;background:color-mix(in srgb,var(--primary) 3%,var(--panel2));transition:.18s}.jp-kpis>div:hover{transform:translateY(-2px);border-color:color-mix(in srgb,var(--primary) 22%,var(--line))}.jp-kpis span{display:block;color:var(--muted);font-size:10px}.jp-kpis b{display:block;margin-top:6px;font-size:21px;letter-spacing:-.02em}.jp-kpis em{font-size:10px;color:var(--muted);font-style:normal;margin-left:3px;font-weight:500}.jp-detail{display:grid;gap:7px;margin-top:14px;padding-top:13px;border-top:1px solid var(--line)}.jp-detail p{margin:0;color:var(--muted);font-size:11px;line-height:1.6}.jp-detail b{color:var(--text)}.jp-notes{padding:18px}.jp-note-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px}.jp-note-grid p{margin:0;padding:12px 13px;border:1px solid var(--line);border-radius:11px;background:var(--panel2);color:var(--muted);font-size:11px;line-height:1.65}.jp-note-grid p:hover{background:color-mix(in srgb,var(--primary) 4%,var(--panel2))}.jp-note-grid b{color:var(--text)}@media(max-width:1000px){.jp-form-grid{grid-template-columns:1fr 1fr}.jp-swap{grid-column:1/-1;justify-content:center}.jp-swap button{transform:rotate(90deg)}.jp-result-grid{grid-template-columns:1fr}}@media(max-width:620px){.jp-form-grid{grid-template-columns:1fr}.jp-swap{grid-column:auto}.jp-swap button{transform:none;width:100%}.jp-kpis,.jp-note-grid{grid-template-columns:1fr}.jp-total strong{font-size:36px}.jp-title{display:block}.jp-badge{display:inline-block;margin-top:10px}}
/* Readability pass: slightly larger supporting text for desktop and dark mode. */
.jp-title p{font-size:13px}.jp-badge{font-size:12px}.jp-form-grid label{font-size:12px}.jp-form-grid input,.jp-form-grid select{font-size:13px}.jp-route-status span{font-size:13px}.jp-route-status small{font-size:12px}.jp-total span{font-size:13px}.jp-total strong i{font-size:16px}.jp-total small{font-size:12px}.jp-kpis span{font-size:12px}.jp-kpis em{font-size:11px}.jp-detail p,.jp-note-grid p{font-size:12px}
/* Color pass: brighter accents and clearer cost categories. */
.jp-hero-icon{background:linear-gradient(145deg,#635bff,#1687e8);box-shadow:0 10px 24px rgba(57,91,236,.28)}
.jp-badge{color:#4f46e5;background:color-mix(in srgb,#6366f1 12%,var(--panel));border-color:color-mix(in srgb,#6366f1 28%,var(--line))}
.jp-panel:before{background:linear-gradient(90deg,#6366f1,#22c7d6)}
.jp-total{background:linear-gradient(135deg,#4338ca 0%,#2563eb 58%,#0891b2 100%);box-shadow:0 18px 38px rgba(37,99,235,.28)}
.jp-total.pending{background:linear-gradient(135deg,#64748b,#475569)}.jp-total.unsupported{background:linear-gradient(135deg,#dc2626,#ea580c)}
.jp-total span{color:#dbeafe}.jp-total small{color:#d9f7ff}.jp-kpis>div:nth-child(1){background:color-mix(in srgb,#3b82f6 10%,var(--panel));border-color:color-mix(in srgb,#3b82f6 25%,var(--line))}.jp-kpis>div:nth-child(2){background:color-mix(in srgb,#f59e0b 10%,var(--panel));border-color:color-mix(in srgb,#f59e0b 25%,var(--line))}.jp-kpis>div:nth-child(3){background:color-mix(in srgb,#8b5cf6 10%,var(--panel));border-color:color-mix(in srgb,#8b5cf6 25%,var(--line))}.jp-kpis>div:nth-child(1) b{color:#2563eb}.jp-kpis>div:nth-child(2) b{color:#d97706}.jp-kpis>div:nth-child(3) b{color:#7c3aed}
</style>
