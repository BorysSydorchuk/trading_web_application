/** Accounts API types (docs/api.md, M1 "Accounts"). Decimal values are strings. */

export const ACCOUNT_PHASES = ['phase_1', 'phase_2', 'funded'] as const
export type AccountPhase = (typeof ACCOUNT_PHASES)[number]

export const ACCOUNT_STATUSES = ['active', 'passed', 'failed', 'archived'] as const
export type AccountStatus = (typeof ACCOUNT_STATUSES)[number]

export const ACCOUNT_PLATFORMS = ['mt5', 'ctrader'] as const
export type AccountPlatform = (typeof ACCOUNT_PLATFORMS)[number]

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
  /** Account size («Розмір рахунку»): base for risk %, P&L %, daily/weekly limits (M5-10). */
  reference_balance: string
  daily_loss_pct: string | null
  max_drawdown_pct: string | null
  profit_target_pct: string | null
}

export interface Account extends AccountInput {
  id: number
  /** Read-only. For cTrader: no terminal, `password_env_key` is "", `password_configured` is true. */
  platform: AccountPlatform
  password_env_key: string
  password_configured: boolean
  balance: string | null
  equity: string | null
  balance_synced_at: string | null
  server_offset_hours: number | null
  /** First MT5 deposit when it differs from starting_balance (2026-11-20); confirm = PATCH starting_balance. */
  starting_balance_suggestion?: { amount: string; time: string } | null
  created_at: string
  updated_at: string
}

/** `POST /api/ctrader/accounts` (backend/app/schemas/ctrader.py); login and server come from cTrader. */
export type CtraderAccountInput = Omit<AccountInput, 'login' | 'server' | 'terminal_path'> & {
  ctid_trader_account_id: number
}

export interface AccountList {
  items: Account[]
}

/** Env key the backend uses for the investor password (docs/api.md). */
export function passwordEnvKey(login: string | number): string {
  return `MT5_PASSWORD_${login}`
}
