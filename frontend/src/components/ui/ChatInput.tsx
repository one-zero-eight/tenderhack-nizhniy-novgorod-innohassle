import {
  forwardRef,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type DragEvent,
  type KeyboardEvent,
  type TextareaHTMLAttributes,
} from 'react'
import { FaPaperclip, FaPaperPlane } from 'react-icons/fa6'
import Button from '@/components/ui/Button'
import ChatAttachments from '@/components/ui/ChatAttachments'
import ChatCommandsMenu, { type ChatCommand } from '@/components/ui/ChatCommandsMenu'
import { cn } from '@/lib/cn'
import type { Attachment } from '@/hooks/useFileAttachments'

type NativeTextareaProps = Omit<TextareaHTMLAttributes<HTMLTextAreaElement>, 'onChange' | 'value' | 'rows'>

interface ChatInputProps extends NativeTextareaProps {
  value: string
  onChange: (value: string) => void
  /** Called when the user submits (Enter without Shift, or the send button). */
  onSubmit?: () => void
  /** Renders the composer in a non-interactive, waiting state. */
  disabled?: boolean
  /** Max height in pixels before the textarea starts scrolling. */
  maxHeight?: number
  /** Files attached to the next message. */
  attachments?: Attachment[]
  /** Called with newly selected or dropped files. */
  onFilesAdded?: (files: File[]) => void
  /** Called when the user removes an attachment. */
  onRemoveAttachment?: (id: string) => void
  /** `accept` attribute for the file picker. */
  accept?: string
  /** Slash-commands offered by the commands button next to the send button. */
  commands?: ChatCommand[]
}

/**
 * Multi-line chat composer with attachments.
 *
 * Layout (top to bottom):
 *  1. Attachment chips (when any are present).
 *  2. The textarea, which grows with content up to `maxHeight`.
 *  3. A control row with the attach button and the send button.
 *
 * - `Enter` submits; `+Enter` inserts a newline.
 * - The attach button opens the system file picker.
 * - Files can also be dropped anywhere on the composer.
 */
const ChatInput = forwardRef<HTMLTextAreaElement, ChatInputProps>(
  (
    {
      value,
      onChange,
      onSubmit,
      disabled = false,
      maxHeight = 160,
      attachments = [],
      onFilesAdded,
      onRemoveAttachment,
      accept,
      commands = [],
      className,
      onKeyDown,
      ...props
    },
    ref,
  ) => {
    const innerRef = useRef<HTMLTextAreaElement | null>(null)
    const fileInputRef = useRef<HTMLInputElement | null>(null)
    const [isDragging, setIsDragging] = useState(false)
    // Drag events fire for every child element; count enter/leave to know when
    // the pointer really left the composer.
    const dragDepth = useRef(0)

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

    const handleDragEnter = (event: DragEvent<HTMLDivElement>) => {
      if (disabled) return
      event.preventDefault()
      dragDepth.current += 1
      if (event.dataTransfer.types.includes('Files')) setIsDragging(true)
    }

    const handleDragOver = (event: DragEvent<HTMLDivElement>) => {
      if (disabled) return
      // Required so the browser allows the drop.
      event.preventDefault()
      event.dataTransfer.dropEffect = 'copy'
    }

    const handleDragLeave = (event: DragEvent<HTMLDivElement>) => {
      if (disabled) return
      event.preventDefault()
      dragDepth.current -= 1
      if (dragDepth.current <= 0) {
        dragDepth.current = 0
        setIsDragging(false)
      }
    }

    const handleDrop = (event: DragEvent<HTMLDivElement>) => {
      if (disabled) return
      event.preventDefault()
      dragDepth.current = 0
      setIsDragging(false)
      const files = Array.from(event.dataTransfer.files)
      if (files.length > 0) onFilesAdded?.(files)
    }

    return (
      <div
        onDragEnter={handleDragEnter}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        className={cn(
          'flex w-full flex-col gap-2 border-2 border-pale-blue bg-white p-2 transition-colors',
          isDragging ? 'border-main-blue/60 bg-pale-blue/20' : 'focus-within:border-main-blue/50',
          disabled ? 'cursor-not-allowed opacity-50' : undefined,
          className,
        )}
      >
        <ChatAttachments attachments={attachments} onRemove={onRemoveAttachment} />

        <textarea
          ref={setRefs}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={disabled}
          rows={1}
          className={cn(
            'block min-h-9 w-full resize-none bg-transparent px-2 py-1 text-sm text-black',
            'placeholder:text-gray outline-none disabled:cursor-not-allowed',
          )}
          {...props}
        />

        <div className="flex items-center justify-between gap-2">
          <input
            ref={fileInputRef}
            type="file"
            multiple
            accept={accept}
            className="hidden"
            onChange={(e) => {
              const files = e.target.files ? Array.from(e.target.files) : []
              if (files.length > 0) onFilesAdded?.(files)
              // Reset so picking the same file again still fires onChange.
              e.target.value = ''
            }}
          />
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="flex items-center gap-2"
            disabled={disabled}
            onClick={() => fileInputRef.current?.click()}
          >
            <FaPaperclip />
            <span>Прикрепить</span>
          </Button>
          <div className="flex items-center gap-2">
            <ChatCommandsMenu
              commands={commands}
              disabled={disabled}
              onSelect={(command) => {
                // Paste the command into the composer; the user still has to
                // send it for it to take effect.
                onChange(command.value)
                innerRef.current?.focus()
              }}
            />
            <Button
              type="button"
              variant="primary"
              size="sm"
              className="flex items-center gap-2"
              disabled={disabled || !value.trim()}
              onClick={() => onSubmit?.()}
            >
              <FaPaperPlane />
              <span>Отправить</span>
            </Button>
          </div>
        </div>
      </div>
    )
  },
)

ChatInput.displayName = 'ChatInput'
export default ChatInput
