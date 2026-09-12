import { useState, type FormEvent } from 'react'
import Button from '@/components/ui/Button'
import ChatMessage from '@/components/ui/ChatMessage'
import ChatRedirectDivider from '@/components/ui/ChatRedirectDivider'
import Input from '@/components/ui/Input'
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

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault()
    if (!trimmed || disabled) return
    onSend?.(trimmed)
    setText('')
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
        <Input
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder={disabled ? 'Ожидайте ответа...' : 'Введите сообщение...'}
          disabled={disabled}
          autoFocus
        />
        <Button type="submit" variant="primary" disabled={disabled || !trimmed}>
          Отправить
        </Button>
      </form>
    </div>
  )
}
