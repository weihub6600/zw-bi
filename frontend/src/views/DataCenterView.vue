<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import {
  AlertTriangle, CheckCircle2, Database, Download, FileCheck2, FileSpreadsheet, GitMerge,
  History, RotateCcw, Search, ShieldCheck, UploadCloud, XCircle
} from 'lucide-vue-next'
import {
  commitImport, fetchImportBatch, fetchImportIssues, fetchLatestBusinessDate, fetchProductNameAliases,
  fetchRecentImports, previewImport, resolveProductNameAlias, rollbackImport
} from '../api/imports'

import { useAuthStore } from '../stores/auth'
import DataDownloadPanel from '../components/DataDownloadPanel.vue'
const auth = useAuthStore()
const departmentCode = computed(() => auth.departmentCode || 'B2C')
const canImport = computed(() => Boolean(auth.capabilities.can_import))
const canDownload = computed(() => Boolean(auth.capabilities.can_download_data))
const visibleTabs = computed(() => {
  const tabs = []
  if (canImport.value) {
    tabs.push({ key: 'import', label: '数据导入', icon: 'upload' })
    tabs.push({ key: 'records', label: '导入记录', icon: 'history' })
    tabs.push({ key: 'quality', label: '数据质量', icon: 'alert' })
  }
  tabs.push({ key: 'download', label: '数据下载', icon: 'download' })
  tabs.push({ key: 'templates', label: '模板下载', icon: 'tpl' })
  return tabs
})
const activeTab = ref(canImport.value ? 'import' : 'download')
const dataType = ref('sales')
const businessDate = ref('2026-08-19')
const selectedFile = ref(null)
const fileInput = ref(null)
const preview = ref(null)
const previewLoading = ref(false)
const commitLoading = ref(false)
const message = ref('')
const errorMessage = ref('')
const records = ref([])
const recordsLoading = ref(false)
const recordFilter = ref('')
const detailCache = ref({})
const qualityBatchNo = ref('')
const qualitySeverity = ref('')
const qualityIssues = ref([])
const qualityTotal = ref(0)
const qualityLoading = ref(false)
const aliasGroups = ref([])
const aliasLoading = ref(false)
const aliasDraft = ref({})

const typeDefs = {
  sales: {
    label: '销量数据', dateLabel: '销售业务日期',
    note: 'Excel 不需要日期列；导入时选择这份文件对应的销售日期。',
    fields: ['店铺', '仓库', '商家编码', '商品名称', '销量', '均价'],
    columns: [['shop_name','店铺'],['warehouse_name','仓库'],['merchant_code','商家编码'],['product_name','商品名称'],['sales_qty','销量'],['avg_price','均价'],['business_date','业务日期']]
  },
  inventory: {
    label: '库存效期', dateLabel: '库存快照日期',
    note: '快照日期由导入时选择；生产日期和过期日期保留在 Excel 中。',
    fields: ['仓库', '商家编码', '商品名称', '库存数量', '生产日期', '过期日期'],
    columns: [['warehouse_name','仓库'],['merchant_code','商家编码'],['product_name','商品名称'],['stock_qty','库存数量'],['production_date','生产日期'],['expire_date','过期日期'],['snapshot_date','快照日期']]
  },
  product: {
    label: '商品资料', dateLabel: '无需业务日期',
    note: '商品资料只记录导入时间，不需要业务日期。',
    fields: ['商家编码', '货品名称', '规格（可选）', '品牌（可选）', '分类（可选）', '条码（可选）'],
    columns: [['merchant_code','商家编码'],['product_name','货品名称'],['spec','规格'],['brand','品牌'],['category','分类'],['barcode','条码']]
  },
  aging: {
    label: '库龄数据', dateLabel: '库龄统计日期',
    note: '统计日期由导入时选择，Excel 不强制带统计日期。',
    fields: ['仓库', '商家编码', '商品名称', '库存数量', '库龄天数'],
    columns: [['warehouse_name','仓库'],['merchant_code','商家编码'],['product_name','商品名称'],['stock_qty','库存数量'],['aging_days','库龄天数'],['snapshot_date','统计日期']]
  }
}

const templateLinks = [
  ['product','product_master.xlsx','商品资料','商家编码、货品名称为必填；规格、品牌、分类、条码可选。'],
  ['sales','sales_daily.xlsx','销量数据','店铺、仓库、商家编码、商品名称、销量、均价。'],
  ['inventory','inventory_expiry.xlsx','库存效期','仓库、商家编码、商品名称、库存、生产日期、过期日期。'],
  ['aging','aging_snapshot.xlsx','库龄数据','仓库、商家编码、商品名称、库存数量、库龄天数。']
]

const currentType = computed(() => typeDefs[dataType.value])
const effectiveDate = computed(() => dataType.value === 'product' ? '' : businessDate.value)
const previewRows = computed(() => preview.value?.rows || [])
const previewSummary = computed(() => preview.value?.summary || null)
const commitAllowed = computed(() => Boolean(preview.value?.commit_allowed && selectedFile.value))
const filteredRecords = computed(() => {
  const q = recordFilter.value.trim().toLowerCase()
  if (!q) return records.value
  return records.value.filter(r => [r.batch_no,r.data_type,r.original_filename,r.user_id,r.username,r.business_date]
    .some(v => String(v || '').toLowerCase().includes(q)))
})
const issueRecords = computed(() => records.value.filter(r => Number(r.error_rows) > 0 || Number(r.warning_rows) > 0))
const qualitySummary = computed(() => ({
  errors: records.value.reduce((n,r)=>n+Number(r.error_rows||0),0),
  warnings: records.value.reduce((n,r)=>n+Number(r.warning_rows||0),0),
  batches: issueRecords.value.length,
  success: records.value.filter(r=>r.status==='success').length
}))

function resetFeedback(){ message.value=''; errorMessage.value='' }
function invalidatePreview(){ preview.value=null; resetFeedback() }
function onFileChange(event){
  selectedFile.value = event.target.files?.[0] || null
  invalidatePreview()
}
function humanType(type){ return typeDefs[type]?.label || type }
function humanStatus(status){ return ({preview:'预览',success:'成功',failed:'失败',rolled_back:'已回滚'})[status] || status }
function statusClass(status){ return status==='success'?'success':status==='failed'?'error':status==='rolled_back'?'muted':'warning' }
function shortHash(hash){ return hash ? `${hash.slice(0,10)}…${hash.slice(-8)}` : '—' }
function displayValue(value){
  if (value === null || value === undefined || value === '') return '—'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}
function issueRaw(raw){
  if (!raw) return '—'
  try { return typeof raw === 'string' ? raw : JSON.stringify(raw, null, 2) } catch { return String(raw) }
}
function validateLocalForm(){
  if (!selectedFile.value) throw new Error('请先选择 .xlsx 或 .csv 文件')
  if (dataType.value !== 'product' && !businessDate.value) throw new Error('请选择业务日期')
}

async function runPreview(){
  resetFeedback()
  try {
    validateLocalForm()
    previewLoading.value=true
    preview.value = await previewImport({
      dataType:dataType.value, departmentCode:departmentCode.value, businessDate:effectiveDate.value, file:selectedFile.value
    })
    if (preview.value.sales_replace_blocked) {
      errorMessage.value=preview.value.replace_block_reason || '该日期销量采用整日覆盖，纠正文件仍有错误行；为保护旧数据，本次禁止覆盖。'
    } else if (preview.value.replace_existing) {
      const r=preview.value.replace_existing
      message.value=`检测到 ${r.business_date} 已有销量数据（${r.existing_rows||0} 行）。本次允许覆盖：提交后先清除该日期旧销量，再以本次文件为准。`
    } else if (preview.value.duplicate) {
      errorMessage.value=`检测到相同文件已经成功导入：${preview.value.duplicate.batch_no}，该数据类型仍禁止重复写入。`
    } else if (preview.value.snapshot_replace_blocked) {
      errorMessage.value='库存效期/库龄属于整表最新快照，存在错误行时禁止覆盖当前快照。请先修正错误后重新校验。'
    } else if (preview.value.partial_import) {
      message.value='校验完成：存在错误行。确认导入时只写入有效行，错误行会进入数据质量记录。'
    } else if (preview.value.commit_allowed) {
      message.value='校验通过，可以确认导入。'
    } else {
      errorMessage.value='没有可写入的有效数据，请先修正文件。'
    }
  } catch (e) { errorMessage.value=e.message }
  finally { previewLoading.value=false }
}

async function runCommit(){
  resetFeedback()
  if (!commitAllowed.value) return
  if (preview.value?.replace_existing) {
    const r=preview.value.replace_existing
    const ok=window.confirm(`确认覆盖 ${r.business_date} 的销量数据？\n现有 ${r.existing_rows||0} 行会先清除，再写入本次文件。\n最后一次成功上传为该日期唯一有效数据。`)
    if(!ok) return
  } else if (preview.value?.partial_import) {
    const ok=window.confirm(`当前有 ${previewSummary.value?.error_rows || 0} 条错误行。\n确认后只导入有效行，错误行会保留在数据质量记录。\n是否继续？`)
    if (!ok) return
  } else if (!window.confirm(`确认把“${selectedFile.value?.name}”写入 ${currentType.value.label}？`)) return
  try {
    commitLoading.value=true
    const result=await commitImport({
      dataType:dataType.value, departmentCode:departmentCode.value, businessDate:effectiveDate.value, file:selectedFile.value
    })
    message.value=`导入完成：${result.batch_no}，成功 ${result.success_rows} 行，错误 ${result.error_rows} 行，警告 ${result.warning_rows} 行。`
    preview.value=null
    await loadRecords()
    await notifyLatestDateChanged()
    if (result.error_rows || result.warning_rows) {
      qualityBatchNo.value=result.batch_no
      activeTab.value='quality'
      await loadQualityIssues()
    } else {
      activeTab.value='records'
    }
  } catch (e) {
    if (e.code === 'DATABASE_SCHEMA_MISSING') {
      errorMessage.value = '销量导入失败：数据库结构版本不完整，请联系管理员升级数据库。本次导入已终止。\n错误代码：DATABASE_SCHEMA_MISSING'
    } else {
      errorMessage.value = e.message
    }
  }
  finally { commitLoading.value=false }
}

async function loadRecords(){
  recordsLoading.value=true
  try {
    const result=await fetchRecentImports({departmentCode:departmentCode.value,limit:100})
    records.value=result.items || []
    if (!qualityBatchNo.value && issueRecords.value.length) qualityBatchNo.value=issueRecords.value[0].batch_no
  } catch (e) { errorMessage.value=e.message }
  finally { recordsLoading.value=false }
}

async function loadBatchDetail(batchNo){
  if (detailCache.value[batchNo]) return detailCache.value[batchNo]
  try {
    const detail=await fetchImportBatch(batchNo)
    detailCache.value={...detailCache.value,[batchNo]:detail}
    return detail
  } catch (e) { errorMessage.value=e.message; return null }
}

async function openQuality(batchNo){
  qualityBatchNo.value=batchNo
  activeTab.value='quality'
  qualitySeverity.value=''
  await loadQualityIssues()
}

async function loadQualityIssues(){
  if (!qualityBatchNo.value) { qualityIssues.value=[]; qualityTotal.value=0; return }
  qualityLoading.value=true
  try {
    const result=await fetchImportIssues(qualityBatchNo.value,{severity:qualitySeverity.value,limit:300})
    qualityIssues.value=result.items || []
    qualityTotal.value=result.total || 0
  } catch (e) { errorMessage.value=e.message }
  finally { qualityLoading.value=false }
}

async function loadProductAliases(){
  aliasLoading.value=true
  try {
    const result=await fetchProductNameAliases({departmentCode:departmentCode.value,pendingOnly:true})
    aliasGroups.value=result.items || []
    const next={}
    for (const item of aliasGroups.value) next[item.product_id]=aliasDraft.value[item.product_id] || item.canonical_name
    aliasDraft.value=next
  } catch (e) { errorMessage.value=e.message }
  finally { aliasLoading.value=false }
}

async function resolveAlias(item){
  const canonicalName=String(aliasDraft.value[item.product_id]||'').trim()
  if(!canonicalName) return
  const ok=window.confirm(`确认把商家编码 ${item.merchant_code} 的名称变体聚合为“${canonicalName}”吗？\n历史销量、库存、库龄仍按同一商家编码/商品ID连续分析，不会拆成多个商品。`)
  if(!ok) return
  try{
    await resolveProductNameAlias(item.product_id,{departmentCode:departmentCode.value,canonicalName})
    message.value=`已完成 ${item.merchant_code} 的商品名称聚合：${canonicalName}`
    await loadProductAliases()
  }catch(e){errorMessage.value=e.message}
}

async function runRollback(record){
  resetFeedback()
  const detail=await loadBatchDetail(record.batch_no)
  const changes=detail?.changes_count ?? '未知'
  const ok=window.confirm(`确认回滚批次 ${record.batch_no}？\n将尝试撤销 ${changes} 条数据变更。\n如果数据已被后续批次修改，后端会拒绝危险回滚。`)
  if (!ok) return
  try {
    const result=await rollbackImport(record.batch_no)
    message.value=`已回滚 ${result.batch_no}，撤销 ${result.changes_reverted} 条变更。`
    detailCache.value={}
    await loadRecords()
    await notifyLatestDateChanged()
  } catch (e) { errorMessage.value=e.message }
}

async function notifyLatestDateChanged(){
  try {
    const latest=await fetchLatestBusinessDate({departmentCode:departmentCode.value})
    window.dispatchEvent(new CustomEvent('bjr:data-date-changed',{detail:latest.latest_business_date || ''}))
  } catch {}
}

watch([dataType,businessDate,departmentCode], invalidatePreview)
watch(qualitySeverity, loadQualityIssues)
watch(activeTab, tab => { if (canImport.value && tab==='records') loadRecords(); if (canImport.value && tab==='quality') { if (qualityBatchNo.value) loadQualityIssues(); loadProductAliases() } })

onMounted(async()=>{
  if (canImport.value) await loadRecords()
})
</script>

<template>
  <div class="page data-center-page">
    <div class="page-title dc-title">
      <div>
        <h1>数据中心</h1>
        <p>本地 Excel / CSV → 校验预览 → MySQL；不连接旺店通外部 OpenAPI</p>
      </div>
      <div class="local-only-badge"><ShieldCheck :size="16" /> 局域网本地导入</div>
    </div>

    <div v-if="message" class="dc-alert success"><CheckCircle2 :size="18" /><span>{{ message }}</span></div>
    <div v-if="errorMessage" class="dc-alert error"><XCircle :size="18" /><span>{{ errorMessage }}</span><button @click="errorMessage=''">关闭</button></div>

    <div class="dc-tabs">
      <button v-for="tab in visibleTabs" :key="tab.key" :class="['dc-tab',{active:activeTab===tab.key}]" @click="activeTab=tab.key">
        <UploadCloud v-if="tab.icon==='upload'" :size="16" />
        <History v-else-if="tab.icon==='history'" :size="16" />
        <AlertTriangle v-else-if="tab.icon==='alert'" :size="16" />
        <Download v-else-if="tab.icon==='download'" :size="16" />
        <FileSpreadsheet v-else-if="tab.icon==='tpl'" :size="16" />
        {{ tab.label }}
      </button>
    </div>

    <template v-if="activeTab==='import'">
      <div class="dc-import-grid">
        <section class="panel">
          <div class="section-head"><div><h3>① 选择导入内容</h3><span>普通用户后端强制禁止导入</span></div><Database :size="20" /></div>
          <div class="dc-form-grid">
            <label>数据类型
              <select v-model="dataType">
                <option value="sales">销量数据</option><option value="inventory">库存效期</option>
                <option value="product">商品资料</option><option value="aging">库龄数据</option>
              </select>
            </label>
            <label>所属部门
              <select disabled><option>{{ auth.departmentName }}</option></select>
            </label>
            <label>{{ currentType.dateLabel }}
              <input v-model="businessDate" type="date" :disabled="dataType==='product'" />
              <small>{{ currentType.note }}</small>
            </label>
            <label>允许文件
              <input value=".xlsx / .csv" disabled />
              <small>旧版 .xls 请先另存为 .xlsx。</small>
            </label>
          </div>

          <label class="dc-dropzone">
            <input ref="fileInput" type="file" accept=".xlsx,.csv" @change="onFileChange" />
            <UploadCloud :size="30" />
            <strong>{{ selectedFile ? selectedFile.name : '点击选择 Excel / CSV 文件' }}</strong>
            <span v-if="selectedFile">{{ (selectedFile.size/1024/1024).toFixed(2) }} MB · 选择新文件会自动使旧预览失效</span>
            <span v-else>文件只上传到百嘉瑞BI本地后端，不会发送给旺店通。</span>
          </label>

          <div class="dc-form-actions">
            <button class="dc-button secondary" :disabled="previewLoading" @click="runPreview"><FileCheck2 :size="16" />{{ previewLoading?'正在校验…':'② 校验并预览' }}</button>
            <button class="dc-button primary" :disabled="!commitAllowed || commitLoading" @click="runCommit"><Database :size="16" />{{ commitLoading?'正在写入…':'③ 确认写入 MySQL' }}</button>
          </div>
        </section>

        <section class="panel dc-schema-panel">
          <div class="section-head"><div><h3>{{ currentType.label }}标准字段</h3><span>使用固定模板最稳定</span></div><FileSpreadsheet :size="20" /></div>
          <div class="schema-chips"><span v-for="field in currentType.fields" :key="field">{{ field }}</span></div>
          <div class="dc-rule-list">
            <div><CheckCircle2 :size="15" />业务日期由导入界面确定，不从 Excel 猜测。</div>
            <div><CheckCircle2 :size="15" />商家编码是唯一商品键；名称变体自动聚合到同一商品，管理员在数据质量中确认规范名称。</div>
            <div><CheckCircle2 :size="15" />销量按业务日期整日覆盖：同一天可重复上传，提交后清除旧数据，以最后一次成功上传为准；其他类型仍使用 SHA256 防重复。</div>
            <div><CheckCircle2 :size="15" />30天汇总销量禁止写入逐日销量表。</div>
            <div><CheckCircle2 :size="15" />库存效期和库龄成功导入后只保留本部门最新整表快照；销量数据持续累计沉淀。</div>
          </div>
        </section>
      </div>

      <section v-if="preview" class="panel dc-preview-panel">
        <div class="section-head">
          <div><h3>校验结果与数据预览</h3><span>{{ preview.original_filename }} · SHA256 {{ shortHash(preview.file_sha256) }}</span></div>
          <span :class="['dc-status',preview.commit_allowed?'success':'error']">{{ preview.commit_allowed?'可提交':'不可提交' }}</span>
        </div>
        <div class="dc-summary-row">
          <div><span>源数据行</span><b>{{ previewSummary.source_rows }}</b></div>
          <div><span>有效行</span><b class="text-success">{{ previewSummary.valid_rows }}</b></div>
          <div><span>错误行</span><b class="text-error">{{ previewSummary.error_rows }}</b></div>
          <div><span>警告</span><b class="text-warning">{{ previewSummary.warning_rows }}</b></div>
          <div><span>跳过行</span><b>{{ previewSummary.skipped_rows }}</b></div>
        </div>

        <div v-if="preview.sales_replace_blocked" class="dc-inline-warning duplicate"><XCircle :size="17" /><span><b>纠正文件暂不可覆盖</b>：{{ preview.replace_block_reason }}</span></div>
        <div v-else-if="preview.replace_existing" class="dc-inline-warning replace"><RotateCcw :size="17" /><span><b>{{ preview.replace_existing.business_date }} 将执行覆盖导入</b>：当前 {{ preview.replace_existing.existing_rows || 0 }} 行销量会先清除，再写入本次文件。<template v-if="preview.replace_existing.previous_batch_no"> 上次批次 {{ preview.replace_existing.previous_batch_no }}。</template></span></div>
        <div v-else-if="preview.duplicate" class="dc-inline-warning duplicate"><XCircle :size="17" />相同文件已在批次 {{ preview.duplicate.batch_no }} 成功导入，该数据类型仍禁止重复写入。</div>
        <div v-else-if="preview.snapshot_replace_blocked" class="dc-inline-warning duplicate"><XCircle :size="17" />库存效期/库龄采用“最新整表替换”策略，当前存在错误行，因此不会覆盖现有最新快照。</div>
        <div v-else-if="preview.partial_import" class="dc-inline-warning"><AlertTriangle :size="17" />存在错误行：确认导入后只写有效行，错误行会保留在该导入批次的数据质量明细。</div>

        <div class="dc-preview-table-wrap">
          <table>
            <thead><tr><th>源行</th><th v-for="[,label] in currentType.columns" :key="label">{{ label }}</th></tr></thead>
            <tbody>
              <tr v-for="row in previewRows" :key="row.row_no"><td>{{ row.row_no }}</td><td v-for="[key] in currentType.columns" :key="key">{{ displayValue(row[key]) }}</td></tr>
              <tr v-if="!previewRows.length"><td :colspan="currentType.columns.length+1" class="dc-empty">没有有效数据可预览</td></tr>
            </tbody>
          </table>
        </div>

        <div v-if="preview.errors?.length || preview.warnings?.length" class="dc-preview-issues">
          <div v-if="preview.errors?.length"><h4>错误（预览前 {{ preview.errors.length }} 条）</h4><div v-for="item in preview.errors" :key="`e-${item.row_no}-${item.code}`" class="issue-line error"><XCircle :size="14" /><span>第 {{ item.row_no }} 行 · {{ item.code }} · {{ item.message }}</span></div></div>
          <div v-if="preview.warnings?.length"><h4>警告（预览前 {{ preview.warnings.length }} 条）</h4><div v-for="item in preview.warnings" :key="`w-${item.row_no}-${item.code}`" class="issue-line warning"><AlertTriangle :size="14" /><span>第 {{ item.row_no }} 行 · {{ item.code }} · {{ item.message }}</span></div></div>
        </div>
      </section>
    </template>

    <template v-if="activeTab==='records'">
      <section class="panel">
        <div class="section-head dc-record-head">
          <div><h3>真实导入记录</h3><span>按批次记录文件、业务日期、成功/错误/警告与回滚状态</span></div>
          <div class="dc-record-search"><Search :size="15" /><input v-model="recordFilter" placeholder="搜索批次 / 文件 / 日期 / 用户" /></div>
        </div>
        <div v-if="recordsLoading" class="dc-empty">正在读取导入记录…</div>
        <div v-else class="dc-record-list">
          <article v-for="record in filteredRecords" :key="record.batch_no" class="dc-record-card">
            <div class="dc-record-main">
              <strong>{{ humanType(record.data_type) }}</strong>
              <span>{{ record.original_filename }}</span>
              <small>{{ record.batch_no }}</small>
            </div>
            <div><small>业务日期</small><b>{{ record.business_date || '—' }}</b></div>
            <div><small>写入结果</small><b>{{ record.success_rows }}/{{ record.total_rows }}</b></div>
            <div><small>问题</small><b><span class="text-error">{{ record.error_rows }}</span> / <span class="text-warning">{{ record.warning_rows }}</span></b></div>
            <div><small>导入人</small><b>{{ record.username || record.user_id || '—' }}</b></div>
            <div><small>时间</small><b>{{ record.created_at }}</b></div>
            <div class="dc-record-actions">
              <span :class="['dc-status',statusClass(record.status)]">{{ humanStatus(record.status) }}</span>
              <button v-if="record.error_rows || record.warning_rows" class="dc-mini" @click="openQuality(record.batch_no)">问题明细</button>
              <button v-if="record.status==='success' && record.can_rollback!==false" class="dc-mini danger" @click="runRollback(record)"><RotateCcw :size="13" /> 回滚</button>
            </div>
          </article>
          <div v-if="!filteredRecords.length" class="dc-empty">暂无导入记录</div>
        </div>
      </section>
    </template>

    <template v-if="activeTab==='quality'">
      <div class="dc-summary-row quality-summary">
        <div><span>近100批错误</span><b class="text-error">{{ qualitySummary.errors }}</b></div>
        <div><span>近100批警告</span><b class="text-warning">{{ qualitySummary.warnings }}</b></div>
        <div><span>存在问题批次</span><b>{{ qualitySummary.batches }}</b></div>
        <div><span>成功批次</span><b class="text-success">{{ qualitySummary.success }}</b></div>
      </div>
      <section class="panel product-alias-panel">
        <div class="section-head">
          <div><h3><GitMerge :size="17" /> 商品名称聚合</h3><span>商家编码为唯一商品键；名称变化不会再阻断导入或拆分分析，只需管理员确认一个规范展示名称。</span></div>
          <button class="dc-mini" :disabled="aliasLoading" @click="loadProductAliases">{{ aliasLoading?'读取中…':'刷新' }}</button>
        </div>
        <div v-if="aliasLoading && !aliasGroups.length" class="dc-empty">正在读取待确认名称变体…</div>
        <div v-else-if="!aliasGroups.length" class="alias-empty"><CheckCircle2 :size="18"/><div><b>当前没有待聚合的商品名称</b><span>后续导入若出现同一商家编码的新名称，会自动进入这里，不再记为导入错误。</span></div></div>
        <div v-else class="alias-list">
          <article v-for="item in aliasGroups" :key="item.product_id" class="alias-card">
            <div class="alias-code"><small>商家编码</small><b>{{ item.merchant_code }}</b></div>
            <div class="alias-names">
              <small>当前规范名</small><b>{{ item.canonical_name }}</b>
              <div class="alias-chips"><span v-for="a in item.aliases" :key="a.alias_id">{{ a.alias_name }} <em>×{{ a.seen_count }}</em></span></div>
            </div>
            <label class="alias-canonical">聚合为
              <input v-model.trim="aliasDraft[item.product_id]" :list="`alias-options-${item.product_id}`" placeholder="选择已有名称或输入新的规范名称" />
              <datalist :id="`alias-options-${item.product_id}`">
                <option :value="item.canonical_name"></option>
                <option v-for="a in item.aliases" :key="`opt-${a.alias_id}`" :value="a.alias_name"></option>
              </datalist>
            </label>
            <button class="dc-button primary alias-resolve" @click="resolveAlias(item)"><GitMerge :size="15"/>确认聚合</button>
          </article>
        </div>
      </section>

      <section class="panel">
        <div class="dc-quality-toolbar">
          <label>导入批次<select v-model="qualityBatchNo" @change="loadQualityIssues"><option value="">请选择批次</option><option v-for="r in issueRecords" :key="r.batch_no" :value="r.batch_no">{{ r.batch_no }} · {{ r.original_filename }}</option></select></label>
          <label>严重级别<select v-model="qualitySeverity"><option value="">全部</option><option value="error">错误</option><option value="warning">警告</option></select></label>
          <div class="quality-count">当前 {{ qualityTotal }} 条</div>
        </div>
        <div v-if="qualityLoading" class="dc-empty">正在读取错误明细…</div>
        <div v-else class="dc-issues-list">
          <article v-for="issue in qualityIssues" :key="issue.id" :class="['dc-issue-card',issue.severity]">
            <div class="dc-issue-icon"><XCircle v-if="issue.severity==='error'" :size="18" /><AlertTriangle v-else :size="18" /></div>
            <div class="dc-issue-main"><strong>第 {{ issue.row_no || '—' }} 行 · {{ issue.error_code }}</strong><p>{{ issue.error_message }}</p><details><summary>查看原始行数据</summary><pre>{{ issueRaw(issue.raw_data) }}</pre></details></div>
          </article>
          <div v-if="!qualityBatchNo" class="dc-empty">请选择一个存在错误或警告的导入批次。</div>
          <div v-else-if="!qualityIssues.length" class="dc-empty">当前筛选下没有问题记录。</div>
        </div>
      </section>
    </template>

    <template v-if="activeTab==='download'">
      <DataDownloadPanel />
    </template>

    <template v-if="activeTab==='templates'">
      <div class="dc-template-grid">
        <article v-for="[type,file,label,desc] in templateLinks" :key="type" class="panel dc-template-card">
          <div class="dc-template-icon"><FileSpreadsheet :size="22" /></div>
          <h3>{{ label }}</h3><p>{{ desc }}</p>
          <a class="dc-button secondary" :href="`/templates/${file}`" download><Download :size="15" />下载标准模板</a>
        </article>
      </div>
    </template>
  </div>
</template>
