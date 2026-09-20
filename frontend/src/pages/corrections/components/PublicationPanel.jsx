import { useCallback, useState } from 'react'
import { listPublications, publishMonth } from '../../../api/exceedances.js'
import { Field, Input } from '../../../components/common/FormField.jsx'
import { Alert } from '../../../components/common/Feedback.jsx'
import Tag from '../../../components/common/Tag.jsx'
import { useToast } from '../../../components/common/ToastProvider.jsx'
import { useAsyncData } from '../../../hooks/useAsyncData.js'
import { formatDateTime } from '../../../utils/format.js'

/**
 * 已对外公布的月份管理: 月份公布后其内超标记录的等级禁止再修正,
 * 保证"跨月发生修正时, 已对外公布的月份不因修正而改变"。
 */
export default function PublicationPanel() {
  const toast = useToast()
  const loader = useCallback(() => listPublications(), [])
  const { data, loading, reload } = useAsyncData(loader)
  const [form, setForm] = useState({ period_month: '', published_by: '', remark: '' })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  const submit = async () => {
    if (!form.period_month || !form.published_by.trim()) {
      setError('请填写公布月份与操作人')
      return
    }
    setBusy(true)
    setError(null)
    try {
      await publishMonth({
        period_month: form.period_month,
        published_by: form.published_by.trim(),
        remark: form.remark.trim() || null
      })
      toast.success(`月份 ${form.period_month} 已标记为对外公布`)
      setForm({ period_month: '', published_by: form.published_by, remark: '' })
      reload()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  const items = data?.items ?? []

  return (
    <div className="card">
      <div className="card-header">
        <div>
          <h3>已对外公布月份</h3>
          <div className="hint">月份一经公布即为定稿, 跨月发生的等级修正不会改变该月已公布结果</div>
        </div>
      </div>
      <div className="card-body tight stack">
        {error ? <Alert tone="error">{error}</Alert> : null}
        <div className="filter-bar">
          <Field label="公布月份">
            <Input
              type="month"
              value={form.period_month}
              onChange={(event) => setForm({ ...form, period_month: event.target.value })}
            />
          </Field>
          <Field label="公布操作人" required>
            <Input
              placeholder="如: 管理员"
              value={form.published_by}
              onChange={(event) => setForm({ ...form, published_by: event.target.value })}
            />
          </Field>
          <Field label="备注">
            <Input
              placeholder="如: 8 月超标月报已发布"
              value={form.remark}
              onChange={(event) => setForm({ ...form, remark: event.target.value })}
            />
          </Field>
          <div className="filter-actions">
            <button type="button" className="btn btn-primary" onClick={submit} disabled={busy || loading}>
              {busy ? '提交中...' : '标记公布'}
            </button>
          </div>
        </div>
        {loading && !data ? (
          <div className="hint">加载中...</div>
        ) : items.length ? (
          <ul className="compact-list">
            {items.map((item) => (
              <li key={item.id} className="inline" style={{ gap: 8 }}>
                <Tag tone="neutral">已公布</Tag>
                <span className="strong mono">{item.period_month}</span>
                <span className="small muted">
                  {item.published_by} · {formatDateTime(item.published_at)}
                </span>
                {item.remark ? <span className="small">· {item.remark}</span> : null}
              </li>
            ))}
          </ul>
        ) : (
          <div className="hint">暂无已公布月份</div>
        )}
      </div>
    </div>
  )
}
