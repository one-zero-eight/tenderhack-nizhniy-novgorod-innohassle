import { cn } from '@/lib/cn'

interface ChatDateDividerProps {
  label: string
  className?: string
}

/**
 * Telegram-style date divider shown between messages of different days.
 */
export default function ChatDateDivider({ label, className }: ChatDateDividerProps) {
  return (
    <div className={cn('flex w-full justify-center py-1', className)} role="separator" aria-label={label}>
      <span className="bg-light-gray/40 text-gray rounded-full px-3 py-1 text-xs font-medium">{label}</span>
    </div>
  )
}
