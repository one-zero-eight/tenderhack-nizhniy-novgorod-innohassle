import { cn } from '@/lib/cn'
import { FaCalendarDays } from 'react-icons/fa6'
import { formatDateTime } from '@/lib/format'
import { CHAT_STATUS_CLASSES, CHAT_STATUS_LABELS, type ChatView } from '@/lib/chat-view'

interface ChatListItemProps {
  chat: ChatView
  isActive?: boolean
  onClick?: (chat: ChatView) => void
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
      <span className="text-black truncate text-sm font-medium">{chat.title}</span>
      <div className="flex gap-4 w-[50%]">
        <span className="flex gap-2 items-center text-gray shrink-0 text-xs">
          <FaCalendarDays />
          {formatDateTime(chat.createdAt)}
        </span>
        <span className="flex items-center justify-between gap-2">
          <span className={cn('rounded px-1.5 py-0.5 text-[11px] font-medium', CHAT_STATUS_CLASSES[chat.status])}>
            {CHAT_STATUS_LABELS[chat.status]}
          </span>
        </span>
      </div>
    </button>
  )
}
