import { useCallback, useEffect, useState } from 'react'
import { correctLevel, getExceedance } from '../../../api/exceedances.js'
import Modal from '../../../components/common/Modal.jsx'
import Tag from '../../../components/common/Tag.jsx'
import { Field, Input, Select, Textarea } from '../../../components/common/FormField.jsx'
import { Alert, ErrorState, Loading } from '../../../components/common/Feedback.jsx'
import { useToast } from '../../../components/common/ToastProvider.jsx'
import { EXCEEDANCE_LEVEL_TONE } from '../../../constants/index.js'
import { useAsyncData } from '../../../hooks/useAsyncData.js'
import { formatDateTime, formatNumber } from '../../../utils/format.js'

const LEVEL_OPTIONS = [
  { value: 'light', label: '轻度超标' },
  { value: 'moderate', label: '中度超标' },
  { value: 'severe', label: '重度超标' }
]

const levelLabel = (key) => LEVEL_OPTIONS.find((item) => item.value === key)?.label || key

export default function LevelCorrectionModal({ exceedanceId, onClose, onSaved }) {
  const toast = useToast()
  const loader = useCallback(() => getExceedance(exceedanceId), [exceedanceId])
  const { data, loading, error, reload } = useAsyncData(loader, { immediate: Boolean(exceedanceId) })
  const [form, setForm] = useState({ level: '', reason: '', operator: '' })
  const [errors, setErrors] = useState({})
  const [message, setMessage] = useState(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (!data) return
    setForm({ level: data.level || '', reason: '', operator: data.last_operator || '' })
    setErrors({})
    setMessage(null)
  }, [data])

  const submit = async () => {
    setBusy(true)
    setMessage(null)
    try {
      const result = await correctLevel(exceedanceId, {
        level: form.level,
        reason: form.reason || null,
        operator: form.operator || null
      })
      toast.success('等级已修正, 留痕已生成')
      if (result.cross_published) {
        toast.warning(`该记录属于已对外公布月份 ${result.published_month}, 公布口径保持不变`)
      }
      onSaved?.()
      reload()
    } catch (err) {
      setErrors(err.fields || {})
      setMessage(err.message)
    } finally {
      setBusy(false)
    }
  }

  const corrections = data?.corrections || []
  const changed = data ? form.level && form.level !== data.level : false
  const measuredMonth = data ? data.measured_at?.slice(0, 7) : null

  return (
    <Modal
      open={Boolean(exceedanceId)}
      wide
      title={data ? `超标等级人工修正 · ${data.station_name}` : '超标等级人工修正'}
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn" onClick={onClose} disabled={busy}>
            关闭
          </button>
          <button
            type="button"
            className="btn btn-primary"
            onClick={submit}
            disabled={busy || !data || !changed}
          >
            {busy ? '提交中...' : '提交修正'}
          </button>
        </>
      }
    >
      {loading && !data ? <Loading /> : null}
      {error && !data ? <ErrorState error={error} /> : null}
      {data ? (
        <div className="stack">
          <dl className="kv">
            <dt>监测点 / 因子</dt>
            <dd>
              {data.station_name} <span className="mono muted">{data.station_code}</span> ·{' '}
              {data.pollutant_label}
            </dd>
            <dt>监测时间</dt>
            <dd>
              {formatDateTime(data.measured_at)} · 所属月 <span className="mono">{measuredMonth}</span>
            </dd>
            <dt>监测值 / 限值</dt>
            <dd className="danger-text">
              {formatNumber(data.value)} / {formatNumber(data.limit_value)} {data.unit || ''}
            </dd>
            <dt>系统判定等级</dt>
            <dd>
              <Tag tone={EXCEEDANCE_LEVEL_TONE[data.auto_level]}>{data.auto_level_label}</Tag>
              <span className="small muted" style={{ marginLeft: 8 }}>
                按超标倍数自动分级, 不随人工修正改变
              </span>
            </dd>
            <dt>当前生效等级</dt>
            <dd>
              <Tag tone={EXCEEDANCE_LEVEL_TONE[data.level]}>{data.level_label}</Tag>
              {data.level_corrected ? <Tag tone="primary">已人工修正</Tag> : null}
            </dd>
          </dl>

          {message ? <Alert tone="error">{message}</Alert> : null}

          <div className="form-grid">
            <Field label="修正后等级" required error={errors.level}>
              <Select
                options={LEVEL_OPTIONS}
                value={form.level}
                onChange={(event) => setForm({ ...form, level: event.target.value })}
              />
            </Field>
            <Field label="操作人" required error={errors.operator}>
              <Input
                value={form.operator}
                onChange={(event) => setForm({ ...form, operator: event.target.value })}
                placeholder="如: 王敏"
              />
            </Field>
          </div>

          <Field
            label="修正理由"
            required
            error={errors.reason}
            hint="修正必须填写理由, 并与前后等级一起永久留痕"
          >
            <Textarea
              value={form.reason}
              onChange={(event) => setForm({ ...form, reason: event.target.value })}
              invalid={Boolean(errors.reason)}
              placeholder="如: 经现场复核, 周边排放源持续超标, 由轻度上调为重度"
            />
          </Field>

          {changed ? (
            <Alert tone="warning">
              等级对比:{' '}
              <Tag tone={EXCEEDANCE_LEVEL_TONE[data.level]}>{data.level_label}</Tag>
              <span style={{ margin: '0 6px' }}>→</span>
              <Tag tone={EXCEEDANCE_LEVEL_TONE[form.level]}>{levelLabel(form.level)}</Tag>
            </Alert>
          ) : null}

          <div>
            <div className="field-label" style={{ marginBottom: 8 }}>
              修正历史 ({corrections.length})
            </div>
            {corrections.length === 0 ? (
              <div className="small muted">该记录尚未做过等级修正</div>
            ) : (
              <div className="stack">
                {corrections.map((item) => (
                  <div key={item.id} className="card" style={{ boxShadow: 'none' }}>
                    <div className="card-body tight">
                      <div className="inline" style={{ justifyContent: 'space-between' }}>
                        <div className="inline">
                          <Tag tone={EXCEEDANCE_LEVEL_TONE[item.from_level]}>
                            {item.from_level_label}
                          </Tag>
                          <span style={{ margin: '0 6px' }}>→</span>
                          <Tag tone={EXCEEDANCE_LEVEL_TONE[item.to_level]}>
                            {item.to_level_label}
                          </Tag>
                          {item.published_month ? (
                            <Tag tone="warning">跨已公布月份 {item.published_month}</Tag>
                          ) : null}
                        </div>
                        <span className="small muted">
                          {item.operator} · {formatDateTime(item.corrected_at)}
                        </span>
                      </div>
                      <div className="small" style={{ marginTop: 6 }}>
                        {item.reason}
                      </div>
                      {item.batch_no ? (
                        <div className="small muted mono" style={{ marginTop: 4 }}>
                          批次 {item.batch_no}
                        </div>
                      ) : null}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      ) : null}
    </Modal>
  )
}
