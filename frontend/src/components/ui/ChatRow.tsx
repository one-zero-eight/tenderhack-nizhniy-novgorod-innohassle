import { useNavigate } from '@tanstack/react-router'
import { FaCalendarDays, FaUser } from 'react-icons/fa6'
import StarRating from '@/components/ui/StarRating'
import { CHAT_STATUS_CLASSES, CHAT_STATUS_LABELS } from '@/lib/chat-view'
import { CHAT_ROW_GRID, chatUserName } from '@/lib/chat-row'
import { formatDateTime } from '@/lib/format'
import { cn } from '@/lib/cn'
import type { SchemaChatOut } from '@/api/types'

interface ChatRowProps {
  chat: SchemaChatOut
  /** Where clicking the row navigates: the chat page within the given section. */
  to: '/history/$chatId' | '/support/$chatId' | '/issues/$topic/$chatId'
  /** Extra route params (e.g. the topic for the issues route). */
  params?: Record<string, string>
  className?: string
}

/** A single clickable chat row, used by the history and issues lists. */
export default function ChatRow({ chat, to, params, className }: ChatRowProps) {
  const navigate = useNavigate()
  return (
    <button
      type="button"
      onClick={() => navigate({ to, params: { chatId: chat.id, ...params } })}
      className={cn(
        CHAT_ROW_GRID,
        'border-gray-blue hover:bg-pale-blue/60 w-full border-b py-4 text-left transition-colors',
        className,
      )}
    >
      <span className="text-black min-w-0 truncate text-sm font-medium" title={chat.title}>
        {chat.title}
      </span>

      <span className="text-pale-black flex min-w-0 items-center gap-1.5 text-sm">
        <FaUser className="text-gray size-3 shrink-0" />
        <span className="truncate" title={chatUserName(chat)}>
          {chatUserName(chat)}
        </span>
      </span>

      <span className="justify-self-start">
        {chat.rating ? (
          <StarRating stars={chat.rating.stars} comment={chat.rating.comment} showComment={false} />
        ) : (
          <span className="text-gray text-xs">—</span>
        )}
      </span>

      <span className="text-gray flex items-center gap-1.5 text-xs whitespace-nowrap">
        <FaCalendarDays className="size-3" />
        {formatDateTime(chat.created_at)}
      </span>

      <span
        className={cn(
          'w-fit rounded px-1.5 py-0.5 text-[11px] font-medium whitespace-nowrap',
          CHAT_STATUS_CLASSES[chat.status],
        )}
      >
        {CHAT_STATUS_LABELS[chat.status]}
      </span>
    </button>
  )
}

/** Column titles matching {@link CHAT_ROW_GRID}. */
export function ChatRowHeader() {
  return (
    <div className={cn(CHAT_ROW_GRID, 'border-gray-blue text-gray border-b py-2 text-xs font-semibold uppercase')}>
      <span>Тема</span>
      <span>Пользователь</span>
      <span>Оценка</span>
      <span>Создано</span>
      <span>Статус</span>
    </div>
  )
}
