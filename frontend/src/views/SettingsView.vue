<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { Users, Activity, ShieldCheck, TimerReset, UserPlus, X, Save, RefreshCw, Building2, ScrollText, Plus, Trash2, UserCog } from 'lucide-vue-next'
import { useAuthStore } from '../stores/auth'
import {
  createAdminUser, fetchActivity, fetchAdminUser, fetchAdminUsers, fetchDepartmentExpiryRule, saveDepartmentExpiryRule, updateAdminUser,
  fetchDepartments, createDepartment, updateDepartment, deleteDepartment, fetchDepartmentMembers, saveMembership, deleteMembership, fetchAuditLogs
} from '../api/admin'

const auth=useAuthStore(),tab=ref('users'),loading=ref(false),error=ref('')
const users=ref([]),activity=ref({summary:{},items:[]}),search=ref(''),role=ref(''),membershipStatus=ref('')
const drawer=ref(false),editing=ref(null),detail=ref(null)
const form=reactive({user_id:'',username:'',password:'',role:'member',account_status:'enabled',membership_status:'enabled'})
const rule=reactive({near_days:30,near_pct:10,warn_days:90,warn_pct:25})
const departments=ref([]),deptForm=reactive({code:'',name:''}),memberModal=ref(false),memberDepartment=ref(null),members=ref([]),memberForm=reactive({user_id:'',role:'member',status:'enabled'})
const audit=ref({items:[],actions:[]}),auditFilter=reactive({department_code:'',user_id:'',action_type:'',days:7})
const canGrantAdmin=computed(()=>!!auth.user?.is_system_admin),deptName=computed(()=>auth.departmentName),auditDepartmentOptions=computed(()=>auth.memberships.filter(m=>canGrantAdmin.value||m.role==='dept_admin'))
function presence(v){return {online:'在线',recent:'最近活跃',offline:'离线',inactive:'长期未活跃'}[v]||'—'}
function roleText(v){return v==='dept_admin'?'部门管理员':'普通用户'}
function fmt(v){return v==null?'—':v}
async function loadUsers(){loading.value=true;error.value='';try{const r=await fetchAdminUsers({search:search.value,role:role.value,membershipStatus:membershipStatus.value});users.value=r.items||[]}catch(e){error.value=e.message}finally{loading.value=false}}
async function loadActivity(){loading.value=true;try{activity.value=await fetchActivity()}catch(e){error.value=e.message}finally{loading.value=false}}
async function loadRule(){try{const r=await fetchDepartmentExpiryRule();Object.assign(rule,r.rule||{})}catch(e){error.value=e.message}}
function openCreate(){editing.value=null;detail.value=null;Object.assign(form,{user_id:'',username:'',password:'',role:'member',account_status:'enabled',membership_status:'enabled'});drawer.value=true}
async function openEdit(row){editing.value=row;detail.value=await fetchAdminUser(row.user_id);Object.assign(form,{user_id:row.user_id,username:row.username,password:'',role:row.role,account_status:row.account_status,membership_status:row.membership_status});drawer.value=true}
async function saveUser(){error.value='';try{if(editing.value){const body={username:form.username,membership_status:form.membership_status};if(form.password)body.password=form.password;if(auth.user?.is_system_admin){body.account_status=form.account_status;body.role=form.role}await updateAdminUser(form.user_id,body)}else{await createAdminUser({user_id:form.user_id,username:form.username,password:form.password,role:canGrantAdmin.value?form.role:'member'})}drawer.value=false;await loadUsers()}catch(e){error.value=e.message}}
async function saveRule(){try{await saveDepartmentExpiryRule({...rule});await loadRule()}catch(e){error.value=e.message}}

async function loadDepartments(){if(!canGrantAdmin.value)return;try{const r=await fetchDepartments(true);departments.value=r.items||[]}catch(e){error.value=e.message}}
async function addDepartment(){try{await createDepartment({...deptForm});deptForm.code='';deptForm.name='';await loadDepartments();auth.loaded=false;await auth.bootstrap()}catch(e){error.value=e.message}}
async function toggleDepartment(d){try{await updateDepartment(d.code,{status:d.status==='enabled'?'disabled':'enabled'});await loadDepartments()}catch(e){error.value=e.message}}
async function hardDeleteDepartment(d){if(!confirm(`确定删除空部门“${d.name}”吗？有成员或业务数据的部门会被后端拒绝。`))return;try{await deleteDepartment(d.code);await loadDepartments()}catch(e){error.value=e.message}}
async function openMembers(d){memberDepartment.value=d;memberModal.value=true;memberForm.user_id='';memberForm.role='member';memberForm.status='enabled';await loadMembers()}
async function loadMembers(){if(!memberDepartment.value)return;try{const r=await fetchDepartmentMembers(memberDepartment.value.code);members.value=r.items||[]}catch(e){error.value=e.message}}
async function addMembership(){try{await saveMembership(memberDepartment.value.code,memberForm.user_id,{role:memberForm.role,status:memberForm.status});memberForm.user_id='';await Promise.all([loadMembers(),loadDepartments()])}catch(e){error.value=e.message}}
async function changeMembership(m,key,value){try{await saveMembership(memberDepartment.value.code,m.user_id,{role:key==='role'?value:m.role,status:key==='status'?value:m.membership_status});await loadMembers()}catch(e){error.value=e.message}}
async function removeMembership(m){if(!confirm(`确定将 ${m.username} 从 ${memberDepartment.value.name} 移除吗？`))return;try{await deleteMembership(memberDepartment.value.code,m.user_id);await Promise.all([loadMembers(),loadDepartments()])}catch(e){error.value=e.message}}

async function loadAudit(){try{audit.value=await fetchAuditLogs({departmentCode:auditFilter.department_code,userId:auditFilter.user_id,actionType:auditFilter.action_type,days:auditFilter.days,limit:300})}catch(e){error.value=e.message}}
function detailText(v){if(!v)return '—';if(typeof v==='string')return v;try{return JSON.stringify(v)}catch{return String(v)}}

watch([search,role,membershipStatus],()=>{clearTimeout(window.__bjrUserSearch);window.__bjrUserSearch=setTimeout(loadUsers,250)})
watch(()=>auth.departmentCode,async()=>{await Promise.all([loadUsers(),loadActivity(),loadRule()])})
onMounted(()=>Promise.all([loadUsers(),loadActivity(),loadRule(),loadDepartments()]))
</script>

<template>
<div class="page settings-page">
  <div class="page-title settings-title"><div><h1>系统设置</h1><p>用户、部门、多部门成员关系、活跃、审计和效期规则 · {{deptName}}</p></div><div class="settings-role"><ShieldCheck :size="16"/>{{auth.roleLabel}}</div></div>
  <div v-if="error" class="api-error"><b>操作失败</b><span>{{error}}</span><button @click="error=''">关闭</button></div>
  <div class="settings-tabs-real">
    <button :class="{active:tab==='users'}" @click="tab='users'"><Users :size="16"/>用户与权限</button>
    <button v-if="canGrantAdmin" :class="{active:tab==='departments'}" @click="tab='departments';loadDepartments()"><Building2 :size="16"/>部门管理</button>
    <button :class="{active:tab==='activity'}" @click="tab='activity';loadActivity()"><Activity :size="16"/>用户活跃</button>
    <button :class="{active:tab==='audit'}" @click="tab='audit';loadAudit()"><ScrollText :size="16"/>操作审计</button>
    <button :class="{active:tab==='rules'}" @click="tab='rules';loadRule()"><TimerReset :size="16"/>效期规则</button>
    <button :class="{active:tab==='matrix'}" @click="tab='matrix'"><ShieldCheck :size="16"/>权限矩阵</button>
  </div>

  <template v-if="tab==='users'">
    <section class="panel settings-toolbar"><input v-model="search" placeholder="搜索 user_id / 用户名"/><select v-model="role"><option value="">全部角色</option><option value="dept_admin">部门管理员</option><option value="member">普通用户</option></select><select v-model="membershipStatus"><option value="">全部成员状态</option><option value="enabled">启用</option><option value="disabled">停用</option></select><button class="settings-primary" @click="openCreate"><UserPlus :size="16"/>新增用户</button></section>
    <section class="panel settings-table-wrap"><table><thead><tr><th>用户</th><th>当前部门角色</th><th>成员状态</th><th>全局账号</th><th>最近登录</th><th>最近活跃</th><th>状态</th><th>登录次数</th><th>操作</th></tr></thead><tbody><tr v-for="u in users" :key="u.user_id"><td><strong>{{u.username}}</strong><small>{{u.user_id}}</small></td><td>{{roleText(u.role)}}</td><td>{{u.membership_status==='enabled'?'启用':'停用'}}</td><td>{{u.account_status==='enabled'?'启用':'停用'}}</td><td>{{fmt(u.last_login_time)}}</td><td>{{fmt(u.last_active_time)}}</td><td><span :class="['presence',u.presence]">{{presence(u.presence)}}</span></td><td>{{u.login_count}}</td><td><button class="settings-mini" :disabled="!u.can_edit" @click="openEdit(u)">{{u.can_edit?'编辑':'不可修改'}}</button></td></tr><tr v-if="!users.length&&!loading"><td colspan="9" class="dc-empty">暂无用户</td></tr></tbody></table></section>
  </template>

  <template v-if="tab==='departments'&&canGrantAdmin">
    <section class="panel department-create"><div><h3>部门管理</h3><p>只有系统管理员可以新增、停用、删除部门和分配部门管理员。</p></div><input v-model="deptForm.code" placeholder="部门编码，如 B2B"/><input v-model="deptForm.name" placeholder="部门名称"/><button class="settings-primary" @click="addDepartment"><Plus :size="15"/>新增部门</button></section>
    <section class="panel settings-table-wrap"><table><thead><tr><th>部门</th><th>状态</th><th>成员</th><th>管理员</th><th>最新销量日期</th><th>未完成待办</th><th>操作</th></tr></thead><tbody><tr v-for="d in departments" :key="d.code"><td><strong>{{d.name}}</strong><small>{{d.code}}</small></td><td>{{d.status==='enabled'?'启用':'停用'}}</td><td>{{d.member_count}}</td><td>{{d.admin_count}}</td><td>{{d.latest_sales_date||'—'}}</td><td>{{d.open_task_count}}</td><td><div class="settings-row-actions"><button class="settings-mini" @click="openMembers(d)"><UserCog :size="13"/>成员</button><button class="settings-mini" @click="toggleDepartment(d)">{{d.status==='enabled'?'停用':'启用'}}</button><button class="settings-mini danger" @click="hardDeleteDepartment(d)"><Trash2 :size="13"/>删除</button></div></td></tr></tbody></table></section>
  </template>

  <template v-if="tab==='activity'">
    <div class="settings-kpis"><article><span>今日登录</span><b>{{activity.summary?.today_login||0}}</b></article><article><span>今日活跃</span><b>{{activity.summary?.today_active||0}}</b></article><article><span>7天未登录</span><b>{{activity.summary?.no_login_7d||0}}</b></article><article><span>30天未活跃</span><b>{{activity.summary?.inactive_30d||0}}</b></article></div>
    <section class="panel settings-table-wrap"><div class="section-head"><h3>用户活跃明细</h3><button class="settings-mini" @click="loadActivity"><RefreshCw :size="14"/>刷新</button></div><table><thead><tr><th>用户</th><th>角色</th><th>最近登录</th><th>最近活跃</th><th>状态</th><th>今日操作</th><th>7天操作</th><th>未完成待办</th></tr></thead><tbody><tr v-for="u in activity.items||[]" :key="u.user_id"><td><strong>{{u.username}}</strong><small>{{u.user_id}}</small></td><td>{{roleText(u.role)}}</td><td>{{u.last_login_time||'—'}}</td><td>{{u.last_active_time||'—'}}</td><td><span :class="['presence',u.presence]">{{presence(u.presence)}}</span></td><td>{{u.today_ops}}</td><td>{{u.week_ops}}</td><td>{{u.incomplete_tasks}}</td></tr></tbody></table></section>
  </template>

  <template v-if="tab==='audit'">
    <section class="panel audit-toolbar"><select v-model="auditFilter.department_code"><option value="">{{canGrantAdmin?'全部可见部门':'当前管理部门'}}</option><option v-for="m in auditDepartmentOptions" :key="m.code" :value="m.code">{{m.name}}</option></select><input v-model="auditFilter.user_id" placeholder="user_id（可选）"/><select v-model="auditFilter.action_type"><option value="">全部动作</option><option v-for="a in audit.actions||[]" :key="a" :value="a">{{a}}</option></select><select v-model.number="auditFilter.days"><option :value="1">近1天</option><option :value="7">近7天</option><option :value="30">近30天</option><option :value="90">近90天</option></select><button class="settings-primary" @click="loadAudit"><RefreshCw :size="14"/>查询</button></section>
    <section class="panel settings-table-wrap"><table><thead><tr><th>时间</th><th>用户</th><th>部门</th><th>动作</th><th>详情</th></tr></thead><tbody><tr v-for="x in audit.items||[]" :key="x.id"><td>{{x.created_at}}</td><td><strong>{{x.username}}</strong><small>{{x.user_id}}</small></td><td>{{x.department_name||'系统级'}}</td><td><code>{{x.action_type}}</code></td><td class="audit-detail">{{detailText(x.action_detail)}}</td></tr><tr v-if="!(audit.items||[]).length"><td colspan="5" class="dc-empty">暂无审计记录</td></tr></tbody></table></section>
    <section v-if="canGrantAdmin" class="panel settings-table-wrap audit-login-panel"><div class="section-head"><div><h3>登录安全审计</h3><span>仅系统管理员可见，包含成功/失败登录和来源 IP</span></div></div><table><thead><tr><th>时间</th><th>登录标识</th><th>识别用户</th><th>结果</th><th>IP</th><th>User-Agent</th></tr></thead><tbody><tr v-for="x in audit.login_items||[]" :key="'login-'+x.id"><td>{{x.login_time}}</td><td>{{x.login_key}}</td><td>{{x.username||'未识别'}}<small>{{x.user_id||'—'}}</small></td><td><span :class="['presence',x.result==='success'?'online':'inactive']">{{x.result==='success'?'成功':'失败'}}</span></td><td>{{x.ip_address||'—'}}</td><td class="audit-detail">{{x.user_agent||'—'}}</td></tr></tbody></table></section>
  </template>

  <template v-if="tab==='rules'">
    <section class="settings-rule-grid"><article class="panel"><div class="section-head"><div><h3>{{deptName}}效期规则</h3><span>部门管理员可设置本部门规则</span></div></div><div class="settings-rule-form"><label>临期：剩余天数 ≤<input v-model.number="rule.near_days" type="number" min="0"/></label><label>临期：剩余效期% ≤<input v-model.number="rule.near_pct" type="number" min="0" max="100"/></label><label>预警：剩余天数 ≤<input v-model.number="rule.warn_days" type="number" min="0"/></label><label>预警：剩余效期% ≤<input v-model.number="rule.warn_pct" type="number" min="0" max="100"/></label></div><p class="muted-text">触发逻辑：天数 OR 百分比；满足任一条件即进入对应风险等级。</p><button class="settings-primary" @click="saveRule"><Save :size="16"/>保存部门规则</button></article><article class="panel"><h3>规则优先级</h3><div class="rule-priority-real"><div><b>单品规则</b><span>最高</span></div><i>→</i><div class="active"><b>部门规则</b><span>{{deptName}}</span></div><i>→</i><div><b>全局规则</b><span>系统默认</span></div></div></article></section>
  </template>

  <template v-if="tab==='matrix'"><section class="panel settings-table-wrap"><h3>权限矩阵</h3><table><thead><tr><th>能力</th><th>系统管理员</th><th>部门管理员</th><th>普通用户</th></tr></thead><tbody><tr><td>跨部门查看</td><td>✓</td><td>—</td><td>—</td></tr><tr><td>本部门经营数据</td><td>✓</td><td>✓</td><td>✓</td></tr><tr><td>本部门全部用户待办</td><td>✓</td><td>✓</td><td>—</td></tr><tr><td>审批本部门删除待办</td><td>✓</td><td>✓（不能审批自己）</td><td>—</td></tr><tr><td>Excel/CSV 数据导入</td><td>✓</td><td>✓</td><td><b class="text-error">永久禁止</b></td></tr><tr><td>管理本部门普通用户</td><td>✓</td><td>✓</td><td>—</td></tr><tr><td>新增/删除部门</td><td>✓</td><td>—</td><td>—</td></tr><tr><td>分配多部门/部门管理员</td><td>✓</td><td>—</td><td>—</td></tr><tr><td>操作审计</td><td>✓ 全部</td><td>✓ 自己管理部门</td><td>—</td></tr></tbody></table></section></template>

  <div v-if="drawer" class="settings-modal-mask" @click.self="drawer=false"><div class="settings-modal"><div class="section-head"><div><h3>{{editing?'编辑用户':'新增用户'}}</h3><span>{{editing?'user_id 永久不可修改、不复用':'新增到 '+deptName}}</span></div><button class="icon-button" @click="drawer=false"><X :size="17"/></button></div><div class="settings-edit-grid"><label>user_id<input v-model="form.user_id" :disabled="!!editing" placeholder="如 U0010"/></label><label>用户名<input v-model="form.username"/></label><label>{{editing?'重置密码（留空不改）':'初始密码'}}<input v-model="form.password" type="password" autocomplete="new-password"/></label><label>当前部门角色<select v-model="form.role" :disabled="!canGrantAdmin"><option value="member">普通用户</option><option v-if="canGrantAdmin" value="dept_admin">部门管理员</option></select></label><label v-if="editing">当前部门成员状态<select v-model="form.membership_status"><option value="enabled">启用</option><option value="disabled">停用</option></select></label><label v-if="editing&&auth.user?.is_system_admin">全局账号状态<select v-model="form.account_status"><option value="enabled">启用</option><option value="disabled">停用</option></select></label></div><div class="settings-modal-actions"><button class="settings-mini" @click="drawer=false">取消</button><button class="settings-primary" @click="saveUser"><Save :size="16"/>保存</button></div></div></div>

  <div v-if="memberModal" class="settings-modal-mask" @click.self="memberModal=false"><div class="settings-modal settings-modal-wide"><div class="section-head"><div><h3>{{memberDepartment?.name}} · 成员管理</h3><span>系统管理员可以让同一用户属于多个部门，并为每个部门单独指定角色。</span></div><button class="icon-button" @click="memberModal=false"><X :size="17"/></button></div><div class="member-add-grid"><input v-model="memberForm.user_id" placeholder="已有用户 user_id"/><select v-model="memberForm.role"><option value="member">普通用户</option><option value="dept_admin">部门管理员</option></select><button class="settings-primary" @click="addMembership"><Plus :size="14"/>加入部门</button></div><div class="settings-table-wrap"><table><thead><tr><th>用户</th><th>角色</th><th>成员状态</th><th>全局账号</th><th>操作</th></tr></thead><tbody><tr v-for="m in members" :key="m.user_id"><td><strong>{{m.username}}</strong><small>{{m.user_id}}</small></td><td><select :value="m.role" @change="changeMembership(m,'role',$event.target.value)"><option value="member">普通用户</option><option value="dept_admin">部门管理员</option></select></td><td><select :value="m.membership_status" @change="changeMembership(m,'status',$event.target.value)"><option value="enabled">启用</option><option value="disabled">停用</option></select></td><td>{{m.account_status==='enabled'?'启用':'停用'}}</td><td><button class="settings-mini danger" @click="removeMembership(m)"><Trash2 :size="13"/>移除</button></td></tr></tbody></table></div></div></div>
</div>
</template>
