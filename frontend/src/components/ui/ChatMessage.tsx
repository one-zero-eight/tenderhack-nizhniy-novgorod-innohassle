import { Markdown, type MarkdownComponentProps, type MarkdownComponents } from '@tanstack/markdown/react'
import { Link } from '@tanstack/react-router'
import { FaCommentDots, FaFileContract, FaPaperclip, FaPencil } from 'react-icons/fa6'
import { cn } from '@/lib/cn'
import { resolveAssetSrc } from '@/lib/assets'
import { chatFileUrl } from '@/api/chat'
import { extractReferences, contractLabel } from '@/lib/contracts'
import type { SchemaContractOut } from '@/api/types'
import type { ChatView } from '@/lib/chat-view'
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
  /** Contracts available to the user, used to resolve referenced contract names. */
  contracts?: SchemaContractOut[]
  /** Chats referenced with `@[name]`; reserved for future name resolution. */
  chats?: ChatView[]
  /**
   * When provided, hovering the row highlights it across the full chat width
   * and offers a pencil action that creates a hand-rule from this exchange.
   */
  onCreateRule?: () => void
  className?: string
}

/** Formats a byte count as a short human-readable size. */
function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} Б`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} КБ`
  return `${(bytes / (1024 * 1024)).toFixed(1)} МБ`
}

/** Props passed to custom components; the parser adds a `node` field we drop. */type ElementProps<Tag extends keyof React.JSX.IntrinsicElements> = MarkdownComponentProps<Tag> & { node?: unknown }

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

export default function ChatMessage({ message, isParticipant = true, contracts = [], chats = [], onCreateRule, className }: ChatMessageProps) {
  const mine = message.senderType === SenderType.user
  const actionable = !!onCreateRule

  // Contract and chat references are sent as plain text but shown as chips, so
  // the header lines, markers and `@[name]` syntax are stripped from the body.
  const { contractIds, chatNames, text: bodyText } = extractReferences(message.text, { contracts, chats })

  // Resolve display names for the referenced contracts.
  const contractById = new Map(contracts.map((contract) => [contract.id, contract]))

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
          bodyText ? (
            <span className="whitespace-pre-wrap">{bodyText}</span>
          ) : null
        ) : bodyText ? (
          <Markdown components={components}>{bodyText}</Markdown>
        ) : (
          // Before the first token arrives the bubble only shows the indicator.
          <span className="text-gray">Ответ формируется</span>
        )}
        {/* Animated ellipsis while tokens are still streaming in. */}
        {message.isStreaming && <TypingDots className="ml-1.5 align-middle" />}
        {/* Contracts referenced in the message, rendered as attachments. */}
        {contractIds.length > 0 && (
          <div className="mt-2 flex flex-col gap-1.5">
            {contractIds.map((id) => {
              const contract = contractById.get(id)
              return (
                <Link
                  key={id}
                  to="/contracts/$contractId"
                  params={{ contractId: id }}
                  title="Открыть контракт"
                  className={cn(
                    'flex max-w-full flex-col gap-0.5 px-2 py-1.5 text-xs no-underline transition-opacity hover:opacity-80',
                    mine ? 'bg-white/15 text-white' : 'bg-pale-blue/60 text-main-blue',
                  )}
                >
                  <span className="flex items-center gap-2">
                    <FaFileContract className="size-3 shrink-0" />
                    <span className="truncate font-medium">{contract ? contractLabel(contract) : id}</span>
                  </span>
                  {contract && <span className={cn('font-mono', mine ? 'text-white/70' : 'text-gray')}>{id}</span>}
                </Link>
              )
            })}
          </div>
        )}
        {/* Chats referenced with `@[name]`, rendered as chips. */}
        {chatNames.length > 0 && (
          <div className="mt-2 flex flex-wrap gap-1.5">
            {chatNames.map((name) => (
              <span
                key={name}
                className={cn(
                  'flex max-w-full items-center gap-2 px-2 py-1.5 text-xs',
                  mine ? 'bg-white/15 text-white' : 'bg-pale-blue/60 text-main-blue',
                )}
              >
                <FaCommentDots className="size-3 shrink-0" />
                <span className="truncate">{name}</span>
              </span>
            ))}
          </div>
        )}
        {/* Files attached to the message: images as thumbnails, the rest as links. */}
        {message.attachments.length > 0 && (
          <div className="mt-2 flex flex-col gap-1.5">
            {message.attachments.map((file) =>
              file.is_image ? (
                <a key={file.id} href={chatFileUrl(file)} target="_blank" rel="noopener noreferrer" className="block">
                  <img
                    src={chatFileUrl(file)}
                    alt={file.filename}
                    loading="lazy"
                    className="border-gray-blue max-h-72 max-w-full border bg-white"
                  />
                </a>
              ) : (
                <a
                  key={file.id}
                  href={chatFileUrl(file)}
                  target="_blank"
                  rel="noopener noreferrer"
                  title={file.filename}
                  className={cn(
                    'flex max-w-full items-center gap-2 px-2 py-1.5 text-xs no-underline',
                    mine ? 'bg-white/15 text-white' : 'bg-pale-blue/60 text-main-blue',
                  )}
                >
                  <FaPaperclip className="size-3 shrink-0" />
                  <span className="truncate">{file.filename}</span>
                  <span className={cn('shrink-0', mine ? 'text-white/70' : 'text-gray')}>
                    {formatFileSize(file.size)}
                  </span>
                </a>
              ),
            )}
          </div>
        )}
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
