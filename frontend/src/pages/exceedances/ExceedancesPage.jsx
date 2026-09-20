import { useCallback, useState } from 'react'
import {
  batchAnnotate,
  batchCorrectLevel,
  listExceedances
} from '../../api/exceedances.js'
import Pagination from '../../components/common/Pagination.jsx'
import { SectionCard } from '../../components/common/Card.jsx'
import { Alert } from '../../components/common/Feedback.jsx'
import Tag from '../../components/common/Tag.jsx'
import { useToast } from '../../components/common/ToastProvider.jsx'
import { useListQuery } from '../../hooks/useListQuery.js'
import AnnotationModal from './components/AnnotationModal.jsx'
import CorrectionHistoryModal from './components/CorrectionHistoryModal.jsx'
import ExceedanceFilters from './components/ExceedanceFilters.jsx'
import ExceedanceSummaryCards from './components/ExceedanceSummaryCards.jsx'
import ExceedanceTable from './components/ExceedanceTable.jsx'
import LevelCorrectionModal from './components/LevelCorrectionModal.jsx'
import PublishedMonthsModal from './components/PublishedMonthsModal.jsx'

const INITIAL_FILTERS = {
  status: '',
  level: '',
  pollutant: '',
  station_id: '',
  date_from: '',
  date_to: '',
  keyword: ''
}

const LEVEL_OPTIONS = [
  { value: 'light', label: '轻度超标' },
  { value: 'moderate', label: '中度超标' },
  { value: 'severe', label: '重度超标' }
]

export default function ExceedancesPage() {
  const toast = useToast()
  const query = useListQuery(listExceedances, INITIAL_FILTERS)
  const [selected, setSelected] = useState([])
  const [activeId, setActiveId] = useState(null)
  const [correctId, setCorrectId] = useState(null)
  const [historyOpen, setHistoryOpen] = useState(false)
  const [publishedOpen, setPublishedOpen] = useState(false)
  const [batch, setBatch] = useState({ status: 'confirmed', note: '', annotator: '' })
  const [batchLevel, setBatchLevel] = useState({ level: 'severe', reason: '', operator: '' })
  const [busy, setBusy] = useState(false)
  const [correcting, setCorrecting] = useState(false)

  const { reload } = query

  const toggleRow = useCallback((id) => {
    setSelected((prev) => (prev.includes(id) ? prev.filter((item) => item !== id) : [...prev, id]))
  }, [])

  const toggleAll = useCallback(
    (ids) => {
      setSelected((prev) =>
        ids.every((id) => prev.includes(id))
          ? prev.filter((id) => !ids.includes(id))
          : Array.from(new Set([...prev, ...ids]))
      )
    },
    []
  )

  const submitBatch = async () => {
    if (selected.length === 0) {
      toast.warning('请先勾选需要标注的超标记录')
      return
    }
    setBusy(true)
    try {
      const result = await batchAnnotate({
        ids: selected,
        status: batch.status,
        note: batch.note || null,
        annotator: batch.annotator || null
      })
      toast.success(`已标注 ${result.updated} 条记录`)
      if (result.missing?.length) toast.warning(`有 ${result.missing.length} 条记录不存在, 已跳过`)
      setSelected([])
      setBatch((prev) => ({ ...prev, note: '' }))
      reload()
    } catch (error) {
      toast.error(error.message)
    } finally {
      setBusy(false)
    }
  }

  const submitBatchCorrection = async () => {
    if (selected.length === 0) {
      toast.warning('请先勾选需要修正等级的超标记录')
      return
    }
    if (!batchLevel.reason.trim()) {
      toast.error('批量修正必须填写统一修正理由')
      return
    }
    if (!batchLevel.operator.trim()) {
      toast.error('批量修正必须填写操作人')
      return
    }
    setCorrecting(true)
    try {
      const result = await batchCorrectLevel({
        ids: selected,
        level: batchLevel.level,
        reason: batchLevel.reason,
        operator: batchLevel.operator
      })
      toast.success(`已整体修正 ${result.updated} 条记录 (批次 ${result.batch_no})`)
      if (result.cross_published?.length) {
        const months = Array.from(new Set(result.cross_published.map((item) => item.published_month)))
        toast.warning(
          `其中 ${result.cross_published.length} 条属于已公布月份 ${months.join('、')}, 公布口径不变`
        )
      }
      setSelected([])
      setBatchLevel((prev) => ({ ...prev, reason: '' }))
      reload()
    } catch (error) {
      toast.error(error.message)
    } finally {
      setCorrecting(false)
    }
  }

  const openCorrection = (row) => {
    setActiveId(null)
    setCorrectId(row.id)
  }

  return (
    <>
      <ExceedanceSummaryCards summary={query.summary} />

      <ExceedanceFilters
        value={query.filters}
        loading={query.loading}
        onSubmit={(next) => {
          setSelected([])
          query.setFilters(next)
        }}
        onReset={() => {
          setSelected([])
          query.setFilters(INITIAL_FILTERS)
        }}
      />

      {query.error ? <Alert tone="error">{query.error.message}</Alert> : null}

      <SectionCard
        title="超标记录工作台"
        hint="点击行打开标注; “修正等级”需填写理由并完整留痕; 勾选多条可批量标注或批量修正"
        actions={
          <>
            <Tag tone="primary">已选 {selected.length} 条</Tag>
            <button type="button" className="btn btn-sm" onClick={() => setHistoryOpen(true)}>
              修正记录检索
            </button>
            <button type="button" className="btn btn-sm" onClick={() => setPublishedOpen(true)}>
              已公布月份
            </button>
            <button type="button" className="btn btn-sm" onClick={reload} disabled={query.loading}>
              刷新
            </button>
          </>
        }
      >
        <div className="stack">
          <div className="card" style={{ boxShadow: 'none' }}>
            <div className="card-body tight">
              <div className="inline">
                <span className="field-label">批量标注</span>
                <select
                  className="select"
                  style={{ width: 150 }}
                  value={batch.status}
                  onChange={(event) => setBatch({ ...batch, status: event.target.value })}
                >
                  <option value="confirmed">已确认</option>
                  <option value="ignored">已忽略</option>
                  <option value="pending">重置为待标注</option>
                </select>
                <input
                  className="input"
                  style={{ flex: 1, minWidth: 220 }}
                  placeholder="标注说明 (确认或忽略时必填)"
                  value={batch.note}
                  onChange={(event) => setBatch({ ...batch, note: event.target.value })}
                />
                <input
                  className="input"
                  style={{ width: 140 }}
                  placeholder="标注人"
                  value={batch.annotator}
                  onChange={(event) => setBatch({ ...batch, annotator: event.target.value })}
                />
                <button type="button" className="btn btn-primary" onClick={submitBatch} disabled={busy}>
                  {busy ? '提交中...' : '提交批量标注'}
                </button>
              </div>
              <div className="inline" style={{ marginTop: 10 }}>
                <span className="field-label">批量修正等级</span>
                <select
                  className="select"
                  style={{ width: 150 }}
                  value={batchLevel.level}
                  onChange={(event) => setBatchLevel({ ...batchLevel, level: event.target.value })}
                >
                  {LEVEL_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
                <input
                  className="input"
                  style={{ flex: 1, minWidth: 220 }}
                  placeholder="统一修正理由 (必填) — 整批先校验, 有不满足条件的记录则一条都不改"
                  value={batchLevel.reason}
                  onChange={(event) => setBatchLevel({ ...batchLevel, reason: event.target.value })}
                />
                <input
                  className="input"
                  style={{ width: 140 }}
                  placeholder="操作人 (必填)"
                  value={batchLevel.operator}
                  onChange={(event) => setBatchLevel({ ...batchLevel, operator: event.target.value })}
                />
                <button
                  type="button"
                  className="btn btn-primary"
                  onClick={submitBatchCorrection}
                  disabled={correcting}
                >
                  {correcting ? '校验提交中...' : '提交批量修正'}
                </button>
                <button
                  type="button"
                  className="btn"
                  onClick={() => setSelected([])}
                  disabled={selected.length === 0}
                >
                  清空选择
                </button>
              </div>
            </div>
          </div>

          <ExceedanceTable
            rows={query.items}
            loading={query.loading}
            selectedIds={selected}
            onToggleRow={toggleRow}
            onToggleAll={toggleAll}
            onOpen={(row) => setActiveId(row.id)}
            onCorrect={openCorrection}
          />
          <Pagination
            page={query.page}
            pages={query.pages}
            total={query.total}
            pageSize={query.pageSize}
            onPageChange={query.setPage}
            onPageSizeChange={query.setPageSize}
          />
        </div>
      </SectionCard>

      <AnnotationModal
        exceedanceId={activeId}
        onClose={() => setActiveId(null)}
        onSaved={() => {
          setActiveId(null)
          reload()
        }}
        onCorrect={(row) => {
          setActiveId(null)
          setCorrectId(row.id)
        }}
      />

      <LevelCorrectionModal
        exceedanceId={correctId}
        onClose={() => setCorrectId(null)}
        onSaved={() => reload()}
      />

      <CorrectionHistoryModal open={historyOpen} onClose={() => setHistoryOpen(false)} />

      <PublishedMonthsModal open={publishedOpen} onClose={() => setPublishedOpen(false)} />
    </>
  )
}
