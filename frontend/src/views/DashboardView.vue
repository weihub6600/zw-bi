<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts'
import FilterBar from '../components/FilterBar.vue'
import { useFilterStore } from '../stores/filter'
import { fetchDashboardData, fetchDashboardOptions } from '../api/dashboard'
import { fetchInventoryAnalysis } from '../api/analysis'

const f = useFilterStore()
const loading = ref(false)
const optionsLoading = ref(false)
const error = ref('')
const data = ref(null)
const inventoryData = ref(null)
const shopOptions = ref([])
const warehouseOptions = ref([])
const productCategoryOptions = ref([])
const activeRank = ref('sales')
const chartEl = ref(null)
const structureChartEl = ref(null)
let chart = null
let structureChart = null
let timer = null
let requestSerial = 0

const days = computed(() => f.dateParams.days)
const showSalesAmount = computed(() => data.value?.meta?.sales_amount_visible === true)
const showPrice = computed(() => data.value?.meta?.price_visible === true)
const kpis = computed(() => data.value?.kpis || {})
const risks = computed(() => data.value?.risks || {})
const comparison = computed(() => data.value?.comparison || {})
const meta = computed(() => data.value?.meta || {})
const expiryCategories = computed(() => data.value?.expiry_categories || { 正常:0, 预警:0, 临期:0, 过期:0 })
const inventoryCategories = computed(() => inventoryData.value?.categories || {})

const rankTabs = computed(() => {
  const tabs = [
    { key:'sales', label:`销量TOP30` },
    { key:'shortage', label:'高动销低库存' },
    { key:'slow', label:'滞销/高库存' }
  ]
  if (showSalesAmount.value) tabs.splice(1,0,{ key:'sales_amount', label:'销售额TOP30' })
  return tabs
})

const rankRows = computed(() => data.value?.rankings?.[activeRank.value] || [])

function n(value, digits = 0) {
  const number = Number(value || 0)
  return number.toLocaleString('zh-CN', { maximumFractionDigits: digits, minimumFractionDigits: digits })
}
function money(value) {
  return Number(value || 0).toLocaleString('zh-CN', { style:'currency', currency:'CNY', maximumFractionDigits:2 })
}
function pct(value) {
  if (value === null || value === undefined) return '历史不足'
  const sign = value > 0 ? '+' : ''
  return `${sign}${Number(value).toFixed(2)}%`
}
function comparisonText(x){if(!x?.available)return '历史不足';if(x.change_pct==null)return '无法计算';const v=Number(x.change_pct);return `${v>0?'+':''}${v.toFixed(1)}%`}
function comparisonClass(x){if(!x?.available||x.change_pct==null)return 'neutral';return Number(x.change_pct)>0?'positive':Number(x.change_pct)<0?'negative':'neutral'}
function coverText(row) {
  if (row.risk_level === '无销量库存') return '无销量'
  return row.cover_days == null ? '—' : `${Number(row.cover_days).toFixed(1)}天`
}
function rankMetricLabel() {
  if (activeRank.value === 'sales_amount') return '销售额'
  if (activeRank.value === 'slow') return '预计周转'
  return '预计可售'
}
function rankMetricValue(row) {
  if (activeRank.value === 'sales_amount') return money(row.sales_amount)
  return coverText(row)
}

async function loadOptions() {
  optionsLoading.value = true
  try {
    const result = await fetchDashboardOptions({ departmentCode:f.departmentCode })
    shopOptions.value = result.shops || []
    warehouseOptions.value = result.warehouses || []
    productCategoryOptions.value = result.product_categories || []
  } catch (e) {
    error.value = `筛选项读取失败：${e.message}`
  } finally {
    optionsLoading.value = false
  }
}

async function loadDashboard() {
  const serial = ++requestSerial
  loading.value = true
  error.value = ''
  try {
    const result = await fetchDashboardData({
      departmentCode:f.departmentCode,
      days: days.value,
      startDate: f.dateParams.startDate,
      endDate: f.dateParams.endDate,
      shops: f.shops,
      warehouses: f.warehouses,
      productSearch: f.productSearch,
      includeName: f.includeName,
      excludeName: f.excludeName,
      productCodes: f.productCodes,
      productCategoryIds: f.productCategoryIds
    })
    if (serial !== requestSerial) return
    data.value = result
    try {
      inventoryData.value = await fetchInventoryAnalysis({
        departmentCode:f.departmentCode,
        days: 30,
        shops: f.shops,
        warehouses: f.warehouses,
        productSearch: f.productSearch,
        includeName: f.includeName,
        excludeName: f.excludeName,
        productCodes: f.productCodes,
        productCategoryIds: f.productCategoryIds
      })
    } catch {
      inventoryData.value = null
    }
    if (!rankTabs.value.some(x => x.key === activeRank.value)) activeRank.value = 'sales'
    await nextTick()
    renderChart()
  } catch (e) {
    if (serial !== requestSerial) return
    error.value = `经营总览读取失败：${e.message}`
    data.value = null
    renderChart()
  } finally {
    if (serial === requestSerial) loading.value = false
  }
}

function scheduleLoad() {
  clearTimeout(timer)
  timer = setTimeout(loadDashboard, 280)
}

function renderChart() {
  if (!chartEl.value) return
  if (!chart) chart = echarts.init(chartEl.value)
  const trend = data.value?.trend || []
  const dates = trend.map(x => x.date.slice(5))
  const sales = trend.map(x => Number(x.sales_qty || 0))
  const series = [{
    name:'销量', type:'line', smooth:.28, symbol:'circle', symbolSize:7,
    data:sales, areaStyle:{ opacity:.08 }, lineStyle:{ width:3 }
  }]
  if (showPrice.value) {
    series.push({
      name:'均价', type:'line', yAxisIndex:1, smooth:.22, symbol:'circle', symbolSize:6,
      data:trend.map(x => x.avg_price == null ? null : Number(x.avg_price)), lineStyle:{ width:2, type:'dashed' }
    })
  }
  chart.setOption({
    animationDuration:350,
    tooltip:{
      trigger:'axis',
      formatter(params) {
        const idx = params?.[0]?.dataIndex ?? 0
        const row = trend[idx] || {}
        const parts = [`${row.date || ''}`, `销量：${n(row.sales_qty,0)}`]
        if (showPrice.value && row.avg_price != null) parts.push(`均价：${money(row.avg_price)}`)
        return parts.join('<br>')
      }
    },
    legend:{ show:showPrice.value, top:0, right:8, textStyle:{ color:getComputedStyle(document.documentElement).getPropertyValue('--muted') } },
    grid:{ left:50, right:showPrice.value?58:24, top:showPrice.value?40:22, bottom:36 },
    xAxis:{ type:'category', boundaryGap:false, data:dates, axisLabel:{ color:'#8b96aa', interval:Math.max(0,Math.floor(dates.length/7)-1) }, axisLine:{ lineStyle:{ color:'#dce3ee' } } },
    yAxis:[
      { type:'value', name:'销量', axisLabel:{ color:'#8b96aa' }, splitLine:{ lineStyle:{ color:'rgba(128,140,165,.14)' } } },
      { type:'value', name:'均价', show:showPrice.value, axisLabel:{ color:'#8b96aa' }, splitLine:{ show:false } }
    ],
    series
  }, true)

  if (structureChartEl.value) {
    if (!structureChart) structureChart=echarts.init(structureChartEl.value)
    const inv=inventoryCategories.value||{}, exp=expiryCategories.value||{}
    const invData=[['健康',inv.healthy?.sku_count||0],['高库存',inv.high?.sku_count||0],['呆滞',inv.stagnant?.sku_count||0],['无销量',inv.no_sales?.sku_count||0]]
    const expData=[['正常',exp['正常']||0],['预警',exp['预警']||0],['临期',exp['临期']||0],['过期',exp['过期']||0]]
    structureChart.setOption({
      tooltip:{trigger:'item',formatter:'{b}<br>{c} 个商品 · {d}%'},
      title:[{text:'库存结构',left:'24%',top:4,textAlign:'center',textStyle:{fontSize:13,fontWeight:700}},{text:'效期结构',left:'75%',top:4,textAlign:'center',textStyle:{fontSize:13,fontWeight:700}}],
      series:[
        {type:'pie',radius:['48%','70%'],center:['25%','58%'],label:{fontSize:11,formatter:'{b}\n{c}'},itemStyle:{borderWidth:2,borderColor:'transparent'},data:invData.map(([name,value])=>({name,value}))},
        {type:'pie',radius:['48%','70%'],center:['75%','58%'],label:{fontSize:11,formatter:'{b}\n{c}'},itemStyle:{borderWidth:2,borderColor:'transparent'},data:expData.map(([name,value])=>({name,value}))}
      ]
    },true)
  }
}

function onResize() { chart?.resize(); structureChart?.resize() }

watch(
  () => [f.departmentCode, f.dateRange, f.customStart, f.customEnd, JSON.stringify(f.shops), JSON.stringify(f.warehouses), JSON.stringify(f.productCategoryIds), f.productSearch, f.includeName, f.excludeName, JSON.stringify(f.productCodes), f.activePreset],
  scheduleLoad
)
watch(() => showPrice.value, () => nextTick(renderChart))

onMounted(async () => {
  window.addEventListener('resize', onResize)
  await loadOptions()
  await loadDashboard()
})
onBeforeUnmount(() => {
  clearTimeout(timer)
  window.removeEventListener('resize', onResize)
  chart?.dispose()
  structureChart?.dispose()
  chart = null
  structureChart = null
})
</script>

<template>
  <div class="page">
    <div class="page-title">
      <h1>经营总览</h1>
      <p>销售、库存、补货、效期与待办风险一屏查看 · 数据来自 MySQL</p>
    </div>
    <FilterBar :shop-options="shopOptions" :warehouse-options="warehouseOptions" :product-category-options="productCategoryOptions" :loading-options="optionsLoading" />

    <div v-if="error" class="api-error">
      <b>真实数据接口暂不可用</b><span>{{ error }}</span>
      <button @click="loadDashboard">重新读取</button>
    </div>
    <div v-else-if="loading && !data" class="dashboard-loading">正在从 MySQL 聚合经营数据…</div>

    <template v-if="data">
      <section class="data-scope-bar">
        <span>销量数据截至：<b>{{ meta.latest_sales_date || '—' }}</b></span>
        <span>库存快照：<b>{{ meta.latest_inventory_date || '—' }}</b></span>
        <span>{{ meta.inventory_dimension_note }}</span>
      </section>

      <section class="kpi-row">
        <article v-if="showSalesAmount" class="kpi-card"><span>销售额</span><b>{{ money(kpis.sales_amount) }}</b><small>仅单店铺显示</small></article>
        <article class="kpi-card kpi-card-primary"><span>{{ f.dateLabel }}销量</span><b>{{ n(kpis.sales_qty) }}</b><small>sales_daily 实时聚合</small></article>
        <article class="kpi-card"><span>活跃 SKU</span><b>{{ n(kpis.active_sku) }}</b><small>当前销售筛选范围</small></article>
        <article class="kpi-card"><span>当前库存</span><b>{{ n(kpis.stock_qty) }}</b><small>不显示库存金额</small></article>
        <article class="kpi-card"><span>平均周转</span><b>{{ kpis.turnover_days == null ? '—' : `${n(kpis.turnover_days,1)}天` }}</b><small>库存 ÷ 30天日均销量</small></article>
        <article class="kpi-card"><span>高动销低库存</span><b>{{ n(kpis.shortage_risk) }}</b><small>0库存已排除</small></article>
        <article class="kpi-card"><span>效期风险</span><b>{{ n(kpis.expiry_risk) }}</b><small>预警 / 临期 / 过期商品</small></article>
      </section>

      <section class="comparison-grid-v154 dashboard-comparison-v154">
        <article class="comparison-card current"><div class="comparison-card-head"><span>当前区间销量</span><span>{{ f.dateLabel }}</span></div><b>{{ n(comparison.current?.sales) }}</b><small>{{ comparison.current?.start_date||'—' }} → {{ comparison.current?.end_date||'—' }}</small></article>
        <article :class="['comparison-card',comparisonClass(comparison.mom)]"><div class="comparison-card-head"><span>环比 · 上一等长区间</span><span>{{ comparisonText(comparison.mom) }}</span></div><b>{{ comparisonText(comparison.mom) }}</b><small v-if="comparison.mom?.available">上期销量 {{ n(comparison.mom.sales) }} · {{ comparison.mom.start_date }} → {{ comparison.mom.end_date }}</small><small v-else>历史数据不足，不伪造环比</small></article>
        <article :class="['comparison-card',comparisonClass(comparison.yoy)]"><div class="comparison-card-head"><span>同比 · 去年同期</span><span>{{ comparisonText(comparison.yoy) }}</span></div><b>{{ comparisonText(comparison.yoy) }}</b><small v-if="comparison.yoy?.available">同期销量 {{ n(comparison.yoy.sales) }} · {{ comparison.yoy.start_date }} → {{ comparison.yoy.end_date }}</small><small v-else>缺少去年同期数据</small></article>
      </section>

      <section class="dashboard-grid">
        <article class="panel trend-panel">
          <div class="section-head">
            <div><h3>{{ f.dateLabel }}销售趋势</h3><span>{{ showPrice ? '单店铺：销量 + 加权均价' : '多/全部店铺：只显示销量' }}</span></div>
            <span v-if="risks.comparison_available">近7天 vs 前7天：<b :class="{'positive':risks.seven_day_change_pct>=0,'negative':risks.seven_day_change_pct<0}">{{ pct(risks.seven_day_change_pct) }}</b></span>
            <span v-else>7天环比：历史数据不足</span>
          </div>
          <div ref="chartEl" class="dashboard-chart"></div>
        </article>

        <article class="panel risk-panel">
          <div class="section-head"><h3>运营风险</h3><span>实时计算</span></div>
          <div class="risk risk-red"><b>{{ n(risks.urgent_shortage) }} 个商品</b><span>高动销且预计10天内缺货</span></div>
          <div class="risk risk-orange"><b>{{ n(risks.slow_moving) }} 个 SKU</b><span>无销量库存或预计周转超过90天</span></div>
          <div class="risk risk-yellow"><b>{{ risks.declining_sales == null ? '历史不足' : `${n(risks.declining_sales)} 个商品` }}</b><span>近7天销量较前7天下降20%以上</span></div>
          <div class="risk-compare">
            <span>近7天销量 <b>{{ n(risks.recent7_sales) }}</b></span>
            <span>前7天销量 <b>{{ risks.comparison_available ? n(risks.prior7_sales) : '—' }}</b></span>
          </div>
        </article>
      </section>

      <section class="panel structure-panel">
        <div class="section-head"><div><h3>库存与效期结构</h3><span>用图形快速查看当前风险构成</span></div></div>
        <div ref="structureChartEl" class="structure-chart"></div>
      </section>

      <section v-if="inventoryData" class="inventory-health-grid">
        <RouterLink :to="{path:'/product',query:{stock_category:'healthy'}}" class="inventory-health-card healthy"><span>健康库存</span><b>{{ n(inventoryCategories.healthy?.sku_count) }}</b><small>点击下钻商品分析</small></RouterLink>
        <RouterLink :to="{path:'/product',query:{stock_category:'high'}}" class="inventory-health-card high"><span>高库存</span><b>{{ n(inventoryCategories.high?.sku_count) }}</b><small>点击下钻商品分析</small></RouterLink>
        <RouterLink :to="{path:'/product',query:{stock_category:'stagnant'}}" class="inventory-health-card stagnant"><span>呆滞库存</span><b>{{ n(inventoryCategories.stagnant?.sku_count) }}</b><small>点击下钻商品分析</small></RouterLink>
        <RouterLink :to="{path:'/product',query:{stock_category:'no_sales'}}" class="inventory-health-card no-sales"><span>无销量库存</span><b>{{ n(inventoryCategories.no_sales?.sku_count) }}</b><small>点击下钻商品分析</small></RouterLink>
      </section>

      <section class="expiry-mini-grid">
        <RouterLink :to="{path:'/product',query:{expiry_status:'正常'}}" class="expiry-mini normal"><span>正常</span><b>{{ n(expiryCategories['正常']) }}</b><small>点击下钻商品分析</small></RouterLink>
        <RouterLink :to="{path:'/product',query:{expiry_status:'预警'}}" class="expiry-mini warn"><span>预警</span><b>{{ n(expiryCategories['预警']) }}</b><small>点击下钻商品分析</small></RouterLink>
        <RouterLink :to="{path:'/product',query:{expiry_status:'临期'}}" class="expiry-mini near"><span>临期</span><b>{{ n(expiryCategories['临期']) }}</b><small>点击下钻商品分析</small></RouterLink>
        <RouterLink :to="{path:'/product',query:{expiry_status:'过期'}}" class="expiry-mini expired"><span>过期</span><b>{{ n(expiryCategories['过期']) }}</b><small>点击下钻商品分析</small></RouterLink>
      </section>

      <section class="panel">
        <div class="section-head rank-head">
          <div><h3>商品排行榜 TOP30</h3><span>当前筛选口径 · 内部滚动</span></div>
          <div class="rank-tabs">
            <button v-for="tab in rankTabs" :key="tab.key" :class="['rank-tab',{active:activeRank===tab.key}]" @click="activeRank=tab.key">{{ tab.label }}</button>
          </div>
        </div>
        <div class="rank-list">
          <div v-for="(p,index) in rankRows" :key="`${activeRank}-${p.product_id}`" class="rank-row">
            <b class="rank-num">{{ String(index + 1).padStart(2,'0') }}</b>
            <div class="rank-product"><RouterLink class="table-product-link" :to="{path:'/product',query:{sku:p.sku}}">{{ p.name }}</RouterLink><small>{{ p.sku }}</small></div>
            <div><small>{{ f.dateLabel }}销量</small><b>{{ n(p.sales_qty) }}</b></div>
            <div><small>库存</small><b>{{ n(p.stock) }}</b></div>
            <div><small>{{ rankMetricLabel() }}</small><b>{{ rankMetricValue(p) }}</b></div>
          </div>
          <div v-if="!rankRows.length" class="rank-empty">当前筛选条件下没有符合该排行榜规则的商品。</div>
        </div>
      </section>
    </template>
  </div>
</template>
