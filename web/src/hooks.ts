import { useState, useEffect, useCallback, useRef } from 'react'
import { api } from './lib'

export function useResource<T>(url: string | null, interval = 0) {
  const [data, setData] = useState<T | null>(null)
  const [loading, setLoading] = useState(!!url)
  const [error, setError] = useState('')
  const [tick, setTick] = useState(0)
  const reload = useCallback(() => setTick(t => t + 1), [])
  useEffect(() => {
    setData(null); setLoading(!!url); setError('')
  }, [url])
  useEffect(() => {
    if (!url) return
    const controller = new AbortController()
    let busy = false
    const load = async () => {
      if (busy) return
      busy = true
      try { const value = await api<T>(url, { signal: controller.signal }); if (!controller.signal.aborted) { setData(value); setError('') } }
      catch (e) { if (!controller.signal.aborted) setError((e as Error).message) }
      finally { busy = false; if (!controller.signal.aborted) setLoading(false) }
    }
    void load()
    const timer = interval ? setInterval(load, interval) : undefined
    return () => { controller.abort(); clearInterval(timer) }
  }, [url, tick, interval])
  return { data, loading, error, reload, setData }
}
export function useQuery() {
  const [search, setSearch] = useState(window.location.search)
  useEffect(() => {
    const handler = () => setSearch(window.location.search)
    window.addEventListener('popstate', handler)
    return () => window.removeEventListener('popstate', handler)
  }, [])
  const update = useCallback((changes: Record<string, string | null>, replace = false) => {
    const params = new URLSearchParams(window.location.search)
    Object.entries(changes).forEach(([key, value]) => value ? params.set(key, value) : params.delete(key))
    const value = `?${params.toString()}`
    window.history[replace ? 'replaceState' : 'pushState']({}, '', value)
    setSearch(value)
  }, [])
  return { query: new URLSearchParams(search), update }
}
export function useDebounced(value: string, delay = 250) {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => { const timer = setTimeout(() => setDebounced(value), delay); return () => clearTimeout(timer) }, [value, delay])
  return debounced
}
export function useDirtyGuard(dirty: boolean) {
  const ref = useRef(dirty); ref.current = dirty
  useEffect(() => {
    const handler = (e: BeforeUnloadEvent) => { if (ref.current) { e.preventDefault(); e.returnValue = '' } }
    window.addEventListener('beforeunload', handler)
    return () => window.removeEventListener('beforeunload', handler)
  }, [])
}
