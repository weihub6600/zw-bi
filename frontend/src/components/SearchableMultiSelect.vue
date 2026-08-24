<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

const props = defineProps({
  modelValue: { type: Array, default: () => [] },
  options: { type: Array, default: () => [] },
  placeholder: { type: String, default: '请选择' },
  searchPlaceholder: { type: String, default: '搜索' },
})
const emit = defineEmits(['update:modelValue'])

const open = ref(false)
const search = ref('')
const triggerEl = ref(null)
const dropPos = ref({ top: 0, left: 0, width: 0 })

// 规范化 options 为 {value, label}
const normalized = computed(() =>
  props.options.map((it) => {
    if (it && typeof it === 'object' && ('value' in it || 'id' in it)) {
      return {
        value: it.value ?? it.id,
        label: it.label ?? it.name ?? it.shop_name ?? it.warehouse_name ?? String(it.value ?? it.id),
      }
    }
    return { value: it, label: String(it) }
  })
)

const filtered = computed(() => {
  const q = search.value.trim().toLowerCase()
  if (!q) return normalized.value
  return normalized.value.filter((it) => String(it.label).toLowerCase().includes(q))
})

const selected = computed(() => new Set(props.modelValue.map((v) => v)))

function toggle(v) {
  const arr = [...props.modelValue]
  const i = arr.indexOf(v)
  if (i >= 0) arr.splice(i, 1)
  else arr.push(v)
  emit('update:modelValue', arr)
}

function clearAll() {
  emit('update:modelValue', [])
}

function summary() {
  const n = props.modelValue.length
  if (n === 0) return ''
  const labels = normalized.value.filter((it) => selected.value.has(it.value)).map((it) => it.label)
  if (n === 1) return labels[0]
  if (n <= 3) return labels.join('、')
  return `${labels.slice(0, 2).join('、')} +${n - 2}`
}

function toggleOpen() {
  if (!open.value) {
    const r = triggerEl.value.getBoundingClientRect()
    dropPos.value = { top: r.bottom + 4, left: r.left, width: r.width }
  }
  open.value = !open.value
}

function onClickOutside(e) {
  if (!open.value) return
  // Teleport 到 body 后，下拉(.sms-drop)已不在 .sms-root 内，需同时判定两者。
  if (e.target.closest('.sms-root, .sms-drop')) return
  open.value = false
}

function onResize() {
  open.value = false
}

onMounted(() => {
  document.addEventListener('click', onClickOutside)
  window.addEventListener('resize', onResize)
})
onBeforeUnmount(() => {
  document.removeEventListener('click', onClickOutside)
  window.removeEventListener('resize', onResize)
})
</script>

<template>
  <div class="sms-root" ref="triggerEl">
    <button type="button" class="sms-trigger" @click="toggleOpen">
      <span v-if="summary()" class="sms-trigger-text" :title="normalized.filter(it => selected.has(it.value)).map(it => it.label).join('、')">{{ summary() }}</span>
      <span v-else class="sms-trigger-text sms-placeholder">{{ placeholder }}</span>
      <span class="sms-count" v-if="modelValue.length">已选 {{ modelValue.length }}</span>
      <span class="sms-arrow" :class="{ open }">▾</span>
    </button>

    <Teleport to="body">
      <div
        v-if="open"
        class="sms-drop"
        :style="{ top: dropPos.top + 'px', left: dropPos.left + 'px', width: dropPos.width + 'px' }"
      >
        <input v-model="search" class="sms-search" :placeholder="searchPlaceholder" />
        <div class="sms-list">
          <label v-for="it in filtered" :key="it.value" class="sms-option" :title="it.label">
            <input type="checkbox" :checked="selected.has(it.value)" @change="toggle(it.value)" />
            <span class="sms-option-label">{{ it.label }}</span>
          </label>
          <div v-if="!filtered.length" class="sms-empty">无匹配</div>
        </div>
        <button type="button" class="sms-clear" @click="clearAll">清空已选</button>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.sms-root { position: relative; width: 100%; min-width: 0; }
.sms-trigger {
  display: flex; align-items: center; gap: 8px; width: 100%; min-width: 0; min-height: 38px;
  padding: 6px 10px; border: 1px solid #e2e8f0; border-radius: 8px; background: #fff;
  cursor: pointer; text-align: left; font-size: 13px; color: #334155;
  overflow: hidden;
}
.sms-trigger-text { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; text-align: left; }
.sms-placeholder { color: #94a3b8; }
.sms-count { flex-shrink: 0; font-size: 12px; color: #2563eb; background: #eef2ff; padding: 1px 8px; border-radius: 999px; }
.sms-arrow { flex-shrink: 0; color: #94a3b8; transition: transform .15s; }
.sms-arrow.open { transform: rotate(180deg); }

.sms-drop {
  position: fixed; z-index: 2000; background: #fff; border: 1px solid #e2e8f0;
  border-radius: 8px; box-shadow: 0 10px 30px rgba(15,23,42,.18); overflow: hidden;
  display: flex; flex-direction: column;
}
.sms-search { width: 100%; box-sizing: border-box; padding: 8px 10px; border: none; border-bottom: 1px solid #f1f5f9; outline: none; font-size: 13px; }
.sms-list { max-height: 240px; overflow-y: auto; overflow-x: hidden; flex-shrink: 1; min-height: 0; }
.sms-option {
  display: flex; align-items: center; justify-content: flex-start; gap: 8px;
  width: 100%; min-height: 36px; padding: 6px 10px; cursor: pointer; font-size: 13px; color: #334155;
  box-sizing: border-box;
}
.sms-option:hover { background: #f8fafc; }
.sms-option input[type="checkbox"] { flex: 0 0 auto; margin: 0; }
.sms-option-label { flex: 1; min-width: 0; text-align: left; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.sms-empty { padding: 12px; text-align: center; color: #94a3b8; font-size: 12px; }
.sms-clear { width: 100%; padding: 6px; border: none; border-top: 1px solid #f1f5f9; background: #f8fafc; color: #dc2626; font-size: 12px; cursor: pointer; }
</style>
