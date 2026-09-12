import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { fetchChatMessages, sendChatMessage } from '@/lib/chats-api'
import type { ChatMessageData } from '@/types/types'

export const chatMessagesQueryKey = (chatId: string) => ['chat', chatId, 'messages'] as const

/**
 * Loads all messages for a chat.
 *
 * Uses a mock async source for now; swapping to the API only requires
 * changing `fetchChatMessages`.
 */
export function useChatMessages(chatId: string | undefined) {
  return useQuery<ChatMessageData[], Error>({
    queryKey: chatMessagesQueryKey(chatId ?? ''),
    queryFn: () => fetchChatMessages(chatId as string),
    enabled: !!chatId,
  })
}

/**
 * Appends a user message to the current chat.
 */
export function useSendChatMessage(chatId: string | undefined) {
  const queryClient = useQueryClient()
  return useMutation<ChatMessageData[], Error, string>({
    mutationFn: (text: string) => sendChatMessage(chatId as string, text),
    onSuccess: (created) => {
      if (!chatId) return
      queryClient.setQueryData(chatMessagesQueryKey(chatId), (prev: ChatMessageData[] | undefined) => [...(prev ?? []), ...created])
    },
  })
}
