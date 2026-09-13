import { FaStar, FaRegStar } from 'react-icons/fa6'
import { cn } from '@/lib/cn'
import { formatDateTime } from '@/lib/format'
import type { SchemaRatingOut } from '@/api/types'

interface ChatRatingCardProps {
  rating: SchemaRatingOut
  className?: string
}

const MAX_STARS = 5

/**
 * Rating card shown inline in the message timeline at the moment the rating was
 * left (`rating.updated_at`), rather than in the chat header.
 */
export default function ChatRatingCard({ rating, className }: ChatRatingCardProps) {
  return (
    <div className={cn('flex w-full justify-center py-1', className)} role="note" aria-label="Оценка обращения">
      <div className="border-orange/30 bg-orange/5 flex max-w-[80%] flex-col gap-2 border px-4 py-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <span className="text-orange flex items-center gap-1.5 text-xs font-semibold tracking-wide uppercase">
            Оценка обращения
          </span>
          <span className="text-gray text-xs">{formatDateTime(rating.updated_at)}</span>
        </div>

        <span
          className="flex items-center gap-0.5"
          role="img"
          aria-label={`Оценка: ${rating.stars} из ${MAX_STARS}`}
        >
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
          <p className="text-black text-sm break-words whitespace-pre-wrap">{rating.comment}</p>
        )}
      </div>
    </div>
  )
}
