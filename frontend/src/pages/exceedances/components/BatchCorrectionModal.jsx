import { useEffect, useState } from 'react'
import { batchCorrectLevels } from '../../../api/exceedances.js'
import Modal from '../../../components/common/Modal.jsx'
import { Field, Input, Select, Textarea } from '../../../components/common/FormField.jsx'
import { Alert } from '../../../components/common/Feedback.jsx'
import { useToast } from '../../../components/common/ToastProvider.jsx'
import { EXCEEDANCE_LEVEL_LABELS } from '../../../constants/index.js'

const LEVEL_OPTIONS = Object.entries(EXCEEDANCE_LEVEL_LABELS).map(([value, label]) => ({ value, label }))

/**
 * 批量等级修正: 选中的记录统一改成同一等级, 共用理由与操作人。
 * 后端对整批做同一套校验, 任一条不满足 (不存在 / 月份已公布 / 等级未变)
 * 都会整体拒绝, 不会只改一半。
 */
export default function BatchCorrectionModal({ open, rows, selectedIds, onClose, onDone }) {
  const toast = useToast()
  const [form, setForm] = useState({ level: '', reason: '', operator: '' })
  const [errors, setErrors] = useState({})
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (open) {
      setForm({ level: '', reason: '', operator: '' })
      setErrors({})
    }
  }, [open])

  const targets = rows.filter((row) => selectedIds.includes(row.id))
  const locked = targets.filter((row) => row.month_published)

  const submit = async () => {
    const fieldErrors = {}
    if (!form.level) fieldErrors.level = '请选择统一的修正后等级'
    if (!form.reason.trim()) fieldErrors.reason = '批量修正必须填写统一理由'
    if (!form.operator.trim()) fieldErrors.operator = '请填写操作人'
    const unchanged = targets.filter((row) => row.level === form.level)
    if (form.level && unchanged.length) {
      fieldErrors.level = `有 ${unchanged.length} 条当前已是${EXCEEDANCE_LEVEL_LABELS[form.level]}, 请取消勾选或更换等级`
    }
    if (locked.length) {
      fieldErrors.items = `有 ${locked.length} 条所属月份已公布, 不能修正, 请取消勾选`
    }
    setErrors(fieldErrors)
    if (Object.keys(fieldErrors).length) return

    setBusy(true)
    try {
      const result = await batchCorrectLevels({
        operator: form.operator.trim(),
        reason: form.reason.trim(),
        items: targets.map((row) => ({ id: row.id, level: form.level }))
      })
      toast.success(`已批量修正 ${result.updated} 条记录 (批次 ${result.batch_no})`)
      onDone?.()
    } catch (err) {
      setErrors({ items: err.message })
      toast.error(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal
      open={open}
      title="批量修正超标等级"
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn" onClick={onClose} disabled={busy}>
            取消
          </button>
          <button type="button" className="btn btn-primary" onClick={submit} disabled={busy}>
            {busy ? '提交中...' : `确认修正选中的 ${targets.length} 条`}
          </button>
        </>
      }
    >
      <div className="stack">
        <Alert tone="warning">
          批量修正按同一套校验整体生效: 只要有一条不满足条件, 整批都不会改动。
        </Alert>

        <div className="card" style={{ boxShadow: 'none' }}>
          <div className="card-body tight">
            <div className="small muted">
              已选 {targets.length} 条 · 其中 {locked.length} 条所属月份已公布 (禁止修正)
            </div>
            <ul className="compact-list">
              {targets.slice(0, 8).map((row) => (
                <li key={row.id} className="small">
                  <span className="mono muted">#{row.id}</span> {row.station_name} · {row.pollutant_label} ·{' '}
                  {row.level_label}
                  {row.month_published ? <span className="danger-text"> · 月份已公布</span> : null}
                </li>
              ))}
              {targets.length > 8 ? <li className="small muted">… 其余 {targets.length - 8} 条略</li> : null}
            </ul>
          </div>
        </div>

        <div className="form-grid">
          <Field label="统一修正后等级" required error={errors.level}>
            <Select
              value={form.level}
              onChange={(event) => setForm({ ...form, level: event.target.value })}
              placeholder="请选择新等级"
              options={LEVEL_OPTIONS}
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
          label="统一修正理由"
          required
          error={errors.reason}
          hint="理由会随每一条修正记录留痕, 可在修正记录页按批次号检索"
        >
          <Textarea
            value={form.reason}
            onChange={(event) => setForm({ ...form, reason: event.target.value })}
            invalid={Boolean(errors.reason)}
            placeholder="如: 月度复核, 结合现场核查与周边排放源证据统一调整"
          />
        </Field>
        {errors.items ? <Alert tone="error">{errors.items}</Alert> : null}
      </div>
    </Modal>
  )
}
