export function currentDepartmentCode(explicit='') {
  return explicit || localStorage.getItem('bjr_department_code') || 'B2C'
}

function append(params,key,value){
  if(value===undefined||value===null||value==='')return
  if(Array.isArray(value)){for(const v of value)params.append(key,String(v))}else params.set(key,String(value))
}

export async function apiRequest(path,{method='GET',params={},body,form}={}){
  const q=new URLSearchParams()
  Object.entries(params||{}).forEach(([k,v])=>append(q,k,v))
  const suffix=q.toString()?`?${q}`:''
  const headers={Accept:'application/json'}
  let requestBody
  if(form) requestBody=form
  else if(body!==undefined){headers['Content-Type']='application/json';requestBody=JSON.stringify(body)}
  const res=await fetch(`${path}${suffix}`,{method,headers,body:requestBody,credentials:'include'})
  if(res.status===401){window.dispatchEvent(new CustomEvent('bjr:auth-required'))}
  if(!res.ok){
    let detail=`HTTP ${res.status}`
    let code=null
    try{
      const p=await res.json()
      if(typeof p.detail==='string'){detail=p.detail}
      else if(p.detail&&typeof p.detail==='object'){detail=p.detail.message||JSON.stringify(p.detail);code=p.detail.code||null}
      else{detail=JSON.stringify(p.detail||p)}
    }catch{}
    const err=new Error(detail);err.status=res.status;if(code)err.code=code;throw err
  }
  if(res.status===204)return null
  return res.json()
}
