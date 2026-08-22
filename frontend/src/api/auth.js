import { apiRequest } from './http'
export const login=(loginKey,password,remember=false)=>apiRequest('/api/auth/login',{method:'POST',body:{login_key:loginKey,password,remember}})
export const fetchMe=()=>apiRequest('/api/auth/me')
export const heartbeat=()=>apiRequest('/api/auth/heartbeat',{method:'POST'})
export const logout=()=>apiRequest('/api/auth/logout',{method:'POST'})
