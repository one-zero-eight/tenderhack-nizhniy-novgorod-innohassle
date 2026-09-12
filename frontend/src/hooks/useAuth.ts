import { useCallback } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { eventsFetch } from '@/api'
import type { SchemaLoginIn, SchemaUserOut } from '@/api/types'
import { clearAuth, getToken, setToken, setUser } from '@/lib/auth-storage'

export const meQueryKey = ['auth', 'me'] as const

async function fetchMe(): Promise<SchemaUserOut> {
  const { data, error } = await eventsFetch.GET('/auth/me')
  if (error || !data) throw error ?? new Error('Не удалось получить данные пользователя')
  return data
}

/**
 * Query options for the current user. Shared so route guards can prefetch it
 * via `queryClient.ensureQueryData` and components can read the same cache.
 */
export function meQueryOptions() {
  return {
    queryKey: meQueryKey,
    queryFn: fetchMe,
    staleTime: Infinity,
    retry: false,
  }
}

/**
 * Loads the current user. Disabled while there is no valid token.
 */
export function useMe() {
  return useQuery({
    ...meQueryOptions(),
    enabled: getToken() !== null,
  })
}

async function login(credentials: SchemaLoginIn): Promise<SchemaUserOut> {
  const { data: token, error } = await eventsFetch.POST('/auth/login', { body: credentials })
  if (error || !token) throw error ?? new Error('Неверный логин или пароль')

  // The token must be persisted before calling /auth/me so the request carries
  // the Authorization header added by the API client middleware.
  setToken(token)

  try {
    const user = await fetchMe()
    setUser(user)
    return user
  } catch (err) {
    clearAuth()
    throw err
  }
}

/**
 * Authenticates the user and seeds the `me` query cache on success.
 */
export function useLogin() {
  const queryClient = useQueryClient()
  return useMutation<SchemaUserOut, Error, SchemaLoginIn>({
    mutationFn: login,
    onSuccess: (user) => queryClient.setQueryData(meQueryKey, user),
  })
}

/**
 * Clears the session and all cached queries. Navigation is left to the caller
 * so it can decide where to redirect.
 */
export function useLogout() {
  const queryClient = useQueryClient()
  return useCallback(() => {
    clearAuth()
    queryClient.clear()
  }, [queryClient])
}
