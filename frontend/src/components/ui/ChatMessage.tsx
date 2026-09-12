import { cn } from '@/lib/cn'
import { formatDateTime } from '@/lib/format'
import { SENDER_LABELS, type MessageView } from '@/lib/chat-view'
import { SenderType } from '@/api/types'

interface ChatMessageProps {
  message: MessageView
  className?: string
}

export default function ChatMessage({ message, className }: ChatMessageProps) {
  const mine = message.senderType === SenderType.user

  return (
    <div className={cn('flex w-full', mine ? 'justify-end' : 'justify-start', className)}>
      <div className={cn('flex max-w-[80%] flex-col gap-1', mine ? 'items-end' : 'items-start')}>
        <span className="text-gray flex items-center gap-2 text-xs">
          <span className="font-medium">{message.senderName || SENDER_LABELS[message.senderType]}</span>
          <span>{formatDateTime(message.createdAt)}</span>
        </span>
        <div
          className={cn(
            'rounded-2xl px-4 py-2 text-sm whitespace-pre-wrap break-words',
            mine ? 'bg-main-blue rounded-br-sm text-white' : 'bg-white text-pale-black rounded-bl-sm',
            message.isRedacted ? 'italic opacity-70' : undefined,
          )}
        >
          {message.text}
        </div>
      </div>
    </div>
  )
}
