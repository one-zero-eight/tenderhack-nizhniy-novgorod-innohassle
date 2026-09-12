import { createFileRoute, redirect } from '@tanstack/react-router'
import { getStoredUser, getToken } from '@/lib/auth-storage'
import { homePath } from '@/lib/roles'

export const Route = createFileRoute('/')({
  beforeLoad: () => {
    throw redirect({ to: getToken() ? homePath(getStoredUser()?.role) : '/auth' })
  },
})
