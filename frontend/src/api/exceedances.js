import http, { toParams } from './client.js'

export const listExceedances = (params) => http.get('/exceedances', { params: toParams(params) })
export const getExceedance = (id) => http.get(`/exceedances/${id}`)
export const annotateExceedance = (id, payload) => http.patch(`/exceedances/${id}`, payload)
export const batchAnnotate = (payload) => http.post('/exceedances/annotations', payload)
export const exceedanceSummary = (params) =>
  http.get('/exceedances/summary', { params: toParams(params) })
export const exceedanceOptions = () => http.get('/exceedances/options')
export const exportExceedancesUrl = (params) =>
  `/exceedances/export?${new URLSearchParams(toParams(params)).toString()}`

// ---- 超标等级人工修正 ----------------------------------------------------

export const correctExceedanceLevel = (id, payload) =>
  http.post(`/exceedances/${id}/corrections`, payload)
export const batchCorrectLevels = (payload) => http.post('/exceedances/corrections/batch', payload)
export const listCorrections = (params) =>
  http.get('/exceedances/corrections', { params: toParams(params) })
export const exportCorrectionsUrl = (params) =>
  `/exceedances/corrections/export?${new URLSearchParams(toParams(params)).toString()}`

// ---- 已对外公布的月份 ----------------------------------------------------

export const listPublications = () => http.get('/exceedances/publications')
export const publishMonth = (payload) => http.post('/exceedances/publications', payload)
