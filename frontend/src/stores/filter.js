import { defineStore } from 'pinia'
import { createPreset, deletePreset as apiDeletePreset, fetchPresets, updatePreset } from '../api/presets'

function joinKeywords(values=[]){return values.join(',')}
function splitKeywords(text=''){return String(text).split(/[,，\s]+/).map(x=>x.trim()).filter(Boolean)}

export const useFilterStore = defineStore('filter', {
  state: () => ({
    department: 'B2C事业部', departmentCode: localStorage.getItem('bjr_department_code') || 'B2C',
    dateRange: '30d', customStart: '', customEnd: '',
    shops: [], warehouses: [], productSearch: '', productCodes: [], productCategoryIds: [], includeName: '', excludeName: '',
    activePreset: '全部', activePresetId: null,
    presets: [], presetsLoaded:false, presetsLoading:false, presetError:''
  }),
  getters: {
    singleShop: s => s.shops.length === 1,
    dateParams: s => {
      if (s.dateRange === 'custom') return { days:30, startDate:s.customStart, endDate:s.customEnd }
      return { days:Number(String(s.dateRange).replace('d','')) || 30, startDate:'', endDate:'' }
    },
    dateLabel: s => {
      if (s.dateRange === '1d') return '昨天'
      if (s.dateRange === '7d') return '近7天'
      if (s.dateRange === '14d') return '近14天'
      if (s.dateRange === '30d') return '近30天'
      if (s.dateRange === 'custom') return s.customStart && s.customEnd ? `${s.customStart} 至 ${s.customEnd}` : '自定义区间'
      return '近30天'
    }
  },
  actions: {
    setDepartment(code,name='') { this.departmentCode=code; if(name)this.department=name; this.resetAll() },
    resetAll() {
      this.shops=[];this.warehouses=[];this.productSearch='';this.productCodes=[];this.productCategoryIds=[];this.includeName='';this.excludeName='';this.activePreset='全部';this.activePresetId=null
    },
    applyPreset(preset) {
      if(!preset || preset==='全部' || preset.name==='全部') return this.resetAll()
      const p=typeof preset==='string'?this.presets.find(x=>x.name===preset):preset
      if(!p)return
      this.activePreset=p.name;this.activePresetId=p.id
      this.shops=[...(p.shops||[])];this.warehouses=[...(p.warehouses||[])];this.productCodes=[...(p.product_codes||[])];this.productCategoryIds=[...(p.product_category_ids||[])]
      this.includeName=joinKeywords(p.include_name_keywords||[]);this.excludeName=joinKeywords(p.exclude_name_keywords||[])
    },
    currentPayload(name){return {name,shops:[...this.shops],warehouses:[...this.warehouses],product_codes:[...this.productCodes],product_category_ids:[...this.productCategoryIds],include_name_keywords:splitKeywords(this.includeName),exclude_name_keywords:splitKeywords(this.excludeName)}},
    async loadPresets(force=false){
      if(this.presetsLoaded&&!force)return
      this.presetsLoading=true;this.presetError=''
      try{const r=await fetchPresets();this.presets=r.rows||[];this.presetsLoaded=true}
      catch(e){this.presetError=e.message}
      finally{this.presetsLoading=false}
    },
    async savePreset({id=null,name,payload=null}){
      const body=payload||this.currentPayload(name)
      const saved=id?await updatePreset(id,body):await createPreset(body)
      await this.loadPresets(true);this.applyPreset(saved);return saved
    },
    async deletePreset(id){
      const p=this.presets.find(x=>x.id===id);await apiDeletePreset(id)
      if(this.activePresetId===id || (p&&this.activePreset===p.name))this.resetAll()
      await this.loadPresets(true)
    }
  }
})
