<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { ArrowUpDown } from 'lucide-vue-next'
import { useRoute } from 'vue-router'
import FilterBar from '../components/FilterBar.vue'
import { useFilterStore } from '../stores/filter'
import { fetchDashboardOptions } from '../api/dashboard'
import { fetchExpiryBatches } from '../api/analysis'

const f=useFilterStore()
const route=useRoute()
const localProductSearch=ref(String(route.query.sku||''))
const data=ref(null),error=ref(''),loading=ref(false)
const shopOptions=ref([]),warehouseOptions=ref([])
const statuses=ref([]),daysMin=ref(''),daysMax=ref(''),pctMin=ref(''),pctMax=ref('')
let timer=null,serial=0
const sort=ref({key:'remaining_days',dir:'asc'})
const rows=computed(()=>sortRows(data.value?.rows||[],sort.value)),summary=computed(()=>data.value?.summary||{})
const statusList=['正常','预警','临期','过期']

function n(v,d=0){return Number(v||0).toLocaleString('zh-CN',{maximumFractionDigits:d})}
function statusClass(s){return {'正常':'expiry-normal','预警':'expiry-warn','临期':'expiry-near','过期':'expiry-expired'}[s]||''}
function sortRows(rows,s){const dir=s.dir==='asc'?1:-1;return [...rows].sort((a,b)=>{const av=a[s.key],bv=b[s.key];if(av==null&&bv==null)return 0;if(av==null)return 1;if(bv==null)return -1;const an=Number(av),bn=Number(bv);return Number.isFinite(an)&&Number.isFinite(bn)?(an-bn)*dir:String(av).localeCompare(String(bv),'zh-CN')*dir})}
function toggleSort(key,defaultDir='desc'){sort.value=sort.value.key===key?{key,dir:sort.value.dir==='asc'?'desc':'asc'}:{key,dir:defaultDir}}
function mark(key){return sort.value.key===key?(sort.value.dir==='asc'?'↑':'↓'):''}
function toggleStatus(s){statuses.value=statuses.value.includes(s)?statuses.value.filter(x=>x!==s):[...statuses.value,s];load()}
async function loadOptions(){try{const r=await fetchDashboardOptions();shopOptions.value=r.shops||[];warehouseOptions.value=r.warehouses||[]}catch(e){error.value=e.message}}
async function load(){
  const id=++serial;loading.value=true;error.value=''
  try{
    const r=await fetchExpiryBatches({warehouses:f.warehouses,productSearch:localProductSearch.value||f.productSearch,includeName:f.includeName,excludeName:f.excludeName,productCodes:f.productCodes,statuses:statuses.value,remainingDaysMin:daysMin.value,remainingDaysMax:daysMax.value,remainingPctMin:pctMin.value,remainingPctMax:pctMax.value})
    if(id===serial)data.value=r
  }catch(e){if(id===serial){error.value=`效期批次读取失败：${e.message}`;data.value=null}}
  finally{if(id===serial)loading.value=false}
}
function schedule(){clearTimeout(timer);timer=setTimeout(load,260)}
watch(()=>[JSON.stringify(f.warehouses),f.productSearch,f.includeName,f.excludeName,JSON.stringify(f.productCodes),localProductSearch.value],schedule)
watch(()=>[daysMin.value,daysMax.value,pctMin.value,pctMax.value],schedule)
onMounted(async()=>{const qs=String(route.query.status||'');if(statusList.includes(qs))statuses.value=[qs];await loadOptions();await load()})
</script>

<template>
  <div class="page">
    <div class="page-title"><h1>效期批次</h1><p>真实读取 inventory_batch，并按商品规则 &gt; 部门规则 &gt; 全局规则计算效期状态</p></div>
    <FilterBar :shop-options="shopOptions" :warehouse-options="warehouseOptions" :show-date="false" />
    <div class="expiry-dimension-note">店铺筛选在本页保留上下文，但效期库存本身不按店铺拆分，因此不会参与效期查询。<template v-if="localProductSearch"> · 当前商品：<b>{{ localProductSearch }}</b> <button class="link-button" @click="localProductSearch='';load()">清除</button></template></div>

    <div v-if="error" class="api-error"><b>效期接口暂不可用</b><span>{{ error }}</span><button @click="load">重新读取</button></div>
    <div v-else-if="loading && !data" class="dashboard-loading">正在计算效期批次…</div>

    <template v-if="data">
      <section class="expiry-mini-grid clickable-expiry">
        <button v-for="s in statusList" :key="s" :class="['expiry-mini',statusClass(s),{active:statuses.includes(s)}]" @click="toggleStatus(s)"><span>{{ s }}</span><b>{{ n(summary[s]) }}</b><small>点击{{ statuses.includes(s)?'取消':'筛选' }}</small></button>
      </section>

      <section class="panel expiry-filters">
        <label>剩余天数 ≥<input v-model="daysMin" type="number" placeholder="不限" /></label>
        <label>剩余天数 ≤<input v-model="daysMax" type="number" placeholder="不限" /></label>
        <label>剩余效期% ≥<input v-model="pctMin" type="number" min="0" max="100" placeholder="不限" /></label>
        <label>剩余效期% ≤<input v-model="pctMax" type="number" min="0" max="100" placeholder="不限" /></label>
        <button class="rank-tab" @click="statuses=[];daysMin='';daysMax='';pctMin='';pctMax='';load()">清除效期筛选</button>
      </section>

      <section class="data-scope-bar"><span>库存快照：<b>{{ data.meta?.latest_inventory_date || '—' }}</b></span><span>筛选后批次：<b>{{ n(data.filtered_count) }}</b></span><span>{{ data.meta?.long_term_note }}</span></section>

      <section class="panel table-wrap">
        <table class="expiry-table-real">
          <thead><tr><th>仓库</th><th>商品名称</th><th>商家编码</th><th><button class="sort-th" @click="toggleSort('stock_qty')">库存 <ArrowUpDown :size="12"/>{{ mark('stock_qty') }}</button></th><th>生产日期</th><th>过期日期</th><th><button class="sort-th" @click="toggleSort('total_shelf_days')">总有效期 <ArrowUpDown :size="12"/>{{ mark('total_shelf_days') }}</button></th><th><button class="sort-th" @click="toggleSort('remaining_days','asc')">剩余天数 <ArrowUpDown :size="12"/>{{ mark('remaining_days') }}</button></th><th><button class="sort-th" @click="toggleSort('remaining_pct','asc')">剩余效期% <ArrowUpDown :size="12"/>{{ mark('remaining_pct') }}</button></th><th>状态</th><th>规则来源</th></tr></thead>
          <tbody>
            <tr v-for="r in rows" :key="r.batch_id">
              <td>{{ r.warehouse }}</td><td><RouterLink class="table-product-link" :to="{path:'/product',query:{sku:r.sku}}">{{ r.name }}</RouterLink></td><td>{{ r.sku }}</td><td>{{ n(r.stock_qty) }}</td>
              <td>{{ r.production_date || '—' }}</td><td>{{ r.expire_date || '—' }}</td><td>{{ r.total_shelf_days==null?'—':`${r.total_shelf_days}天` }}</td><td>{{ r.remaining_days==null?'—':`${r.remaining_days}天` }}</td>
              <td><template v-if="r.remaining_pct!=null"><div class="pct"><span :class="statusClass(r.status)" :style="{width:`${Math.max(0,Math.min(100,r.remaining_pct))}%`}"></span></div><b>{{ n(r.remaining_pct,1) }}%</b></template><span v-else>—</span></td>
              <td><span :class="['expiry-status-tag',statusClass(r.status)]">{{ r.status }}</span></td><td>{{ r.rule_source==='product'?'单品规则':r.rule_source==='department'?'部门规则':'全局规则' }}</td>
            </tr>
            <tr v-if="!rows.length"><td colspan="11" class="table-empty">当前条件下没有效期批次。</td></tr>
          </tbody>
        </table>
      </section>
    </template>
  </div>
</template>
