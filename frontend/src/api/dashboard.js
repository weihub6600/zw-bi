import { apiRequest, currentDepartmentCode } from './http'
export function fetchDashboardOptions({departmentCode=''}={}){return apiRequest('/api/dashboard/options',{params:{department_code:currentDepartmentCode(departmentCode)}})}
export function fetchDashboardData({departmentCode='',days=30,startDate='',endDate='',shops=[],warehouses=[],productSearch='',includeName='',excludeName='',productCodes=[]}={}){
  return apiRequest('/api/dashboard',{params:{department_code:currentDepartmentCode(departmentCode),days,start_date:startDate||undefined,end_date:endDate||undefined,shops,warehouses,product_search:productSearch,include_name:includeName,exclude_name:excludeName,product_codes:productCodes}})
}
