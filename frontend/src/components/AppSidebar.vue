<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { fetchLatestBusinessDate } from '../api/imports'
import { fetchTasks } from '../api/tasks'
import { useAuthStore } from '../stores/auth'
import { LayoutDashboard, PackageSearch, Warehouse, CalendarClock, ListTodo, Database, Wrench, Settings, Truck, Calculator } from 'lucide-vue-next'
const auth=useAuthStore()
const items=computed(()=>[
  ['/', '经营总览', LayoutDashboard,true],['/product','商品分析',PackageSearch,true],['/inventory','库存分析',Warehouse,true],['/expiry','效期批次',CalendarClock,true],['/todo','待办任务',ListTodo,true],
  ['/data-center','数据中心',Database,!!(auth.capabilities.can_import||auth.capabilities.can_download_data)],['/settings','系统设置',Settings,!!(auth.capabilities.can_manage_users||auth.capabilities.can_manage_expiry_rules)]
].filter(x=>x[3]))
const latestText=ref('最新数据统计自—'),todoCount=ref(0)
function cnDate(v){if(!v)return '最新数据统计自—';const [y,m,d]=v.split('-').map(Number);return `最新数据统计自${y}年${m}月${d}日`}
function onTodoCount(e){todoCount.value=Number(e.detail||0)}
function onDataDateChanged(e){latestText.value=cnDate(e.detail||'')}
async function reloadContext(){try{latestText.value=cnDate((await fetchLatestBusinessDate({departmentCode:auth.departmentCode})).latest_business_date)}catch{latestText.value='最新数据统计自—'}try{const t=await fetchTasks({view:'mine',departmentCode:auth.departmentCode});todoCount.value=t.meta?.mine_incomplete_count||0}catch{todoCount.value=0}}
function deptChanged(){reloadContext()}
onMounted(async()=>{window.addEventListener('bjr:todo-count',onTodoCount);window.addEventListener('bjr:data-date-changed',onDataDateChanged);window.addEventListener('bjr:department-changed',deptChanged);await reloadContext()})
onBeforeUnmount(()=>{window.removeEventListener('bjr:todo-count',onTodoCount);window.removeEventListener('bjr:data-date-changed',onDataDateChanged);window.removeEventListener('bjr:department-changed',deptChanged)})
</script>
<template><aside class="sidebar"><div class="brand"><div class="brand-mark">B</div><div><div class="brand-name">百嘉瑞 BI</div><div class="brand-date">{{ latestText }}</div></div></div><nav class="nav-list"><RouterLink v-for="[path,label,Icon] in items" :key="path" :to="path" class="nav-item"><component :is="Icon" :size="18"/><span>{{label}}</span><span v-if="path==='/todo'&&todoCount>0" class="sidebar-badge">{{todoCount}}</span></RouterLink><div class="nav-section-label">更多工具</div><RouterLink to="/tools/tc" class="nav-item"><Wrench :size="18"/><span>TC计算器</span></RouterLink><RouterLink to="/tools/jp" class="nav-item"><Truck :size="18"/><span>京配计算器</span></RouterLink><RouterLink to="/tools/yuncang" class="nav-item"><Calculator :size="18"/><span>云仓计算器</span></RouterLink></nav></aside></template>
