import { cn } from '@/lib/cn'
import { formatDateTime } from '@/lib/format'
import type { ChatMessageData, ChatMessageSender } from '@/types/types'

const SENDER_LABELS: Record<ChatMessageSender, string> = {
  user: 'Вы',
  ai: 'ИИ-ассистент',
  'first-lane': 'Линия 1',
  'second-lane': 'Линия 2',
  'third-lane': 'Линия 3',
}

const isUser = (sender: ChatMessageSender) => sender === 'user'

interface ChatMessageProps {
  message: ChatMessageData
  className?: string
}

export default function ChatMessage({ message, className }: ChatMessageProps) {
  const mine = isUser(message.sender)

  return (
    <div className={cn('flex w-full', mine ? 'justify-end' : 'justify-start', className)}>
      <div className={cn('flex max-w-[80%] flex-col gap-1', mine ? 'items-end' : 'items-start')}>
        <span className="text-gray flex items-center gap-2 text-xs">
          <span className="font-medium">{SENDER_LABELS[message.sender]}</span>
          <span>{formatDateTime(message.sent_at)}</span>
        </span>
        <div
          className={cn(
            'rounded-2xl px-4 py-2 text-sm whitespace-pre-wrap break-words',
            mine ? 'bg-main-blue rounded-br-sm text-white' : 'bg-white text-pale-black rounded-bl-sm',
          )}
        >
          {message.text}
        </div>
      </div>
    </div>
  )
}
