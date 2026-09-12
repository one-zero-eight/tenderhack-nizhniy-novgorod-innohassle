import { FaXmark } from 'react-icons/fa6'
import { IoDocumentOutline } from 'react-icons/io5'
import { cn } from '@/lib/cn'
import type { Attachment } from '@/hooks/useFileAttachments'

interface ChatAttachmentsProps {
  attachments: Attachment[]
  onRemove?: (id: string) => void
  className?: string
}

/** Formats a byte count as a short human-readable size. */
function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} Б`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} КБ`
  return `${(bytes / (1024 * 1024)).toFixed(1)} МБ`
}

/**
 * Chips for files attached to the next message, shown above the composer.
 */
export default function ChatAttachments({ attachments, onRemove, className }: ChatAttachmentsProps) {
  if (attachments.length === 0) return null

  return (
    <ul className={cn('flex flex-wrap gap-2', className)}>
      {attachments.map(({ id, file }) => (
        <li
          key={id}
          className="border-gray-blue bg-pale-blue/40 text-pale-black flex max-w-full items-center gap-2 border px-2 py-1 text-xs"
        >
          <IoDocumentOutline className="text-main-blue size-4 shrink-0" />
          <span className="max-w-48 truncate font-medium" title={file.name}>
            {file.name}
          </span>
          <span className="text-gray shrink-0">{formatSize(file.size)}</span>
          <button
            type="button"
            onClick={() => onRemove?.(id)}
            aria-label={`Удалить файл ${file.name}`}
            className="text-gray hover:text-red shrink-0 rounded-full p-0.5 transition-colors"
          >
            <FaXmark className="size-3.5" />
          </button>
        </li>
      ))}
    </ul>
  )
}
