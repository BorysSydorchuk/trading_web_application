/** cTrader API types (docs/api.md "cTrader integration, phase a"). No token ever reaches the UI. */

export interface CtraderStatus {
  configured: boolean
  connected: boolean
  /** `not_configured`, `token_expired`, `token_invalid`, `token_store_failed` or null. */
  error_code: string | null
}

export interface CtraderAccountItem {
  ctid_trader_account_id: number
  is_live: boolean
  /** Optional in cTrader's model; an account without it cannot be added. */
  trader_login: number | null
  broker: string
  already_added: boolean
}

export interface CtraderAccountList {
  items: CtraderAccountItem[]
}
