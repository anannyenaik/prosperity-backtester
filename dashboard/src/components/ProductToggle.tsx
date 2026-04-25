import { clsx } from 'clsx'
import { useStore } from '../store'
import { productGroups, productLabel, productShortLabel } from '../lib/products'

export function ProductToggle() {
  const { activeProduct, setActiveProduct, getActiveRun } = useStore()
  const payload = getActiveRun()?.payload
  const groups = productGroups(payload)

  if (!groups.length) return null

  return (
    <div className="space-y-2">
      {groups.map((group) => (
        <div key={group.id}>
          {groups.length > 1 && (
            <div className="hud-label mb-2 flex items-center gap-2 text-muted">
              <span>{group.label}</span>
              <span className="text-accent/70">{group.products.length}</span>
            </div>
          )}
          <div className={clsx('flex flex-wrap', group.products.length > 4 ? 'gap-1.5' : 'gap-2')}>
            {group.products.map((product) => {
              const active = product === activeProduct
              const compact = group.products.length > 4
              const strike = payload?.productMetadata?.[product]?.strike
              const secondaryLabel = compact && typeof strike === 'number'
                ? `K ${strike.toLocaleString()}`
                : productLabel(payload, product)
              return (
                <button
                  key={product}
                  onClick={() => setActiveProduct(product)}
                  className={clsx(
                    'rounded-lg text-left transition-all duration-500 ease-observatory',
                    compact ? 'min-w-[82px] px-3 py-2' : 'px-4 py-3',
                    active ? 'signal-button' : 'subtle-button',
                  )}
                >
                  <div className="hud-label">{productShortLabel(payload, product)}</div>
                  <div className={clsx('mt-1 font-serif text-current', compact ? 'text-xs' : 'text-sm')}>
                    {secondaryLabel}
                  </div>
                </button>
              )
            })}
          </div>
        </div>
      ))}
    </div>
  )
}
