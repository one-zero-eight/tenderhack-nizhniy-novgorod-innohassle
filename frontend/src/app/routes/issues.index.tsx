import { Link, createFileRoute } from '@tanstack/react-router'
import { useMemo, useState } from 'react'
import { FaChevronRight, FaSort, FaSortDown, FaSortUp } from 'react-icons/fa6'
import LoadingSpinner from '@/components/ui/LoadingSpinner'
import { requireRole } from '@/app/routes/-guards'
import { useAllAdminChats } from '@/hooks/useAdminChats'
import { summarizeTopics, type TopicSummary } from '@/lib/issues'
import { cn } from '@/lib/cn'
import { Role } from '@/api/types'

export const Route = createFileRoute('/issues/')({
  beforeLoad: () => requireRole([Role.admin]),
  component: IssuesPage,
})

/** Sortable columns of the topics table. */
type SortKey = 'chatCount' | 'averageAnswerSeconds'
type SortDirection = 'asc' | 'desc'

/** Formats an average answer time given in seconds. */
function formatAverageAnswer(seconds: number | null): string {
  if (seconds === null) return '—'
  if (seconds < 60) return `${Math.round(seconds)} сек`
  const minutes = seconds / 60
  return minutes < 60 ? `${minutes.toFixed(1)} мин` : `${(minutes / 60).toFixed(1)} ч`
}


/** Sorts topics by the active key, pushing unavailable values last. */
function sortTopics(topics: TopicSummary[], key: SortKey, direction: SortDirection): TopicSummary[] {
  const factor = direction === 'asc' ? 1 : -1
  return [...topics].sort((a, b) => {
    const left = a[key]
    const right = b[key]
    // Missing values (null) always sort to the bottom, regardless of direction.
    if (left === null && right === null) return a.topic.localeCompare(b.topic, 'ru')
    if (left === null) return 1
    if (right === null) return -1
    if (left === right) return a.topic.localeCompare(b.topic, 'ru')
    return (left - right) * factor
  })
}

/** Clickable column header that toggles the sort direction. */
function SortableHeader({
  label,
  sortKey,
  activeKey,
  direction,
  onSort,
  className,
}: {
  label: string
  sortKey: SortKey
  activeKey: SortKey
  direction: SortDirection
  onSort: (key: SortKey) => void
  className?: string
}) {
  const active = activeKey === sortKey
  const Icon = !active ? FaSort : direction === 'asc' ? FaSortUp : FaSortDown
  return (
    <button
      type="button"
      onClick={() => onSort(sortKey)}
      aria-label={`Сортировать по «${label}»`}
      className={cn(
        'flex items-center gap-1.5 text-left text-xs font-semibold uppercase transition-colors',
        active ? 'text-main-blue' : 'text-gray hover:text-main-blue',
        className,
      )}
    >
      <span>{label}</span>
      <Icon className="size-3 shrink-0" />
    </button>
  )
}

function TopicRow({ summary }: { summary: TopicSummary }) {
  return (
    <Link
      to="/issues/$topic"
      params={{ topic: summary.topic }}
      className="border-gray-blue hover:bg-pale-blue/60 grid grid-cols-[minmax(0,1fr)_8rem_12rem_3rem] items-center gap-4 border-b px-4 py-4 no-underline transition-colors"
    >
      <span className="text-black truncate text-sm font-medium" title={summary.topic}>
        {summary.topic}
      </span>
      <span className="text-pale-black text-sm">
        {summary.chatCount}
      </span>
      <span className="text-gray text-sm">{formatAverageAnswer(summary.averageAnswerSeconds)}</span>
      <FaChevronRight className="text-gray size-4 justify-self-end" />
    </Link>
  )
}

function IssuesPage() {
  const { data: chats, isLoading, isError, error, refetch } = useAllAdminChats()
  const [sortKey, setSortKey] = useState<SortKey>('chatCount')
  const [direction, setDirection] = useState<SortDirection>('desc')

  const topics = useMemo(() => {
    const summarized = summarizeTopics(chats ?? [])
    return sortTopics(summarized, sortKey, direction)
  }, [chats, sortKey, direction])

  // Toggle direction when re-clicking the active column.
  const handleSort = (key: SortKey) => {
    if (key === sortKey) {
      setDirection((value) => (value === 'asc' ? 'desc' : 'asc'))
      return
    }
    setSortKey(key)
    setDirection('desc')
  }

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-1 flex-col gap-6 px-4 py-8">
      <div className="flex items-center justify-between gap-4">
        <h1 className="text-black text-2xl font-bold">Типичные проблемы</h1>
        {!isLoading && <span className="text-gray text-sm">Тем: {topics.length}</span>}
      </div>

      {isLoading ? (
        <div className="flex justify-center py-10">
          <LoadingSpinner size="lg" />
        </div>
      ) : isError ? (
        <div className="flex flex-col items-center gap-3 py-10">
          <p className="text-red text-sm">{error?.message || 'Не удалось загрузить данные'}</p>
          <button type="button" onClick={() => refetch()} className="text-main-blue text-sm underline underline-offset-4">
            Повторить
          </button>
        </div>
      ) : topics.length === 0 ? (
        <p className="text-gray text-sm">Обращений пока нет.</p>
      ) : (
        <div className="border-gray-blue border">
          <div className="border-gray-blue grid grid-cols-[minmax(0,1fr)_8rem_12rem_3rem] items-center gap-4 border-b px-4 py-2">
            <span className="text-gray text-xs font-semibold uppercase">Тема</span>
            <SortableHeader label="Обращений" sortKey="chatCount" activeKey={sortKey} direction={direction} onSort={handleSort} />
            <SortableHeader
              label="Среднее время ответа"
              sortKey="averageAnswerSeconds"
              activeKey={sortKey}
              direction={direction}
              onSort={handleSort}
            />
            <span />
          </div>
          {topics.map((summary) => (
            <TopicRow key={summary.topic} summary={summary} />
          ))}
        </div>
      )}
    </div>
  )
}
