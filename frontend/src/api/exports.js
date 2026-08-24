/**
 * 下载数据 XLSX 文件。通过 fetch 获取 blob 并触发浏览器下载。
 * @param {Object} opts { path, params }
 */
async function downloadFile({ path, params }) {
  const q = new URLSearchParams()
  Object.entries(params || {}).forEach(([k, v]) => {
    if (v === undefined || v === null || v === '') return
    q.set(k, String(v))
  })
  const suffix = q.toString() ? `?${q}` : ''
  const res = await fetch(`${path}${suffix}`, { method: 'GET', credentials: 'include' })
  if (res.status === 401) window.dispatchEvent(new CustomEvent('bjr:auth-required'))
  if (!res.ok) {
    let detail = `HTTP ${res.status}`
    try {
      const p = await res.json()
      detail = typeof p.detail === 'string' ? p.detail : JSON.stringify(p.detail || p)
    } catch { /* ignore */ }
    const err = new Error(detail)
    err.status = res.status
    throw err
  }
  const disposition = res.headers.get('Content-Disposition') || ''
  const match = disposition.match(/filename="?([^";]+)"?/)
  let filename = match ? match[1] : 'download.xlsx'
  const rowCount = Number(res.headers.get('X-Export-Row-Count') || 0) || 0
  const blob = await res.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
  return { filename, rowCount }
}

export function exportProduct(departmentCode) {
  return downloadFile({ path: '/api/exports/product', params: { department_code: departmentCode } })
}

export function exportSales({ departmentCode, startDate, endDate, shops, warehouses, productSearch, includeName, excludeName, productCodes }) {
  return downloadFile({
    path: '/api/exports/sales',
    params: {
      department_code: departmentCode,
      start_date: startDate,
      end_date: endDate,
      shops: (shops || []).join(','),
      warehouses: (warehouses || []).join(','),
      product_search: productSearch,
      include_name: includeName,
      exclude_name: excludeName,
      product_codes: (productCodes || []).join(','),
    },
  })
}

export function exportInventory(departmentCode) {
  return downloadFile({ path: '/api/exports/inventory', params: { department_code: departmentCode } })
}

export function exportAging(departmentCode) {
  return downloadFile({ path: '/api/exports/aging', params: { department_code: departmentCode } })
}

export function exportInventoryAnalysis({ departmentCode, warehouses, productSearch, includeName, excludeName, productCodes, category }) {
  return downloadFile({
    path: '/api/exports/inventory-analysis',
    params: {
      department_code: departmentCode,
      warehouses: (warehouses || []).join(','),
      product_search: productSearch,
      include_name: includeName,
      exclude_name: excludeName,
      product_codes: (productCodes || []).join(','),
      category: category || '',
    },
  })
}

export function exportExpiryBatches({ departmentCode, warehouses, productSearch, includeName, excludeName, productCodes, statuses, remainingDaysMin, remainingDaysMax, remainingPctMin, remainingPctMax }) {
  return downloadFile({
    path: '/api/exports/expiry-batches',
    params: {
      department_code: departmentCode,
      warehouses: (warehouses || []).join(','),
      product_search: productSearch,
      include_name: includeName,
      exclude_name: excludeName,
      product_codes: (productCodes || []).join(','),
      statuses: (statuses || []).join(','),
      remaining_days_min: remainingDaysMin,
      remaining_days_max: remainingDaysMax,
      remaining_pct_min: remainingPctMin,
      remaining_pct_max: remainingPctMax,
    },
  })
}
