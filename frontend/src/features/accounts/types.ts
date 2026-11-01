/** Accounts API types (docs/api.md, M1 "Accounts"). Decimal values are strings. */

export const ACCOUNT_PHASES = ['phase_1', 'phase_2', 'funded'] as const
export type AccountPhase = (typeof ACCOUNT_PHASES)[number]

export const ACCOUNT_STATUSES = ['active', 'passed', 'failed', 'archived'] as const
export type AccountStatus = (typeof ACCOUNT_STATUSES)[number]

export interface AccountInput {
  name: string
  firm: string
  program: string
  phase: AccountPhase
  login: number
  server: string
  terminal_path: string | null
  starting_balance: string
  currency: string
  status: AccountStatus
  reference_balance: string | null
  daily_loss_pct: string | null
  max_drawdown_pct: string | null
  profit_target_pct: string | null
}

export interface Account extends AccountInput {
  id: number
  password_env_key: string
  password_configured: boolean
  balance: string | null
  equity: string | null
  balance_synced_at: string | null
  server_offset_hours: number | null
  created_at: string
  updated_at: string
}

export interface AccountList {
  items: Account[]
}

/** Env key the backend uses for the investor password (docs/api.md). */
export function passwordEnvKey(login: string | number): string {
  return `MT5_PASSWORD_${login}`
}
