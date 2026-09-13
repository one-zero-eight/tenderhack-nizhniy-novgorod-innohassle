import { createFileRoute } from '@tanstack/react-router'
import { useState } from 'react'
import LoadingSpinner from '@/components/ui/LoadingSpinner'
import Button from '@/components/ui/Button'
import ChatRow, { ChatRowHeader } from '@/components/ui/ChatRow'
import { requireRole } from '@/app/routes/-guards'
import { useAdminChats } from '@/hooks/useAdminChats'
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
        <div className={cn('border-gray-blue border', isFetching ? 'opacity-60' : undefined)}>
          <ChatRowHeader />
          {chats.map((chat) => (
            <ChatRow key={chat.id} chat={chat} to="/history/$chatId" />
          ))}
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
