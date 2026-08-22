<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import * as echarts from 'echarts'
import {
  ArrowUpDown, Boxes, CalendarDays, ChevronRight, ClipboardPlus, History,
  ListFilter, PackageSearch, RotateCcw, Search, SlidersHorizontal, Sparkles,
  Store, TrendingDown, TrendingUp, Warehouse
} from 'lucide-vue-next'
import { useFilterStore } from '../stores/filter'
import {
  fetchExpiryBatches, fetchInventoryAnalysis, fetchProductDetail, saveProductNote, searchProducts
} from '../api/analysis'

const route=useRoute(),router=useRouter(),f=useFilterStore()
const data=ref(null),error=ref(''),loading=ref(false),note=ref(''),noteState=ref('')
const listRows=ref([]),listTitle=ref('')
const chartEl=ref(null),shopChartEl=ref(null);let chart=null,shopChart=null,serial=0,searchTimer=null
const searchText=ref(''),searchRows=ref([]),searchLoading=ref(false),searchOpen=ref(false),searchError=ref('')
const shopSort=ref({key:'sales30',dir:'desc'}),expirySort=ref({key:'remaining_days',dir:'asc'})
const sku=computed(()=>String(route.query.sku||'').trim())
const stockCategory=computed(()=>String(route.query.stock_category||'').trim())
const expiryStatus=computed(()=>String(route.query.expiry_status||'').trim())
const listMode=computed(()=>!sku.value && (!!stockCategory.value || !!expiryStatus.value))
const priceVisible=computed(()=>data.value?.meta?.price_visible===true)
const stockLabels={healthy:'健康库存',high:'高库存',stagnant:'呆滞库存',no_sales:'无销量库存'}
const sortedShopSales=computed(()=>sortRows(data.value?.shop_sales||[],shopSort.value))
const sortedExpiry=computed(()=>sortRows(data.value?.expiry_batches||[],expirySort.value))
const selectedProductLabel=computed(()=>data.value?`${data.value.product.name} · ${data.value.product.sku}`:'')
const shopContext=computed(()=>!f.shops.length?'全部店铺':f.shops.length<=2?f.shops.join('、'):`${f.shops.slice(0,2).join('、')} 等 ${f.shops.length} 个`)
const warehouseContext=computed(()=>!f.warehouses.length?'全部仓库':f.warehouses.length<=2?f.warehouses.join('、'):`${f.warehouses.slice(0,2).join('、')} 等 ${f.warehouses.length} 个`)
const sourceContext=computed(()=>stockCategory.value?`库存分类：${stockLabels[stockCategory.value]||stockCategory.value}`:expiryStatus.value?`效期状态：${expiryStatus.value}`:'')

function n(v,d=0){return Number(v||0).toLocaleString('zh-CN',{maximumFractionDigits:d})}
function money(v){return Number(v||0).toLocaleString('zh-CN',{style:'currency',currency:'CNY',maximumFractionDigits:2})}
function statusClass(s){return {'正常':'expiry-normal','预警':'expiry-warn','临期':'expiry-near','过期':'expiry-expired'}[s]||''}
function cover(v){return v==null?'—':`${Number(v).toFixed(1)}天`}
function taskStatus(s){return ({running:'进行中',pending_delete:'删除待审批',done:'已完成',delete_rejected:'删除被驳回'})[s]||s}
function sortRows(rows,sort){const dir=sort.dir==='asc'?1:-1;return [...rows].sort((a,b)=>{const av=a[sort.key],bv=b[sort.key];if(av==null&&bv==null)return 0;if(av==null)return 1;if(bv==null)return -1;const an=Number(av),bn=Number(bv);if(Number.isFinite(an)&&Number.isFinite(bn))return (an-bn)*dir;return String(av).localeCompare(String(bv),'zh-CN')*dir})}
function toggleSort(target,key,defaultDir='desc'){const current=target?.value??target;if(!current)return;const next=current.key===key?{key,dir:current.dir==='asc'?'desc':'asc'}:{key,dir:defaultDir};if(target&&Object.prototype.hasOwnProperty.call(target,'value'))target.value=next;else Object.assign(target,next)}
function sortMark(target,key){const current=target?.value??target;return current?.key===key?(current.dir==='asc'?'↑':'↓'):''}
function compareText(x){if(!x?.available)return '历史不足';if(x.change_pct==null)return '无法计算';const v=Number(x.change_pct);return `${v>0?'+':''}${v.toFixed(1)}%`}
function compareClass(x){if(!x?.available||x.change_pct==null)return 'neutral';return Number(x.change_pct)>0?'positive':Number(x.change_pct)<0?'negative':'neutral'}
function compareIcon(x){if(!x?.available||x.change_pct==null)return History;return Number(x.change_pct)>=0?TrendingUp:TrendingDown}
function markCustomContext(){f.activePreset='自定义';f.activePresetId=null}
function clearShopFilter(){if(!f.shops.length)return;f.shops=[];markCustomContext()}
function clearWarehouseFilter(){if(!f.warehouses.length)return;f.warehouses=[];markCustomContext()}
function clearCategory(){const q={...route.query};delete q.stock_category;delete q.expiry_status;router.replace({path:'/product',query:q})}
function resetDrillContext(){f.shops=[];f.warehouses=[];markCustomContext();clearCategory()}

async function runSearch(value=searchText.value){
  const q=String(value||'').trim();searchError.value=''
  if(!q){searchRows.value=[];searchOpen.value=false;return}
  searchLoading.value=true
  try{const r=await searchProducts(q,{limit:20});searchRows.value=r.rows||[];searchOpen.value=true}
  catch(e){searchRows.value=[];searchOpen.value=true;searchError.value=e.message}
  finally{searchLoading.value=false}
}
function scheduleSearch(){clearTimeout(searchTimer);searchTimer=setTimeout(()=>runSearch(),180)}
function selectProduct(row){searchText.value='';searchRows.value=[];searchOpen.value=false;router.push({path:'/product',query:{sku:row.sku,stock_category:stockCategory.value||undefined,expiry_status:expiryStatus.value||undefined}})}
async function searchEnter(){if(searchRows.value.length){selectProduct(searchRows.value[0]);return}await runSearch();if(searchRows.value.length)selectProduct(searchRows.value[0])}

async function loadCategoryList(id){
  if(stockCategory.value){
    const r=await fetchInventoryAnalysis({days:30,shops:f.shops,warehouses:f.warehouses,productSearch:f.productSearch,includeName:f.includeName,excludeName:f.excludeName,productCodes:f.productCodes,category:stockCategory.value})
    if(id!==serial)return
    listTitle.value=stockLabels[stockCategory.value]||'库存分类'
    listRows.value=(r.rows||[]).map(x=>({sku:x.sku,name:x.name,stock:x.stock_qty,sales30:x.sales30,metric:x.cover_days==null?'—':`${Number(x.cover_days).toFixed(1)}天`,metricLabel:'预计周转'}));return
  }
  if(expiryStatus.value){
    const r=await fetchExpiryBatches({warehouses:f.warehouses,productSearch:f.productSearch,includeName:f.includeName,excludeName:f.excludeName,productCodes:f.productCodes,statuses:[expiryStatus.value],limit:5000})
    if(id!==serial)return
    const bySku=new Map()
    for(const x of r.rows||[]){const old=bySku.get(x.sku);if(!old)bySku.set(x.sku,{sku:x.sku,name:x.name,stock:Number(x.stock_qty||0),sales30:null,pct:x.remaining_pct});else{old.stock+=Number(x.stock_qty||0);if(x.remaining_pct!=null)old.pct=old.pct==null?x.remaining_pct:Math.min(old.pct,x.remaining_pct)}}
    listTitle.value=`效期状态：${expiryStatus.value}`
    listRows.value=[...bySku.values()].map(x=>({...x,metric:x.pct==null?'—':`${Number(x.pct).toFixed(1)}%`,metricLabel:'最低剩余效期'}))
  }
}

async function load(){
  const id=++serial;loading.value=true;error.value='';data.value=null;listRows.value=[]
  try{
    if(listMode.value){await loadCategoryList(id);return}
    if(!sku.value)return
    const r=await fetchProductDetail(sku.value,{shops:f.shops,warehouses:f.warehouses,days:f.dateParams.days,startDate:f.dateParams.startDate,endDate:f.dateParams.endDate})
    if(id!==serial)return
    data.value=r;note.value=r.personal_note?.note||'';noteState.value=r.personal_note?.updated_at?'已读取已保存备注':'暂无备注'
    await nextTick();renderCharts()
  }catch(e){if(id===serial){error.value=`商品分析读取失败：${e.message}`;data.value=null;listRows.value=[];renderCharts()}}
  finally{if(id===serial)loading.value=false}
}
async function saveNote(){if(!sku.value)return;noteState.value='保存中…';try{await saveProductNote(sku.value,note.value);noteState.value='已保存'}catch(e){noteState.value=`保存失败：${e.message}`}}
function renderCharts(){
  if(chartEl.value){
    if(!chart)chart=echarts.init(chartEl.value)
    const trend=data.value?.trend||[]
    const series=[{name:'销量',type:'line',smooth:.3,symbol:'circle',symbolSize:7,data:trend.map(x=>Number(x.sales_qty||0)),areaStyle:{opacity:.08},lineStyle:{width:3}}]
    if(priceVisible.value)series.push({name:'均价',type:'line',yAxisIndex:1,smooth:.24,symbol:'circle',symbolSize:5,data:trend.map(x=>x.avg_price==null?null:Number(x.avg_price)),lineStyle:{width:2,type:'dashed'}})
    chart.setOption({tooltip:{trigger:'axis',backgroundColor:'rgba(20,28,50,.94)',borderWidth:0,textStyle:{color:'#fff'},formatter(ps){const i=ps?.[0]?.dataIndex||0,row=trend[i]||{};const parts=[row.date||'',`销量：${n(row.sales_qty)}`];if(priceVisible.value&&row.avg_price!=null)parts.push(`均价：${money(row.avg_price)}`);return parts.join('<br>')}},legend:{show:priceVisible.value,right:8},grid:{left:54,right:priceVisible.value?64:28,top:38,bottom:38},xAxis:{type:'category',boundaryGap:false,data:trend.map(x=>x.date.slice(5)),axisLabel:{interval:Math.max(0,Math.floor(trend.length/8)-1)}},yAxis:[{type:'value',name:'销量'},{type:'value',name:'均价',show:priceVisible.value,splitLine:{show:false}}],series},true)
  }
  if(shopChartEl.value){
    if(!shopChart)shopChart=echarts.init(shopChartEl.value)
    const rows=[...(data.value?.shop_sales||[])].sort((a,b)=>Number(b.sales30||0)-Number(a.sales30||0)).slice(0,12).reverse()
    shopChart.setOption({tooltip:{trigger:'axis',axisPointer:{type:'shadow'},backgroundColor:'rgba(20,28,50,.94)',borderWidth:0,textStyle:{color:'#fff'},formatter(ps){const i=ps?.[0]?.dataIndex||0,row=rows[i]||{};return `${row.shop||''}<br>7天：${n(row.sales7)}<br>14天：${n(row.sales14)}<br>30天：${n(row.sales30)}<br>30天占比：${n(row.share30_pct,1)}%`}},grid:{left:138,right:36,top:12,bottom:28},xAxis:{type:'value',name:'30天销量'},yAxis:{type:'category',data:rows.map(x=>x.shop),axisLabel:{width:122,overflow:'truncate'}},series:[{type:'bar',data:rows.map(x=>Number(x.sales30||0)),barMaxWidth:18,label:{show:true,position:'right',fontSize:12},itemStyle:{borderRadius:[0,6,6,0]}}]},true)
  }
}
function onResize(){chart?.resize();shopChart?.resize()}
watch(searchText,scheduleSearch)
watch(()=>[sku.value,stockCategory.value,expiryStatus.value],load)
watch(()=>[f.dateRange,f.customStart,f.customEnd,JSON.stringify(f.shops),JSON.stringify(f.warehouses)],load)
onMounted(()=>{window.addEventListener('resize',onResize);load()})
onBeforeUnmount(()=>{clearTimeout(searchTimer);window.removeEventListener('resize',onResize);chart?.dispose();shopChart?.dispose();chart=null;shopChart=null})
</script>

<template>
  <div class="page product-view-v154" @click="searchOpen=false">
    <div class="product-command-head">
      <div class="product-command-title">
        <div class="product-command-icon"><PackageSearch :size="22"/></div>
        <div><h1>商品分析</h1><p>商品定位、销售趋势、同比环比、店铺贡献、仓库库存与效期风险</p></div>
      </div>
      <button v-if="sku" class="ui-btn ui-btn-primary" @click.stop="router.push({path:'/todo',query:{create:'1',sku,shop:f.shops.length===1?f.shops[0]:'',warehouse:f.warehouses.length===1?f.warehouses[0]:''}})"><ClipboardPlus :size="16"/>生成待办</button>
    </div>

    <section class="product-search-shell" @click.stop>
      <div class="product-search-leading"><Search :size="20"/></div>
      <input v-model="searchText" autocomplete="off" placeholder="输入商家编码、商品名称或历史商品名，直接搜索…" @focus="searchText&&runSearch()" @keyup.enter="searchEnter"/>
      <div v-if="searchLoading" class="product-search-state">搜索中…</div>
      <div v-else-if="selectedProductLabel&&!searchText" class="product-search-selected">当前：{{ selectedProductLabel }}</div>
      <div v-if="searchOpen" class="product-search-results">
        <div v-if="searchError" class="product-search-empty">{{ searchError }}</div>
        <button v-for="row in searchRows" :key="row.sku" class="product-search-result" @click="selectProduct(row)">
          <span class="product-result-icon"><Boxes :size="17"/></span>
          <span class="product-result-main"><b>{{ row.name }}</b><small>{{ row.sku }}<template v-if="row.spec"> · {{ row.spec }}</template></small><em v-if="row.matched_aliases">曾用名：{{ row.matched_aliases }}</em></span>
          <ChevronRight :size="17"/>
        </button>
        <div v-if="!searchLoading&&!searchError&&!searchRows.length" class="product-search-empty">没有找到匹配商品</div>
      </div>
    </section>

    <section class="drill-context-panel">
      <div class="drill-context-title"><SlidersHorizontal :size="16"/><div><b>当前分析口径</b><span>下钻后完整保留筛选上下文，可在这里快速恢复全部店铺/仓库</span></div></div>
      <div class="drill-context-chips">
        <span class="context-chip"><CalendarDays :size="14"/>{{ f.dateLabel }}</span>
        <span :class="['context-chip',{active:f.shops.length}]"><Store :size="14"/>{{ shopContext }}</span>
        <span :class="['context-chip',{active:f.warehouses.length}]"><Warehouse :size="14"/>{{ warehouseContext }}</span>
        <span v-if="sourceContext" class="context-chip source"><ListFilter :size="14"/>{{ sourceContext }}</span>
      </div>
      <div class="drill-context-actions">
        <button class="ui-btn ui-btn-ghost" :disabled="!f.shops.length" @click="clearShopFilter"><Store :size="14"/>全部店铺</button>
        <button class="ui-btn ui-btn-ghost" :disabled="!f.warehouses.length" @click="clearWarehouseFilter"><Warehouse :size="14"/>全部仓库</button>
        <button v-if="sourceContext" class="ui-btn ui-btn-ghost" @click="clearCategory"><ListFilter :size="14"/>清除下钻分类</button>
        <button v-if="f.shops.length||f.warehouses.length||sourceContext" class="ui-btn ui-btn-soft" @click="resetDrillContext"><RotateCcw :size="14"/>重置下钻</button>
      </div>
    </section>

    <section v-if="listMode" class="panel product-list-mode product-list-v154">
      <div class="section-head"><div><h3>{{ listTitle }}</h3><span>当前口径下 {{ listRows.length }} 个商品 · 点击商品继续下钻</span></div></div>
      <div class="rank-list">
        <div v-for="(r,i) in listRows" :key="r.sku" class="rank-row product-category-row"><b class="rank-num">{{ String(i+1).padStart(2,'0') }}</b><div class="rank-product"><RouterLink class="table-product-link" :to="{path:'/product',query:{sku:r.sku,stock_category:stockCategory||undefined,expiry_status:expiryStatus||undefined}}">{{ r.name }}</RouterLink><small>{{ r.sku }}</small></div><div><small>库存</small><b>{{ n(r.stock) }}</b></div><div><small v-if="r.sales30!=null">30天销量</small><b v-if="r.sales30!=null">{{ n(r.sales30) }}</b></div><div><small>{{ r.metricLabel }}</small><b>{{ r.metric }}</b></div></div>
        <div v-if="!listRows.length" class="rank-empty">当前分类和筛选条件下没有商品。</div>
      </div>
    </section>

    <section v-else-if="!sku" class="product-welcome-panel">
      <div class="product-welcome-icon"><Sparkles :size="24"/></div><h2>搜索一个商品开始分析</h2><p>可直接输入商家编码、当前商品名称或历史商品名称；也可以从经营总览、库存分析、效期中心点击商品下钻。</p>
    </section>
    <div v-if="error" class="api-error"><b>商品接口暂不可用</b><span>{{ error }}</span><button class="ui-btn ui-btn-ghost" @click="load">重新读取</button></div>
    <div v-else-if="loading && !data && !listMode && sku" class="dashboard-loading">正在读取商品分析…</div>

    <template v-if="data">
      <section class="product-hero-v154">
        <div class="product-identity"><small>当前商品</small><h2>{{ data.product.name }}</h2><p>{{ data.product.sku }}<template v-if="data.product.spec"> · {{ data.product.spec }}</template><template v-if="data.product.brand"> · {{ data.product.brand }}</template></p><div class="product-tags"><span>{{ data.product.inventory_category_label }}</span><span :class="statusClass(data.product.expiry_status)">{{ data.product.expiry_status }}</span><span>{{ data.meta?.department?.name }}</span></div></div>
        <div class="hero-data-date"><span>销量截至 <b>{{ data.meta.latest_sales_date||'—' }}</b></span><span>分析区间 <b>{{ data.meta.selected_start_date||'—' }} → {{ data.meta.selected_end_date||'—' }}</b></span><span>库存快照 <b>{{ data.meta.latest_inventory_date||'—' }}</b></span></div>
      </section>

      <section class="comparison-grid-v154">
        <article class="comparison-card current"><div class="comparison-card-head"><span>当前区间销量</span><CalendarDays :size="17"/></div><b>{{ n(data.comparison?.current?.sales) }}</b><small>{{ data.comparison?.current?.start_date }} → {{ data.comparison?.current?.end_date }}</small></article>
        <article :class="['comparison-card',compareClass(data.comparison?.mom)]"><div class="comparison-card-head"><span>环比 · 上一等长区间</span><component :is="compareIcon(data.comparison?.mom)" :size="17"/></div><b>{{ compareText(data.comparison?.mom) }}</b><small v-if="data.comparison?.mom?.available">上期销量 {{ n(data.comparison.mom.sales) }} · {{ data.comparison.mom.start_date }} → {{ data.comparison.mom.end_date }}</small><small v-else>需要更早的销售历史，当前不伪造环比</small></article>
        <article :class="['comparison-card',compareClass(data.comparison?.yoy)]"><div class="comparison-card-head"><span>同比 · 去年同期</span><component :is="compareIcon(data.comparison?.yoy)" :size="17"/></div><b>{{ compareText(data.comparison?.yoy) }}</b><small v-if="data.comparison?.yoy?.available">同期销量 {{ n(data.comparison.yoy.sales) }} · {{ data.comparison.yoy.start_date }} → {{ data.comparison.yoy.end_date }}</small><small v-else>缺少去年同期数据，显示历史不足</small></article>
      </section>

      <section class="product-kpis-real product-kpis-v154">
        <article><span>7天销量</span><b>{{ n(data.sales.sales7) }}</b></article><article><span>14天销量</span><b>{{ n(data.sales.sales14) }}</b></article><article><span>30天销量</span><b>{{ n(data.sales.sales30) }}</b></article>
        <article v-if="priceVisible"><span>7天均价</span><b>{{ money(data.sales.avg_price7) }}</b></article><article v-if="priceVisible"><span>14天均价</span><b>{{ money(data.sales.avg_price14) }}</b></article><article v-if="priceVisible"><span>30天均价</span><b>{{ money(data.sales.avg_price30) }}</b></article>
        <article><span>当前库存</span><b>{{ n(data.inventory.stock_qty) }}</b></article><article><span>预计日销</span><b>{{ n(data.inventory.predicted_daily,2) }}</b></article><article><span>预计可售</span><b>{{ cover(data.inventory.cover_days) }}</b></article><article><span>最低剩余效期</span><b>{{ data.product.lowest_remaining_pct==null?'—':`${n(data.product.lowest_remaining_pct,1)}%` }}</b></article>
      </section>

      <section class="data-scope-bar"><span>{{ priceVisible?'单店铺：趋势显示销量 + 加权均价':'全部/多店铺：趋势只显示销量' }}</span><span>{{ data.meta.inventory_dimension_note }}</span></section>

      <section class="product-grid-real product-grid-v154">
        <article class="panel"><div class="section-head"><div><h3>{{ f.dateLabel }}销售趋势</h3><span>鼠标悬停查看每日销量{{ priceVisible?'与加权均价':'' }}</span></div></div><div ref="chartEl" class="product-chart-real"></div></article>
        <article class="panel"><div class="section-head"><div><h3>各仓库存</h3><span>最新库存快照 · 不按店铺拆分</span></div><b>{{ n(data.inventory.stock_qty) }}</b></div><div class="warehouse-stock-list"><div v-for="w in data.inventory.warehouses" :key="w.warehouse" class="warehouse-stock-row"><span>{{ w.warehouse }}</span><div class="warehouse-stock-track"><i :style="{width:`${data.inventory.stock_qty?Math.max(3,w.stock_qty/data.inventory.stock_qty*100):0}%`}"></i></div><b>{{ n(w.stock_qty) }}</b></div><div v-if="!data.inventory.warehouses.length" class="table-empty">暂无库存</div></div></article>
      </section>

      <section class="panel shop-sales-panel shop-sales-v154">
        <div class="section-head"><div><h3>各店铺销量贡献</h3><span>同一商品按店铺拆分销售贡献；库存不伪造店铺维度</span></div><b>{{ data.shop_sales?.length||0 }} 个店铺</b></div>
        <div class="shop-sales-layout"><div ref="shopChartEl" class="shop-sales-chart"></div><div class="table-wrap shop-sales-table-wrap"><table class="sortable-table"><thead><tr><th>店铺</th><th><button @click="toggleSort(shopSort,'sales7')">7天销量 <ArrowUpDown :size="12"/>{{ sortMark(shopSort,'sales7') }}</button></th><th><button @click="toggleSort(shopSort,'sales14')">14天销量 <ArrowUpDown :size="12"/>{{ sortMark(shopSort,'sales14') }}</button></th><th><button @click="toggleSort(shopSort,'sales30')">30天销量 <ArrowUpDown :size="12"/>{{ sortMark(shopSort,'sales30') }}</button></th><th><button @click="toggleSort(shopSort,'share30_pct')">30天占比 <ArrowUpDown :size="12"/>{{ sortMark(shopSort,'share30_pct') }}</button></th></tr></thead><tbody><tr v-for="r in sortedShopSales" :key="r.shop"><td><b>{{ r.shop }}</b></td><td>{{ n(r.sales7) }}</td><td>{{ n(r.sales14) }}</td><td><b>{{ n(r.sales30) }}</b></td><td>{{ n(r.share30_pct,1) }}%</td></tr><tr v-if="!sortedShopSales.length"><td colspan="5" class="table-empty">该商品当前没有店铺销量。</td></tr></tbody></table></div></div>
      </section>

      <section class="panel table-wrap expiry-table-v154">
        <div class="section-head"><div><h3>效期批次</h3><span>最低剩余效期 {{ data.product.lowest_remaining_pct==null?'—':`${n(data.product.lowest_remaining_pct,1)}%` }}</span></div><RouterLink class="ui-btn ui-btn-ghost" :to="{path:'/expiry',query:{sku:data.product.sku}}">进入效期中心 <ChevronRight :size="14"/></RouterLink></div>
        <table class="sortable-table"><thead><tr><th>仓库</th><th><button @click="toggleSort(expirySort,'stock_qty')">库存 <ArrowUpDown :size="12"/>{{ sortMark(expirySort,'stock_qty') }}</button></th><th>生产日期</th><th>过期日期</th><th><button @click="toggleSort(expirySort,'total_shelf_days')">总有效期 <ArrowUpDown :size="12"/>{{ sortMark(expirySort,'total_shelf_days') }}</button></th><th><button @click="toggleSort(expirySort,'remaining_days','asc')">剩余天数 <ArrowUpDown :size="12"/>{{ sortMark(expirySort,'remaining_days') }}</button></th><th><button @click="toggleSort(expirySort,'remaining_pct','asc')">剩余效期% <ArrowUpDown :size="12"/>{{ sortMark(expirySort,'remaining_pct') }}</button></th><th>状态</th></tr></thead><tbody>
          <tr v-for="b in sortedExpiry" :key="b.batch_id"><td>{{ b.warehouse }}</td><td>{{ n(b.stock_qty) }}</td><td>{{ b.production_date||'—' }}</td><td>{{ b.expire_date||'—' }}</td><td>{{ b.total_shelf_days==null?'—':`${b.total_shelf_days}天` }}</td><td>{{ b.remaining_days==null?'—':`${b.remaining_days}天` }}</td><td>{{ b.remaining_pct==null?'—':`${n(b.remaining_pct,1)}%` }}</td><td><span :class="['expiry-status-tag',statusClass(b.status)]">{{ b.status }}</span></td></tr>
          <tr v-if="!sortedExpiry.length"><td colspan="8" class="table-empty">暂无效期批次。</td></tr>
        </tbody></table>
      </section>

      <section class="product-bottom-grid"><article class="panel"><div class="section-head"><div><h3>我的商品备注</h3><span>按当前登录用户隔离</span></div></div><textarea v-model="note" class="product-note-area" @input="noteState='有未保存修改'" placeholder="记录跟进情况、运营观察、补货判断……"></textarea><div class="note-actions"><span>{{ noteState }}</span><button class="ui-btn ui-btn-primary" @click="saveNote">保存备注</button></div></article><article class="panel"><div class="section-head"><div><h3>关联待办</h3><span>{{ data.tasks.length }} 项</span></div></div><div class="related-task-list"><div v-for="t in data.tasks" :key="t.task_no" class="related-task"><b>{{ t.task_no }} · {{ t.owner_name }}</b><span>目标 {{ t.target_qty==null?'未设置':n(t.target_qty) }} · 分配 {{ t.assign_date }} · 开始 {{ t.start_date }}</span><small>{{ taskStatus(t.status) }} · {{ t.manager_note||'无管理员任务要求' }}</small></div><div v-if="!data.tasks.length" class="table-empty">暂无当前权限可见的关联待办。</div></div></article></section>
    </template>
  </div>
</template>
