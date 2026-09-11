import { createFileRoute, redirect } from '@tanstack/react-router'
import { getUsername } from '@/lib/storage'

export const Route = createFileRoute('/')({
  beforeLoad: () => {
    throw redirect({ to: getUsername() ? '/support' : '/auth' })
  },
})
