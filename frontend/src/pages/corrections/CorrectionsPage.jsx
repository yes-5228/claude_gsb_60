import { useState } from 'react'
import { exportCorrectionsUrl, listCorrections } from '../../api/exceedances.js'
import Pagination from '../../components/common/Pagination.jsx'
import { SectionCard, FilterPanel } from '../../components/common/Card.jsx'
import { Alert } from '../../components/common/Feedback.jsx'
import StatCard from '../../components/common/StatCard.jsx'
import Tag from '../../components/common/Tag.jsx'
import DataTable from '../../components/common/DataTable.jsx'
import { useToast } from '../../components/common/ToastProvider.jsx'
import { useListQuery } from '../../hooks/useListQuery.js'
import { downloadFile } from '../../api/client.js'
import { saveBlob } from '../../utils/download.js'
import { Field, Input, Select } from '../../components/common/FormField.jsx'
import { EXCEEDANCE_LEVEL_LABELS, EXCEEDANCE_LEVEL_TONE } from '../../constants/index.js'
import { formatDateTime } from '../../utils/format.js'
import PublicationPanel from './components/PublicationPanel.jsx'

const INITIAL_FILTERS = {
  operator: '',
  date_from: '',
  date_to: '',
  period_month: '',
  level_after: '',
  pollutant: '',
  batch_no: '',
  exceedance_id: ''
}

const LEVEL_OPTIONS = Object.entries(EXCEEDANCE_LEVEL_LABELS).map(([value, label]) => ({ value, label }))

export default function CorrectionsPage() {
  const toast = useToast()
  const query = useListQuery(listCorrections, INITIAL_FILTERS)
  const [draft, setDraft] = useState(INITIAL_FILTERS)
  const [exporting, setExporting] = useState(false)

  const update = (key) => (event) => setDraft({ ...draft, [key]: event.target.value })

  const doExport = async () => {
    setExporting(true)
    try {
      const blob = await downloadFile(exportCorrectionsUrl(query.filters))
      saveBlob(blob, `level_corrections_${Date.now()}.csv`)
      toast.success('留痕 CSV 已导出')
    } catch (err) {
      toast.error(err.message)
    } finally {
      setExporting(false)
    }
  }

  const columns = [
    {
      key: 'corrected_at',
      title: '修正时间',
      className: 'cell-nowrap',
      render: (row) => formatDateTime(row.corrected_at)
    },
    {
      key: 'station',
      title: '监测点',
      render: (row) => (
        <div>
          <div>{row.station_name}</div>
          <div className="small muted mono">{row.station_code}</div>
        </div>
      )
    },
    { key: 'pollutant', title: '因子', className: 'cell-nowrap' },
    {
      key: 'period_month',
      title: '所属月份',
      className: 'cell-nowrap',
      render: (row) => <span className="mono">{row.period_month}</span>
    },
    {
      key: 'level_change',
      title: '等级变化 (前 → 后)',
      className: 'cell-nowrap',
      render: (row) => (
        <div className="inline" style={{ gap: 4 }}>
          <Tag tone={EXCEEDANCE_LEVEL_TONE[row.level_before]}>{row.level_before_label}</Tag>
          <span className="muted">→</span>
          <Tag tone={EXCEEDANCE_LEVEL_TONE[row.level_after]}>{row.level_after_label}</Tag>
        </div>
      )
    },
    {
      key: 'reason',
      title: '修正理由',
      render: (row) => <div className="small" style={{ maxWidth: 280 }}>{row.reason}</div>
    },
    { key: 'operator', title: '操作人', className: 'cell-nowrap' },
    {
      key: 'batch_no',
      title: '批次号',
      className: 'cell-nowrap',
      render: (row) => <span className="small mono muted">{row.batch_no}</span>
    },
    {
      key: 'exceedance_id',
      title: '超标记录',
      className: 'cell-nowrap',
      render: (row) => <span className="mono">#{row.exceedance_id}</span>
    }
  ]

  const summary = query.data?.summary

  return (
    <>
      <div className="stat-grid">
        <StatCard label="修正次数" value={summary?.correction_count ?? '-'} foot="每次人工修正都计入留痕" />
        <StatCard label="涉及超标记录" value={summary?.affected_records ?? '-'} foot="同一条反复修正只计一条记录" />
        <StatCard label="参与修正操作人" value={summary?.operator_count ?? '-'} foot="可按操作人检索" />
      </div>

      <PublicationPanel />

      <FilterPanel
        loading={query.loading}
        onSearch={() => query.setFilters(draft)}
        onReset={() => {
          setDraft(INITIAL_FILTERS)
          query.setFilters(INITIAL_FILTERS)
        }}
        extra={
          <div className="inline">
            <button type="button" className="btn" onClick={doExport} disabled={exporting}>
              {exporting ? '导出中...' : '导出留痕 CSV'}
            </button>
          </div>
        }
      >
        <Field label="操作人">
          <Input placeholder="操作人姓名 (模糊匹配)" value={draft.operator} onChange={update('operator')} />
        </Field>
        <Field label="修正开始日期">
          <Input type="date" value={draft.date_from} onChange={update('date_from')} />
        </Field>
        <Field label="修正结束日期">
          <Input type="date" value={draft.date_to} onChange={update('date_to')} />
        </Field>
        <Field label="数据所属月份">
          <Input type="month" value={draft.period_month} onChange={update('period_month')} />
        </Field>
        <Field label="修正后等级">
          <Select value={draft.level_after} onChange={update('level_after')} placeholder="全部等级" options={LEVEL_OPTIONS} />
        </Field>
        <Field label="因子代码">
          <Input placeholder="如 SO2 / NO2" value={draft.pollutant} onChange={update('pollutant')} />
        </Field>
        <Field label="批次号">
          <Input placeholder="批量修正批次号" value={draft.batch_no} onChange={update('batch_no')} />
        </Field>
        <Field label="超标记录 ID">
          <Input placeholder="定位单条记录的全部变化" value={draft.exceedance_id} onChange={update('exceedance_id')} />
        </Field>
      </FilterPanel>

      {query.error ? <Alert tone="error">{query.error.message}</Alert> : null}

      <SectionCard
        title="等级修正留痕"
        hint="append-only 审计记录: 包含修正前后等级对比、理由、操作人与批次号, 按修正时间倒序"
      >
        <DataTable
          columns={columns}
          rows={query.items}
          loading={query.loading}
          emptyText="当前条件下没有等级修正记录"
          emptyIcon="🧾"
        />
        <Pagination
          page={query.page}
          pages={query.pages}
          total={query.total}
          pageSize={query.pageSize}
          onPageChange={query.setPage}
          onPageSizeChange={query.setPageSize}
        />
      </SectionCard>
    </>
  )
}
