import { useQuery } from '@tanstack/react-query'
import { fetchChats } from '@/lib/chats-api'
import type { ChatMinimal } from '@/types/types'

export const chatsQueryKey = ['chats'] as const

/**
 * Loads the current user's chats.
 *
 * Uses a mock async source for now; swapping to the API only requires
 * changing `fetchChats` (or `queryFn`) here.
 */
export function useChats() {
  return useQuery<ChatMinimal[], Error>({
    queryKey: chatsQueryKey,
    queryFn: fetchChats,
  })
}
