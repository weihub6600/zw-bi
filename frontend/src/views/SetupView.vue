<script setup>
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Database, ShieldCheck, ArrowRight } from 'lucide-vue-next'
import { initializeSystem } from '../api/setup'
const router=useRouter(),loading=ref(false),error=ref('')
const form=reactive({department_code:'B2C',department_name:'B2C事业部',admin_user_id:'SYS0001',admin_username:'admin',admin_password:''})
async function submit(){error.value='';loading.value=true;try{await initializeSystem({...form});router.replace('/login')}catch(e){error.value=e.message}finally{loading.value=false}}
</script>
<template><div class="setup-page"><section class="setup-card"><div class="setup-brand"><div class="setup-logo"><Database :size="23"/></div><div><strong>百嘉瑞 BI</strong><span>首次部署初始化</span></div></div><div class="setup-copy"><h1>初始化本地系统</h1><p>只创建百嘉瑞BI本地 MySQL 数据库中的首个部门和系统管理员；不会连接旺店通/WMS 外部 OpenAPI。</p></div><div v-if="error" class="login-error">{{error}}</div><form class="setup-form" @submit.prevent="submit"><div class="setup-grid"><label>首个部门编码<input v-model="form.department_code" required/></label><label>首个部门名称<input v-model="form.department_name" required/></label><label>系统管理员 user_id<input v-model="form.admin_user_id" required/></label><label>系统管理员用户名<input v-model="form.admin_username" required/></label><label class="wide">系统管理员密码<input v-model="form.admin_password" type="password" minlength="8" autocomplete="new-password" required/></label></div><div class="setup-security"><ShieldCheck :size="16"/><span>初始化成功后此接口自动关闭；后续部门和管理员统一在“系统设置”中管理。</span></div><button :disabled="loading"><span>{{loading?'初始化中…':'完成初始化'}}</span><ArrowRight :size="17"/></button></form></section></div></template>
