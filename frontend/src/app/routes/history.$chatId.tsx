import { createFileRoute, Link } from '@tanstack/react-router'
import { useState } from 'react'
import ChatContainer from '@/components/ui/ChatContainer'
import ChatRating from '@/components/ui/ChatRating'
import HandRuleModal from '@/components/ui/HandRuleModal'
import LoadingSpinner from '@/components/ui/LoadingSpinner'
import { requireRole } from '@/app/routes/-guards'
import { useChat } from '@/hooks/useChat'
import { useChatMessages } from '@/hooks/useChatMessages'
import { useCreateHandRule } from '@/hooks/useHandrules'
import { Role } from '@/api/types'

export const Route = createFileRoute('/history/$chatId')({
  beforeLoad: () => requireRole([Role.admin]),
  component: HistoryChatPage,
})

/** Draft hand-rule seeded from a chat exchange. */
interface HandRuleDraft {
  assistantText: string
  userText: string
}

/**
 * Read-only view of a single chat from the history list. Mirrors the support
 * chat layout, but without the composer: admins inspect conversations rather
 * than take part in them.
 *
 * Admins can turn any assistant reply into a hand-rule by clicking the message.
 */
function HistoryChatPage() {
  const { chatId } = Route.useParams()
  const { data: chat, isLoading, isError, error } = useChat(chatId)
  const { data: messages, isLoading: messagesLoading, isError: messagesError, error: messagesErr } = useChatMessages(chatId)
  const createRule = useCreateHandRule()
  const [draft, setDraft] = useState<HandRuleDraft | null>(null)

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

  const closeModal = () => {
    setDraft(null)
    createRule.reset()
  }

  return (
    // Fill the viewport below the 4rem navbar so the message list scrolls.
    <div className="mx-auto flex h-[calc(100vh-4rem)] w-full max-w-6xl flex-col px-4 py-6">
      {/* Bordered chat surface: the header and message list share it. */}
      <div className="border-gray-blue flex min-h-0 flex-1 flex-col gap-4 border-x px-4 py-4">
        <div className="flex shrink-0 flex-col gap-1">
          <Link to="/history" className="text-gray hover:text-main-blue text-xs underline underline-offset-4">
            ← История обращений
          </Link>
          <h1 className="text-pale-black text-2xl font-bold">{chat.title}</h1>
          <ChatRating rating={chat.rating} showEmpty className="mt-1" />
        </div>

        {messagesLoading ? (
          <div className="flex flex-1 justify-center py-20">
            <LoadingSpinner size="lg" />
          </div>
        ) : messagesError ? (
          <p className="text-red py-10 text-center text-sm">{messagesErr?.message || 'Не удалось загрузить сообщения'}</p>
        ) : (
          <ChatContainer
            messages={messages ?? []}
            readOnly
            className="min-h-0"
            onCreateRule={(assistantText, userText) => setDraft({ assistantText, userText })}
          />
        )}
      </div>

      {draft && (
        <HandRuleModal
          defaultUserMessage={draft.userText}
          defaultInstructions={draft.assistantText}
          submitting={createRule.isPending}
          error={createRule.isError ? (createRule.error?.message ?? 'Не удалось создать правило') : null}
          onClose={closeModal}
          onSubmit={(userMessage, instructions) =>
            createRule.mutate(
              { user_message: userMessage, instructions },
              { onSuccess: closeModal },
            )
          }
        />
      )}
    </div>
  )
}
