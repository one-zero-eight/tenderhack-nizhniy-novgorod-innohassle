import { redirect } from '@tanstack/react-router'
import type { SchemaUserOut } from '@/api/types'
import { meQueryOptions } from '@/hooks/useAuth'
import { getToken } from '@/lib/auth-storage'
import { queryClient } from '@/lib/query-client'

/**
 * Route guard for authenticated pages. Verifies a token exists, then loads the
 * current user (and caches it) via the shared QueryClient. Redirects to the
 * login page when either step fails.
 */
export async function requireAuth(): Promise<SchemaUserOut> {
  if (!getToken()) throw redirect({ to: '/auth' })
  try {
    return await queryClient.ensureQueryData(meQueryOptions())
  } catch {
    throw redirect({ to: '/auth' })
  }
}

/**
 * Route guard that additionally restricts access to the given roles.
 * Users lacking the role are sent to the page appropriate for them: admins to
 * the history view, everyone else to support.
 */
export async function requireRole(roles: readonly SchemaUserOut['role'][]): Promise<SchemaUserOut> {
  const user = await requireAuth()
  if (!roles.includes(user.role)) throw redirect({ to: user.role === 'admin' ? '/history' : '/support' })
  return user
}

/**
 * Guard for regular-user pages. Admins do not participate in chats and are
 * always sent to the history view instead.
 */
export async function requireUser(): Promise<SchemaUserOut> {
  const user = await requireAuth()
  if (user.role === 'admin') throw redirect({ to: '/history' })
  return user
}
