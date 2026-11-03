/** App route of the Describe screen for a trade (PRD 6.5). */
export function describePath(tradeId: number): string {
  return `/trades/${tradeId}/describe`
}
