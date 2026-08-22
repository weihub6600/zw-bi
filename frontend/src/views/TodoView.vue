<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { fetchDashboardOptions } from '../api/dashboard'
import { createTask, decideTaskDelete, fetchTaskAssignees, fetchTasks, requestTaskDelete, saveTaskOwnerNote, withdrawTaskDelete } from '../api/tasks'

const route=useRoute(),router=useRouter()
function localToday(){const d=new Date(),p=n=>String(n).padStart(2,'0');return `${d.getFullYear()}-${p(d.getMonth()+1)}-${p(d.getDate())}`} 
const tab=ref('mine'),data=ref(null),loading=ref(false),error=ref(''),savingNote=ref('')
const filters=reactive({ownerUserId:'',status:'',productSearch:''})
const assignees=ref([]),options=ref({shops:[],warehouses:[]}),createOpen=ref(false),createError=ref(''),creating=ref(false)
const form=reactive({merchant_code:'',owner_user_id:'',target_qty:'',assign_date:localToday(),manager_note:'',shop_name:'',warehouse_name:''})
let timer=null
const rows=computed(()=>data.value?.rows||[]),meta=computed(()=>data.value?.meta||{}),isAdmin=computed(()=>['system_admin','dept_admin'].includes(meta.value.actor_role))
function n(v,d=0){return Number(v||0).toLocaleString('zh-CN',{minimumFractionDigits:d,maximumFractionDigits:d})}
function money(v){return v==null?'—':Number(v).toLocaleString('zh-CN',{style:'currency',currency:'CNY',maximumFractionDigits:2})}
function statusText(v){return ({running:'进行中',pending_delete:'删除待审批',done:'已完成',delete_rejected:'删除被驳回'})[v]||v}
function startDate(assign){if(!assign)return'';const d=new Date(assign+'T00:00:00');d.setDate(d.getDate()+1);return d.toISOString().slice(0,10)}
async function load(){loading.value=true;error.value='';try{data.value=await fetchTasks({view:tab.value,ownerUserId:filters.ownerUserId,status:filters.status,productSearch:filters.productSearch});window.dispatchEvent(new CustomEvent('bjr:todo-count',{detail:data.value?.meta?.mine_incomplete_count||0}))}catch(e){error.value=e.message;data.value=null}finally{loading.value=false}}
function schedule(){clearTimeout(timer);timer=setTimeout(load,220)}
async function loadOptions(){try{const [a,o]=await Promise.all([fetchTaskAssignees(),fetchDashboardOptions()]);assignees.value=a.rows||[];options.value={shops:o.shops||[],warehouses:o.warehouses||[]};if(!form.owner_user_id&&assignees.value.length)form.owner_user_id=assignees.value[0].user_id}catch(e){error.value=e.message}}
function openCreate(sku=''){form.merchant_code=sku||'';if(!form.owner_user_id&&assignees.value.length)form.owner_user_id=assignees.value[0].user_id;form.target_qty='';form.assign_date=localToday();form.manager_note='';form.shop_name='';form.warehouse_name='';createError.value='';createOpen.value=true}
async function submitCreate(){creating.value=true;createError.value='';try{await createTask({...form,target_qty:form.target_qty===''?null:Number(form.target_qty),shop_name:form.shop_name||null,warehouse_name:form.warehouse_name||null});createOpen.value=false;tab.value='mine';await load()}catch(e){createError.value=e.message}finally{creating.value=false}}
async function saveNote(t){savingNote.value=t.task_no;try{await saveTaskOwnerNote(t.task_no,t.owner_note);await load()}catch(e){alert(e.message)}finally{savingNote.value=''}}
async function askDelete(t){const reason=prompt('请输入删除原因：','任务已无需继续');if(reason===null)return;try{await requestTaskDelete(t.task_no,reason);await load()}catch(e){alert(e.message)}}
async function withdraw(t){try{await withdrawTaskDelete(t.task_no);await load()}catch(e){alert(e.message)}}
async function decide(t,decision){const verb=decision==='approve'?'批准删除':'驳回删除';if(!confirm(`确定${verb} ${t.task_no} 吗？`))return;try{await decideTaskDelete(t.task_no,decision);await load()}catch(e){alert(e.message)}}
watch(tab,load);watch(()=>[filters.ownerUserId,filters.status,filters.productSearch],schedule)
onMounted(async()=>{await loadOptions();if(route.query.create==='1'){openCreate(String(route.query.sku||''));form.shop_name=String(route.query.shop||'');form.warehouse_name=String(route.query.warehouse||'')}await load()})
</script>

<template>
  <div class="page">
    <div class="page-title todo-title"><div><h1>待办任务</h1><p>真实读取 todo_tasks；任务自动数据从分配日期次日开始统计</p></div><button class="rank-tab active" @click="openCreate()">＋ 新建待办</button></div>
    <div v-if="error" class="api-error"><b>待办接口暂不可用</b><span>{{ error }}</span><button @click="load">重新读取</button></div>
    <section class="todo-kpi-row">
      <article><span>我的未完成</span><b>{{ n(meta.mine_incomplete_count) }}</b></article><article><span>删除待审批</span><b>{{ n(meta.approval_count) }}</b></article><article><span>当前角色</span><b class="role-text">{{ meta.actor_role||'—' }}</b></article>
    </section>
    <section class="panel">
      <div class="todo-tabs-real"><button :class="['rank-tab',{active:tab==='mine'}]" @click="tab='mine'">我的待办</button><button v-if="isAdmin" :class="['rank-tab',{active:tab==='department'}]" @click="tab='department'">部门待办</button><button v-if="isAdmin" :class="['rank-tab',{active:tab==='approval'}]" @click="tab='approval'">删除审批</button></div>
      <div class="todo-filters-real"><label>负责人<select v-model="filters.ownerUserId"><option value="">全部</option><option v-for="u in assignees" :key="u.user_id" :value="u.user_id">{{ u.username }} · {{ u.user_id }}</option></select></label><label>状态<select v-model="filters.status"><option value="">全部</option><option value="running">进行中</option><option value="pending_delete">删除待审批</option><option value="delete_rejected">删除被驳回</option><option value="done">已完成</option></select></label><label>商品搜索<input v-model="filters.productSearch" placeholder="商品名 / 商家编码" /></label></div>
      <div v-if="loading" class="dashboard-loading">正在读取待办…</div>
      <div v-else class="todo-real-list">
        <article v-for="t in rows" :key="t.task_no" class="todo-real-card">
          <div class="todo-card-head"><div><RouterLink class="table-product-link" :to="{path:'/product',query:{sku:t.sku}}">{{ t.product_name }}</RouterLink><small>{{ t.task_no }} · {{ t.sku }}</small></div><span :class="['task-status-real',t.status]">{{ statusText(t.status) }}</span></div>
          <div class="todo-main-grid"><div><small>负责人</small><b>{{ t.owner.username }}</b></div><div><small>创建人</small><b>{{ t.creator.username }}</b></div><div><small>分配 / 开始</small><b>{{ t.assign_date }} / {{ t.start_date }}</b></div><div><small>目标销量</small><b>{{ t.target_qty==null?'未设置':n(t.target_qty) }}</b></div><div><small>店铺</small><b>{{ t.shop_name||'全部店铺' }}</b></div><div><small>仓库</small><b>{{ t.warehouse_name||'全部仓库' }}</b></div></div>
          <div class="task-progress-real"><span>自动完成率</span><div><i :style="{width:`${Math.min(100,t.metrics.completion_pct||0)}%`}"></i></div><b>{{ n(t.metrics.completion_pct,1) }}%</b></div>
          <div class="task-metrics-real"><div><small>7天销量 <em v-if="!t.metrics.window_complete['7d']">数据未满7天</em></small><b>{{ n(t.metrics.sales7) }}</b></div><div><small>7天均价</small><b>{{ money(t.metrics.avg_price7) }}</b></div><div><small>14天销量 <em v-if="!t.metrics.window_complete['14d']">未满</em></small><b>{{ n(t.metrics.sales14) }}</b></div><div><small>14天均价</small><b>{{ money(t.metrics.avg_price14) }}</b></div><div><small>30天销量 <em v-if="!t.metrics.window_complete['30d']">未满</em></small><b>{{ n(t.metrics.sales30) }}</b></div><div><small>30天均价</small><b>{{ money(t.metrics.avg_price30) }}</b></div></div>
          <div class="todo-notes-real"><div><label>管理员任务要求</label><p>{{ t.manager_note||'无' }}</p></div><div><label>{{ t.permissions.can_edit_owner_note?'我的个人备注':'负责人个人备注' }}</label><textarea v-if="t.permissions.can_edit_owner_note" v-model="t.owner_note" placeholder="只有负责人本人可以修改"></textarea><p v-else>{{ t.owner_note||'—' }}</p><button v-if="t.permissions.can_edit_owner_note" class="rank-tab" :disabled="savingNote===t.task_no" @click="saveNote(t)">{{ savingNote===t.task_no?'保存中…':'保存个人备注' }}</button></div></div>
          <div v-if="t.delete_request" class="delete-request-box">删除申请：{{ t.delete_request.requester_name }} · {{ t.delete_request.reason||'未填写原因' }}</div>
          <div class="todo-actions-real"><button v-if="t.permissions.can_request_delete" class="rank-tab danger" @click="askDelete(t)">申请删除</button><button v-if="t.permissions.can_withdraw_delete" class="rank-tab" @click="withdraw(t)">撤回删除申请</button><button v-if="t.permissions.can_decide_delete" class="rank-tab approve" @click="decide(t,'approve')">批准删除</button><button v-if="t.permissions.can_decide_delete" class="rank-tab danger active-danger" @click="decide(t,'reject')">驳回</button></div>
        </article><div v-if="!rows.length" class="rank-empty">当前条件下没有待办。</div>
      </div>
    </section>

    <div v-if="createOpen" class="preset-modal-mask" @click.self="createOpen=false"><div class="preset-modal task-create-modal"><div class="section-head"><div><h3>新建待办</h3><span>开始日期固定为分配日期次日：{{ startDate(form.assign_date) }}</span></div><button class="modal-close" @click="createOpen=false">×</button></div><div class="preset-form-grid"><label>商家编码<input v-model.trim="form.merchant_code" placeholder="SKU-A00182" /></label><label>负责人<select v-model="form.owner_user_id"><option v-for="u in assignees" :key="u.user_id" :value="u.user_id">{{ u.username }} · {{ u.role }}</option></select></label><label>目标销量<input v-model="form.target_qty" type="number" min="0" placeholder="可不填" /></label><label>分配日期<input v-model="form.assign_date" type="date" /></label><label>店铺<select v-model="form.shop_name"><option value="">全部店铺（不显示均价）</option><option v-for="s in options.shops" :key="s" :value="s">{{ s }}</option></select></label><label>仓库<select v-model="form.warehouse_name"><option value="">全部仓库</option><option v-for="w in options.warehouses" :key="w" :value="w">{{ w }}</option></select></label><label class="full">管理员任务要求<textarea v-model="form.manager_note" placeholder="任务要求创建后负责人不能修改"></textarea></label></div><div v-if="createError" class="api-error compact">{{ createError }}</div><div class="modal-actions"><button class="rank-tab" @click="createOpen=false">取消</button><button class="rank-tab active" :disabled="creating" @click="submitCreate">{{ creating?'创建中…':'创建待办' }}</button></div></div></div>
  </div>
</template>
