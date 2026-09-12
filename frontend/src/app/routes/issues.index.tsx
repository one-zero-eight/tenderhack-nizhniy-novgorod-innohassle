import { createFileRoute } from '@tanstack/react-router'
import { requireRole } from '@/app/routes/-guards'
import { Role } from '@/api/types'

export const Route = createFileRoute('/issues/')({
  beforeLoad: () => requireRole([Role.admin]),
  component: IssuesPage,
})

function IssuesPage() {
  return (
    <div className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-6 px-4 py-8">
      <h1 className="text-2xl font-bold text-black">Типичные проблемы</h1>
      <p className="text-gray text-sm">Раздел наполняется.</p>
    </div>
  )
}
