import { cn } from '@/lib/cn'

interface TypingDotsProps {
  className?: string
  /** Accessible label announced to screen readers. */
  label?: string
}

/** Staggered delays make the dots brighten in sequence, `.` → `..` → `...`. */
const DELAYS = ['0ms', '180ms', '360ms']

/**
 * Animated ellipsis shown while the assistant is composing an answer.
 *
 * The dots pulse in sequence so the indicator reads as an ongoing activity
 * rather than a static character.
 */
export default function TypingDots({ className, label = 'Ассистент печатает' }: TypingDotsProps) {
  return (
    <span className={cn('inline-flex items-end gap-0.5', className)} role="status" aria-label={label}>
      {DELAYS.map((delay) => (
        <span
          key={delay}
          aria-hidden="true"
          className="bg-gray inline-block size-1 rounded-full"
          style={{ animation: 'typing-dot 1.2s ease-in-out infinite', animationDelay: delay }}
        />
      ))}
    </span>
  )
}
