import { apiRequest } from './http'
export const fetchSetupStatus=()=>apiRequest('/api/setup/status')
export const initializeSystem=body=>apiRequest('/api/setup/initialize',{method:'POST',body})
