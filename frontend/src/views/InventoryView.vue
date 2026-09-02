<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { ArrowUpDown, Download, Warehouse } from 'lucide-vue-next'
import FilterBar from '../components/FilterBar.vue'
import { useFilterStore } from '../stores/filter'
import { fetchDashboardOptions } from '../api/dashboard'
import { fetchInventoryAnalysis } from '../api/analysis'
import { exportInventoryAnalysis } from '../api/exports'

const f = useFilterStore()
const data = ref(null)
const error = ref('')
const loading = ref(false)
const shopOptions = ref([])
const warehouseOptions = ref([])
const productCategoryOptions = ref([])
const detailWarehouses = ref(false)
const exporting = ref(false)
const exportError = ref('')
const lastExportCount = ref(null)
let timer = null
let serial = 0

const days = computed(() => Number(String(f.dateRange).replace('d','')) || 30)
const cats = computed(() => data.value?.categories || {})
const sort=ref({key:'stock_qty',dir:'desc'})
const rows = computed(() => sortRows(data.value?.rows || [],sort.value))
const meta = computed(() => data.value?.meta || {})
const warehouseColumns = computed(() => meta.value.warehouse_columns || [])
const cards = [
  ['healthy','健康库存'],['high','高库存'],['stagnant','呆滞库存'],['no_sales','无销量库存']
]

function n(v,d=0){return Number(v||0).toLocaleString('zh-CN',{maximumFractionDigits:d})}
function cover(v){return v==null?'—':`${Number(v).toFixed(1)}天`}
function sortRows(rows,s){const dir=s.dir==='asc'?1:-1;return [...rows].sort((a,b)=>{const av=a[s.key],bv=b[s.key];if(av==null&&bv==null)return 0;if(av==null)return 1;if(bv==null)return -1;const an=Number(av),bn=Number(bv);return Number.isFinite(an)&&Number.isFinite(bn)?(an-bn)*dir:String(av).localeCompare(String(bv),'zh-CN')*dir})}
function toggleSort(key,defaultDir='desc'){sort.value=sort.value.key===key?{key,dir:sort.value.dir==='asc'?'desc':'asc'}:{key,dir:defaultDir}}
function mark(key){return sort.value.key===key?(sort.value.dir==='asc'?'↑':'↓'):''}

async function loadOptions(){
  try{
    const r=await fetchDashboardOptions();shopOptions.value=r.shops||[];warehouseOptions.value=r.warehouses||[];productCategoryOptions.value=r.product_categories||[]
  }catch(e){error.value=`筛选项读取失败：${e.message}`}
}
async function load(){
  const id=++serial;loading.value=true;error.value=''
  try{
    const r=await fetchInventoryAnalysis({
      days:days.value,shops:f.shops,warehouses:f.warehouses,
      productSearch:f.productSearch,includeName:f.includeName,excludeName:f.excludeName,productCodes:f.productCodes,
      productCategoryIds:f.productCategoryIds,detailWarehouses:detailWarehouses.value
    })
    if(id===serial)data.value=r
  }catch(e){if(id===serial){error.value=`库存分析读取失败：${e.message}`;data.value=null}}
  finally{if(id===serial)loading.value=false}
}
function schedule(){clearTimeout(timer);timer=setTimeout(load,260)}
async function downloadFiltered(){
  exporting.value=true;exportError.value=''
  try{
    const r=await exportInventoryAnalysis({
      departmentCode:f.departmentCode,
      shops:f.shops,warehouses:f.warehouses,days:days.value,
      productSearch:f.productSearch,
      includeName:f.includeName,excludeName:f.excludeName,productCodes:f.productCodes,productCategoryIds:f.productCategoryIds,
      detailWarehouses:detailWarehouses.value,
    })
    lastExportCount.value=r.rowCount
  }catch(e){exportError.value=e.message}
  finally{exporting.value=false}
}
watch(()=>[f.dateRange,JSON.stringify(f.shops),JSON.stringify(f.warehouses),JSON.stringify(f.productCategoryIds),f.productSearch,f.includeName,f.excludeName,JSON.stringify(f.productCodes),detailWarehouses.value],schedule)
onMounted(async()=>{await loadOptions();await load()})
</script>

<template>
  <div class="page">
    <div class="page-title"><h1>库存分析</h1><p>真实读取本地NAS最新库存快照、30天销量与库龄数据进行分类</p></div>
    <FilterBar :shop-options="shopOptions" :warehouse-options="warehouseOptions" :product-category-options="productCategoryOptions" :show-date="false" />

    <div v-if="error" class="api-error"><b>库存接口暂不可用</b><span>{{ error }}</span><button @click="load">重新读取</button></div>
    <div v-else-if="loading && !data" class="dashboard-loading">正在计算库存健康分类…</div>

    <template v-if="data">
      <section class="data-scope-bar">
        <span>库存快照：<b>{{ meta.latest_inventory_date || '—' }}</b></span>
        <span>销量截至：<b>{{ meta.latest_sales_date || '—' }}</b></span>
        <span>库龄快照：<b>{{ meta.latest_aging_date || '—' }}</b></span>
        <span>{{ meta.inventory_dimension_note }}</span>
      </section>

      <section class="category-grid inventory-category-grid">
        <RouterLink v-for="[key,label] in cards" :key="key" :to="{path:'/product',query:{stock_category:key}}" class="category-card category-button">
          <b>{{ label }}</b><strong>{{ n(cats[key]?.sku_count) }}</strong>
          <span>库存 {{ n(cats[key]?.stock_qty) }} · 点击进入商品分析</span>
        </RouterLink>
      </section>

      <section class="panel inventory-rule-note">
        <b>当前分类默认口径</b>
        <span>高库存：预计周转 &gt; {{ meta.thresholds?.high_cover_days }}天；呆滞：加权库龄 ≥ {{ meta.thresholds?.stagnant_aging_days }}天或预计周转 &gt; {{ meta.thresholds?.stagnant_cover_days }}天；无销量库存优先单独分类。</span>
        <small>{{ meta.classification_rule_status }}</small>
      </section>

      <section class="panel table-wrap">
        <div class="section-head"><div><h3>全部库存商品</h3><span>当前 {{ n(data.totals?.sku_count) }} 个 SKU</span></div><div class="inventory-table-actions"><label class="inventory-detail-toggle"><input v-model="detailWarehouses" type="checkbox" /><Warehouse :size="14" />细分仓库</label><button class="rank-tab" :disabled="exporting" @click="downloadFiltered"><Download :size="14" /> {{ exporting?'正在生成…':`下载当前筛选结果${lastExportCount!=null?'（'+lastExportCount+'条）':''}` }}</button></div></div>
        <div v-if="exportError" class="api-error compact"><span>{{ exportError }}</span></div>
        <table class="inventory-table">
          <thead><tr><th>商品</th><th>商家编码</th><th>分类</th><th v-for="warehouse in warehouseColumns" :key="warehouse">{{ warehouse }}</th><th><button class="sort-th" @click="toggleSort('stock_qty')">总库存 <ArrowUpDown :size="12"/>{{ mark('stock_qty') }}</button></th><th><button class="sort-th" @click="toggleSort('sales7')">7天销量 <ArrowUpDown :size="12"/>{{ mark('sales7') }}</button></th><th><button class="sort-th" @click="toggleSort('sales14')">14天销量 <ArrowUpDown :size="12"/>{{ mark('sales14') }}</button></th><th><button class="sort-th" @click="toggleSort('sales30')">30天销量 <ArrowUpDown :size="12"/>{{ mark('sales30') }}</button></th><th><button class="sort-th" @click="toggleSort('predicted_daily')">预计日销 <ArrowUpDown :size="12"/>{{ mark('predicted_daily') }}</button></th><th><button class="sort-th" @click="toggleSort('cover_days','asc')">预计周转 <ArrowUpDown :size="12"/>{{ mark('cover_days') }}</button></th><th><button class="sort-th" @click="toggleSort('weighted_aging_days')">加权库龄 <ArrowUpDown :size="12"/>{{ mark('weighted_aging_days') }}</button></th></tr></thead>
          <tbody>
            <tr v-for="r in rows" :key="r.product_id">
              <td><RouterLink class="table-product-link" :to="{path:'/product',query:{sku:r.sku}}">{{ r.name }}</RouterLink></td>
              <td>{{ r.sku }}</td><td><span :class="['stock-category-tag',`stock-${r.category}`]">{{ r.category_label }}</span></td><td v-for="warehouse in warehouseColumns" :key="warehouse">{{ n(r.warehouse_stocks?.[warehouse]) }}</td>
              <td>{{ n(r.stock_qty) }}</td><td>{{ n(r.sales7) }}</td><td>{{ n(r.sales14) }}</td><td>{{ n(r.sales30) }}</td><td>{{ n(r.predicted_daily,2) }}</td><td>{{ cover(r.cover_days) }}</td><td>{{ r.weighted_aging_days==null?'—':`${n(r.weighted_aging_days,1)}天` }}</td>
            </tr>
            <tr v-if="!rows.length"><td :colspan="10+warehouseColumns.length" class="table-empty">当前筛选条件下没有库存商品。</td></tr>
          </tbody>
        </table>
      </section>
    </template>
  </div>
</template>
