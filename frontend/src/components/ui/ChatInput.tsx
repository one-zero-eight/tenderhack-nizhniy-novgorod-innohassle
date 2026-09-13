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
import MentionMenu from '@/components/ui/MentionMenu'
import { cn } from '@/lib/cn'
import { contractToken, chatToken } from '@/lib/contracts'
import type { Attachment } from '@/hooks/useFileAttachments'
import type { SchemaContractOut } from '@/api/types'
import type { ChatView } from '@/lib/chat-view'

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
  /** Contracts offered by the `@` mention popup. */
  contracts?: SchemaContractOut[]
  /** Chats offered by the `@` mention popup (second tab). */
  chats?: ChatView[]
}
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
      contracts = [],
      chats = [],
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
    // `@` mention state: the query after `@` and where it starts in the text.
    const [mention, setMention] = useState<{ query: string; start: number } | null>(null)
    const [mentionIndex, setMentionIndex] = useState(0)

    const mentionQuery = mention?.query ?? ''
    // Options currently shown by the popup, published for keyboard navigation.
    const [mentionOptions, setMentionOptions] = useState<{ token: string }[]>([])

    /** Recomputes the mention state from the text and the caret position. */
    const syncMention = (text: string, caret: number) => {
      // Walk back from the caret to the nearest `@` on the same line.
      const before = text.slice(0, caret)
      const at = before.lastIndexOf('@')
      if (at === -1) return setMention(null)

      const between = before.slice(at + 1)
      // A mention ends at whitespace or a line break.
      if (/[\s\n]/.test(between)) return setMention(null)
      setMention({ query: between, start: at })
      setMentionIndex(0)
    }

    /**
     * Replaces the `@query` fragment with the chosen reference.
     *
     * Contracts insert their marker token; chats insert `@[name]` verbatim, so
     * nothing else is added to the message.
     */
    const acceptMention = (token: string) => {
      const el = innerRef.current
      if (!el || !mention) return
      const caret = el.selectionStart ?? value.length
      const next = `${value.slice(0, mention.start)}${token} ${value.slice(caret)}`
      onChange(next)
      setMention(null)
      // Restore focus and place the caret after the inserted token.
      requestAnimationFrame(() => {
        const position = mention.start + token.length + 1
        el.focus()
        el.setSelectionRange(position, position)
      })
    }

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

      // While the mention popup is open, keys navigate it instead of submitting.
      // The visible options are tracked by the popup itself (`mentionOptions`).
      if (mention && mentionOptions.length > 0) {
        if (event.key === 'ArrowDown') {
          event.preventDefault()
          setMentionIndex((index) => (index + 1) % mentionOptions.length)
          return
        }
        if (event.key === 'ArrowUp') {
          event.preventDefault()
          setMentionIndex((index) => (index - 1 + mentionOptions.length) % mentionOptions.length)
          return
        }
        // Tab and Enter accept the highlighted option.
        if (event.key === 'Tab' || (event.key === 'Enter' && !event.shiftKey)) {
          event.preventDefault()
          const option = mentionOptions[mentionIndex]
          if (option) acceptMention(option.token)
          return
        }
        if (event.key === 'Escape') {
          event.preventDefault()
          setMention(null)
          return
        }
      }

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

        <div className="relative">
          <textarea
            ref={setRefs}
            value={value}
            onChange={(e) => {
              onChange(e.target.value)
              syncMention(e.target.value, e.target.selectionStart ?? e.target.value.length)
            }}
            onKeyDown={handleKeyDown}
            // Clicking elsewhere in the text re-evaluates the mention context.
            onClick={(e) => syncMention(value, e.currentTarget.selectionStart ?? value.length)}
            onBlur={() => setMention(null)}
            disabled={disabled}
            rows={1}
            className={cn(
              'block min-h-9 w-full resize-none bg-transparent px-2 py-1 text-sm text-black',
              'placeholder:text-gray outline-none disabled:cursor-not-allowed',
            )}
            {...props}
          />

          {mention && (
            <MentionMenu
              contracts={contracts}
              chats={chats}
              query={mentionQuery}
              activeIndex={mentionIndex}
              onSelectContract={(contract) => acceptMention(contractToken(contract.id))}
              onSelectChat={(chat) => acceptMention(chatToken(chat.title))}
              onHover={setMentionIndex}
              onOptionsChange={setMentionOptions}
            />
          )}
        </div>

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
