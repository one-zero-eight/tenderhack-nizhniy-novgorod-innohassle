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
 */
export async function requireRole(roles: readonly SchemaUserOut['role'][]): Promise<SchemaUserOut> {
  const user = await requireAuth()
  if (!roles.includes(user.role)) throw redirect({ to: '/support' })
  return user
}
