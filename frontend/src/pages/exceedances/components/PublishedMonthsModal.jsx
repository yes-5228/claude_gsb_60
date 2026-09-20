import { useCallback, useEffect, useState } from 'react'
import {
  exportPublishedMonthUrl,
  getPublishedMonth,
  listPublishedExceedances,
  listPublishedMonths,
  publishMonth
} from '../../../api/exceedances.js'
import Modal from '../../../components/common/Modal.jsx'
import Pagination from '../../../components/common/Pagination.jsx'
import Tag from '../../../components/common/Tag.jsx'
import { Field, Input, Textarea } from '../../../components/common/FormField.jsx'
import { Alert, Loading } from '../../../components/common/Feedback.jsx'
import { useToast } from '../../../components/common/ToastProvider.jsx'
import { EXCEEDANCE_LEVEL_TONE } from '../../../constants/index.js'
import { downloadFile } from '../../../api/client.js'
import { formatDateTime, formatNumber } from '../../../utils/format.js'

export default function PublishedMonthsModal({ open, onClose }) {
  const toast = useToast()
  const [months, setMonths] = useState([])
  const [loading, setLoading] = useState(false)
  const [form, setForm] = useState({ month: '', published_by: '', remark: '' })
  const [errors, setErrors] = useState({})
  const [busy, setBusy] = useState(false)
  const [active, setActive] = useState(null) // { month, detail, rows, total, pages, page }

  const loadMonths = useCallback(async () => {
    setLoading(true)
    try {
      const payload = await listPublishedMonths()
      setMonths(payload.items || [])
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (open) loadMonths()
  }, [open, loadMonths])

  const doPublish = async () => {
    setBusy(true)
    setErrors({})
    try {
      const result = await publishMonth({
        month: form.month,
        published_by: form.published_by || null,
        remark: form.remark || null
      })
      toast.success(`${result.month} 已公布, 冻结 ${result.snapshot_count} 条超标记录等级`)
      setForm({ month: '', published_by: '', remark: '' })
      loadMonths()
    } catch (err) {
      setErrors(err.fields || {})
      toast.error(err.message)
    } finally {
      setBusy(false)
    }
  }

  const openMonth = async (month, page = 1) => {
    try {
      const [detail, rows] = await Promise.all([
        getPublishedMonth(month),
        listPublishedExceedances(month, { page, page_size: 10 })
      ])
      setActive({ month, detail, ...rows })
    } catch (err) {
      toast.error(err.message)
    }
  }

  const doExport = async (month) => {
    const blob = await downloadFile(exportPublishedMonthUrl(month))
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = `published_${month}.csv`
    anchor.click()
    URL.revokeObjectURL(url)
  }

  return (
    <Modal
      open={open}
      wide
      title="已对外公布月份管理"
      onClose={onClose}
      footer={
        <button type="button" className="btn btn-primary" onClick={onClose}>
          关闭
        </button>
      }
    >
      <div className="stack">
        <Alert tone="info">
          月份公布后, 该月超标记录的等级即被冻结。之后发生跨月修正时, 列表/统计/导出使用新等级,
          已公布月份的对外口径保持不变。
        </Alert>

        {!active ? (
          <>
            <div className="card" style={{ boxShadow: 'none' }}>
              <div className="card-body tight">
                <div className="field-label">公布新月份</div>
                <div className="form-grid">
                  <Field label="月份 (YYYY-MM)" required error={errors.month}>
                    <Input
                      value={form.month}
                      onChange={(event) => setForm({ ...form, month: event.target.value })}
                      placeholder="如 2026-08"
                    />
                  </Field>
                  <Field label="公布操作人" error={errors.published_by}>
                    <Input
                      value={form.published_by}
                      onChange={(event) =>
                        setForm({ ...form, published_by: event.target.value })
                      }
                      placeholder="如 管理员"
                    />
                  </Field>
                </div>
                <Field label="备注" error={errors.remark}>
                  <Textarea
                    value={form.remark}
                    onChange={(event) => setForm({ ...form, remark: event.target.value })}
                    placeholder="如 月度环境质量报告对外报送"
                  />
                </Field>
                <div className="inline">
                  <button
                    type="button"
                    className="btn btn-primary btn-sm"
                    onClick={doPublish}
                    disabled={busy || !form.month}
                  >
                    {busy ? '公布中...' : '公布并冻结等级'}
                  </button>
                </div>
              </div>
            </div>

            {loading ? <Loading text="正在加载已公布月份..." /> : null}
            {months.length === 0 && !loading ? (
              <div className="small muted">尚未公布任何月份</div>
            ) : (
              <div className="table-wrap">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>月份</th>
                      <th>公布时间</th>
                      <th>操作人</th>
                      <th>冻结记录数</th>
                      <th>备注</th>
                      <th className="text-right">操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {months.map((item) => (
                      <tr key={item.month}>
                        <td className="mono strong">{item.month}</td>
                        <td className="cell-nowrap">{formatDateTime(item.published_at)}</td>
                        <td className="cell-nowrap">{item.published_by}</td>
                        <td>{item.snapshot_count}</td>
                        <td>
                          <span className="small">{item.remark || '-'}</span>
                        </td>
                        <td className="text-right cell-nowrap">
                          <button
                            type="button"
                            className="btn btn-sm"
                            onClick={() => openMonth(item.month)}
                          >
                            查看冻结口径
                          </button>
                          <button
                            type="button"
                            className="btn btn-sm"
                            onClick={() => doExport(item.month)}
                          >
                            导出
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </>
        ) : (
          <PublishedMonthDetail active={active} onBack={() => setActive(null)} onPage={(p) => openMonth(active.month, p)} />
        )}
      </div>
    </Modal>
  )
}

function PublishedMonthDetail({ active, onBack, onPage }) {
  const levelCounts = Object.fromEntries(
    (active.detail.level_summary?.by_level || []).map((item) => [item.key, item.count])
  )
  return (
    <div className="stack">
      <div className="inline" style={{ justifyContent: 'space-between' }}>
        <div className="inline">
          <button type="button" className="btn btn-sm" onClick={onBack}>
            ← 返回月份列表
          </button>
          <span className="strong mono">{active.month} 冻结口径</span>
          <span className="small muted">
            公布于 {formatDateTime(active.detail.published_at)} · {active.detail.published_by}
          </span>
        </div>
        <div className="inline">
          {Object.entries(levelCounts).map(([key, count]) => (
            <Tag key={key} tone={EXCEEDANCE_LEVEL_TONE[key]}>
              {key === 'light' ? '轻度' : key === 'moderate' ? '中度' : '重度'} {count}
            </Tag>
          ))}
        </div>
      </div>
      <div className="table-wrap">
        <table className="data-table">
          <thead>
            <tr>
              <th>监测时间</th>
              <th>监测点</th>
              <th>因子</th>
              <th>监测值 / 限值</th>
              <th>公布时等级</th>
            </tr>
          </thead>
          <tbody>
            {(active.items || []).map((row) => (
              <tr key={row.id}>
                <td className="cell-nowrap">{formatDateTime(row.measured_at)}</td>
                <td>{row.station_name}</td>
                <td>{row.pollutant}</td>
                <td className="cell-nowrap">
                  {formatNumber(row.value)} / {formatNumber(row.limit_value)}
                </td>
                <td>
                  <Tag tone={EXCEEDANCE_LEVEL_TONE[row.level]}>{row.level_label}</Tag>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <Pagination
        page={active.page}
        pages={active.pages}
        total={active.total}
        pageSize={active.page_size}
        onPageChange={onPage}
      />
    </div>
  )
}
