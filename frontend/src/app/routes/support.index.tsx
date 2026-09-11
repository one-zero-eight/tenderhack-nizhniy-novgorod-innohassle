import { createFileRoute, redirect } from '@tanstack/react-router'
import { getUsername } from '@/lib/storage'

export const Route = createFileRoute('/support/')({
  beforeLoad: () => {
    if (!getUsername()) {
      throw redirect({ to: '/auth' })
    }
  },
  component: SupportPage,
})

function SupportPage() {
  return (
    <div className="flex min-h-[calc(100vh-20rem)] flex-col items-center justify-center gap-4 px-4">
      <h1 className="text-4xl font-bold text-pale-black">Support page</h1>
    </div>
  )
}
