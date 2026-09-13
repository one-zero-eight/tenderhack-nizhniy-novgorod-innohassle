import { Link } from '@tanstack/react-router'
import { useState } from 'react'
import ChatContainer from '@/components/ui/ChatContainer'
import ChatRating from '@/components/ui/ChatRating'
import HandRuleModal from '@/components/ui/HandRuleModal'
import LoadingSpinner from '@/components/ui/LoadingSpinner'
import { useChat } from '@/hooks/useChat'
import { useChatMessages } from '@/hooks/useChatMessages'
import { useCreateHandRule } from '@/hooks/useHandrules'

/** Draft hand-rule seeded from a chat exchange. */
interface HandRuleDraft {
  assistantText: string
  userText: string
}

interface AdminChatViewProps {
  chatId: string
  /** Route the back link points at. */
  backTo: '/history' | '/issues/$topic'
  /** Params for `backTo` (required for the topic route). */
  backParams?: { topic: string }
  /** Text of the back link. */
  backLabel: string
  /** Text shown when the chat cannot be loaded. */
  notFoundLabel: string
}

/**
 * Read-only chat view for admins: the same layout as the support chat, but
 * without the composer. Assistant replies can be turned into hand-rules by
 * clicking them.
 *
 * Shared by the history list and the issues-by-topic list, which differ only in
 * where the back link leads.
 */
export default function AdminChatView({ chatId, backTo, backParams, backLabel, notFoundLabel }: AdminChatViewProps) {
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
        <p className="text-red text-sm">{error?.message || notFoundLabel}</p>
        <Link to={backTo} params={backParams} className="text-main-blue text-sm underline underline-offset-4">
          {backLabel}
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
          <Link to={backTo} params={backParams} className="text-gray hover:text-main-blue text-xs underline underline-offset-4">
            {backLabel}
          </Link>
          <h1 className="text-pale-black text-2xl font-bold">{chat.title}</h1>
          {/* Admins see whose conversation this is. */}
          <span className="text-pale-black text-sm">Пользователь: {chat.userName}</span>
          {/* Rating summary in the header; it also appears inline in the timeline. */}
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
            rating={chat.rating}
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
            createRule.mutate({ user_message: userMessage, instructions }, { onSuccess: closeModal })
          }
        />
      )}
    </div>
  )
}
