<script setup>
import { computed, onMounted, ref } from 'vue'
import { Download, FileSpreadsheet, Loader2, ListFilter } from 'lucide-vue-next'
import { exportProduct, exportSales, exportInventory, exportAging } from '../api/exports'
import { fetchLatestBusinessDate } from '../api/imports'
import { useAuthStore } from '../stores/auth'
import { useFilterStore } from '../stores/filter'

const auth = useAuthStore()
const f = useFilterStore()
const departmentCode = computed(() => auth.departmentCode || f.departmentCode || 'B2C')
const departmentName = computed(() => auth.departmentName || '—')

const startDate = ref('')
const endDate = ref('')
const downloading = ref('')
const errorMessage = ref('')
const salesRowCount = ref(null)

function toISO(d) {
  if (!d) return ''
  return d instanceof Date ? d.toISOString().slice(0, 10) : String(d).slice(0, 10)
}

async function loadDefaultRange() {
  try {
    const r = await fetchLatestBusinessDate({ departmentCode: departmentCode.value })
    const latest = r.latest_business_date
    const end = latest ? new Date(latest) : new Date()
    const start = new Date(end)
    start.setDate(start.getDate() - 29)
    startDate.value = toISO(start)
    endDate.value = toISO(end)
  } catch {
    const end = new Date()
    const start = new Date(end)
    start.setDate(start.getDate() - 29)
    startDate.value = toISO(start)
    endDate.value = toISO(end)
  }
}

// 销量：从全局筛选条继承全部有效筛选条件，构造与列表一致的查询参数。
function salesFilterParams() {
  const p = f.dateParams
  // 自定义区间传 start/end；预设(1d/7d/14d/30d)传 days，由后端以最新销售日为锚点解析。
  const isCustom = f.dateRange === 'custom'
  return {
    departmentCode: departmentCode.value,
    startDate: isCustom ? (p.startDate || '') : '',
    endDate: isCustom ? (p.endDate || '') : '',
    days: p.days || 30,
    shops: [...f.shops],
    warehouses: [...f.warehouses],
    productSearch: f.productSearch || '',
    includeName: f.includeName || '',
    excludeName: f.excludeName || '',
    productCodes: [...f.productCodes],
  }
}

const salesFilterSummary = computed(() => {
  const parts = []
  if (f.shops.length) parts.push(`店铺 ${f.shops.length} 个`)
  if (f.warehouses.length) parts.push(`仓库 ${f.warehouses.length} 个`)
  if (f.productSearch) parts.push(`搜索“${f.productSearch}”`)
  if (f.includeName) parts.push(`含“${f.includeName}”`)
  if (f.excludeName) parts.push(`不含“${f.excludeName}”`)
  if (f.productCodes.length) parts.push(`编码 ${f.productCodes.length} 个`)
  return parts.length ? parts.join(' · ') : '全部商品'
})

async function runDownload(kind) {
  errorMessage.value = ''
  try {
    downloading.value = kind
    if (kind === 'product') {
      await exportProduct(departmentCode.value)
    } else if (kind === 'sales') {
      const r = await exportSales(salesFilterParams())
      salesRowCount.value = r.rowCount
      if (r.rowCount === 0) {
        errorMessage.value = '当前筛选条件下暂无可导出数据'
      }
    } else if (kind === 'inventory') {
      await exportInventory(departmentCode.value)
    } else if (kind === 'aging') {
      await exportAging(departmentCode.value)
    }
  } catch (e) {
    errorMessage.value = e.message
  } finally {
    downloading.value = ''
  }
}

onMounted(() => {
  loadDefaultRange()
})

const cards = computed(() => [
  { kind: 'product', title: '商品资料', desc: '当前部门的商品主数据（商家编码、名称、规格、品牌、分类、条码）。' },
  { kind: 'sales', title: '销量明细', desc: '下载当前筛选结果的完整销量明细（不限分页），严格限定当前部门权限。', filtered: true },
  { kind: 'inventory', title: '库存效期', desc: '当前部门最新库存快照（数量、生产日期、过期日期）。' },
  { kind: 'aging', title: '库龄数据', desc: '当前部门最新库龄快照（数量、库龄天数）。' },
])
</script>

<template>
  <section class="panel dc-download-panel">
    <div class="section-head">
      <div>
        <h3>数据下载</h3>
        <span>下载内容严格按当前部门权限生成。</span>
      </div>
      <div class="dc-download-dept"><strong>当前部门：{{ departmentName }}</strong></div>
    </div>

    <div v-if="errorMessage" class="dc-alert error"><span>{{ errorMessage }}</span><button @click="errorMessage=''">关闭</button></div>

    <div class="dc-download-grid">
      <article v-for="card in cards" :key="card.kind" class="dc-template-card panel">
        <div class="dc-template-icon"><FileSpreadsheet :size="22" /></div>
        <h3>{{ card.title }}</h3>
        <p>{{ card.desc }}</p>
        <div v-if="card.filtered" class="dc-sales-filter">
          <div class="dc-sales-dates">
            <label>开始日期<input v-model="startDate" type="date" /></label>
            <label>结束日期<input v-model="endDate" type="date" /></label>
          </div>
          <div class="dc-filter-summary"><ListFilter :size="13" /> {{ salesFilterSummary }}</div>
        </div>
        <button class="dc-button primary" :disabled="downloading !== ''" @click="runDownload(card.kind)">
          <Loader2 v-if="downloading === card.kind" class="spin" :size="15" />
          <Download v-else :size="15" />
          {{ downloading === card.kind ? '正在生成…' : (card.filtered ? '下载当前筛选结果' : '下载 XLSX') }}
        </button>
        <div v-if="card.filtered && salesRowCount !== null" class="dc-sales-count">上次导出 {{ salesRowCount }} 条</div>
      </article>
    </div>
  </section>
</template>

<style scoped>
.dc-download-dept { display: flex; align-items: center; color: var(--accent, #2563eb); }
.dc-download-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 16px; margin-top: 8px; }
.dc-template-card { display: flex; flex-direction: column; gap: 8px; }
.dc-template-card p { flex: 1; }
.dc-sales-filter { display: flex; flex-direction: column; gap: 8px; }
.dc-sales-dates { display: flex; flex-direction: column; gap: 6px; }
.dc-sales-dates label { display: flex; flex-direction: column; gap: 4px; font-size: 12px; color: #64748b; }
.dc-sales-dates input { padding: 6px 8px; border: 1px solid #e2e8f0; border-radius: 6px; }
.dc-filter-summary { display: flex; align-items: center; gap: 4px; font-size: 12px; color: #475569; background: #f1f5f9; padding: 4px 6px; border-radius: 6px; }
.dc-sales-count { font-size: 12px; color: #2563eb; }
.spin { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
</style>
