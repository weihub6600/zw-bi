<script setup>
import { Calculator, ExternalLink } from 'lucide-vue-next'

function openStandalone() {
  window.open('/云仓费用计算器.html', '_blank', 'noopener,noreferrer')
}
</script>

<template>
  <div class="page yun-cang-page">
    <div class="page-title yun-cang-title">
      <div class="yun-cang-heading">
        <span class="yun-cang-icon"><Calculator :size="19" /></span>
        <div><h1>云仓计算器</h1><p>单票试算、批量对账与价卡参数管理</p></div>
      </div>
      <button class="ui-btn ui-btn-ghost" type="button" @click="openStandalone"><ExternalLink :size="15" />独立打开</button>
    </div>
    <section class="panel yun-cang-frame-panel"><iframe title="云仓计算器" src="/云仓费用计算器.html" class="yun-cang-frame" /></section>
  </div>
</template>

<style scoped>
.yun-cang-page{max-width:1440px;padding-bottom:24px}.yun-cang-title{display:flex;align-items:center;justify-content:space-between;gap:18px;margin-bottom:16px}.yun-cang-heading{display:flex;align-items:center;gap:12px}.yun-cang-icon{width:42px;height:42px;border-radius:13px;display:grid;place-items:center;color:#fff;background:linear-gradient(145deg,#2f54eb,#16a3a3);box-shadow:0 9px 22px rgba(47,84,235,.2)}.yun-cang-title h1{font-size:25px;letter-spacing:-.02em}.yun-cang-title p{margin:5px 0 0;color:var(--muted);font-size:12px}.yun-cang-frame-panel{padding:0;overflow:hidden;border-radius:16px}.yun-cang-frame{display:block;width:100%;height:calc(100vh - 150px);min-height:760px;border:0;background:#f4f6fa}@media(max-width:700px){.yun-cang-title{align-items:flex-start;flex-direction:column}.yun-cang-frame{height:calc(100vh - 180px);min-height:720px}}
</style>
