const dateTimeFormatter = new Intl.DateTimeFormat('ru-RU', {
  day: '2-digit',
  month: '2-digit',
  year: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
})

const timeFormatter = new Intl.DateTimeFormat('ru-RU', {
  hour: '2-digit',
  minute: '2-digit',
})

const dayMonthFormatter = new Intl.DateTimeFormat('ru-RU', {
  day: 'numeric',
  month: 'long',
})

const dayMonthYearFormatter = new Intl.DateTimeFormat('ru-RU', {
  day: 'numeric',
  month: 'long',
  year: 'numeric',
})

/** Formats an ISO 8601 timestamp as a localized date-time string. */
export function formatDateTime(iso: string): string {
  const date = new Date(iso)
  return Number.isNaN(date.getTime()) ? '' : dateTimeFormatter.format(date)
}

/** Formats an ISO 8601 timestamp as `HH:MM`. */
export function formatTime(iso: string): string {
  const date = new Date(iso)
  return Number.isNaN(date.getTime()) ? '' : timeFormatter.format(date)
}

/** Returns the local calendar day key (`YYYY-MM-DD`) for grouping by date. */
export function dayKey(iso: string): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return ''
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

/**
 * Formats a date divider label Telegram-style: `Сегодня`, `Вчера`, or a full
 * date for older messages (year is added only when it is not the current year).
 */
export function formatDateSeparator(iso: string): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return ''

  const today = new Date()
  const yesterday = new Date()
  yesterday.setDate(today.getDate() - 1)

  const key = dayKey(iso)
  if (key === dayKey(today.toISOString())) return 'Сегодня'
  if (key === dayKey(yesterday.toISOString())) return 'Вчера'

  return date.getFullYear() === today.getFullYear()
    ? dayMonthFormatter.format(date)
    : dayMonthYearFormatter.format(date)
}
