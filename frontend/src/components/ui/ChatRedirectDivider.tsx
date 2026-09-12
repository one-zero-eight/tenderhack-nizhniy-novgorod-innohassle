import { cn } from '@/lib/cn'
import { MdOutlineSupportAgent } from 'react-icons/md'

interface ChatRedirectDividerProps {
  text: string
  className?: string
}

/**
 * Delimiter shown in the chat when the AI hands the conversation off to a
 * support lane. Rendered instead of a regular message bubble.
 */
export default function ChatRedirectDivider({ text, className }: ChatRedirectDividerProps) {
  return (
    <div className={cn('flex w-full flex-col items-center gap-2 py-1 text-center', className)} role="separator">
      <div className="flex items-center gap-2 rounded-full bg-orange/10 px-4 py-1.5 text-xs font-medium text-orange">
        <MdOutlineSupportAgent className="size-4 shrink-0" />
        <span>{text}</span>
      </div>
      <span className="bg-orange/20 h-px w-full" aria-hidden="true" />
    </div>
  )
}
