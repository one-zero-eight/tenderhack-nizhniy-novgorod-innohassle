import { Outlet, createFileRoute } from '@tanstack/react-router'
import { requireRole } from '@/app/routes/-guards'
import { Role } from '@/api/types'

export const Route = createFileRoute('/issues/$topic')({
  beforeLoad: () => requireRole([Role.admin]),
  component: TopicLayout,
})

/**
 * Layout for a topic route.
 *
 * The single-chat route (`/issues/$topic/$chatId`) nests under the topic route,
 * so the parent must render an `<Outlet />` for the child to appear. Both
 * children own their own header and back link.
 */
function TopicLayout() {
  return <Outlet />
}
