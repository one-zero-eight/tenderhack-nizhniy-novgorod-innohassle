import { useState, type FormEvent } from 'react'
import { FaRegStar, FaStar, FaXmark, FaPaperPlane } from 'react-icons/fa6'
import Button from '@/components/ui/Button'
import { cn } from '@/lib/cn'

interface RatingInputProps {
  /** Called with the chosen stars and comment when the user submits. */
  onSubmit?: (stars: number, comment: string) => void
  /** Called when the user closes the dialog via the cross button. */
  onClose?: () => void
  /** Renders the composer in a non-interactive, waiting state. */
  disabled?: boolean
  /** Initial comment, e.g. the text typed after `/оценить`. */
  defaultComment?: string
  /** Used as the dialog's accessible name. */
  title?: string
  className?: string
}

const STARS = [1, 2, 3, 4, 5] as const

/**
 * 1–5 star rating dialog with an optional comment field.
 *
 * Shown as an overlay once the user submits `/оценить`. The submit button is
 * disabled until a star rating is selected; the comment is optional. Closable
 * via the cross button in the header.
 */
export default function RatingInput({
  onSubmit,
  onClose,
  disabled = false,
  defaultComment = '',
  title = 'Оценка поддержки',
  className,
}: RatingInputProps) {
  const [stars, setStars] = useState<number | null>(null)
  const [comment, setComment] = useState(defaultComment)
  const [hovered, setHovered] = useState<number | null>(null)

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault()
    if (disabled || stars === null) return
    onSubmit?.(stars, comment.trim())
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      role="dialog"
      aria-modal="true"
      aria-label={title}
    >
      <form
        onSubmit={handleSubmit}
        className={cn(
          'flex w-full max-w-md flex-col gap-3 border-2 border-pale-blue bg-white p-4 shadow-lg transition-colors focus-within:border-main-blue/50',
          disabled ? 'cursor-not-allowed opacity-50' : undefined,
          className,
        )}
      >
        <div className="flex items-center justify-between gap-2">
          <h2 className="text-black text-base font-bold">{title}</h2>
          <button
            type="button"
            onClick={onClose}
            disabled={disabled}
            aria-label="Закрыть"
            className="text-gray hover:text-red shrink-0 rounded-full p-1 transition-colors focus:outline-red/40"
          >
            <FaXmark className="size-5" />
          </button>
        </div>

        <div className="flex items-center gap-1" role="radiogroup" aria-label="Оценка от 1 до 5">
          {STARS.map((star) => {
            const active = star <= (hovered ?? stars ?? 0)
            return (
              <button
                key={star}
                type="button"
                disabled={disabled}
                onClick={() => setStars(star)}
                onMouseEnter={() => setHovered(star)}
                onMouseLeave={() => setHovered(null)}
                aria-label={`${star} из 5`}
                aria-checked={stars === star}
                role="radio"
                className="text-2xl transition-colors focus:outline-red/40"
              >
                {active ? <FaStar className="text-orange" /> : <FaRegStar className="text-gray" />}
              </button>
            )
          })}
        </div>

        <textarea
          value={comment}
          onChange={(e) => setComment(e.target.value)}
          disabled={disabled}
          rows={3}
          placeholder="Комментарий (необязательно)"
          className={cn(
            'block min-h-9 w-full resize-none bg-transparent px-2 py-1 text-sm text-pale-black border border-gray-2000',
            'placeholder:text-gray outline-none disabled:cursor-not-allowed',
          )}
          aria-label="Комментарий"
        />

        <div className="flex items-center justify-end gap-2">
          <Button
            type="submit"
            variant="primary"
            size="sm"
            className="flex items-center gap-2"
            disabled={disabled || stars === null}
          >
            <FaPaperPlane />
            <span>Отправить оценку</span>
          </Button>
        </div>
      </form>
    </div>
  )
}
