import { useId } from 'react'
import { ChevronLeft, ChevronRight } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { NativeSelect } from '@/components/ui/native-select'
import { uk } from '@/i18n/uk'
import { PAGE_SIZES } from './filters'

interface PaginationProps {
  page: number
  limit: number
  total: number
  onPage: (page: number) => void
  onLimit: (limit: number) => void
}

export function Pagination({ page, limit, total, onPage, onLimit }: PaginationProps) {
  const id = useId()
  const p = uk.journal.pagination
  const pages = Math.max(1, Math.ceil(total / limit))
  const from = total === 0 ? 0 : (page - 1) * limit + 1
  const to = Math.min(total, page * limit)

  return (
    <nav aria-label={p.label} className="flex items-center justify-end gap-3 text-xs text-muted-foreground">
      <label htmlFor={`${id}-size`}>{p.pageSize}</label>
      <div className="w-20">
        <NativeSelect
          id={`${id}-size`}
          className="num h-7 text-xs"
          value={limit}
          onChange={(e) => onLimit(Number(e.target.value))}
        >
          {PAGE_SIZES.map((size) => (
            <option key={size} value={size}>
              {size}
            </option>
          ))}
        </NativeSelect>
      </div>
      <span className="num">{p.range(from, to, total)}</span>
      <Button
        variant="outline"
        size="icon"
        className="size-7"
        onClick={() => onPage(page - 1)}
        disabled={page <= 1}
        aria-label={p.prev}
        title={p.prev}
      >
        <ChevronLeft aria-hidden />
      </Button>
      <Button
        variant="outline"
        size="icon"
        className="size-7"
        onClick={() => onPage(page + 1)}
        disabled={page >= pages}
        aria-label={p.next}
        title={p.next}
      >
        <ChevronRight aria-hidden />
      </Button>
    </nav>
  )
}
