import { createFileRoute, useNavigate } from '@tanstack/react-router'
import Button from '@/components/ui/Button'
import ChatList from '@/components/ui/ChatList'
import LoadingSpinner from '@/components/ui/LoadingSpinner'
import { requireUser } from '@/app/routes/-guards'
import { useCreateChat } from '@/hooks/useChat'
import { useChats } from '@/hooks/useChats'
import type { ChatView } from '@/lib/chat-view'

export const Route = createFileRoute('/support/')({
  beforeLoad: requireUser,
  component: SupportPage,
})

function SupportPage() {
  const navigate = useNavigate()
  const { data: chats, isLoading, isError, error, refetch } = useChats()
  const createChat = useCreateChat()

  const handleCreate = () => {
    createChat.mutate(undefined, {
      onSuccess: (chat) => navigate({ to: '/support/$chatId', params: { chatId: chat.id } }),
    })
  }

  const handleSelect = (chat: ChatView) => {
    navigate({ to: '/support/$chatId', params: { chatId: chat.id } })
  }

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-1 flex-col gap-6 px-4 py-8">
      <div className="flex items-center justify-between gap-4">
        <h1 className="text-2xl font-bold text-black">Мои обращения</h1>
        <Button variant="primary" onClick={handleCreate} disabled={createChat.isPending}>
          Задать вопрос
        </Button>
      </div>

      {createChat.isError && <p className="text-red text-sm">{createChat.error?.message || 'Не удалось создать чат'}</p>}

      {isLoading ? (
        <div className="flex justify-center py-10">
          <LoadingSpinner size="lg" />
        </div>
      ) : isError ? (
        <div className="flex flex-col items-center gap-3 py-10">
          <p className="text-red text-sm">{error?.message || 'Не удалось загрузить чаты'}</p>
          <button type="button" onClick={() => refetch()} className="text-main-blue text-sm underline underline-offset-4">
            Повторить
          </button>
        </div>
      ) : (
        <ChatList chats={chats ?? []} onSelect={handleSelect} />
      )}
    </div>
  )
}
