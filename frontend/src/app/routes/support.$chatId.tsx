import { createFileRoute, Link } from '@tanstack/react-router'
import ChatContainer from '@/components/ui/ChatContainer'
import LoadingSpinner from '@/components/ui/LoadingSpinner'
import { requireAuth } from '@/app/routes/-guards'
import { useChat } from '@/hooks/useChat'
import { useChatMessages, useSendChatMessage } from '@/hooks/useChatMessages'

export const Route = createFileRoute('/support/$chatId')({
  beforeLoad: requireAuth,
  component: ChatPage,
})

function ChatPage() {
  const { chatId } = Route.useParams()
  const { data: chat, isLoading, isError, error } = useChat(chatId)
  const { data: messages, isLoading: messagesLoading, isError: messagesError, error: messagesErr } = useChatMessages(chatId)
  const sendMessage = useSendChatMessage(chatId)

  if (isLoading) {
    return (
      <div className="flex flex-1 justify-center py-20">
        <LoadingSpinner size="lg" />
      </div>
    )
  }

  if (isError || !chat) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-4 px-4">
        <p className="text-red text-sm">{error?.message || 'Чат не найден'}</p>
        <Link to="/support" className="text-main-blue text-sm underline underline-offset-4">
          Вернуться к списку обращений
        </Link>
      </div>
    )
  }

  const isClosed = chat.status === 'closed'

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-4 px-4 py-8">
      <div className="flex flex-col gap-1">
        <Link to="/support" className="text-gray hover:text-main-blue text-xs underline underline-offset-4">
          ← Все обращения
        </Link>
        <h1 className="text-2xl font-bold text-pale-black">{chat.title}</h1>
      </div>

      {messagesLoading ? (
        <div className="flex flex-1 justify-center py-20">
          <LoadingSpinner size="lg" />
        </div>
      ) : messagesError ? (
        <p className="text-red py-10 text-center text-sm">{messagesErr?.message || 'Не удалось загрузить сообщения'}</p>
      ) : (
        <>
          {sendMessage.isError && (
            <p className="text-red text-center text-sm">{sendMessage.error?.message || 'Не удалось отправить сообщение'}</p>
          )}
          <ChatContainer
            messages={messages ?? []}
            onSend={(text) => sendMessage.mutate(text)}
            disabled={sendMessage.isPending || isClosed}
          />
        </>
      )}
    </div>
  )
}
