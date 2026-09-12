import { createContext, useContext } from 'react'
import type { SchemaLoginIn, SchemaUserOut } from '@/api/types'

export interface AuthContextValue {
  user: SchemaUserOut | null
  isLoading: boolean
  isAuthenticated: boolean
  login: (credentials: SchemaLoginIn) => Promise<SchemaUserOut>
  logout: () => void
}

export const AuthContext = createContext<AuthContextValue | null>(null)

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext)
  if (!context) throw new Error('useAuth must be used within an AuthProvider')
  return context
}
