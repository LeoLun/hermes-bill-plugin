import { host, useQuery, PALETTE_AREA, Button, Codicon } from '@hermes/plugin-sdk'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { jsx, jsxs, Fragment } from 'react/jsx-runtime'

const COLORS = ['#c96442', '#d97757', '#8a503a', '#b57c66', '#a18b76', '#5e5d59', '#87867f', '#b0aea5']
const MONTHS = Array.from({ length: 12 }, (_, index) => index + 1)
const BUDGET = 8000

const styles = {
  root: { height: '100%', overflow: 'auto', color: 'var(--ui-text-primary)' },
  shell: { maxWidth: 1440, margin: '0 auto', padding: '24px', display: 'grid', gap: 18 },
  header: { display: 'flex', flexWrap: 'wrap', alignItems: 'center', justifyContent: 'space-between', gap: 12 },
  title: { fontSize: 24, fontWeight: 650, letterSpacing: '-0.02em' },
  subtitle: { color: 'var(--ui-text-tertiary)', fontSize: 12, marginTop: 4 },
  controls: { display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' },
  select: {
    height: 30, border: '1px solid var(--ui-stroke-secondary)', borderRadius: 6,
    background: 'var(--ui-control-background)', color: 'var(--ui-text-primary)', padding: '0 28px 0 9px',
  },
  summaryGrid: { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(185px, 1fr))', gap: 12 },
  contentGrid: { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 360px), 1fr))', gap: 12 },
  card: {
    minWidth: 0, border: '1px solid var(--ui-stroke-secondary)', borderRadius: 10,
    background: 'var(--ui-editor-background)', padding: 16,
  },
  highlightCard: {
    minWidth: 0, border: '1px solid color-mix(in srgb, var(--ui-accent) 45%, transparent)', borderRadius: 10,
    background: 'color-mix(in srgb, var(--ui-accent) 8%, var(--ui-editor-background))', padding: 16,
  },
  cardLabel: { display: 'flex', alignItems: 'center', gap: 7, color: 'var(--ui-text-tertiary)', fontSize: 12 },
  cardValue: { marginTop: 12, fontSize: 24, fontWeight: 650, fontVariantNumeric: 'tabular-nums' },
  hint: { marginTop: 5, color: 'var(--ui-text-quaternary)', fontSize: 11 },
  sectionTitle: { fontSize: 13, fontWeight: 600 },
  sectionDescription: { color: 'var(--ui-text-quaternary)', fontSize: 11, marginTop: 3 },
  chart: { width: '100%', height: 230, display: 'block', marginTop: 12 },
  muted: { color: 'var(--ui-text-tertiary)' },
  empty: { minHeight: 190, display: 'grid', placeItems: 'center', color: 'var(--ui-text-quaternary)', fontSize: 12 },
  error: {
    border: '1px solid var(--ui-danger-border, #8f3a3a)', borderRadius: 8,
    padding: 14, display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12,
  },
  table: { width: '100%', borderCollapse: 'collapse', marginTop: 10, fontSize: 12 },
  cell: { padding: '9px 6px', borderTop: '1px solid var(--ui-stroke-secondary)', textAlign: 'left' },
  amount: { textAlign: 'right', fontVariantNumeric: 'tabular-nums', whiteSpace: 'nowrap' },
  legend: { display: 'grid', gap: 7, marginTop: 12 },
  legendRow: { display: 'grid', gridTemplateColumns: '10px 1fr auto', alignItems: 'center', gap: 7, fontSize: 11 },
}

function currency(value) {
  return `¥${Number(value || 0).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

function percent(value) {
  return `${Number(value || 0).toFixed(1)}%`
}

function shortCurrency(value) {
  const amount = Number(value || 0)
  return Math.abs(amount) >= 10000 ? `¥${(amount / 10000).toFixed(1)}万` : `¥${Math.round(amount).toLocaleString('zh-CN')}`
}

function displayTime(value) {
  if (!value) return '--'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' }).format(date)
}

function Section({ title, description, children, span }) {
  return jsxs('section', {
    style: { ...styles.card, ...(span ? { gridColumn: '1 / -1' } : {}) },
    children: [
      jsx('div', { style: styles.sectionTitle, children: title }),
      jsx('div', { style: styles.sectionDescription, children: description }),
      children,
    ],
  })
}

function SummaryCard({ icon, label, value, hint, highlight }) {
  return jsxs('div', {
    style: highlight ? styles.highlightCard : styles.card,
    children: [
      jsxs('div', { style: styles.cardLabel, children: [jsx(Codicon, { name: icon }), label] }),
      jsx('div', { style: styles.cardValue, children: value }),
      jsx('div', { style: styles.hint, children: hint }),
    ],
  })
}

function EmptyChart() {
  return jsx('div', { style: styles.empty, children: '暂无数据' })
}

function LineChart({ months }) {
  const rows = months.filter((item) => item.cumulative !== null || item.lastYearCumulative !== null)
  if (!rows.length) return jsx(EmptyChart, {})
  const width = 720
  const height = 220
  const padding = { left: 58, right: 18, top: 18, bottom: 32 }
  const values = rows.flatMap((item) => [item.cumulative, item.lastYearCumulative]).filter((value) => value !== null)
  const max = Math.max(...values, 1)
  const x = (month) => padding.left + ((month - 1) / 11) * (width - padding.left - padding.right)
  const y = (value) => padding.top + (1 - value / max) * (height - padding.top - padding.bottom)
  const points = (key) => months.filter((item) => item[key] !== null).map((item) => `${x(item.month)},${y(item[key])}`).join(' ')
  const grid = [0, 0.5, 1].map((ratio) => {
    const yy = padding.top + ratio * (height - padding.top - padding.bottom)
    return jsxs(Fragment, {
      children: [
        jsx('line', { x1: padding.left, x2: width - padding.right, y1: yy, y2: yy, stroke: 'var(--ui-stroke-secondary)' }),
        jsx('text', { x: padding.left - 8, y: yy + 4, textAnchor: 'end', fill: 'var(--ui-text-quaternary)', fontSize: 10, children: shortCurrency(max * (1 - ratio)) }),
      ],
    }, ratio)
  })
  return jsxs('svg', {
    viewBox: `0 0 ${width} ${height}`, style: styles.chart, role: 'img', 'aria-label': '累计净支出折线图',
    children: [
      ...grid,
      jsx('polyline', { points: points('lastYearCumulative'), fill: 'none', stroke: 'var(--ui-text-quaternary)', strokeWidth: 2, strokeDasharray: '5 5' }),
      jsx('polyline', { points: points('cumulative'), fill: 'none', stroke: 'var(--ui-accent)', strokeWidth: 3, strokeLinecap: 'round', strokeLinejoin: 'round' }),
      ...MONTHS.map((month) => jsx('text', { x: x(month), y: height - 8, textAnchor: 'middle', fill: 'var(--ui-text-quaternary)', fontSize: 9, children: month }, month)),
    ],
  })
}

function BarChart({ months }) {
  const populated = months.filter((item) => item.amount !== null)
  if (!populated.length) return jsx(EmptyChart, {})
  const width = 720
  const height = 220
  const padding = { left: 48, right: 14, top: 16, bottom: 30 }
  const max = Math.max(BUDGET, ...populated.map((item) => item.amount), 1)
  const plotWidth = width - padding.left - padding.right
  const step = plotWidth / 12
  const barWidth = Math.max(8, step * 0.58)
  const y = (value) => padding.top + (1 - value / max) * (height - padding.top - padding.bottom)
  const budgetY = y(BUDGET)
  return jsxs('svg', {
    viewBox: `0 0 ${width} ${height}`, style: styles.chart, role: 'img', 'aria-label': '每月净支出柱状图',
    children: [
      jsx('line', { x1: padding.left, x2: width - padding.right, y1: budgetY, y2: budgetY, stroke: '#c96442', strokeWidth: 1.5, strokeDasharray: '5 4' }),
      jsx('text', { x: width - padding.right, y: budgetY - 5, textAnchor: 'end', fill: '#c96442', fontSize: 9, children: '预算 ¥8,000' }),
      ...months.map((item) => {
        const value = item.amount || 0
        const xx = padding.left + (item.month - 0.5) * step - barWidth / 2
        const yy = y(Math.max(value, 0))
        return jsxs(Fragment, {
          children: [
            item.amount === null ? null : jsx('rect', {
              x: xx, y: yy, width: barWidth, height: Math.max(1, height - padding.bottom - yy), rx: 3,
              fill: value >= BUDGET ? '#c96442' : 'var(--ui-accent)', opacity: value >= BUDGET ? 0.9 : 0.65,
            }),
            jsx('text', { x: padding.left + (item.month - 0.5) * step, y: height - 8, textAnchor: 'middle', fill: 'var(--ui-text-quaternary)', fontSize: 9, children: item.month }),
          ],
        }, item.month)
      }),
    ],
  })
}

function DonutChart({ categories, total }) {
  if (!categories.length) return jsx(EmptyChart, {})
  let offset = 0
  const circles = categories.map((category, index) => {
    const length = Math.max(0, category.percent)
    const node = jsx('circle', {
      cx: 70, cy: 70, r: 48, fill: 'none', stroke: COLORS[index % COLORS.length], strokeWidth: 18,
      strokeDasharray: `${length} ${100 - length}`, strokeDashoffset: -offset,
      pathLength: 100, transform: 'rotate(-90 70 70)',
    }, category.type)
    offset += length
    return node
  })
  return jsxs('div', {
    style: { display: 'grid', gridTemplateColumns: 'minmax(130px, 0.8fr) minmax(160px, 1.2fr)', alignItems: 'center', gap: 8, marginTop: 10 },
    children: [
      jsxs('svg', { viewBox: '0 0 140 140', style: { width: '100%', maxHeight: 190 }, children: [
        ...circles,
        jsx('text', { x: 70, y: 66, textAnchor: 'middle', fill: 'var(--ui-text-tertiary)', fontSize: 9, children: '支出' }),
        jsx('text', { x: 70, y: 82, textAnchor: 'middle', fill: 'var(--ui-text-primary)', fontSize: 12, fontWeight: 650, children: shortCurrency(total) }),
      ] }),
      jsx('div', { style: styles.legend, children: categories.slice(0, 8).map((category, index) => jsxs('div', {
        style: styles.legendRow,
        children: [
          jsx('span', { style: { width: 8, height: 8, borderRadius: 2, background: COLORS[index % COLORS.length] } }),
          jsx('span', { style: { overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }, children: `${category.type} · ${category.count} 笔` }),
          jsx('span', { style: styles.muted, children: percent(category.percent) }),
        ],
      }, category.type)) }),
    ],
  })
}

function RecentTable({ records }) {
  if (!records.length) return jsx(EmptyChart, {})
  return jsx('div', { style: { overflowX: 'auto' }, children: jsxs('table', {
    style: styles.table,
    children: [
      jsx('thead', { children: jsxs('tr', { style: styles.muted, children: [
        jsx('th', { style: styles.cell, children: '时间' }),
        jsx('th', { style: styles.cell, children: '交易对方' }),
        jsx('th', { style: styles.cell, children: '分类' }),
        jsx('th', { style: { ...styles.cell, ...styles.amount }, children: '金额' }),
      ] }) }),
      jsx('tbody', { children: records.map((record) => jsxs('tr', { children: [
        jsx('td', { style: { ...styles.cell, whiteSpace: 'nowrap', color: 'var(--ui-text-tertiary)' }, children: displayTime(record.transaction_time) }),
        jsx('td', { style: styles.cell, children: record.counterparty }),
        jsx('td', { style: styles.cell, children: record.category }),
        jsx('td', {
          style: { ...styles.cell, ...styles.amount, color: record.direction === '收入' ? 'var(--ui-success, #57965c)' : 'var(--ui-text-primary)' },
          children: `${record.direction === '收入' ? '+' : '-'}${currency(record.amount)}`,
        }),
      ] }, record.transaction_id)) }),
    ],
  }) })
}

function createDashboard(ctx) {
  return function BillDashboard() {
    const [year, setYear] = useState(null)
    const [month, setMonth] = useState(null)
    const path = useMemo(() => {
      const params = new URLSearchParams()
      if (year) params.set('year', String(year))
      if (month) params.set('month', String(month))
      const query = params.toString()
      return `/overview${query ? `?${query}` : ''}`
    }, [year, month])
    const query = useQuery({
      queryKey: [ctx.source, 'overview', year, month],
      queryFn: () => ctx.rest(path),
      refetchInterval: 30000,
      refetchOnWindowFocus: true,
      retry: 1,
    })
    const data = query.data
    useEffect(() => {
      if (!data) return
      if (!year) setYear(data.selectedYear)
      if (!month) setMonth(data.selectedMonth)
    }, [data, year, month])

    if (query.isLoading && !data) {
      return jsx('div', { style: { ...styles.root, ...styles.empty }, children: '正在读取远程账单…' })
    }
    if (query.error && !data) {
      const message = query.error instanceof Error ? query.error.message : '远程账单服务不可用'
      return jsx('div', { style: styles.root, children: jsx('div', { style: styles.shell, children: jsxs('div', {
        style: styles.error,
        children: [
          jsxs('div', { children: [jsx('div', { children: '无法连接远程账单服务' }), jsx('div', { style: styles.hint, children: `${message}。请确认远程 Agent 插件已安装并启用。` })] }),
          jsx(Button, { size: 'sm', onClick: () => query.refetch(), children: '重试' }),
        ],
      }) }) })
    }

    const summary = data?.summary || {}
    const top = summary.topCategory
    const yearLabel = year === new Date().getFullYear() ? '今年' : `${year} 年`
    return jsx('main', { style: styles.root, children: jsxs('div', {
      style: styles.shell,
      children: [
        jsxs('header', { style: styles.header, children: [
          jsxs('div', { children: [jsx('div', { style: styles.title, children: '账单' }), jsx('div', { style: styles.subtitle, children: '数据、解析与统计均来自当前远程 Hermes 服务' })] }),
          jsxs('div', { style: styles.controls, children: [
            jsx('select', {
              style: styles.select, value: year || '', 'aria-label': '年份',
              onChange: (event) => setYear(Number(event.target.value)),
              children: (data?.availableYears?.length ? data.availableYears : [data?.selectedYear]).filter(Boolean).map((value) => jsx('option', { value, children: `${value} 年` }, value)),
            }),
            jsx('select', {
              style: styles.select, value: month || '', 'aria-label': '月份',
              onChange: (event) => setMonth(Number(event.target.value)),
              children: MONTHS.map((value) => jsx('option', { value, children: `${value} 月` }, value)),
            }),
            jsx(Button, { size: 'sm', variant: 'ghost', disabled: query.isFetching, onClick: () => query.refetch(), children: query.isFetching ? '刷新中…' : '刷新' }),
          ] }),
        ] }),
        jsx('section', { style: styles.summaryGrid, children: [
          jsx(SummaryCard, { icon: 'credit-card', label: '累计净支出', value: currency(summary.totalExpense), hint: `${yearLabel}已统计 ${summary.monthsWithData || 0} 个月`, highlight: true }, 'net'),
          jsx(SummaryCard, { icon: 'graph-line', label: '月均净支出', value: currency(summary.averageMonthlyExpense), hint: summary.peakMonth ? `峰值出现在 ${summary.peakMonth.label}` : '暂无峰值月份' }, 'average'),
          jsx(SummaryCard, { icon: 'pie-chart', label: '最大分类', value: top ? `${top.type} ${percent(top.percent)}` : '--', hint: top ? `${currency(top.amount)} / ${top.count} 笔` : '暂无分类' }, 'category'),
          jsx(SummaryCard, { icon: 'list-unordered', label: '交易笔数', value: Number(summary.transactionCount || 0).toLocaleString('zh-CN'), hint: `${yearLabel}全部交易` }, 'count'),
        ] }),
        jsx('section', { style: styles.contentGrid, children: [
          jsx(Section, { title: `${yearLabel}累计支出（净）`, description: '按交易时间累计，对比去年同期', children: jsx(LineChart, { months: data?.months || [] }) }, 'line'),
          jsx(Section, { title: '合计支出分类', description: '年度毛支出金额占比', children: jsx(DonutChart, { categories: data?.categories || [], total: summary.grossExpense || 0 }) }, 'annual'),
          jsx(Section, { title: '每月支出', description: '已冲减退款收入 · 红线为 ¥8,000 预算阈值', children: jsx(BarChart, { months: data?.months || [] }) }, 'bars'),
          jsx(Section, { title: '月度支出分类', description: `${year || ''}年${month || ''}月 · 毛支出金额占比`, children: jsx(DonutChart, { categories: data?.monthlyCategories || [], total: data?.monthlyGrossExpense || 0 }) }, 'monthly'),
          jsx(Section, { title: '最近交易', description: '按时间倒序，最多显示 5 笔', span: true, children: jsx(RecentTable, { records: data?.recent || [] }) }, 'recent'),
        ] }),
      ],
    }) })
  }
}

export default {
  id: 'hermes-bill',
  name: '账单',
  defaultEnabled: false,
  register(ctx) {
    const Dashboard = createDashboard(ctx)
    let workspaceDispose = null
    const open = () => {
      if (typeof host.openWorkspace === 'function') {
        workspaceDispose = host.openWorkspace('hermes-bill-dashboard', {
          title: '账单',
          minWidth: 520,
          render: () => jsx(Dashboard, {}),
          onClose: () => { workspaceDispose = null },
        })
      }
    }

    ctx.register({
      id: 'open',
      area: PALETTE_AREA,
      data: { id: 'hermes-bill.open', label: '打开账单', keywords: ['bill', '账单', '消费', '支出'], run: open },
    })

    if (typeof host.openWorkspace === 'function') {
      open()
      ctx.onDispose(() => { if (workspaceDispose) workspaceDispose() })
    } else {
      ctx.register({
        id: 'dashboard',
        area: 'panes',
        title: '账单',
        data: { placement: 'main', dock: { pane: 'workspace', pos: 'center' }, width: '720px' },
        render: () => jsx(Dashboard, {}),
      })
    }
  },
}
