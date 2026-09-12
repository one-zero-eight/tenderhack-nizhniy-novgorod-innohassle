import { forwardRef, useEffect, useLayoutEffect, useRef, type KeyboardEvent, type TextareaHTMLAttributes } from 'react'
import { cn } from '@/lib/cn'

type NativeTextareaProps = Omit<TextareaHTMLAttributes<HTMLTextAreaElement>, 'onChange' | 'value' | 'rows'>

interface ChatInputProps extends NativeTextareaProps {
  value: string
  onChange: (value: string) => void
  /** Called when the user submits with Enter (without Shift). */
  onSubmit?: () => void
  /** Renders the input in a non-interactive, waiting state. */
  disabled?: boolean
  /** Max height in pixels before the textarea starts scrolling. */
  maxHeight?: number
  /** Optional content rendered on the right, vertically centered (e.g. a submit button). */
  action?: React.ReactNode
}

/**
 * Multi-line chat composer.
 *
 * - `Enter` submits the message.
 * - `Shift+Enter` inserts a newline.
 *
 * The textarea grows with its content up to `maxHeight`, after which it
 * scrolls. An optional `action` (e.g. a send button) sits vertically centered
 * on the right so the composer reads as a single, bounded control.
 */
const ChatInput = forwardRef<HTMLTextAreaElement, ChatInputProps>(
  ({ value, onChange, onSubmit, disabled = false, maxHeight = 160, action, className, onKeyDown, ...props }, ref) => {
    const innerRef = useRef<HTMLTextAreaElement | null>(null)

    // Keep the height synced with the content, resetting first so it can shrink.
    useLayoutEffect(() => {
      const el = innerRef.current
      if (!el) return
      el.style.height = 'auto'
      el.style.height = `${Math.min(el.scrollHeight, maxHeight)}px`
      el.style.overflowY = el.scrollHeight > maxHeight ? 'auto' : 'hidden'
    }, [value, maxHeight])

    // Focus the composer once mounted.
    useEffect(() => {
      innerRef.current?.focus()
    }, [])

    const setRefs = (node: HTMLTextAreaElement | null) => {
      innerRef.current = node
      if (typeof ref === 'function') ref(node)
      else if (ref) ref.current = node
    }

    const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
      onKeyDown?.(event)
      if (event.defaultPrevented) return

      // Enter submits; Shift+Enter falls through to insert a newline.
      if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault()
        if (!disabled && value.trim()) onSubmit?.()
      }
    }

    return (
      <div
        className={cn(
          'flex w-full items-end gap-2 border-2 border-pale-blue bg-white px-2 py-1.5 transition-colors',
          'focus-within:border-main-blue/50',
          disabled ? 'cursor-not-allowed opacity-50' : undefined,
          className,
        )}
      >
        <textarea
          ref={setRefs}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={disabled}
          rows={1}
          className={cn(
            'block min-h-9 w-full flex-1 resize-none self-center bg-transparent px-2 py-1 text-sm text-pale-black',
            'placeholder:text-gray outline-none disabled:cursor-not-allowed',
          )}
          {...props}
        />
        {action && <div className="shrink-0 self-end">{action}</div>}
      </div>
    )
  },
)

ChatInput.displayName = 'ChatInput'
export default ChatInput
