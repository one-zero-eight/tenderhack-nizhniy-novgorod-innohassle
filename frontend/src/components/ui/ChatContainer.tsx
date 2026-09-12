import { useState, type FormEvent } from 'react'
import Button from '@/components/ui/Button'
import ChatInput from '@/components/ui/ChatInput'
import ChatMessage from '@/components/ui/ChatMessage'
import ChatRedirectDivider from '@/components/ui/ChatRedirectDivider'
import { cn } from '@/lib/cn'
import { SenderType } from '@/api/types'
import type { MessageView } from '@/lib/chat-view'

interface ChatContainerProps {
  messages: MessageView[]
  onSend?: (text: string) => void
  disabled?: boolean
  className?: string
}

export default function ChatContainer({ messages, onSend, disabled = false, className }: ChatContainerProps) {
  const [text, setText] = useState('')
  const trimmed = text.trim()

  const submit = () => {
    if (!trimmed || disabled) return
    onSend?.(trimmed)
    setText('')
  }

  // Also allow submitting via the "Отправить" button (native form submit).
  const handleSubmit = (e: FormEvent) => {
    e.preventDefault()
    submit()
  }

  return (
    <div className={cn('flex flex-1 flex-col gap-4', className)}>
      <div className="flex flex-1 flex-col gap-4 overflow-y-auto">
        {messages.length === 0 ? (
          <p className="text-gray py-10 text-center text-sm">Сообщений пока нет. Задайте свой вопрос.</p>
        ) : (
          messages.map((message) =>
            // System messages are the assistant's handoff offers; render them as
            // a delimiter rather than a chat bubble.
            message.senderType === SenderType.system ? (
              <ChatRedirectDivider key={message.id} text={message.text} />
            ) : (
              <ChatMessage key={message.id} message={message} />
            ),
          )
        )}
      </div>

      <form onSubmit={handleSubmit} className="flex items-end gap-2">
        <ChatInput
          value={text}
          onChange={setText}
          onSubmit={submit}
          placeholder={disabled ? 'Ожидайте ответа...' : 'Введите сообщение... (Shift+Enter — новая строка)'}
          disabled={disabled}
          aria-label="Сообщение"
          action={
            <Button type="submit" variant="primary" size="sm" disabled={disabled || !trimmed} className="h-9">
              Отправить
            </Button>
          }
        />
      </form>
    </div>
  )
}
