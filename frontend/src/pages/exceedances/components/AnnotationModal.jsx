import { useCallback, useEffect, useState } from 'react'
import { annotateExceedance, correctExceedanceLevel, getExceedance } from '../../../api/exceedances.js'
import Modal from '../../../components/common/Modal.jsx'
import Tag from '../../../components/common/Tag.jsx'
import { Field, Input, Select, Textarea } from '../../../components/common/FormField.jsx'
import { Alert, ErrorState, Loading } from '../../../components/common/Feedback.jsx'
import { useToast } from '../../../components/common/ToastProvider.jsx'
import { EXCEEDANCE_LEVEL_LABELS, EXCEEDANCE_LEVEL_TONE, EXCEEDANCE_STATUS_TONE } from '../../../constants/index.js'
import { useAsyncData } from '../../../hooks/useAsyncData.js'
import { formatDateTime, formatNumber, formatRatio } from '../../../utils/format.js'

const STATUS_CHOICES = [
  { value: 'confirmed', label: '确认超标', hint: '经复核确属超标, 需记录处置说明' },
  { value: 'ignored', label: '忽略记录', hint: '设备异常 / 校准期数据等, 需说明原因' },
  { value: 'pending', label: '保持待标注', hint: '暂不处理, 保留在待办列表' }
]

const LEVEL_OPTIONS = Object.entries(EXCEEDANCE_LEVEL_LABELS).map(([value, label]) => ({ value, label }))

export default function AnnotationModal({ exceedanceId, onClose, onSaved }) {
  const toast = useToast()
  const loader = useCallback(() => getExceedance(exceedanceId), [exceedanceId])
  const { data, loading, error, reload } = useAsyncData(loader, { immediate: Boolean(exceedanceId) })
  const [form, setForm] = useState({ status: 'confirmed', note: '', annotator: '' })
  const [errors, setErrors] = useState({})
  const [message, setMessage] = useState(null)
  const [busy, setBusy] = useState(false)

  // 等级修正表单 (与标注相互独立, 各自留痕)
  const [correction, setCorrection] = useState({ level: '', reason: '', operator: '' })
  const [correcting, setCorrecting] = useState(false)
  const [correctErrors, setCorrectErrors] = useState({})

  useEffect(() => {
    if (!data) return
    setForm({
      status: data.status,
      note: data.note || '',
      annotator: data.annotator || ''
    })
    setCorrection((prev) => ({
      level: prev.level || '',
      reason: '',
      operator: prev.operator || data.annotator || ''
    }))
    setErrors({})
    setMessage(null)
    setCorrectErrors({})
  }, [data])

  const submitAnnotation = async () => {
    setBusy(true)
    setMessage(null)
    try {
      await annotateExceedance(exceedanceId, {
        status: form.status,
        note: form.note || null,
        annotator: form.annotator || null
      })
      toast.success('标注已保存')
      onSaved?.()
    } catch (err) {
      setErrors(err.fields || {})
      setMessage(err.message)
    } finally {
      setBusy(false)
    }
  }

  const submitCorrection = async () => {
    if (!correction.level) {
      setCorrectErrors({ level: '请选择修正后等级' })
      return
    }
    if (correction.level === data.level) {
      setCorrectErrors({ level: '修正后等级与当前等级一致' })
      return
    }
    setCorrecting(true)
    setCorrectErrors({})
    try {
      await correctExceedanceLevel(exceedanceId, {
        level: correction.level,
        reason: correction.reason,
        operator: correction.operator
      })
      toast.success('等级已修正, 已记录留痕')
      await reload()
      setCorrection((prev) => ({ ...prev, level: '', reason: '' }))
      onSaved?.('corrected')
    } catch (err) {
      setCorrectErrors(err.fields || {})
      toast.error(err.message)
    } finally {
      setCorrecting(false)
    }
  }

  const measurement = data?.measurement
  const history = data?.level_corrections || []
  const published = data?.month_published

  return (
    <Modal
      open={Boolean(exceedanceId)}
      wide
      title={data ? `超标记录标注 · ${data.station_name}` : '超标记录标注'}
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn" onClick={onClose} disabled={busy || correcting}>
            关闭
          </button>
          <button
            type="button"
            className="btn btn-primary"
            onClick={submitAnnotation}
            disabled={busy || correcting || !data}
          >
            {busy ? '保存中...' : '保存标注'}
          </button>
        </>
      }
    >
      {loading && !data ? <Loading /> : null}
      {error && !data ? <ErrorState error={error} /> : null}
      {data ? (
        <div className="stack">
          <div className="stat-grid">
            <div className="stat-card">
              <div className="stat-label">监测值 / 限值</div>
              <div className="stat-value danger-text">
                {formatNumber(data.value)} <small>/ {formatNumber(data.limit_value)} {data.unit || ''}</small>
              </div>
            </div>
            <div className="stat-card">
              <div className="stat-label">超标倍数</div>
              <div className="stat-value">{formatRatio(data.exceed_ratio)}</div>
            </div>
            <div className="stat-card">
              <div className="stat-label">当前等级 / 系统判定</div>
              <div style={{ marginTop: 8 }}>
                <Tag tone={EXCEEDANCE_LEVEL_TONE[data.level]}>
                  {data.level_label}{data.level_corrected ? ' (已修正)' : ''}
                </Tag>
              </div>
              <div className="stat-foot">
                系统判定: <Tag tone={EXCEEDANCE_LEVEL_TONE[data.original_level]}>{data.original_level_label}</Tag>
              </div>
            </div>
            <div className="stat-card">
              <div className="stat-label">当前状态</div>
              <div style={{ marginTop: 8 }}>
                <Tag tone={EXCEEDANCE_STATUS_TONE[data.status]}>{data.status_label}</Tag>
              </div>
              <div className="stat-foot">所属月份 {data.period_month}</div>
            </div>
          </div>

          <dl className="kv">
            <dt>监测点</dt>
            <dd>
              {data.station_name} <span className="mono muted">{data.station_code}</span>
            </dd>
            <dt>监测时间</dt>
            <dd>
              {formatDateTime(data.measured_at)} · {data.period_label}
            </dd>
            <dt>监测因子</dt>
            <dd>{measurement?.pollutant_label || data.pollutant_label}</dd>
            <dt>数据录入</dt>
            <dd>
              {measurement?.recorder || '-'} · {measurement?.data_source_label || '-'}
            </dd>
          </dl>

          {/* ---- 等级人工修正 ---- */}
          <div className="card" style={{ boxShadow: 'none' }}>
            <div className="card-header">
              <div>
                <h3>超标等级人工修正</h3>
                <div className="hint">
                  修正后列表、看板、统计与导出统一使用新等级; 必须填写修正理由, 每次变化都会留痕可追溯
                </div>
              </div>
            </div>
            <div className="card-body tight stack">
              {published ? (
                <Alert tone="warning">
                  所属月份 {data.period_month} 已对外公布, 按规定该月记录的等级不得再修正
                </Alert>
              ) : null}
              <div className="form-grid">
                <Field label="修正后等级" required error={correctErrors.level}>
                  <Select
                    value={correction.level}
                    onChange={(event) => setCorrection({ ...correction, level: event.target.value })}
                    placeholder="请选择新等级"
                    options={LEVEL_OPTIONS}
                    disabled={published}
                  />
                </Field>
                <Field label="操作人" required error={correctErrors.operator}>
                  <Input
                    value={correction.operator}
                    onChange={(event) => setCorrection({ ...correction, operator: event.target.value })}
                    placeholder="如: 王敏"
                    disabled={published}
                  />
                </Field>
              </div>
              <Field
                label="修正理由"
                required
                error={correctErrors.reason}
                hint="需说明修正依据 (现场复核 / 设备核查 / 周边排放源证据等)"
              >
                <Textarea
                  value={correction.reason}
                  onChange={(event) => setCorrection({ ...correction, reason: event.target.value })}
                  invalid={Boolean(correctErrors.reason)}
                  placeholder="如: 经现场复核, 周边工地连续作业导致浓度持续偏高, 上调为重度"
                  disabled={published}
                />
              </Field>
              <div className="inline" style={{ justifyContent: 'flex-end' }}>
                <button
                  type="button"
                  className="btn btn-primary"
                  onClick={submitCorrection}
                  disabled={correcting || published}
                >
                  {correcting ? '提交中...' : '提交等级修正'}
                </button>
              </div>

              <CorrectionTimeline history={history} />
            </div>
          </div>

          {message ? <Alert tone="error">{message}</Alert> : null}

          {/* ---- 标注结论 (与等级修正解耦) ---- */}
          <Field label="标注结论" required error={errors.status}>
            <div className="stack">
              {STATUS_CHOICES.map((choice) => (
                <label key={choice.value} className="checkbox" style={{ alignItems: 'flex-start' }}>
                  <input
                    type="radio"
                    name="annotation-status"
                    checked={form.status === choice.value}
                    onChange={() => setForm({ ...form, status: choice.value })}
                  />
                  <span>
                    <span className="strong">{choice.label}</span>
                    <span className="small muted" style={{ display: 'block' }}>
                      {choice.hint}
                    </span>
                  </span>
                </label>
              ))}
            </div>
          </Field>

          <div className="form-grid">
            <Field label="标注人" error={errors.annotator}>
              <Input
                value={form.annotator}
                onChange={(event) => setForm({ ...form, annotator: event.target.value })}
                placeholder="如: 王敏"
              />
            </Field>
          </div>

          <Field
            label="标注说明"
            required={form.status !== 'pending'}
            error={errors.note}
            hint="确认或忽略时必须填写原因, 便于后续追溯"
          >
            <Textarea
              value={form.note}
              onChange={(event) => setForm({ ...form, note: event.target.value })}
              invalid={Boolean(errors.note)}
              placeholder="如: 数据经复核属实, 已通知运维排查周边排放源"
            />
          </Field>
        </div>
      ) : null}
    </Modal>
  )
}

function CorrectionTimeline({ history }) {
  if (!history.length) {
    return <div className="hint" style={{ marginTop: 4 }}>该记录尚无等级修正记录, 当前等级为系统按超标倍数自动判定。</div>
  }
  return (
    <div className="stack" style={{ marginTop: 4 }}>
      <div className="field-label">修正轨迹 ({history.length})</div>
      <ul className="timeline">
        {history.map((log) => (
          <li key={log.id} className="timeline-item">
            <div className="inline">
              <Tag tone={EXCEEDANCE_LEVEL_TONE[log.level_before]}>{log.level_before_label}</Tag>
              <span className="muted">→</span>
              <Tag tone={EXCEEDANCE_LEVEL_TONE[log.level_after]}>{log.level_after_label}</Tag>
              <span className="small muted">{log.operator} · {formatDateTime(log.corrected_at)}</span>
            </div>
            <div className="small">{log.reason}</div>
            <div className="small mono muted">批次 {log.batch_no}</div>
          </li>
        ))}
      </ul>
    </div>
  )
}
