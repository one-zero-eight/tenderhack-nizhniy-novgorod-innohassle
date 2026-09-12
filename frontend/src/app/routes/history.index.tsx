import { createFileRoute } from '@tanstack/react-router'
import { requireRole } from '@/app/routes/-guards'
import { Role } from '@/api/types'

export const Route = createFileRoute('/history/')({
  beforeLoad: () => requireRole([Role.admin]),
  component: HistoryPage,
})

function HistoryPage() {
  return (
    <div className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-6 px-4 py-8">
      <h1 className="text-2xl font-bold text-black">История обращений</h1>
      <p className="text-gray text-sm">Раздел наполняется.</p>
    </div>
  )
}
