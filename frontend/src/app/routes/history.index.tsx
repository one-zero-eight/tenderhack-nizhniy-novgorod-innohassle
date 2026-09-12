import { Link, createFileRoute } from '@tanstack/react-router'
import { useState } from 'react'
import LoadingSpinner from '@/components/ui/LoadingSpinner'
import Button from '@/components/ui/Button'
import StarRating from '@/components/ui/StarRating'
import { requireRole } from '@/app/routes/-guards'
import { useAdminChats } from '@/hooks/useAdminChats'
import { CHAT_STATUS_CLASSES, CHAT_STATUS_LABELS, SUPPORT_LINE_NAMES } from '@/lib/chat-view'
import { formatDateTime } from '@/lib/format'
import { cn } from '@/lib/cn'
import { Role } from '@/api/types'

export const Route = createFileRoute('/history/')({
  beforeLoad: () => requireRole([Role.admin]),
  component: HistoryPage,
})

const PAGE_SIZE = 25

function HistoryPage() {
  const [offset, setOffset] = useState(0)
  const { data, isLoading, isError, error, refetch, isFetching } = useAdminChats({ offset, limit: PAGE_SIZE })

  const chats = data?.items ?? []
  const total = data?.total ?? 0
  const hasPrev = offset > 0
  const hasNext = offset + PAGE_SIZE < total

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-1 flex-col gap-6 px-4 py-8">
      <div className="flex items-center justify-between gap-4">
        <h1 className="text-black text-2xl font-bold">История обращений</h1>
        {!isLoading && <span className="text-gray text-sm">Всего: {total}</span>}
      </div>

      {isLoading ? (
        <div className="flex justify-center py-10">
          <LoadingSpinner size="lg" />
        </div>
      ) : isError ? (
        <div className="flex flex-col items-center gap-3 py-10">
          <p className="text-red text-sm">{error?.message || 'Не удалось загрузить историю'}</p>
          <button type="button" onClick={() => refetch()} className="text-main-blue text-sm underline underline-offset-4">
            Повторить
          </button>
        </div>
      ) : chats.length === 0 ? (
        <p className="text-gray text-sm">Обращений пока нет.</p>
      ) : (
        <div className={cn('border-gray-blue overflow-x-auto border', isFetching ? 'opacity-60' : undefined)}>
          <table className="w-full border-collapse text-sm">
            <thead>
              <tr className="border-gray-blue text-gray border-b text-left text-xs uppercase">
                <th className="px-3 py-2 font-semibold">Тема</th>
                <th className="px-3 py-2 font-semibold">Статус</th>
                <th className="px-3 py-2 font-semibold">Получатель</th>
                <th className="px-3 py-2 font-semibold">Оператор</th>
                <th className="px-3 py-2 font-semibold">Оценка</th>
                <th className="px-3 py-2 font-semibold">Создано</th>
                <th className="px-3 py-2 font-semibold">Обновлено</th>
              </tr>
            </thead>
            <tbody>
              {chats.map((chat) => (
                <tr key={chat.id} className="border-gray-blue hover:bg-pale-blue/40 border-b last:border-b-0">
                  <td className="max-w-xs px-3 py-2">
                    <Link
                      to="/history/$chatId"
                      params={{ chatId: chat.id }}
                      className="text-main-blue block truncate font-medium underline underline-offset-2"
                      title={chat.title}
                    >
                      {chat.title}
                    </Link>
                  </td>
                  <td className="px-3 py-2">
                    <span className={cn('rounded px-1.5 py-0.5 text-[11px] font-medium whitespace-nowrap', CHAT_STATUS_CLASSES[chat.status])}>
                      {CHAT_STATUS_LABELS[chat.status]}
                    </span>
                  </td>
                  <td className="text-pale-black px-3 py-2 whitespace-nowrap">
                    {chat.support_line
                      ? (SUPPORT_LINE_NAMES[`L${chat.support_line.id}`] ?? chat.support_line.name)
                      : chat.recipient.display_name}
                  </td>
                  <td className="text-pale-black px-3 py-2 whitespace-nowrap">{chat.operator?.display_name ?? '—'}</td>
                  <td className="px-3 py-2 whitespace-nowrap">
                    {chat.rating ? <StarRating stars={chat.rating.stars} comment={chat.rating.comment} showComment={false} /> : <span className="text-gray">—</span>}
                  </td>
                  <td className="text-gray px-3 py-2 whitespace-nowrap">{formatDateTime(chat.created_at)}</td>
                  <td className="text-gray px-3 py-2 whitespace-nowrap">{formatDateTime(chat.updated_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {total > PAGE_SIZE && (
        <div className="flex items-center justify-between gap-4">
          <Button variant="outline" size="sm" disabled={!hasPrev} onClick={() => setOffset((value) => Math.max(0, value - PAGE_SIZE))}>
            Назад
          </Button>
          <span className="text-gray text-sm">
            {offset + 1}–{Math.min(offset + PAGE_SIZE, total)} из {total}
          </span>
          <Button variant="outline" size="sm" disabled={!hasNext} onClick={() => setOffset((value) => value + PAGE_SIZE)}>
            Вперёд
          </Button>
        </div>
      )}
    </div>
  )
}
