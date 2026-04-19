import { clsx } from 'clsx'
import { useStore } from '../store'
import type { Product } from '../types'

const PRODUCTS: Array<{ id: Product; label: string; short: string }> = [
  { id: 'ASH_COATED_OSMIUM', label: 'Ash Coated Osmium', short: 'OSMIUM' },
  { id: 'INTARIAN_PEPPER_ROOT', label: 'Intarian Pepper Root', short: 'PEPPER' },
]

export function ProductToggle() {
  const { activeProduct, setActiveProduct } = useStore()

  return (
    <div className="flex flex-wrap gap-2">
      {PRODUCTS.map((product) => {
        const active = product.id === activeProduct
        return (
          <button
            key={product.id}
            onClick={() => setActiveProduct(product.id)}
            className={clsx(
              'rounded-lg px-4 py-3 text-left transition-all duration-500 ease-observatory',
              active ? 'signal-button' : 'subtle-button',
            )}
          >
            <div className="hud-label">{product.short}</div>
            <div className="mt-1 font-serif text-sm text-current">{product.label}</div>
          </button>
        )
      })}
    </div>
  )
}
