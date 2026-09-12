import { Role } from '@/api/types'

/**
 * Account type chosen at registration.
 *
 * This is a UI-level concept: the backend only knows `user` and `admin`
 * (the `operator` role is being removed). Both «Заказчик» and «Поставщик»
 * are regular `user` accounts and are distinguished only by this label.
 */
export type AccountType = 'customer' | 'supplier' | 'admin'

/** Backend role each account type maps to. */
export const ACCOUNT_TYPE_ROLE: Record<AccountType, Role> = {
  customer: Role.user,
  supplier: Role.user,
  admin: Role.admin,
}

/** Display labels, in registration order. */
export const ACCOUNT_TYPE_LABELS: Record<AccountType, string> = {
  customer: 'Заказчик',
  supplier: 'Поставщик',
  admin: 'Администратор',
}

/** Account types offered during self-registration, in display order. */
export const REGISTER_ACCOUNT_TYPES: AccountType[] = ['customer', 'supplier', 'admin']

/** Labels for the backend `Role`, used for users created elsewhere. */
export const ROLE_LABELS: Record<Role, string> = {
  [Role.user]: 'Пользователь',
  [Role.operator]: 'Оператор',
  [Role.admin]: 'Администратор',
}

/** Returns the localized label for a backend role, falling back to the raw value. */
export function roleLabel(role: Role | null | undefined): string {
  return role ? (ROLE_LABELS[role] ?? role) : ''
}

/** Default landing path after login, registration, or clicking the portal logo. */
export function homePath(role: Role | null | undefined): '/history' | '/support' {
  return role === Role.admin ? '/history' : '/support'
}
