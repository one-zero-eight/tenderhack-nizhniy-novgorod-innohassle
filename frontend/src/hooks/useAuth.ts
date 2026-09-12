import { useCallback } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { eventsFetch } from '@/api'
import type { SchemaLoginIn, SchemaRegisterIn, SchemaTokenOut, SchemaUserOut } from '@/api/types'
import { clearAuth, getStoredUser, getToken, setToken, setUser } from '@/lib/auth-storage'

export const meQueryKey = ['auth', 'me'] as const

async function fetchMe(): Promise<SchemaUserOut> {
  const { data, error } = await eventsFetch.GET('/auth/me')
  if (error || !data) throw error ?? new Error('Не удалось получить данные пользователя')
  return data
}

/**
 * Query options for the current user. Shared so route guards can prefetch it
 * via `queryClient.ensureQueryData` and components can read the same cache.
 *
 * `staleTime` is 0 on purpose: the cached profile must never outlive the token
 * it was fetched with, otherwise switching accounts can briefly show the
 * previous user until a hard refresh.
 */
export function meQueryOptions() {
  return {
    queryKey: meQueryKey,
    queryFn: fetchMe,
    staleTime: 0,
    retry: false,
  }
}

/**
 * Loads the current user. Disabled while there is no valid token.
 *
 * The persisted profile is used as `initialData` so the UI can render the
 * account immediately, while `staleTime: 0` guarantees it is revalidated
 * against `/auth/me` (important after switching accounts).
 */
export function useMe() {
  const token = getToken()
  return useQuery<SchemaUserOut, Error>({
    ...meQueryOptions(),
    enabled: token !== null,
    initialData: token ? (getStoredUser() ?? undefined) : undefined,
    initialDataUpdatedAt: 0,
  })
}

/**
 * Persists an access token, loads the profile, and caches it.
 *
 * The token must be stored before calling `/auth/me` so the request carries the
 * Authorization header added by the API client middleware. On failure the
 * session is cleared so a half-established login is not left behind.
 */
async function establishSession(token: SchemaTokenOut): Promise<SchemaUserOut> {
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

async function login(credentials: SchemaLoginIn): Promise<SchemaUserOut> {
  const { data: token, error } = await eventsFetch.POST('/auth/login', { body: credentials })
  if (error || !token) throw error ?? new Error('Неверный логин или пароль')
  return establishSession(token)
}

/**
 * Authenticates the user, drops any data cached for the previous session, and
 * seeds the `me` query cache on success.
 */
export function useLogin() {
  const queryClient = useQueryClient()
  return useMutation<SchemaUserOut, Error, SchemaLoginIn>({
    mutationFn: login,
    onSuccess: (user) => {
      // A different account may have been signed in before: clear every cached
      // query so no stale chats or profile leak into the new session.
      queryClient.clear()
      queryClient.setQueryData(meQueryKey, user)
    },
  })
}

async function register(payload: SchemaRegisterIn): Promise<SchemaUserOut> {
  const { data: token, error } = await eventsFetch.POST('/auth/register', { body: payload })
  if (error || !token) throw error ?? new Error('Не удалось зарегистрироваться')
  return establishSession(token)
}

/**
 * Registers a new user. The endpoint returns a token directly, so the new user
 * is signed in and the `me` cache seeded in the same step.
 */
export function useRegister() {
  const queryClient = useQueryClient()
  return useMutation<SchemaUserOut, Error, SchemaRegisterIn>({
    mutationFn: register,
    onSuccess: (user) => {
      queryClient.clear()
      queryClient.setQueryData(meQueryKey, user)
    },
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
