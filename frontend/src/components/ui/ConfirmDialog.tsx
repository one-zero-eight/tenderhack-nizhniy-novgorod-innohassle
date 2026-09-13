import type { ReactNode } from 'react'
import { FaXmark } from 'react-icons/fa6'
import Button from '@/components/ui/Button'
import { cn } from '@/lib/cn'

interface ConfirmDialogProps {
  title: string
  /** Body text explaining what will happen. */
  message: ReactNode
  onConfirm: () => void
  onClose: () => void
  confirmLabel?: string
  cancelLabel?: string
  /** Renders the confirm action in red to signal a destructive operation. */
  destructive?: boolean
  /** Disables the controls while the action is running. */
  pending?: boolean
  error?: string | null
}

/**
 * Small modal asking for confirmation before a destructive action, so a stray
 * click cannot delete anything on its own.
 */
export default function ConfirmDialog({
  title,
  message,
  onConfirm,
  onClose,
  confirmLabel = 'Подтвердить',
  cancelLabel = 'Отмена',
  destructive = false,
  pending = false,
  error = null,
}: ConfirmDialogProps) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      role="dialog"
      aria-modal="true"
      aria-label={title}
      onClick={(event) => {
        // Clicking the backdrop cancels, matching the rest of the app's modals.
        if (event.target === event.currentTarget && !pending) onClose()
      }}
    >
      <div
        className={cn(
          'border-pale-blue flex w-full max-w-md flex-col gap-4 border-2 bg-white p-4 shadow-lg',
          pending ? 'cursor-not-allowed opacity-70' : undefined,
        )}
      >
        <div className="flex items-center justify-between gap-2">
          <h2 className="text-black text-base font-bold">{title}</h2>
          <button
            type="button"
            onClick={onClose}
            disabled={pending}
            aria-label="Закрыть"
            className="text-gray hover:text-red shrink-0 rounded-full p-1 transition-colors focus:outline-red/40"
          >
            <FaXmark className="size-5" />
          </button>
        </div>

        <div className="text-pale-black text-sm">{message}</div>

        {error && <p className="text-red text-sm">{error}</p>}

        <div className="flex items-center justify-end gap-2">
          <Button type="button" variant="outline" onClick={onClose} disabled={pending}>
            {cancelLabel}
          </Button>
          <Button
            type="button"
            variant={destructive ? 'primary' : 'outline'}
            onClick={onConfirm}
            disabled={pending}
          >
            {pending ? 'Удаление...' : confirmLabel}
          </Button>
        </div>
      </div>
    </div>
  )
}
