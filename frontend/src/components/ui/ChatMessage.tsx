import { Markdown, type MarkdownComponentProps, type MarkdownComponents } from '@tanstack/markdown/react'
import { FaPencil } from 'react-icons/fa6'
import { cn } from '@/lib/cn'
import { resolveAssetSrc } from '@/lib/assets'
import TypingDots from '@/components/ui/TypingDots'
import { formatTime } from '@/lib/format'
import { SENDER_LABELS, type MessageView } from '@/lib/chat-view'
import { SenderType } from '@/api/types'

interface ChatMessageProps {
  message: MessageView
  /**
   * True when the viewer is a participant (the user themselves). In the
   * read-only admin view this is false, so the user is labelled «Пользователь»
   * instead of «Вы».
   */
  isParticipant?: boolean
  /**
   * When provided, hovering the row highlights it across the full chat width
   * and offers a pencil action that creates a hand-rule from this exchange.
   */
  onCreateRule?: () => void
  className?: string
}

/** Props passed to custom components; the parser adds a `node` field we drop. */
type ElementProps<Tag extends keyof React.JSX.IntrinsicElements> = MarkdownComponentProps<Tag> & { node?: unknown }

/** Removes the non-DOM `node` prop before spreading onto an element. */
function withoutNode<T extends { node?: unknown }>({ node, ...rest }: T): Omit<T, 'node'> {
  void node
  return rest
}

/**
 * Element styling for rendered Markdown. Kept compact so it fits inside a chat
 * bubble; `current`-relative colors let it adapt to the bubble background.
 */
const components = {
  p: (props: ElementProps<'p'>) => <p {...withoutNode(props)} className="not-first:mt-2 whitespace-pre-wrap" />,
  code: (props: ElementProps<'code'>) => (
    <code {...withoutNode(props)} className={cn('rounded bg-black/10 px-1 py-0.5 font-mono text-[0.85em]', props.className)} />
  ),
  pre: (props: ElementProps<'pre'>) => (
    <pre {...withoutNode(props)} className="my-2 overflow-x-auto rounded bg-black/10 p-2 text-[0.85em]" />
  ),
  ul: (props: ElementProps<'ul'>) => <ul {...withoutNode(props)} className="my-2 list-disc space-y-1 pl-5" />,
  ol: (props: ElementProps<'ol'>) => <ol {...withoutNode(props)} className="my-2 list-decimal space-y-1 pl-5" />,
  a: (props: ElementProps<'a'>) => (
    <a {...withoutNode(props)} target="_blank" rel="noopener noreferrer" className="underline underline-offset-2 hover:opacity-80" />
  ),
  blockquote: (props: ElementProps<'blockquote'>) => (
    <blockquote {...withoutNode(props)} className="my-2 border-l-2 border-current pl-3 opacity-80" />
  ),
  hr: (props: ElementProps<'hr'>) => <hr {...withoutNode(props)} className="my-2 border-current opacity-20" />,
  h1: (props: ElementProps<'h1'>) => <p {...withoutNode(props)} className="mt-2 mb-1 font-semibold" />,
  h2: (props: ElementProps<'h2'>) => <p {...withoutNode(props)} className="mt-2 mb-1 font-semibold" />,
  h3: (props: ElementProps<'h3'>) => <p {...withoutNode(props)} className="mt-2 mb-1 font-semibold" />,
  img: (props: ElementProps<'img'>) => {
    const { src, alt, ...rest } = withoutNode(props)
    return (
      // Images are served by the API origin, so the `/ml-assets/...` path has to
      // be rewritten before the browser resolves it.
      <img
        {...rest}
        src={resolveAssetSrc(src ?? '')}
        alt={alt ?? ''}
        loading="lazy"
        className="border-gray-blue my-2 block h-auto max-w-full rounded border bg-white"
      />
    )
  },
} satisfies MarkdownComponents

export default function ChatMessage({ message, isParticipant = true, onCreateRule, className }: ChatMessageProps) {
  const mine = message.senderType === SenderType.user
  const actionable = !!onCreateRule

  // The backend reports the requester as the sender for every user message, so
  // for those we use a viewer-relative label rather than `sender_name`.
  const senderLabel = mine
    ? isParticipant
      ? 'Вы'
      : 'Пользователь'
    : message.senderName || SENDER_LABELS[message.senderType]

  const body = (
    <>
      <span className="text-gray text-xs">
        <span className="font-medium">{senderLabel}</span>
      </span>
      <div
        className={cn(
          'relative rounded-lg pt-2 pr-16 pb-2 pl-4 text-sm wrap-break-word border-gray-200 border',
          mine ? 'bg-main-blue rounded-br-none text-white' : 'bg-white text-black rounded-bl-none',
          message.isRedacted ? 'italic opacity-70' : undefined,
        )}
      >
        {/* The user's own text is shown verbatim; assistant replies may contain Markdown. */}
        {mine ? (
          <span className="whitespace-pre-wrap">{message.text}</span>
        ) : message.text ? (
          <Markdown components={components}>{message.text}</Markdown>
        ) : (
          // Before the first token arrives the bubble only shows the indicator.
          <span className="text-gray">Ответ формируется</span>
        )}
        {/* Animated ellipsis while tokens are still streaming in. */}
        {message.isStreaming && <TypingDots className="ml-1.5 align-middle" />}
        {/* Timestamp pinned to the bubble's bottom-right corner. */}
        <span
          className={cn(
            'absolute right-3 bottom-1.5 text-[0.7rem] leading-none select-none',
            mine ? 'text-white/70' : 'text-gray',
          )}
        >
          {formatTime(message.createdAt)}
        </span>
      </div>
    </>
  )

  // Read-only mode: a plain, non-interactive row.
  if (!actionable) {
    return (
      <div className={cn('flex w-full', mine ? 'justify-end' : 'justify-start', className)}>
        <div className={cn('flex max-w-[80%] flex-col gap-1', mine ? 'items-end' : 'items-start')}>{body}</div>
      </div>
    )
  }

  // Actionable mode: the whole row is clickable, tints on hover and reveals the
  // pencil hint to the right of the message.
  return (
    <button
      type="button"
      onClick={onCreateRule}
      title="Создать правило по этому ответу"
      className={cn(
        'group flex w-full cursor-pointer items-center gap-3 px-2 py-1 text-left transition-colors',
        'hover:bg-pale-blue/70 focus:bg-pale-blue/70 focus:outline-none',
        mine ? 'flex-row-reverse justify-start' : 'justify-start',
        className,
      )}
    >
      <div className={cn('flex max-w-[80%] min-w-0 flex-col gap-1', mine ? 'items-end' : 'items-start')}>{body}</div>
      {/* Hint sits outside the bubble and appears on hover/focus. */}
      <span className="text-main-blue flex shrink-0 items-center gap-2 text-xs font-medium opacity-0 transition-opacity group-hover:opacity-100 group-focus-visible:opacity-100">
        <FaPencil className="size-3.5" />
        <span className="whitespace-nowrap">Добавить правило</span>
      </span>
    </button>
  )
}
