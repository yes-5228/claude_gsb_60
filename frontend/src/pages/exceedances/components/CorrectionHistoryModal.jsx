import { useCallback, useEffect, useState } from 'react'
import { exportCorrectionsUrl, listCorrections } from '../../../api/exceedances.js'
import Modal from '../../../components/common/Modal.jsx'
import Pagination from '../../../components/common/Pagination.jsx'
import Tag from '../../../components/common/Tag.jsx'
import { Field, Input, Select } from '../../../components/common/FormField.jsx'
import { Alert, Loading } from '../../../components/common/Feedback.jsx'
import { useToast } from '../../../components/common/ToastProvider.jsx'
import { EXCEEDANCE_LEVEL_TONE } from '../../../constants/index.js'
import { downloadFile } from '../../../api/client.js'
import { formatDateTime } from '../../../utils/format.js'

const INITIAL_FILTERS = {
  operator: '',
  pollutant: '',
  cross_published: '',
  date_from: '',
  date_to: ''
}

export default function CorrectionHistoryModal({ open, onClose, exceedanceId }) {
  const toast = useToast()
  const [filters, setFilters] = useState(INITIAL_FILTERS)
  const [applied, setApplied] = useState({ ...INITIAL_FILTERS, exceedanceId: exceedanceId || '' })
  const [page, setPage] = useState(1)
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const payload = await listCorrections({
        ...applied,
        exceedance_id: applied.exceedanceId || undefined,
        page,
        page_size: 10
      })
      setData(payload)
    } catch (err) {
      setError(err)
    } finally {
      setLoading(false)
    }
  }, [applied, page])

  useEffect(() => {
    if (open) load()
  }, [open, load])

  const search = () => {
    setPage(1)
    setApplied({ ...filters, exceedanceId: exceedanceId || '' })
  }

  const reset = () => {
    setFilters(INITIAL_FILTERS)
    setPage(1)
    setApplied({ ...INITIAL_FILTERS, exceedanceId: exceedanceId || '' })
  }

  const doExport = async () => {
    try {
      const blob = await downloadFile(exportCorrectionsUrl(applied))
      const url = URL.createObjectURL(blob)
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = 'level_corrections.csv'
      anchor.click()
      URL.revokeObjectURL(url)
      toast.success('修正记录已导出')
    } catch (err) {
      toast.error(err.message)
    }
  }

  const items = data?.items || []

  return (
    <Modal
      open={open}
      wide
      title={exceedanceId ? '该记录的等级修正历史' : '等级修正记录检索'}
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn" onClick={doExport} disabled={!data?.total}>
            导出 CSV
          </button>
          <button type="button" className="btn btn-primary" onClick={onClose}>
            关闭
          </button>
        </>
      }
    >
      <div className="stack">
        <div className="card" style={{ boxShadow: 'none' }}>
          <div className="card-body tight">
            <div className="form-grid">
              <Field label="操作人">
                <Input
                  value={filters.operator}
                  onChange={(event) => setFilters({ ...filters, operator: event.target.value })}
                  placeholder="按操作人姓名检索"
                />
              </Field>
              <Field label="监测因子">
                <Input
                  value={filters.pollutant}
                  onChange={(event) => setFilters({ ...filters, pollutant: event.target.value })}
                  placeholder="如 SO2"
                />
              </Field>
              {!exceedanceId ? (
                <Field label="跨已公布月份">
                  <Select
                    value={filters.cross_published}
                    onChange={(event) =>
                      setFilters({ ...filters, cross_published: event.target.value })
                    }
                    options={[
                      { value: '', label: '全部' },
                      { value: 'true', label: '仅跨已公布月份' },
                      { value: 'false', label: '仅非跨月' }
                    ]}
                  />
                </Field>
              ) : null}
              <Field label="修正时间起">
                <Input
                  type="date"
                  value={filters.date_from}
                  onChange={(event) => setFilters({ ...filters, date_from: event.target.value })}
                />
              </Field>
              <Field label="修正时间止">
                <Input
                  type="date"
                  value={filters.date_to}
                  onChange={(event) => setFilters({ ...filters, date_to: event.target.value })}
                />
              </Field>
            </div>
            <div className="inline" style={{ marginTop: 10 }}>
              <button type="button" className="btn btn-primary btn-sm" onClick={search}>
                检索
              </button>
              <button type="button" className="btn btn-sm" onClick={reset}>
                重置
              </button>
              {data ? (
                <span className="small muted">
                  共 {data.total} 条修正 · 其中跨已公布月份{' '}
                  {data.summary?.cross_published_count ?? 0} 条
                </span>
              ) : null}
            </div>
          </div>
        </div>

        {error ? <Alert tone="error">{error.message}</Alert> : null}
        {loading ? <Loading text="正在检索修正记录..." /> : null}
        {!loading && items.length === 0 ? (
          <div className="small muted">没有符合条件的修正记录</div>
        ) : null}

        {items.length > 0 ? (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>修正时间</th>
                  {!exceedanceId ? <th>超标记录</th> : null}
                  <th>等级变化</th>
                  <th>修正理由</th>
                  <th>操作人</th>
                  <th>数据所属月</th>
                </tr>
              </thead>
              <tbody>
                {items.map((item) => (
                  <tr key={item.id}>
                    <td className="cell-nowrap">{formatDateTime(item.corrected_at)}</td>
                    {!exceedanceId ? (
                      <td className="cell-nowrap">
                        <div className="small">
                          #{item.exceedance_id} · {item.station_name}
                        </div>
                        <div className="small muted">{item.pollutant}</div>
                      </td>
                    ) : null}
                    <td className="cell-nowrap">
                      <Tag tone={EXCEEDANCE_LEVEL_TONE[item.from_level]}>{item.from_level_label}</Tag>
                      <span style={{ margin: '0 4px' }}>→</span>
                      <Tag tone={EXCEEDANCE_LEVEL_TONE[item.to_level]}>{item.to_level_label}</Tag>
                      {item.published_month ? (
                        <div className="small muted" style={{ marginTop: 4 }}>
                          跨公布 {item.published_month}
                        </div>
                      ) : null}
                    </td>
                    <td>
                      <div className="small" style={{ maxWidth: 260 }}>
                        {item.reason}
                      </div>
                    </td>
                    <td className="cell-nowrap">{item.operator}</td>
                    <td className="cell-nowrap mono">{item.measured_month}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}

        {data?.total ? (
          <Pagination
            page={page}
            pages={data.pages}
            total={data.total}
            pageSize={data.page_size}
            onPageChange={setPage}
          />
        ) : null}
      </div>
    </Modal>
  )
}
