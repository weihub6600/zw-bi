<script setup>
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { BarChart3, LockKeyhole, ShieldCheck } from 'lucide-vue-next'
import { useAuthStore } from '../stores/auth'
const auth=useAuthStore(),route=useRoute(),router=useRouter()
const loginKey=ref(''),password=ref(''),remember=ref(false),loading=ref(false),error=ref('')
async function submit(){loading.value=true;error.value='';try{await auth.login(loginKey.value,password.value,remember.value);router.replace(String(route.query.redirect||'/'))}catch(e){error.value=e.message}finally{loading.value=false}}
</script>
<template>
  <div class="login-page">
    <div class="login-card">
      <div class="login-brand"><div class="login-logo"><BarChart3 :size="25" /></div><div><strong>百嘉瑞 BI</strong><span>局域网经营分析与任务协作</span></div></div>
      <div class="login-copy"><h1>登录工作台</h1><p>支持使用 user_id 或用户名登录。账号身份由本地NAS和服务器 Session 校验。</p></div>
      <form class="login-form" @submit.prevent="submit">
        <label>user_id / 用户名<input v-model.trim="loginKey" autocomplete="username" placeholder="请输入账号" required /></label>
        <label>密码<input v-model="password" type="password" autocomplete="current-password" placeholder="请输入密码" required /></label>
        <label class="login-remember"><input v-model="remember" type="checkbox" />保持登录 7 天</label>
        <div v-if="error" class="login-error">{{ error }}</div>
        <button :disabled="loading"><LockKeyhole :size="17" />{{ loading?'正在登录…':'登录' }}</button>
      </form>
      <div class="login-security"><ShieldCheck :size="16" /><span>仅连接百嘉瑞BI本地后端与本地NAS，不连接旺店通/WMS 外部 OpenAPI。</span></div>
    </div>
  </div>
</template>
