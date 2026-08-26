import { apiRequest, currentDepartmentCode } from './http'
function makeImportForm({dataType,departmentCode='',businessDate,file}){const form=new FormData();form.set('data_type',dataType);form.set('department_code',currentDepartmentCode(departmentCode));if(businessDate)form.set('business_date',businessDate);form.set('file',file);return form}
export const previewImport=payload=>apiRequest('/api/imports/preview',{method:'POST',form:makeImportForm(payload)})
export const commitImport=payload=>apiRequest('/api/imports/commit',{method:'POST',form:makeImportForm(payload)})
export const fetchRecentImports=({departmentCode='',limit=80}={})=>apiRequest('/api/imports/recent',{params:{department_code:currentDepartmentCode(departmentCode),limit}})
export const fetchImportBatch=batchNo=>apiRequest(`/api/imports/${encodeURIComponent(batchNo)}`)
export const fetchImportIssues=(batchNo,{severity='',limit=200,offset=0}={})=>apiRequest(`/api/imports/${encodeURIComponent(batchNo)}/issues`,{params:{severity,limit,offset}})
export const rollbackImport=batchNo=>apiRequest(`/api/imports/${encodeURIComponent(batchNo)}/rollback`,{method:'POST'})
export const fetchLatestBusinessDate=({departmentCode=''}={})=>apiRequest('/api/imports/latest-business-date',{params:{department_code:currentDepartmentCode(departmentCode)}})
