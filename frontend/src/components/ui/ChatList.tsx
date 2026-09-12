import ChatListItem from '@/components/ui/ChatListItem'
import { cn } from '@/lib/cn'
import type { ChatView } from '@/lib/chat-view'

interface ChatListProps {
  chats: ChatView[]
  activeChatId?: string | null
  onSelect?: (chat: ChatView) => void
  className?: string
}

export default function ChatList({ chats, activeChatId, onSelect, className }: ChatListProps) {
  if (chats.length === 0) {
    return <p className={cn('text-gray px-3 py-6 text-center text-sm', className)}>Чатов пока нет</p>
  }

  return (
    <ul className={cn('flex flex-col gap-0', className)}>
      {chats.map((chat) => (
        <li key={chat.id}>
          <ChatListItem chat={chat} isActive={chat.id === activeChatId} onClick={onSelect} />
        </li>
      ))}
    </ul>
  )
}
