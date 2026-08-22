<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import {
  Ban, CalendarDays, Check, ChevronDown, Plus, Search, Settings2,
  SlidersHorizontal, Store, Tags, Warehouse, X
} from 'lucide-vue-next'
import { useFilterStore } from '../stores/filter'

const props=defineProps({
  shopOptions:{type:Array,default:()=>[]},
  warehouseOptions:{type:Array,default:()=>[]},
  loadingOptions:{type:Boolean,default:false},
  showDate:{type:Boolean,default:true}
})
const f=useFilterStore(),manage=ref(false),modal=ref(false),saving=ref(false),error=ref('')
const shopQuery=ref(''),warehouseQuery=ref('')
const form=reactive({id:null,name:'',shops:[],warehouses:[],productCodes:'',includeName:'',excludeName:''})
const filteredShops=computed(()=>props.shopOptions.filter(x=>String(x).toLowerCase().includes(shopQuery.value.trim().toLowerCase())))
const filteredWarehouses=computed(()=>props.warehouseOptions.filter(x=>String(x).toLowerCase().includes(warehouseQuery.value.trim().toLowerCase())))
const activeConditionCount=computed(()=>[
  props.showDate&&f.dateRange!=='30d',f.shops.length>0,f.warehouses.length>0,Boolean(f.productSearch),f.productCodes.length>0,Boolean(f.includeName),Boolean(f.excludeName)
].filter(Boolean).length)
const datePresets=[['1d','昨天'],['7d','7天'],['14d','14天'],['30d','30天'],['custom','自定义']]

function split(v){return String(v||'').split(/[,，\s]+/).map(x=>x.trim()).filter(Boolean)}
function optionSummary(values,allLabel){if(!values.length)return allLabel;if(values.length===1)return values[0];return `已选 ${values.length} 项`}
function setDateRange(v){f.dateRange=v;if(v!=='custom'){f.customStart='';f.customEnd=''}}
function clearFilters(){f.dateRange='30d';f.customStart='';f.customEnd='';f.shops=[];f.warehouses=[];f.productSearch='';f.productCodes=[];f.includeName='';f.excludeName='';f.activePreset='全部';f.activePresetId=null}
function openNew(){Object.assign(form,{id:null,name:'',shops:[...f.shops],warehouses:[...f.warehouses],productCodes:f.productCodes.join('\n'),includeName:f.includeName,excludeName:f.excludeName});error.value='';modal.value=true}
function openEdit(p){Object.assign(form,{id:p.id,name:p.name,shops:[...(p.shops||[])],warehouses:[...(p.warehouses||[])],productCodes:(p.product_codes||[]).join('\n'),includeName:(p.include_name_keywords||[]).join(','),excludeName:(p.exclude_name_keywords||[]).join(',')});error.value='';modal.value=true}
async function save(){saving.value=true;error.value='';try{await f.savePreset({id:form.id,name:form.name,payload:{name:form.name,shops:form.shops,warehouses:form.warehouses,product_codes:split(form.productCodes),include_name_keywords:split(form.includeName),exclude_name_keywords:split(form.excludeName)}});modal.value=false}catch(e){error.value=e.message}finally{saving.value=false}}
async function remove(p){if(!confirm(`确定删除个人筛选预设“${p.name}”吗？`))return;try{await f.deletePreset(p.id)}catch(e){alert(e.message)}}
onMounted(()=>f.loadPresets())
</script>

<template>
  <section class="filter-shell filter-shell-v153">
    <div class="filter-head">
      <div class="filter-head-title">
        <span class="filter-head-icon"><SlidersHorizontal :size="18"/></span>
        <div><b>筛选工作台</b><small>{{ activeConditionCount ? `已启用 ${activeConditionCount} 组条件` : '30天 · 全部店铺 · 全部仓库' }}</small></div>
      </div>
      <div class="filter-head-actions">
        <button v-if="activeConditionCount" class="filter-ghost" @click="clearFilters"><X :size="15"/>重置</button>
        <button class="filter-ghost" :class="{active:manage}" @click="manage=!manage"><Settings2 :size="15"/>{{ manage?'完成':'管理预设' }}</button>
      </div>
    </div>

    <div v-if="showDate" class="filter-date-row">
      <div class="filter-date-title"><CalendarDays :size="16"/><span>销售日期</span></div>
      <div class="date-segmented">
        <button v-for="[value,label] in datePresets" :key="value" :class="{active:f.dateRange===value}" @click="setDateRange(value)">{{ label }}</button>
      </div>
      <div v-if="f.dateRange==='custom'" class="custom-date-range">
        <input v-model="f.customStart" type="date" aria-label="开始日期"/><span>至</span><input v-model="f.customEnd" type="date" aria-label="结束日期"/>
      </div>
      <div class="filter-date-current">{{ f.dateLabel }}</div>
    </div>

    <div class="preset-strip">
      <span class="preset-caption">个人预设</span>
      <button :class="['preset-chip',{active:f.activePreset==='全部'}]" @click="f.applyPreset('全部')"><Check v-if="f.activePreset==='全部'" :size="13"/>全部</button>
      <span v-for="p in f.presets" :key="p.id" class="preset-chip-wrap">
        <button :class="['preset-chip',{active:f.activePresetId===p.id}]" @click="f.applyPreset(p)"><Check v-if="f.activePresetId===p.id" :size="13"/>{{ p.name }}</button>
        <span v-if="manage" class="preset-chip-tools"><button title="编辑" @click="openEdit(p)">✎</button><button title="删除" @click="remove(p)">×</button></span>
      </span>
      <button class="preset-chip add" @click="openNew"><Plus :size="13"/>新增</button>
      <span v-if="f.presetsLoading" class="preset-state">读取中…</span><span v-else-if="f.presetError" class="preset-state error">{{ f.presetError }}</span>
    </div>

    <div class="filter-controls filter-controls-v153">
      <details class="filter-dropdown">
        <summary><span class="filter-label"><Store :size="15"/><i>店铺</i></span><b>{{ optionSummary(f.shops,'全部店铺') }}</b><ChevronDown :size="15"/></summary>
        <div class="filter-popover">
          <div class="filter-pop-search"><Search :size="14"/><input v-model="shopQuery" placeholder="搜索店铺"/></div>
          <div class="filter-pop-actions"><button @click.prevent="f.shops=[]">选择全部</button><span>{{ f.shops.length }} 项已选</span></div>
          <div class="filter-check-list"><label v-for="shop in filteredShops" :key="shop"><input v-model="f.shops" type="checkbox" :value="shop" :disabled="loadingOptions"/><span>{{ shop }}</span></label><div v-if="!filteredShops.length" class="filter-empty">没有匹配店铺</div></div>
        </div>
      </details>

      <details class="filter-dropdown">
        <summary><span class="filter-label"><Warehouse :size="15"/><i>仓库</i></span><b>{{ optionSummary(f.warehouses,'全部仓库') }}</b><ChevronDown :size="15"/></summary>
        <div class="filter-popover">
          <div class="filter-pop-search"><Search :size="14"/><input v-model="warehouseQuery" placeholder="搜索仓库"/></div>
          <div class="filter-pop-actions"><button @click.prevent="f.warehouses=[]">选择全部</button><span>{{ f.warehouses.length }} 项已选</span></div>
          <div class="filter-check-list"><label v-for="warehouse in filteredWarehouses" :key="warehouse"><input v-model="f.warehouses" type="checkbox" :value="warehouse" :disabled="loadingOptions"/><span>{{ warehouse }}</span></label><div v-if="!filteredWarehouses.length" class="filter-empty">没有匹配仓库</div></div>
        </div>
      </details>

      <label class="filter-control"><span><Search :size="15"/>商品</span><input v-model="f.productSearch" placeholder="名称 / 商家编码"/></label>
      <label class="filter-control"><span><Tags :size="15"/>商品名包含</span><input v-model="f.includeName" placeholder="例如：泡菜, 海苔"/></label>
      <label class="filter-control"><span><Ban :size="15"/>商品名不包含</span><input v-model="f.excludeName" placeholder="例如：赠品, 测试"/></label>
    </div>

    <div class="filter-foot">
      <span class="filter-scope-dot"></span><template v-if="showDate"><b>{{ f.dateLabel }}</b><span class="filter-divider"></span></template><span>{{ f.shops.length?`${f.shops.length}个店铺`:'全部店铺' }}</span><span>·</span><span>{{ f.warehouses.length?`${f.warehouses.length}个仓库`:'全部仓库' }}</span>
      <template v-if="f.productCodes.length"><span>·</span><span>指定 {{ f.productCodes.length }} 个商家编码</span></template>
      <template v-if="f.includeName"><span>·</span><span>包含“{{ f.includeName }}”</span></template>
      <template v-if="f.excludeName"><span>·</span><span>排除“{{ f.excludeName }}”</span></template>
    </div>

    <div v-if="modal" class="preset-modal-mask" @click.self="modal=false">
      <div class="preset-modal">
        <div class="section-head"><div><h3>{{ form.id?'编辑筛选预设':'新增筛选预设' }}</h3><span>仅当前用户可见，管理员不干预个人预设</span></div><button class="modal-close" @click="modal=false">×</button></div>
        <div class="preset-form-grid">
          <label class="full">预设名称<input v-model.trim="form.name" maxlength="64" placeholder="例如：临期泡菜检查" /></label>
          <label>店铺<select v-model="form.shops" multiple><option v-for="shop in shopOptions" :key="shop" :value="shop">{{ shop }}</option></select></label>
          <label>仓库<select v-model="form.warehouses" multiple><option v-for="warehouse in warehouseOptions" :key="warehouse" :value="warehouse">{{ warehouse }}</option></select></label>
          <label class="full">指定商家编码<textarea v-model="form.productCodes" placeholder="多个编码用逗号、空格或换行分隔"></textarea></label>
          <label>商品名包含<textarea v-model="form.includeName" placeholder="泡菜, 海苔"></textarea></label>
          <label>商品名不包含<textarea v-model="form.excludeName" placeholder="赠品, 试吃, 测试"></textarea></label>
        </div>
        <div v-if="error" class="api-error compact">{{ error }}</div>
        <div class="modal-actions"><button class="rank-tab" @click="modal=false">取消</button><button class="rank-tab active" :disabled="saving" @click="save">{{ saving?'保存中…':'保存预设' }}</button></div>
      </div>
    </div>
  </section>
</template>
