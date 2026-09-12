import { FaRegStar, FaStar } from 'react-icons/fa6'
import { cn } from '@/lib/cn'

interface StarRatingProps {
  /** Score from 1 to 5. */
  stars: number
  /** Optional comment, shown after the stars. */
  comment?: string | null
  /** Number of stars rendered in total. */
  max?: number
  /** Renders the comment next to the stars (off in compact lists). */
  showComment?: boolean
  className?: string
}

/**
 * Read-only star rating. Fills `stars` of `max` icons and optionally shows the
 * accompanying comment.
 *
 * Hovering always reveals a tooltip with the score and the comment, which also
 * covers the compact list variant where the comment itself is hidden.
 */
export default function StarRating({ stars, comment, max = 5, showComment = true, className }: StarRatingProps) {
  const tooltip = comment ? `Оценка ${stars} из ${max}: ${comment}` : `Оценка ${stars} из ${max}`

  return (
    <span className={cn('inline-flex items-center gap-1 text-xs', className)} title={tooltip}>
      <span className="inline-flex items-center gap-0.5" role="img" aria-label={`Оценка: ${stars} из ${max}`}>
        {Array.from({ length: max }, (_, index) => {
          const value = index + 1
          return value <= stars ? (
            <FaStar key={value} className="text-orange size-3" />
          ) : (
            <FaRegStar key={value} className="text-gray size-3" />
          )
        })}
      </span>
      {showComment && comment && (
        <span className="text-gray max-w-48 truncate">{comment}</span>
      )}
    </span>
  )
}
