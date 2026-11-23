import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { DialogClose, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { CtraderAccountStep } from '@/features/ctrader/CtraderAccountStep'
import type { CtraderAccountItem } from '@/features/ctrader/types'
import { uk } from '@/i18n/uk'
import { AccountForm, AccountFormHeader } from './AccountForm'
import type { AccountPlatform } from './types'

const p = uk.ctrader.platform
const f = uk.ctrader.flow

type Step =
  | { kind: 'platform' }
  | { kind: 'mt5' }
  | { kind: 'ctrader' }
  | { kind: 'ctraderForm'; account: CtraderAccountItem }

interface AddAccountFlowProps {
  initialPlatform: AccountPlatform | null
  onDone: () => void
}

/** «Додати рахунок»: platform first, then the MT5 form or the cTrader connect + pick + form path. */
export function AddAccountFlow({ initialPlatform, onDone }: AddAccountFlowProps) {
  const [step, setStep] = useState<Step>(initialPlatform === 'ctrader' ? { kind: 'ctrader' } : { kind: 'platform' })

  switch (step.kind) {
    case 'platform':
      return <PlatformStep onChoose={(kind) => setStep({ kind })} />
    case 'mt5':
      return (
        <>
          <AccountFormHeader title={uk.accounts.form.createTitle} />
          <AccountForm account={null} onDone={onDone} />
        </>
      )
    case 'ctrader':
      return (
        <>
          <DialogHeader>
            <DialogTitle>{f.title}</DialogTitle>
            <DialogDescription>{f.description}</DialogDescription>
          </DialogHeader>
          <CtraderAccountStep
            onBack={() => setStep({ kind: 'platform' })}
            onPick={(account) => setStep({ kind: 'ctraderForm', account })}
          />
        </>
      )
    case 'ctraderForm':
      return (
        <>
          <AccountFormHeader title={f.title} />
          <AccountForm
            account={null}
            ctraderAccount={step.account}
            onBack={() => setStep({ kind: 'ctrader' })}
            onDone={onDone}
          />
        </>
      )
  }
}

function PlatformStep({ onChoose }: { onChoose: (platform: AccountPlatform) => void }) {
  return (
    <>
      <DialogHeader>
        <DialogTitle>{p.title}</DialogTitle>
        <DialogDescription>{p.description}</DialogDescription>
      </DialogHeader>
      <div role="group" aria-label={p.legend} className="grid gap-3 sm:grid-cols-2">
        <PlatformButton title={p.mt5} hint={p.mt5Hint} onClick={() => onChoose('mt5')} />
        <PlatformButton title={p.ctrader} hint={p.ctraderHint} onClick={() => onChoose('ctrader')} />
      </div>
      <DialogFooter>
        <DialogClose asChild>
          <Button type="button" variant="outline">
            {uk.common.cancel}
          </Button>
        </DialogClose>
      </DialogFooter>
    </>
  )
}

function PlatformButton({ title, hint, onClick }: { title: string; hint: string; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex flex-col gap-1 rounded-tile border border-line bg-card px-4 py-3 text-left hover:bg-accent/60 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
    >
      <span className="text-sm font-semibold text-foreground">{title}</span>
      <span className="text-xs text-muted-foreground">{hint}</span>
    </button>
  )
}
