import { Markdown, type MarkdownComponentProps, type MarkdownComponents } from '@tanstack/markdown/react'
import { cn } from '@/lib/cn'
import { formatTime } from '@/lib/format'
import { SENDER_LABELS, type MessageView } from '@/lib/chat-view'
import { SenderType } from '@/api/types'

interface ChatMessageProps {
  message: MessageView
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
} satisfies MarkdownComponents

export default function ChatMessage({ message, className }: ChatMessageProps) {
  const mine = message.senderType === SenderType.user

  return (
    <div className={cn('flex w-full', mine ? 'justify-end' : 'justify-start', className)}>
      <div className={cn('flex max-w-[80%] flex-col gap-1', mine ? 'items-end' : 'items-start')}>
        <span className="text-gray text-xs">
          <span className="font-medium">{message.senderName || SENDER_LABELS[message.senderType]}</span>
        </span>
        <div
          className={cn(
            'relative rounded-lg pt-2 pr-16 pb-2 pl-4 text-sm wrap-break-word border-gray-200 border',
            mine ? 'bg-main-blue rounded-br-none text-white' : 'bg-white text-pale-black rounded-bl-none',
            message.isRedacted ? 'italic opacity-70' : undefined,
          )}
        >
          {/* The user's own text is shown verbatim; assistant replies may contain Markdown. */}
          {mine ? (
            <span className="whitespace-pre-wrap">{message.text}</span>
          ) : message.text ? (
            <Markdown components={components}>{message.text}</Markdown>
          ) : (
            // Before the first token arrives the bubble would be empty.
            <span className="text-gray">…</span>
          )}
          {/* Blinking caret while tokens are still streaming in. */}
          {message.isStreaming && <span className="bg-main-blue ml-0.5 inline-block h-3.5 w-1.5 animate-pulse align-text-bottom" aria-hidden="true" />}
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
      </div>
    </div>
  )
}
