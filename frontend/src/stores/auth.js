import { defineStore } from 'pinia'
import * as authApi from '../api/auth'

let heartbeatTimer=null
export const useAuthStore=defineStore('auth',{
  state:()=>({user:null,memberships:[],capabilities:{},loaded:false,loading:false,departmentCode:localStorage.getItem('bjr_department_code')||''}),
  getters:{
    authenticated:s=>!!s.user,
    departmentOptions:s=>s.memberships||[],
    currentMembership:s=>s.memberships.find(x=>x.code===s.departmentCode)||s.memberships[0]||null,
    roleLabel(){if(this.user?.is_system_admin)return '系统管理员';return this.currentMembership?.role==='dept_admin'?'部门管理员':'普通用户'},
    departmentName(){return this.currentMembership?.name||'—'}
  },
  actions:{
    applyProfile(profile){this.user=profile.user;this.memberships=profile.memberships||[];this.capabilities=profile.capabilities||{};const allowed=this.memberships.map(x=>x.code);if(!this.departmentCode||!allowed.includes(this.departmentCode))this.departmentCode=allowed[0]||'';if(this.departmentCode)localStorage.setItem('bjr_department_code',this.departmentCode);this.loaded=true},
    async bootstrap(){if(this.loaded)return;this.loading=true;try{this.applyProfile(await authApi.fetchMe());this.startHeartbeat()}catch{this.user=null;this.memberships=[];this.capabilities={};this.loaded=true}finally{this.loading=false}},
    async login(loginKey,password,remember=false){const p=await authApi.login(loginKey,password,remember);this.applyProfile(p);this.startHeartbeat();return p},
    async logout(){try{await authApi.logout()}catch{}this.stopHeartbeat();this.user=null;this.memberships=[];this.capabilities={};this.loaded=true},
    setDepartment(code){if(!this.memberships.some(x=>x.code===code))return;this.departmentCode=code;localStorage.setItem('bjr_department_code',code);window.dispatchEvent(new CustomEvent('bjr:department-changed',{detail:code}))},
    startHeartbeat(){this.stopHeartbeat();heartbeatTimer=setInterval(()=>authApi.heartbeat().catch(()=>{}),5*60*1000)},
    stopHeartbeat(){if(heartbeatTimer)clearInterval(heartbeatTimer);heartbeatTimer=null}
  }
})
