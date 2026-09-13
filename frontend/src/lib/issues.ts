import type { SchemaChatOut } from '@/api/types'

/** Topic name used for chats without a classified topic. */
export const NO_TOPIC = 'Без темы'

/** Subtopic name used for chats without a classified subtopic. */
export const NO_SUBTOPIC = 'Без подтемы'

/** Topic name of a chat, with a fallback for unclassified chats. */
export function chatTopic(chat: SchemaChatOut): string {
  return chat.topic?.trim() || NO_TOPIC
}

/** Subtopic name of a chat, with a fallback for unclassified chats. */
export function chatSubtopic(chat: SchemaChatOut): string {
  return chat.subtopic?.trim() || NO_SUBTOPIC
}

export interface TopicSummary {
  topic: string
  /** Number of chats in this topic. */
  chatCount: number
  /** Distinct subtopics within the topic. */
  subtopicCount: number
  /**
   * Average time to answer across the topic's chats, in seconds. `null` when no
   * chat in the topic reports a timing.
   */
  averageAnswerSeconds: number | null
}

/** Groups chats by topic and computes per-topic counts and averages. */
export function summarizeTopics(chats: SchemaChatOut[]): TopicSummary[] {
  const byTopic = new Map<string, { chats: SchemaChatOut[]; subtopics: Set<string> }>()

  for (const chat of chats) {
    const topic = chatTopic(chat)
    if (!byTopic.has(topic)) byTopic.set(topic, { chats: [], subtopics: new Set() })
    const entry = byTopic.get(topic) as { chats: SchemaChatOut[]; subtopics: Set<string> }
    entry.chats.push(chat)
    entry.subtopics.add(chatSubtopic(chat))
  }

  return [...byTopic.entries()]
    .map(([topic, entry]) => ({
      topic,
      chatCount: entry.chats.length,
      subtopicCount: entry.subtopics.size,
      averageAnswerSeconds: averageTurnSeconds(entry.chats),
    }))
    .sort((a, b) => {
      if (a.topic === NO_TOPIC) return 1
      if (b.topic === NO_TOPIC) return -1
      return a.topic.localeCompare(b.topic, 'ru')
    })
}

/**
 * Mean `avg_turn_seconds` across chats that report one. Returns `null` when
 * none do, so topics without data sort to the bottom instead of showing 0.
 */
export function averageTurnSeconds(chats: SchemaChatOut[]): number | null {
  const values = chats.map((chat) => chat.avg_turn_seconds).filter((value): value is number => typeof value === 'number')
  if (values.length === 0) return null
  return values.reduce((total, value) => total + value, 0) / values.length
}

export interface SubtopicSummary {
  subtopic: string
  chatCount: number
}

/** Counts chats per subtopic within a topic, sorted by name. */
export function summarizeSubtopics(chats: SchemaChatOut[], topic: string): SubtopicSummary[] {
  const counts = new Map<string, number>()
  for (const chat of chats) {
    if (chatTopic(chat) !== topic) continue
    const subtopic = chatSubtopic(chat)
    counts.set(subtopic, (counts.get(subtopic) ?? 0) + 1)
  }
  return [...counts.entries()]
    .map(([subtopic, chatCount]) => ({ subtopic, chatCount }))
    .sort((a, b) => {
      if (a.subtopic === NO_SUBTOPIC) return 1
      if (b.subtopic === NO_SUBTOPIC) return -1
      return a.subtopic.localeCompare(b.subtopic, 'ru')
    })
}

/** Chats belonging to a topic, optionally narrowed to a subtopic. */
export function chatsForTopic(chats: SchemaChatOut[], topic: string, subtopic: string | null): SchemaChatOut[] {
  return chats.filter((chat) => chatTopic(chat) === topic && (subtopic === null || chatSubtopic(chat) === subtopic))
}
