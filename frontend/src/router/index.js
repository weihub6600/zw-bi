import { createRouter, createWebHistory } from 'vue-router'
import DashboardView from '../views/DashboardView.vue'
import ProductView from '../views/ProductView.vue'
import InventoryView from '../views/InventoryView.vue'
import ExpiryView from '../views/ExpiryView.vue'
import TodoView from '../views/TodoView.vue'
import DataCenterView from '../views/DataCenterView.vue'
import SettingsView from '../views/SettingsView.vue'
import LoginView from '../views/LoginView.vue'
import SetupView from '../views/SetupView.vue'
import TcCalculatorView from '../views/TcCalculatorView.vue'
import JpCalculatorView from '../views/JpCalculatorView.vue'
import YunCangCalculatorView from '../views/YunCangCalculatorView.vue'
import { fetchSetupStatus } from '../api/setup'
import { useAuthStore } from '../stores/auth'
const routes=[
  {path:'/setup',component:SetupView,meta:{public:true,setup:true,title:'初始化'}},
  {path:'/login',component:LoginView,meta:{public:true,title:'登录'}},
  {path:'/',component:DashboardView,meta:{title:'经营总览'}},
  {path:'/product',component:ProductView,meta:{title:'商品分析'}},
  {path:'/inventory',component:InventoryView,meta:{title:'库存分析'}},
  {path:'/expiry',component:ExpiryView,meta:{title:'效期批次'}},
  {path:'/todo',component:TodoView,meta:{title:'待办任务'}},
  {path:'/data-center',component:DataCenterView,meta:{title:'数据中心'}},
  {path:'/tools/tc',component:TcCalculatorView,meta:{title:'TC计算器'}},
  {path:'/tools/jp',component:JpCalculatorView,meta:{title:'京配计算器'}},
  {path:'/tools/yuncang',component:YunCangCalculatorView,meta:{title:'云仓计算器'}},
  {path:'/settings',component:SettingsView,meta:{title:'系统设置'}}
]
const router=createRouter({history:createWebHistory(),routes})
router.beforeEach(async to=>{
  let setup
  try{setup=await fetchSetupStatus()}catch{setup={initialized:true}}
  if(!setup.initialized&&to.path!=='/setup')return '/setup'
  if(setup.initialized&&to.path==='/setup')return '/login'
  const auth=useAuthStore();await auth.bootstrap()
  if(to.meta.public){if(auth.authenticated&&to.path==='/login')return '/';return true}
  if(!auth.authenticated)return {path:'/login',query:{redirect:to.fullPath}}
  if(to.path==='/data-center'&&!auth.capabilities.can_import&&!auth.capabilities.can_download_data)return '/'
  if(to.path==='/settings'&&!auth.capabilities.can_manage_users&&!auth.capabilities.can_manage_expiry_rules)return '/'
  return true
})
export default router
