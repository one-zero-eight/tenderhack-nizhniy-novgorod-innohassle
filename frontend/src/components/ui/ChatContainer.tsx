import { Fragment, useState, type FormEvent } from 'react'
import ChatDateDivider from '@/components/ui/ChatDateDivider'
import ChatInput from '@/components/ui/ChatInput'
import ChatMessage from '@/components/ui/ChatMessage'
import ChatRedirectDivider from '@/components/ui/ChatRedirectDivider'
import LoadingSpinner from '@/components/ui/LoadingSpinner'
import RatingInput from '@/components/ui/RatingInput'
import type { ChatCommand } from '@/components/ui/ChatCommandsMenu'
import { useFileAttachments } from '@/hooks/useFileAttachments'
import { cn } from '@/lib/cn'
import { dayKey, formatDateSeparator } from '@/lib/format'
import { SenderType } from '@/api/types'
import type { MessageView } from '@/lib/chat-view'

interface ChatContainerProps {
  messages: MessageView[]
  onSend?: (text: string) => void
  onRate?: (stars: number, comment: string) => void
  disabled?: boolean
  /** Short status shown while the assistant runs a tool (searching, reading…). */
  toolStatus?: string | null
  className?: string
}

const RATE_COMMAND = "/оценить"
const HELP_COMMAND = "/запросить_помощь"

/** Slash-commands offered near the composer's send button. */
const COMMANDS: ChatCommand[] = [
  {
    value: RATE_COMMAND,
    description: 'Оценить работу поддержки: поставить звёзды и оставить комментарий',
  },
  {
    value: HELP_COMMAND,
    description: 'Перевести диалог на оператора-человека',
  },
]

export default function ChatContainer({ messages, onSend, onRate, disabled = false, toolStatus, className }: ChatContainerProps) {
  const [text, setText] = useState('')
  const [showRating, setShowRating] = useState(false)
  const trimmed = text.trim()
  const { attachments, addFiles, removeFile, clearFiles } = useFileAttachments()

  const submit = () => {
    if (!trimmed || disabled) return
    // Submitting `/оценить` opens the rating dialog instead of sending a
    // regular streaming message. Other commands (`/передать`) are handled
    // elsewhere and fall through to the regular send above.
    if (trimmed === RATE_COMMAND) {
      setText('')
      setShowRating(true)
      return
    }
    if (trimmed === HELP_COMMAND) {
        setText('')
        alert("Запрошена поддержка от реальных людей")
        return
    }
    onSend?.(trimmed)
    setText('')
    // Attachments are local-only for now; dropped once the message is sent.
    clearFiles()
  }

  const submitRating = (stars: number, comment: string) => {
    if (disabled) return
    onRate?.(stars, comment)
    setShowRating(false)
  }

  // Also allow submitting via the "Отправить" button (native form submit).
  const handleSubmit = (e: FormEvent) => {
    e.preventDefault()
    submit()
  }

  return (
    <div className={cn('flex min-h-0 flex-1 flex-col gap-4', className)}>
      <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto">
        {messages.length === 0 ? (
          <p className="text-gray py-10 text-center text-sm">Сообщений пока нет. Задайте свой вопрос.</p>
        ) : (
          messages.map((message, index) => {
            // Insert a Telegram-style date divider whenever the calendar day
            // changes between consecutive messages.
            const showDate = index === 0 || dayKey(message.createdAt) !== dayKey(messages[index - 1].createdAt)
            return (
              <Fragment key={message.id}>
                {showDate && <ChatDateDivider label={formatDateSeparator(message.createdAt)} />}
                {/* System messages and hand-off notices are rendered as a
                    delimiter rather than a chat bubble. */}
                {message.senderType === SenderType.system || message.redirectLine ? (
                  <ChatRedirectDivider text={message.text} />
                ) : (
                  <ChatMessage message={message} />
                )}
              </Fragment>
            )
          })
        )}

        {toolStatus && (
          <div className="text-gray flex items-center gap-2 text-xs" role="status">
            <LoadingSpinner size="sm" />
            <span>{toolStatus}</span>
          </div>
        )}
      </div>

      <form onSubmit={handleSubmit} className="shrink-0">
        <ChatInput
          value={text}
          onChange={setText}
          onSubmit={submit}
          placeholder={disabled ? 'Ожидайте ответа...' : 'Введите сообщение...'}
          disabled={disabled}
          aria-label="Сообщение"
          attachments={attachments}
          onFilesAdded={addFiles}
          onRemoveAttachment={removeFile}
          commands={COMMANDS}
        />
      </form>

      {showRating && (
        <RatingInput onSubmit={submitRating} onClose={() => setShowRating(false)} disabled={disabled} />
      )}
    </div>
  )
}
