import { useCallback, useEffect, useMemo, type ReactNode } from 'react'
import { AuthContext, type AuthContextValue } from '@/app/providers/auth-context'
import { useMe, useLogin, useLogout } from '@/hooks/useAuth'
import { onUnauthorized } from '@/lib/auth-events'
import { router } from '@/app/router'
import type { SchemaLoginIn } from '@/api/types'

/**
 * Provides reactive auth state to the tree and wires the API client's 401
 * events to a session reset + redirect.
 */
export function AuthProvider({ children }: { children: ReactNode }) {
  // `useMe` seeds from the persisted profile and always revalidates, so the
  // navbar reflects the account that owns the current token even right after
  // signing in as someone else (no manual refresh needed).
  const { data: me, isLoading } = useMe()
  const user = me ?? null
  const loginMutation = useLogin()
  const clearSession = useLogout()

  const logout = useCallback(() => {
    clearSession()
    void router.navigate({ to: '/auth', replace: true })
  }, [clearSession])

  useEffect(() => {
    return onUnauthorized(() => {
      clearSession()
      void router.navigate({ to: '/auth', replace: true })
    })
  }, [clearSession])

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      isLoading,
      isAuthenticated: user !== null,
      login: (credentials: SchemaLoginIn) => loginMutation.mutateAsync(credentials),
      logout,
    }),
    [user, isLoading, loginMutation, logout],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
