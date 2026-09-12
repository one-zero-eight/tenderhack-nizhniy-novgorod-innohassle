import { useCallback, useState } from 'react'

/**
 * A file selected for the next message. Not uploaded anywhere yet — it is kept
 * in memory until the backend gains an attachment endpoint.
 */
export interface Attachment {
  id: string
  file: File
}

interface UseFileAttachmentsResult {
  attachments: Attachment[]
  /** Adds files, skipping duplicates of the same name+size. */
  addFiles: (files: FileList | File[] | null) => void
  removeFile: (id: string) => void
  clearFiles: () => void
}

/**
 * Client-side attachment state for the chat composer.
 *
 * Purely local for now: nothing is sent to the backend. The hook is the single
 * place to swap in an upload call later.
 */
export function useFileAttachments(): UseFileAttachmentsResult {
  const [attachments, setAttachments] = useState<Attachment[]>([])

  const addFiles = useCallback((files: FileList | File[] | null) => {
    if (!files) return
    const incoming = Array.from(files)
    if (incoming.length === 0) return

    setAttachments((prev) => {
      const next = [...prev]
      for (const file of incoming) {
        const duplicate = next.some(
          (item) => item.file.name === file.name && item.file.size === file.size && item.file.lastModified === file.lastModified,
        )
        if (!duplicate) next.push({ id: crypto.randomUUID(), file })
      }
      return next
    })
  }, [])

  const removeFile = useCallback((id: string) => {
    setAttachments((prev) => prev.filter((item) => item.id !== id))
  }, [])

  const clearFiles = useCallback(() => setAttachments([]), [])

  return { attachments, addFiles, removeFile, clearFiles }
}
