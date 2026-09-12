import { createFileRoute, Link } from '@tanstack/react-router'
import ChatContainer from '@/components/ui/ChatContainer'
import LoadingSpinner from '@/components/ui/LoadingSpinner'
import StarRating from '@/components/ui/StarRating'
import { requireRole } from '@/app/routes/-guards'
import { useChat } from '@/hooks/useChat'
import { useChatMessages } from '@/hooks/useChatMessages'
import { Role } from '@/api/types'

export const Route = createFileRoute('/history/$chatId')({
  beforeLoad: () => requireRole([Role.admin]),
  component: HistoryChatPage,
})

/**
 * Read-only view of a single chat from the history list. Mirrors the support
 * chat layout, but without the composer: admins inspect conversations rather
 * than take part in them.
 */
function HistoryChatPage() {
  const { chatId } = Route.useParams()
  const { data: chat, isLoading, isError, error } = useChat(chatId)
  const { data: messages, isLoading: messagesLoading, isError: messagesError, error: messagesErr } = useChatMessages(chatId)

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
        <p className="text-red text-sm">{error?.message || 'Обращение не найдено'}</p>
        <Link to="/history" className="text-main-blue text-sm underline underline-offset-4">
          Вернуться к истории обращений
        </Link>
      </div>
    )
  }

  return (
    // Fill the viewport below the 4rem navbar so the message list scrolls.
    <div className="mx-auto flex h-[calc(100vh-4rem)] w-full max-w-6xl flex-col gap-4 px-4 py-6">
      <div className="flex shrink-0 flex-col gap-1">
        <Link to="/history" className="text-gray hover:text-main-blue text-xs underline underline-offset-4">
          ← История обращений
        </Link>
        <h1 className="text-pale-black text-2xl font-bold">{chat.title}</h1>
        {chat.rating && (
          <span className="text-gray flex items-center gap-1 text-xs">
            Оценка обращения: <StarRating stars={chat.rating.stars} comment={chat.rating.comment} />
          </span>
        )}
      </div>

      {messagesLoading ? (
        <div className="flex flex-1 justify-center py-20">
          <LoadingSpinner size="lg" />
        </div>
      ) : messagesError ? (
        <p className="text-red py-10 text-center text-sm">{messagesErr?.message || 'Не удалось загрузить сообщения'}</p>
      ) : (
        <ChatContainer messages={messages ?? []} readOnly className="min-h-0" />
      )}
    </div>
  )
}
