import { cn } from '@/lib/cn'
import { FaCalendarDays } from "react-icons/fa6"
import { formatDateTime } from '@/lib/format'
import type { ChatMinimal, ChatStatus } from '@/types/types'

const STATUS_LABELS: Record<ChatStatus, string> = {
  'ai': 'Ассистент',
  'first-lane': 'Первая линия',
  'second-lane': 'Вторая линия',
  'third-lane': 'Третья линия',
  'closed': 'Закрыто',
  'banned': 'Заблокировано',
}

const STATUS_CLASSES: Record<ChatStatus, string> = {
  'ai': 'bg-pale-blue text-main-blue',
  'first-lane': 'bg-orange/10 text-orange',
  'second-lane': 'bg-orange/10 text-orange',
  'third-lane': 'bg-orange/10 text-orange',
  'banned': 'bg-red/10 text-red',
  'closed': 'bg-light-gray/40 text-gray',
}

interface ChatListItemProps {
  chat: ChatMinimal
  isActive?: boolean
  onClick?: (chat: ChatMinimal) => void
  className?: string
}

export default function ChatListItem({ chat, isActive = false, onClick, className }: ChatListItemProps) {
  return (
    <button
      type="button"
      onClick={() => onClick?.(chat)}
      aria-current={isActive ? 'true' : undefined}
      className={cn(
        'flex w-full justify-between p-4 border border-transparent text-left transition-colors',
        'border-b-gray-200',
        isActive ? 'bg-main-blue/10' : 'hover:bg-pale-blue/60',
        className,
      )}
    >
      <span className="text-pale-black truncate text-sm font-medium">{chat.chat_title}</span>
      <div className="flex gap-4 w-[50%]">
        <span className="flex gap-2 items-center text-gray shrink-0 text-xs"><FaCalendarDays/>{formatDateTime(chat.chat_creation_date)}</span>
        <span className="flex items-center justify-between gap-2">
            <span className={cn('rounded px-1.5 py-0.5 text-[11px] font-medium', STATUS_CLASSES[chat.chat_status])}>
            {STATUS_LABELS[chat.chat_status]}
            </span>
        </span>
      </div>
    </button>
  )
}
