import { useMutation, useQueryClient } from '@tanstack/react-query'
import { rateChat } from '@/api/chat'
import { chatQueryKey } from '@/hooks/useChat'
import { chatsQueryKey } from '@/hooks/useChats'
import type { SchemaRatingOut } from '@/api/types'
import type { ChatView } from '@/lib/chat-view'

export interface RateChatInput {
  stars: number
  comment?: string | null
}

/**
 * Submits a rating for the conversation via `PUT /chats/{chat_id}/rating` and
 * writes the result back into the chat caches so the stars appear without a
 * refetch.
 */
export function useRateChat(chatId: string | undefined) {
  const queryClient = useQueryClient()

  return useMutation<SchemaRatingOut, Error, RateChatInput>({
    mutationFn: ({ stars, comment }) => rateChat(chatId as string, { stars, comment: comment?.trim() ? comment.trim() : null }),
    onSuccess: (rating) => {
      if (!chatId) return
      queryClient.setQueryData<ChatView>(chatQueryKey(chatId), (prev) => (prev ? { ...prev, rating } : prev))
      queryClient.setQueryData<ChatView[]>(chatsQueryKey, (prev) =>
        (prev ?? []).map((chat) => (chat.id === chatId ? { ...chat, rating } : chat)),
      )
    },
  })
}
