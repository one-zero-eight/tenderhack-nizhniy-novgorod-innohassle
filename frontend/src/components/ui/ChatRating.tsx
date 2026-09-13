import { FaRegStar, FaStar } from 'react-icons/fa6'
import { cn } from '@/lib/cn'
import type { SchemaRatingOut } from '@/api/types'

interface ChatRatingProps {
  /** The chat's rating, or `null` when it has not been rated. */
  rating: SchemaRatingOut | null | undefined
  /**
   * Shows an explicit «нет оценки» placeholder when the chat is unrated.
   * Used in the read-only admin view, where a missing rating is meaningful.
   */
  showEmpty?: boolean
  className?: string
}

const MAX_STARS = 5

/**
 * Rating block for a chat: stars on top, the comment underneath.
 *
 * The comment wraps and can span multiple lines, so long feedback renders
 * correctly instead of being truncated.
 */
export default function ChatRating({ rating, showEmpty = false, className }: ChatRatingProps) {
  if (!rating) {
    if (!showEmpty) return null
    return (
      <span className={cn('text-gray text-xs', className)}>Оценка не выставлена</span>
    )
  }

  return (
    <div className={cn('flex flex-col gap-1', className)}>
      <span className="flex items-center gap-0.5" role="img" aria-label={`Оценка: ${rating.stars} из ${MAX_STARS}`}>
        {Array.from({ length: MAX_STARS }, (_, index) => {
          const value = index + 1
          return value <= rating.stars ? (
            <FaStar key={value} className="text-orange size-4" />
          ) : (
            <FaRegStar key={value} className="text-gray size-4" />
          )
        })}
      </span>
      {rating.comment && (
        <p className="text-black max-w-prose text-sm break-words whitespace-pre-wrap">{rating.comment}</p>
      )}
    </div>
  )
}
