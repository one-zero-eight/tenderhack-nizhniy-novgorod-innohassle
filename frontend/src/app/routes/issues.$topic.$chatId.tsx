import { createFileRoute } from '@tanstack/react-router'
import AdminChatView from '@/components/admin/AdminChatView'
import { requireRole } from '@/app/routes/-guards'
import { Role } from '@/api/types'

export const Route = createFileRoute('/issues/$topic/$chatId')({
  beforeLoad: () => requireRole([Role.admin]),
  component: IssueChatPage,
})

/** Read-only chat opened from a topic's chat list. */
function IssueChatPage() {
  const { topic, chatId } = Route.useParams()
  return (
    <AdminChatView
      chatId={chatId}
      backTo="/issues/$topic"
      backParams={{ topic }}
      backLabel="← Типичные проблемы"
      notFoundLabel="Обращение не найдено"
    />
  )
}
