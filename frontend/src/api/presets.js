import { apiRequest } from './http'
export const fetchPresets=()=>apiRequest('/api/presets')
export const createPreset=body=>apiRequest('/api/presets',{method:'POST',body})
export const updatePreset=(id,body)=>apiRequest(`/api/presets/${id}`,{method:'PUT',body})
export const deletePreset=id=>apiRequest(`/api/presets/${id}`,{method:'DELETE'})
