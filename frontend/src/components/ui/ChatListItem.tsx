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
        // Single row: flexible title, then fixed-width date, rating and status.
        'flex w-full items-center gap-6 p-4 text-left',
        'border-gray-blue border-b transition-colors',
        isActive ? 'bg-main-blue/10' : 'hover:bg-pale-blue/60',
        className,
      )}
    >
      <span className="text-black min-w-0 flex-1 truncate text-sm font-medium" title={chat.title}>
        {chat.title}
      </span>

      {/* <span className="flex w-16 shrink-0 justify-end">
        {chat.rating && <StarRating stars={chat.rating.stars} comment={chat.rating.comment} showComment={false} />}
      </span> */}

      <span className="text-gray flex shrink-0 items-center gap-1.5 text-xs whitespace-nowrap">
        <FaCalendarDays className="size-3" />
        {formatDateTime(chat.createdAt)}
      </span>


      <span
        className={cn(
          'w-36 shrink-0 rounded px-1.5 py-0.5 text-center text-[11px] font-medium whitespace-nowrap',
          CHAT_STATUS_CLASSES[chat.status],
        )}
      >
        {CHAT_STATUS_LABELS[chat.status]}
      </span>

    </button>
  )
}
