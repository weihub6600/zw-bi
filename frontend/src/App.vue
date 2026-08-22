<script setup>
import { onBeforeUnmount, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AppSidebar from './components/AppSidebar.vue'
import AppTopbar from './components/AppTopbar.vue'
import { useAuthStore } from './stores/auth'
const route=useRoute(),router=useRouter(),auth=useAuthStore()
function required(){auth.user=null;auth.loaded=true;if(route.path!=='/login')router.replace({path:'/login',query:{redirect:route.fullPath}})}
onMounted(()=>window.addEventListener('bjr:auth-required',required))
onBeforeUnmount(()=>window.removeEventListener('bjr:auth-required',required))
</script>
<template>
  <router-view v-if="route.meta.public" />
  <div v-else class="app-shell">
    <AppSidebar />
    <main class="app-main"><AppTopbar /><router-view /></main>
  </div>
</template>
