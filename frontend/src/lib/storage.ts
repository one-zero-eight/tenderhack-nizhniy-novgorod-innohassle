const USERNAME_KEY = 'support.username'

export function getUsername(): string | null {
  return localStorage.getItem(USERNAME_KEY)
}

export function setUsername(username: string): void {
  localStorage.setItem(USERNAME_KEY, username)
}

export function clearUsername(): void {
  localStorage.removeItem(USERNAME_KEY)
}
