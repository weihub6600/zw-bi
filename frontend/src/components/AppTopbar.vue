<script setup>
import { Moon, Sun, LogOut, ChevronDown } from 'lucide-vue-next'
import { useRoute, useRouter } from 'vue-router'
import { useUiStore } from '../stores/ui'
import { useAuthStore } from '../stores/auth'
import { useFilterStore } from '../stores/filter'
const ui=useUiStore(),auth=useAuthStore(),filters=useFilterStore(),router=useRouter(),route=useRoute()
function changeDepartment(e){const code=e.target.value;const m=auth.memberships.find(x=>x.code===code);auth.setDepartment(code);filters.setDepartment(code,m?.name||'')}
async function signOut(){await auth.logout();router.replace('/login')}
</script>
<template>
  <header class="topbar">
    <div class="topbar-heading-row">
      <div class="topbar-route-title">{{ route.meta.title || '百嘉瑞 BI' }}</div>
      <span class="topbar-separator"></span>
      <div class="topbar-workspace-inline">
        <template v-if="auth.memberships.length>1">
          <select :value="auth.departmentCode" @change="changeDepartment"><option v-for="m in auth.memberships" :key="m.code" :value="m.code">{{ m.name }}</option></select><ChevronDown :size="13"/>
        </template>
        <span v-else class="topbar-dept-chip">{{ auth.departmentName }}</span>
      </div>
    </div>
    <div class="topbar-actions">
      <button class="icon-button" @click="ui.toggleTheme" title="切换深浅背景"><Sun v-if="ui.theme==='dark'" :size="18"/><Moon v-else :size="18"/></button>
      <div class="user-chip"><span>{{ auth.user?.username }}</span><small>{{ auth.roleLabel }}</small></div>
      <button class="icon-button" @click="signOut" title="退出登录"><LogOut :size="17"/></button>
    </div>
  </header>
</template>
