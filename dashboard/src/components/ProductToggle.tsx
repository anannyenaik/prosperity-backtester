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
          {groups.length > 1 && <div className="hud-label mb-2 text-muted">{group.label}</div>}
          <div className="flex flex-wrap gap-2">
            {group.products.map((product) => {
              const active = product === activeProduct
              return (
                <button
                  key={product}
                  onClick={() => setActiveProduct(product)}
                  className={clsx(
                    'rounded-lg px-4 py-3 text-left transition-all duration-500 ease-observatory',
                    active ? 'signal-button' : 'subtle-button',
                  )}
                >
                  <div className="hud-label">{productShortLabel(payload, product)}</div>
                  <div className="mt-1 font-serif text-sm text-current">{productLabel(payload, product)}</div>
                </button>
              )
            })}
          </div>
        </div>
      ))}
    </div>
  )
}
