import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { createChat, fetchChat } from '@/lib/chats-api'
import { chatsQueryKey } from '@/hooks/useChats'
import type { ChatMinimal } from '@/types/types'

export const chatQueryKey = (chatId: string) => ['chat', chatId] as const

/**
 * Loads a single chat by id.
 *
 * Uses a mock async source for now; swapping to the API only requires
 * changing `fetchChat`.
 */
export function useChat(chatId: string | undefined) {
  return useQuery<ChatMinimal, Error>({
    queryKey: chatQueryKey(chatId ?? ''),
    queryFn: () => fetchChat(chatId as string),
    enabled: !!chatId,
  })
}

/**
 * Creates a new chat and refreshes the chats list.
 */
export function useCreateChat() {
  const queryClient = useQueryClient()
  return useMutation<ChatMinimal, Error, void>({
    mutationFn: createChat,
    onSuccess: (chat) => {
      queryClient.setQueryData(chatsQueryKey, (prev: ChatMinimal[] | undefined) => (prev ? [chat, ...prev] : [chat]))
      queryClient.invalidateQueries({ queryKey: chatsQueryKey })
    },
  })
}
