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
const detailProductCategories = ref(false)
const exporting = ref(false)
const exportError = ref('')
const lastExportCount = ref(null)
const currentPage = ref(1)
const pageSize = ref(50)
let timer = null
let serial = 0

const days = computed(() => Number(String(f.dateRange).replace('d','')) || 30)
const cats = computed(() => data.value?.categories || {})
const sort=ref({key:'stock_qty',dir:'desc'})
const sortedRows = computed(() => sortRows(data.value?.rows || [],sort.value))
const totalPages = computed(() => Math.max(1, Math.ceil(sortedRows.value.length / pageSize.value)))
const rows = computed(() => {
  const page = Math.min(currentPage.value, totalPages.value)
  const start = (page - 1) * pageSize.value
  return sortedRows.value.slice(start, start + pageSize.value)
})
const meta = computed(() => data.value?.meta || {})
const warehouseColumns = computed(() => meta.value.warehouse_columns || [])
const cards = [
  ['healthy','健康库存'],['high','高库存'],['stagnant','呆滞库存'],['no_sales','无销量库存'],['stockout','缺货动销']
]

function n(v,d=0){return Number(v||0).toLocaleString('zh-CN',{maximumFractionDigits:d})}
function cover(v){return v==null?'—':`${Number(v).toFixed(1)}天`}
function sortRows(rows,s){const dir=s.dir==='asc'?1:-1;return [...rows].sort((a,b)=>{const av=a[s.key],bv=b[s.key];if(av==null&&bv==null)return 0;if(av==null)return 1;if(bv==null)return -1;const an=Number(av),bn=Number(bv);return Number.isFinite(an)&&Number.isFinite(bn)?(an-bn)*dir:String(av).localeCompare(String(bv),'zh-CN')*dir})}
function toggleSort(key,defaultDir='desc'){sort.value=sort.value.key===key?{key,dir:sort.value.dir==='asc'?'desc':'asc'}:{key,dir:defaultDir};currentPage.value=1}
function mark(key){return sort.value.key===key?(sort.value.dir==='asc'?'↑':'↓'):''}
function goPage(page){currentPage.value=Math.max(1,Math.min(totalPages.value,page))}

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
      productCategoryIds:f.productCategoryIds,
      detailWarehouses:detailWarehouses.value,detailProductCategories:detailProductCategories.value,
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
      detailProductCategories:detailProductCategories.value,
    })
    lastExportCount.value=r.rowCount
  }catch(e){exportError.value=e.message}
  finally{exporting.value=false}
}
watch(()=>[f.dateRange,JSON.stringify(f.shops),JSON.stringify(f.warehouses),JSON.stringify(f.productCategoryIds),f.productSearch,f.includeName,f.excludeName,JSON.stringify(f.productCodes),detailWarehouses.value,detailProductCategories.value],schedule)
watch(()=>[JSON.stringify(f.shops),JSON.stringify(f.warehouses),JSON.stringify(f.productCategoryIds),f.productSearch,f.includeName,f.excludeName,JSON.stringify(f.productCodes),detailWarehouses.value,detailProductCategories.value],()=>{currentPage.value=1})
watch(pageSize,()=>{currentPage.value=1})
watch(()=>data.value?.rows?.length,()=>{currentPage.value=1})
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
          <span v-if="key==='stockout'">近30天销量 {{ n(cats[key]?.sales30_qty) }} · 点击进入商品分析</span>
          <span v-else>库存 {{ n(cats[key]?.stock_qty) }} · 点击进入商品分析</span>
        </RouterLink>
      </section>

      <section class="panel inventory-rule-note">
        <b>当前分类默认口径</b>
        <span>高库存：预计周转 &gt; {{ meta.thresholds?.high_cover_days }}天；呆滞：加权库龄 ≥ {{ meta.thresholds?.stagnant_aging_days }}天或预计周转 &gt; {{ meta.thresholds?.stagnant_cover_days }}天；无销量库存优先单独分类。</span>
        <small>{{ meta.classification_rule_status }}</small>
      </section>

      <section class="panel table-wrap">
        <div class="section-head"><div><h3>全部库存商品</h3><span>当前 {{ n(data.totals?.sku_count) }} 个 SKU</span></div><div class="inventory-table-actions"><label class="inventory-detail-toggle"><input v-model="detailProductCategories" type="checkbox" />商品分类</label><label class="inventory-detail-toggle"><input v-model="detailWarehouses" type="checkbox" /><Warehouse :size="14" />细分仓库</label><button class="rank-tab" :disabled="exporting" @click="downloadFiltered"><Download :size="14" /> {{ exporting?'正在生成…':`下载当前筛选结果${lastExportCount!=null?'（'+lastExportCount+'条）':''}` }}</button></div></div>
        <div v-if="exportError" class="api-error compact"><span>{{ exportError }}</span></div>
        <table class="inventory-table">
          <thead><tr><th>商品</th><th>商家编码</th><th v-if="detailProductCategories">商品分类</th><th>分类</th><th v-for="warehouse in warehouseColumns" :key="warehouse">{{ warehouse }}</th><th><button class="sort-th" @click="toggleSort('stock_qty')">总库存 <ArrowUpDown :size="12"/>{{ mark('stock_qty') }}</button></th><th><button class="sort-th" @click="toggleSort('sales7')">7天销量 <ArrowUpDown :size="12"/>{{ mark('sales7') }}</button></th><th><button class="sort-th" @click="toggleSort('sales14')">14天销量 <ArrowUpDown :size="12"/>{{ mark('sales14') }}</button></th><th><button class="sort-th" @click="toggleSort('sales30')">30天销量 <ArrowUpDown :size="12"/>{{ mark('sales30') }}</button></th><th><button class="sort-th" @click="toggleSort('predicted_daily')">预计日销 <ArrowUpDown :size="12"/>{{ mark('predicted_daily') }}</button></th><th><button class="sort-th" @click="toggleSort('cover_days','asc')">预计周转 <ArrowUpDown :size="12"/>{{ mark('cover_days') }}</button></th><th><button class="sort-th" @click="toggleSort('weighted_aging_days')">加权库龄 <ArrowUpDown :size="12"/>{{ mark('weighted_aging_days') }}</button></th></tr></thead>
          <tbody>
            <tr v-for="r in rows" :key="r.product_id">
              <td><RouterLink class="table-product-link" :to="{path:'/product',query:{sku:r.sku}}">{{ r.name }}</RouterLink></td>
              <td>{{ r.sku }}</td><td v-if="detailProductCategories">{{ r.product_category_names || '—' }}</td><td><span :class="['stock-category-tag',`stock-${r.category}`]">{{ r.category_label }}</span></td><td v-for="warehouse in warehouseColumns" :key="warehouse">{{ n(r.warehouse_stocks?.[warehouse]) }}</td>
              <td>{{ n(r.stock_qty) }}</td><td>{{ n(r.sales7) }}</td><td>{{ n(r.sales14) }}</td><td>{{ n(r.sales30) }}</td><td>{{ n(r.predicted_daily,2) }}</td><td>{{ cover(r.cover_days) }}</td><td>{{ r.weighted_aging_days==null?'—':`${n(r.weighted_aging_days,1)}天` }}</td>
            </tr>
            <tr v-if="!rows.length"><td :colspan="10+warehouseColumns.length+(detailProductCategories?1:0)" class="table-empty">当前筛选条件下没有库存商品。</td></tr>
          </tbody>
        </table>
        <div v-if="sortedRows.length" class="table-pagination">
          <span>共 {{ n(sortedRows.length) }} 条，第 {{ Math.min(currentPage,totalPages) }} / {{ totalPages }} 页</span>
          <label>每页<select v-model.number="pageSize"><option :value="50">50</option><option :value="100">100</option></select>条</label>
          <button class="pagination-button" :disabled="currentPage<=1" @click="goPage(currentPage-1)">上一页</button>
          <button v-for="page in Math.min(totalPages,7)" :key="page" :class="['pagination-button',{active:page===currentPage}]" @click="goPage(page)">{{ page }}</button>
          <button class="pagination-button" :disabled="currentPage>=totalPages" @click="goPage(currentPage+1)">下一页</button>
        </div>
      </section>
    </template>
  </div>
</template>
