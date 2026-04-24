import { create } from 'zustand'
import type { DashboardPayload, LoadedRun, Product, TabId } from './types'
import { normaliseDashboardPayload } from './lib/bundles'
import { availableProducts } from './lib/products'

interface DashboardStore {
  runs: LoadedRun[]
  activeRunId: string | null
  compareRunId: string | null
  activeTab: TabId
  activeProduct: Product
  sampleRunName: string | null
  timeWindow: 'all' | 'start' | 'middle' | 'end'
  serverRuns: ServerRunMeta[]

  loadRun: (payload: DashboardPayload, fileName: string) => void
  setActiveRun: (id: string) => void
  setCompareRun: (id: string | null) => void
  setActiveTab: (tab: TabId) => void
  setActiveProduct: (product: Product) => void
  setSampleRun: (name: string | null) => void
  setTimeWindow: (w: 'all' | 'start' | 'middle' | 'end') => void
  removeRun: (id: string) => void
  setServerRuns: (runs: ServerRunMeta[]) => void
  getActiveRun: () => LoadedRun | null
  getCompareRun: () => LoadedRun | null
}

export interface ServerRunMeta {
  path: string
  name: string
  type: string
  profile?: string | null
  createdAt: string | null
  finalPnl: number | null
  sizeBytes?: number | null
  dashboardSizeBytes?: number | null
  fileCount?: number | null
  workflowTier?: string | null
  engineBackend?: string | null
  monteCarloBackend?: string | null
  parallelism?: string | null
  workerCount?: number | null
  gitCommit?: string | null
  gitDirty?: boolean | null
  source?: string | null
  workspaceName?: string | null
  workspaceSourceCount?: number | null
  workspaceSectionsPresent?: string[] | null
  workspaceSectionsMissing?: string[] | null
}

export const useStore = create<DashboardStore>((set, get) => ({
  runs: [],
  activeRunId: null,
  compareRunId: null,
  activeTab: 'overview',
  activeProduct: 'ASH_COATED_OSMIUM',
  sampleRunName: null,
  timeWindow: 'all',
  serverRuns: [],

  loadRun: (payload, fileName) => {
    const normalisedPayload = normaliseDashboardPayload(payload)
    const name = normalisedPayload.meta?.runName || fileName.replace(/\.json$/, '')
    const id = `${name}_${Date.now()}`
    const run: LoadedRun = { id, name, fileName, payload: normalisedPayload }
    set((state) => {
      const existing = state.runs.findIndex((r) => r.name === name)
      const replacedId = existing >= 0 ? state.runs[existing].id : null
      let newRuns: LoadedRun[]
      if (existing >= 0) {
        newRuns = [...state.runs]
        newRuns[existing] = run
      } else {
        newRuns = [...state.runs, run]
      }
      const previousActiveId =
        state.activeRunId && newRuns.some((r) => r.id === state.activeRunId)
          ? state.activeRunId
          : null
      const previousCompareId =
        state.compareRunId && newRuns.some((r) => r.id === state.compareRunId)
          ? state.compareRunId
          : null
      const activeRunId =
        state.activeRunId === replacedId
          ? id
          : previousActiveId ?? id
      const compareRunId =
        state.compareRunId === replacedId
          ? id
          : previousCompareId ?? (newRuns.length > 1 && activeRunId !== id ? id : null)
      const activeRun = newRuns.find((run) => run.id === activeRunId) ?? null
      const activeProducts = availableProducts(activeRun?.payload)
      const activeProduct =
        activeProducts.includes(state.activeProduct)
          ? state.activeProduct
          : activeProducts[0] ?? state.activeProduct
      return {
        runs: newRuns,
        activeRunId,
        compareRunId,
        activeProduct,
      }
    })
  },

  setActiveRun: (id) =>
    set((state) => {
      const target = state.runs.find((run) => run.id === id) ?? null
      const products = availableProducts(target?.payload)
      return {
        activeRunId: id,
        activeProduct: products.includes(state.activeProduct) ? state.activeProduct : products[0] ?? state.activeProduct,
      }
    }),
  setCompareRun: (id) => set({ compareRunId: id }),
  setActiveTab: (tab) => set({ activeTab: tab }),
  setActiveProduct: (product) => set({ activeProduct: product }),
  setSampleRun: (name) => set({ sampleRunName: name }),
  setTimeWindow: (w) => set({ timeWindow: w }),
  setServerRuns: (runs) => set({ serverRuns: runs }),

  removeRun: (id) =>
    set((state) => {
      const runs = state.runs.filter((r) => r.id !== id)
      const nextActiveRun =
        state.activeRunId === id
          ? (runs[0] ?? null)
          : (runs.find((run) => run.id === state.activeRunId) ?? runs[0] ?? null)
      const nextProducts = availableProducts(nextActiveRun?.payload)
      return {
        runs,
        activeRunId: state.activeRunId === id ? (runs[0]?.id ?? null) : state.activeRunId,
        compareRunId: state.compareRunId === id ? null : state.compareRunId,
        activeProduct: nextProducts.includes(state.activeProduct) ? state.activeProduct : nextProducts[0] ?? state.activeProduct,
      }
    }),

  getActiveRun: () => {
    const { runs, activeRunId } = get()
    return runs.find((r) => r.id === activeRunId) ?? runs[0] ?? null
  },

  getCompareRun: () => {
    const { runs, compareRunId } = get()
    return runs.find((r) => r.id === compareRunId) ?? null
  },
}))
