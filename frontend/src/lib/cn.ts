import { twMerge } from 'tailwind-merge'
import clsx from 'clsx'

/**
 * Combines classes using twMerge and clsx
 * @param inputs classes
 * @returns combined classes
 */
export function cn(...inputs: (string | undefined | null)[]): string {
  return twMerge(clsx(inputs))
}
