import { apiRequest, currentDepartmentCode } from './http'
function dc(params={}){return {department_code:currentDepartmentCode(params.departmentCode),...params,departmentCode:undefined}}
export const fetchTasks=({view='mine',ownerUserId='',status='',productSearch='',departmentCode=''}={})=>apiRequest('/api/tasks',{params:dc({departmentCode,view,owner_user_id:ownerUserId,status,product_search:productSearch})})
export const fetchTaskAssignees=({departmentCode=''}={})=>apiRequest('/api/tasks/assignees',{params:{department_code:currentDepartmentCode(departmentCode)}})
export const createTask=(body,{departmentCode=''}={})=>apiRequest('/api/tasks',{method:'POST',params:{department_code:currentDepartmentCode(departmentCode)},body})
export const saveTaskOwnerNote=(taskNo,note)=>apiRequest(`/api/tasks/${encodeURIComponent(taskNo)}/owner-note`,{method:'PUT',body:{note}})
export const requestTaskDelete=(taskNo,reason)=>apiRequest(`/api/tasks/${encodeURIComponent(taskNo)}/delete-request`,{method:'POST',body:{reason}})
export const withdrawTaskDelete=taskNo=>apiRequest(`/api/tasks/${encodeURIComponent(taskNo)}/delete-withdraw`,{method:'POST'})
export const decideTaskDelete=(taskNo,decision)=>apiRequest(`/api/tasks/${encodeURIComponent(taskNo)}/delete-decision`,{method:'POST',body:{decision}})
