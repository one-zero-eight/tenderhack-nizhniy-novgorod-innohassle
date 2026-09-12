import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ApiError, fetchChatMessages, sendChatMessage } from '@/api/chat'
import { chatQueryKey } from '@/hooks/useChat'
import { chatsQueryKey } from '@/hooks/useChats'
import { toChatView, toMessageView, type MessageView } from '@/lib/chat-view'

export const chatMessagesQueryKey = (chatId: string) => ['chat', chatId, 'messages'] as const

/** Merges new/updated messages into the cached list, keeping it sorted by sequence. */
function mergeMessages(prev: MessageView[] | undefined, incoming: MessageView[]): MessageView[] {
  const byId = new Map<string, MessageView>()
  for (const message of prev ?? []) byId.set(message.id, message)
  for (const message of incoming) byId.set(message.id, message)
  return [...byId.values()].sort((a, b) => a.sequence - b.sequence)
}

/**
 * Loads all messages for a chat from `GET /chats/{id}/messages`, following the
 * `has_more` / `next_sequence` cursor to fetch every page.
 *
 * Polls every 2s so replies produced asynchronously (AI answer, operator reply)
 * appear without a manual refresh.
 */
export function useChatMessages(chatId: string | undefined) {
  return useQuery<MessageView[], Error>({
    queryKey: chatMessagesQueryKey(chatId ?? ''),
    queryFn: async () => {
      const all: MessageView[] = []
      let afterSequence = 0
      // Guard against an unbounded loop if the backend misbehaves.
      for (let page = 0; page < 100; page += 1) {
        const result = await fetchChatMessages(chatId as string, afterSequence)
        all.push(...result.items.map(toMessageView))
        if (!result.has_more) break
        afterSequence = result.next_sequence
      }
      return all
    },
    enabled: !!chatId,
    refetchInterval: 2000,
  })
}

/**
 * Sends a user message via `POST /chats/{id}/messages`.
 *
 * The request blocks until moderation (and, in AI mode, the answer) completes,
 * which can take up to ~45s. A fresh `client_message_id` is generated per
 * submission; `onSuccess` merges the returned messages and refreshes the chat
 * so status/recipient changes are reflected.
 */
export function useSendChatMessage(chatId: string | undefined) {
  const queryClient = useQueryClient()
  return useMutation<MessageView[], Error, string>({
    mutationFn: async (text: string) => {
      const result = await sendChatMessage(chatId as string, text, crypto.randomUUID())
      // Update the chat cache immediately with the authoritative chat state.
      queryClient.setQueryData(chatQueryKey(chatId as string), toChatView(result.chat))
      return result.messages.map(toMessageView)
    },
    onSuccess: (created) => {
      if (!chatId) return
      queryClient.setQueryData(chatMessagesQueryKey(chatId), (prev: MessageView[] | undefined) => mergeMessages(prev, created))
      queryClient.invalidateQueries({ queryKey: chatQueryKey(chatId) })
      queryClient.invalidateQueries({ queryKey: chatsQueryKey })
    },
  })
}

/** True when an error is a retryable "AI is still busy" condition. */
export function isAiBusy(error: Error | null): boolean {
  return error instanceof ApiError && error.code === 'AI_BUSY'
}
