import type { ChatMessageData, ChatMinimal } from '@/types/types'

const CHATS_KEY = 'support.chats'
const MESSAGES_KEY = 'support.messages'
const MOCK_DELAY_MS = 1000
const MOCK_MUTATION_DELAY_MS = 500

/**
 * Reads chats from localStorage. Returns an empty list if nothing is stored.
 */
function readChats(): ChatMinimal[] {
  const raw = localStorage.getItem(CHATS_KEY)
  if (!raw) return []
  try {
    const parsed = JSON.parse(raw)
    return Array.isArray(parsed) ? (parsed as ChatMinimal[]) : []
  } catch {
    return []
  }
}

/**
 * Writes chats to localStorage.
 */
export function writeChats(chats: ChatMinimal[]): void {
  localStorage.setItem(CHATS_KEY, JSON.stringify(chats))
}

const SEED_CHATS: ChatMinimal[] = [
  {
    chat_id: 'seed-1',
    chat_title: 'Не приходит счёт на оплату',
    chat_status: 'second-lane',
    chat_creation_date: '2026-09-10T09:24:00+00:00',
  },
  {
    chat_id: 'seed-2',
    chat_title: 'Как изменить реквизиты организации?',
    chat_status: 'ai',
    chat_creation_date: '2026-09-09T14:02:00+00:00',
  },
  {
    chat_id: 'seed-3',
    chat_title: 'Вопрос по закупке №12345',
    chat_status: 'closed',
    chat_creation_date: '2026-09-05T11:47:00+00:00',
  },
]

/**
 * Mock replacement for `GET /chats`.
 *
 * Simulates a network request by waiting 2 seconds, then returns the chats
 * stored in localStorage. Seeds demo data on first run. Replace this with the
 * real API call once the backend interface is wired up.
 */
export async function fetchChats(): Promise<ChatMinimal[]> {
  await new Promise((resolve) => setTimeout(resolve, MOCK_DELAY_MS))
  const stored = readChats()
  if (stored.length === 0 && localStorage.getItem(CHATS_KEY) === null) {
    writeChats(SEED_CHATS)
    return SEED_CHATS
  }
  return stored
}

/**
 * Mock replacement for `GET /chats/{chat_id}`.
 *
 * Throws when the chat does not exist so callers can show an error state.
 */
export async function fetchChat(chatId: string): Promise<ChatMinimal> {
  await new Promise((resolve) => setTimeout(resolve, MOCK_MUTATION_DELAY_MS))
  const chat = readChats().find((c) => c.chat_id === chatId)
  if (!chat) throw new Error('Чат не найден')
  return chat
}

/**
 * Mock replacement for `POST /chats`.
 *
 * Creates a new chat, assigns it an id, persists it to localStorage and
 * returns it. Replace with the real API call once the backend is wired up.
 */
export async function createChat(): Promise<ChatMinimal> {
  await new Promise((resolve) => setTimeout(resolve, MOCK_MUTATION_DELAY_MS))
  const chat: ChatMinimal = {
    chat_id: crypto.randomUUID(),
    chat_title: 'Новый чат',
    chat_status: 'ai',
    chat_creation_date: new Date().toISOString(),
  }
  writeChats([chat, ...readChats()])
  return chat
}

/** All messages keyed by chat id. */
type MessagesStore = Record<string, ChatMessageData[]>

function readMessages(): MessagesStore {
  const raw = localStorage.getItem(MESSAGES_KEY)
  if (!raw) return {}
  try {
    const parsed = JSON.parse(raw)
    return parsed && typeof parsed === 'object' ? (parsed as MessagesStore) : {}
  } catch {
    return {}
  }
}

function writeMessages(store: MessagesStore): void {
  localStorage.setItem(MESSAGES_KEY, JSON.stringify(store))
}

const SEED_MESSAGES: MessagesStore = {
  'seed-1': [
    { chatId: 'seed-1', id: 1, sender: 'user', text: 'Здравствуйте! Не приходит счёт на оплату.', sent_at: '2026-09-10T09:24:00+00:00', questionRedirected: false },
    { chatId: 'seed-1', id: 2, sender: 'ai', text: 'Добрый день! Проверяю статус счёта, одну минуту.', sent_at: '2026-09-10T09:24:30+00:00', questionRedirected: false },
    { chatId: 'seed-1', id: 3, sender: 'ai', text: 'К сожалению, я не могу ответить на этот вопрос. Перевожу вас на Линию 2 — специалист поможет вам.', sent_at: '2026-09-10T09:25:00+00:00', questionRedirected: true },
    { chatId: 'seed-1', id: 4, sender: 'second-lane', text: 'Здравствуйте, счёт сформирован. Отправим повторно в течение дня.', sent_at: '2026-09-10T09:31:00+00:00', questionRedirected: false },
  ],
  'seed-2': [
    { chatId: 'seed-2', id: 1, sender: 'user', text: 'Как изменить реквизиты организации?', sent_at: '2026-09-09T14:02:00+00:00', questionRedirected: false },
    { chatId: 'seed-2', id: 2, sender: 'ai', text: 'Реквизиты можно изменить в разделе «Профиль» → «Реквизиты».', sent_at: '2026-09-09T14:02:20+00:00', questionRedirected: false },
  ],
}

/** Lane the AI hands off to when it cannot answer itself. */
type RedirectLane = 'second-lane' | 'third-lane'

const LANE_NAMES: Record<RedirectLane, string> = {
  'second-lane': 'Линию 2',
  'third-lane': 'Линию 3',
}

/** Keywords marking a critical bug / "something is broken". */
const CRITICAL_PATTERNS = [
  'не работает', 'сломал', 'ошибка', 'баг', 'критич', 'вылет', 'не грузит', 'не открывается',
  'зависает', 'недоступн', 'не отправляется', 'not working', 'broken', 'bug', 'crash', 'error',
]

/** Keywords marking technical questions or questions about the user's own data. */
const TECHNICAL_PATTERNS = [
  'мой', 'моя', 'мои', 'счёт', 'счет', 'реквизит', 'заявк', 'закупк', 'контракт', 'платеж', 'платёж',
  'оплат', 'баланс', 'профил', 'аккаунт', 'пароль', 'статус', 'история', 'данн', 'выписк', 'договор',
  'возврат', 'счет-фактур', 'счёт-фактур', 'my ', 'account', 'payment', 'invoice', 'contract',
]

/**
 * Decides how the AI mock responds to a user message.
 *
 * - Critical bugs / "something is broken" → third lane.
 * - Technical or personal-data questions → second lane.
 * - Everything else (general/how-the-site-works) → the AI answers itself.
 */
function classifyQuestion(text: string): { answer: string; redirectTo: RedirectLane | null } {
  const lower = text.toLowerCase()

  if (CRITICAL_PATTERNS.some((p) => lower.includes(p))) {
    return {
      answer: `К сожалению, я не могу ответить на этот вопрос. Перевожу вас на ${LANE_NAMES['third-lane']} — специалист поможет вам.`,
      redirectTo: 'third-lane',
    }
  }

  if (TECHNICAL_PATTERNS.some((p) => lower.includes(p))) {
    return {
      answer: `К сожалению, я не могу ответить на этот вопрос. Перевожу вас на ${LANE_NAMES['second-lane']} — специалист поможет вам.`,
      redirectTo: 'second-lane',
    }
  }

  return {
    answer: 'Спасибо за вопрос! Это общий вопрос, отвечаю сам: вы можете найти нужный раздел в меню слева, а подробная инструкция доступна в справке «Помощь».',
    redirectTo: null,
  }
}

/** Canned opening reply from the lane the AI redirected to. */
function laneReply(lane: RedirectLane): string {
  return lane === 'third-lane'
    ? 'Здравствуйте, это Линия 3. Принял вашу заявку о проблеме, уточню детали и передам разработчикам.'
    : 'Здравствуйте, это Линия 2. Изучу ваш вопрос по данным и помогу разобраться.'
}

/**
 * Mock replacement for `GET /chats/{chat_id}/messages`.
 *
 * Waits, then returns the stored messages for the given chat (seeding demo
 * messages on first run). Replace with the real API call later.
 */
export async function fetchChatMessages(chatId: string): Promise<ChatMessageData[]> {
  await new Promise((resolve) => setTimeout(resolve, MOCK_DELAY_MS))
  const store = readMessages()
  if (Object.keys(store).length === 0 && localStorage.getItem(MESSAGES_KEY) === null) {
    writeMessages(SEED_MESSAGES)
    return SEED_MESSAGES[chatId] ?? []
  }
  return store[chatId] ?? []
}

/**
 * Mock replacement for `POST /chats/{chat_id}/messages`.
 *
 * Appends a user message to the chat and returns it. Replace with the real
 * API call later.
 */
export async function sendChatMessage(chatId: string, text: string): Promise<ChatMessageData[]> {
  await new Promise((resolve) => setTimeout(resolve, MOCK_MUTATION_DELAY_MS))
  const store = readMessages()
  const existing = store[chatId] ?? []
  const nextId = existing.length > 0 ? Math.max(...existing.map((m) => m.id)) + 1 : 1
  const now = Date.now()

  const userMessage: ChatMessageData = {
    chatId,
    id: nextId,
    sender: 'user',
    text,
    sent_at: new Date(now).toISOString(),
    questionRedirected: false,
  }

  const { answer, redirectTo } = classifyQuestion(text)
  const created: ChatMessageData[] = [userMessage]

  const aiMessage: ChatMessageData = {
    chatId,
    id: nextId + 1,
    sender: 'ai',
    text: answer,
    sent_at: new Date(now + 1000).toISOString(),
    questionRedirected: redirectTo !== null,
  }
  created.push(aiMessage)

  if (redirectTo) {
    created.push({
      chatId,
      id: nextId + 2,
      sender: redirectTo,
      text: laneReply(redirectTo),
      sent_at: new Date(now + 2000).toISOString(),
      questionRedirected: false,
    })
  }

  writeMessages({ ...store, [chatId]: [...existing, ...created] })
  return created
}
