import { Fragment, useCallback, useEffect, useLayoutEffect, useRef, useState, type FormEvent } from 'react'
import ChatDateDivider from '@/components/ui/ChatDateDivider'
import ChatInput from '@/components/ui/ChatInput'
import ChatMessage from '@/components/ui/ChatMessage'
import ChatRedirectDivider from '@/components/ui/ChatRedirectDivider'
import LoadingSpinner from '@/components/ui/LoadingSpinner'
import RatingInput from '@/components/ui/RatingInput'
import type { ChatCommand } from '@/components/ui/ChatCommandsMenu'
import { useFileAttachments } from '@/hooks/useFileAttachments'
import { useContracts } from '@/hooks/useContracts'
import { extractContracts, withContractHeader } from '@/lib/contracts'
import { cn } from '@/lib/cn'
import { dayKey, formatDateSeparator } from '@/lib/format'
import { SenderType } from '@/api/types'
import type { MessageView } from '@/lib/chat-view'

interface ChatContainerProps {
  messages: MessageView[]
  /**
   * Called with the message text and any pending files. The caller uploads the
   * files and sends the text; files are uploaded before sending because the AI
   * attaches everything pending to the next message.
   */
  onSend?: (text: string, files: File[]) => void | Promise<void>
  onRate?: (stars: number, comment: string) => void
  disabled?: boolean
  /** Text shown in the composer while `disabled` (defaults to a waiting hint). */
  disabledPlaceholder?: string
  /** Hides the composer entirely (e.g. the read-only admin history view). */
  readOnly?: boolean
  /**
   * When provided, assistant replies expose a «Добавить правило» action that
   * receives the assistant reply and the user question it answers.
   */
  onCreateRule?: (assistantText: string, userText: string) => void
  /** Short status shown while the assistant runs a tool (searching, reading…). */
  toolStatus?: string | null
  className?: string
}

const RATE_COMMAND = "/оценить"
const HELP_COMMAND = "/запросить_помощь"

/** Message actually sent when the user requests a human operator. */
const HELP_MESSAGE = 'Пожалуйста, переведите меня на оператора поддержки.'

/**
 * Recognises `/оценить` at the start of a message, returning the optional
 * trailing text to use as the rating comment. `null` when it is not that
 * command.
 */
function parseRateCommand(text: string): { comment: string } | null {
  const value = text.trim()
  if (value === RATE_COMMAND) return { comment: '' }
  if (!value.startsWith(RATE_COMMAND)) return null
  // Require a separator so `/оценитьчто-то` is not treated as the command.
  const rest = value.slice(RATE_COMMAND.length)
  if (rest === '' || !/\s/.test(rest[0])) return null
  return { comment: rest.trim() }
}

/** Whether a message is a reply from the assistant/operator side. */
function isAssistantReply(message: MessageView): boolean {
  return (
    !message.isRedacted &&
    (message.senderType === SenderType.ai ||
      message.senderType === SenderType.operator ||
      message.senderType === SenderType.support)
  )
}

/**
 * The user message that prompted the reply at `index`: the nearest preceding
 * message authored by the user.
 */
function precedingUserMessage(messages: MessageView[], index: number): string | null {
  for (let i = index - 1; i >= 0; i -= 1) {
    if (messages[i].senderType === SenderType.user && !messages[i].isRedacted) return messages[i].text
  }
  return null
}

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

export default function ChatContainer({ messages, onSend, onRate, disabled = false, disabledPlaceholder, readOnly = false, onCreateRule, toolStatus, className }: ChatContainerProps) {
  const [text, setText] = useState('')
  const [showRating, setShowRating] = useState(false)
  const [ratingComment, setRatingComment] = useState('')
  const trimmed = text.trim()
  const { attachments, addFiles, removeFile, clearFiles } = useFileAttachments()
  // Contracts offered by the `@` mention popup in the composer.
  const { contracts } = useContracts()

  const scrollRef = useRef<HTMLDivElement | null>(null)
  // Whether the view is pinned to the newest message. Cleared when the user
  // scrolls up so incoming tokens do not yank them back down.
  const stickToBottom = useRef(true)

  const scrollToBottom = useCallback(() => {
    const el = scrollRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [])

  const handleScroll = useCallback(() => {
    const el = scrollRef.current
    if (!el) return
    // Treat "within 48px of the bottom" as pinned.
    stickToBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 48
  }, [])

  // Jump to the newest message on open, before the browser paints.
  useLayoutEffect(() => {
    scrollToBottom()
  }, [scrollToBottom])

  // Follow the conversation as messages and streamed tokens arrive. The last
  // message's text is part of the dependency list so token updates scroll too.
  const lastMessageText = messages.length > 0 ? messages[messages.length - 1].text : ''
  useEffect(() => {
    if (stickToBottom.current) scrollToBottom()
  }, [messages.length, lastMessageText, toolStatus, scrollToBottom])

  const submit = async () => {
    if (!trimmed || disabled) return
    // `/оценить` opens the rating dialog instead of sending a message. Any text
    // after the command becomes the comment, e.g. `/оценить было быстро`.
    const rate = parseRateCommand(trimmed)
    if (rate) {
      setText('')
      setRatingComment(rate.comment)
      setShowRating(true)
      return
    }
    // `/запросить_помощь` is replaced with a readable message so the request
    // reads naturally in the conversation.
    const outgoing = trimmed === HELP_COMMAND ? HELP_MESSAGE : trimmed
    const files = attachments.map((item) => item.file)

    // Referenced contracts travel as plain text (a header line + an inline
    // marker) while the UI renders them as attachments.
    const { contractIds } = extractContracts(outgoing)
    const withContracts = withContractHeader(outgoing, contractIds)

    // Clear the composer immediately so the UI feels responsive while the
    // upload and the (potentially long) answer happen.
    setText('')
    clearFiles()
    await onSend?.(withContracts, files)
  }

  const submitRating = (stars: number, comment: string) => {
    if (disabled) return
    onRate?.(stars, comment)
    setShowRating(false)
    setRatingComment('')
  }

  // Also allow submitting via the "Отправить" button (native form submit).
  const handleSubmit = (e: FormEvent) => {
    e.preventDefault()
    void submit()
  }

  return (
    <div className={cn('flex min-h-0 flex-1 flex-col gap-4', className)}>
      <div ref={scrollRef} onScroll={handleScroll} className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto">
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
                  <ChatMessage
                    message={message}
                    isParticipant={!readOnly}
                    contracts={contracts}
                    onCreateRule={
                      // Only assistant replies can seed a rule, and only when
                      // there is a preceding user question to prefill.
                      onCreateRule && isAssistantReply(message)
                        ? () => onCreateRule(message.text, precedingUserMessage(messages, index) ?? '')
                        : undefined
                    }
                  />
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
      {!readOnly && (
      <form onSubmit={handleSubmit} className="shrink-0">
        <ChatInput
          value={text}
          onChange={setText}
          onSubmit={submit}
          placeholder={disabled ? (disabledPlaceholder ?? 'Ожидайте ответа...') : 'Введите сообщение...'}
          disabled={disabled}
          aria-label="Сообщение"
          attachments={attachments}
          onFilesAdded={addFiles}
          onRemoveAttachment={removeFile}
          commands={COMMANDS}
          contracts={contracts}
        />
      </form>
      )}
      {showRating && (
        <RatingInput
          defaultComment={ratingComment}
          onSubmit={submitRating}
          onClose={() => {
            setShowRating(false)
            setRatingComment('')
          }}
          disabled={disabled}
        />
      )}
    </div>
  )
}
