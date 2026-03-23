import { useState, useEffect, useRef, useCallback } from 'react'

/*
  useApi — a custom React hook for fetching data from the Flask backend.

  WHAT IS A HOOK?
  In React, a "hook" is a reusable function that manages some kind of
  state or side effect. This hook manages: fetching JSON from a URL,
  tracking loading/error state, and optionally auto-refreshing.

  WHY A CUSTOM HOOK?
  Every page in the app needs to fetch data from the API. Instead of
  writing fetch() + useState + useEffect in every component, we write
  it once here and reuse it everywhere.

  Usage:
    const { data, loading, error } = useApi('/api/status', { refreshInterval: 10000 })
*/

export function useApi(url, options = {}) {
  const { refreshInterval = null, enabled = true } = options
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const intervalRef = useRef(null)

  const fetchData = useCallback(async () => {
    if (!enabled) return

    try {
      const response = await fetch(url)
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`)
      }
      const json = await response.json()
      setData(json)
      setError(null)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [url, enabled])

  // Fetch on mount and when URL changes.
  useEffect(() => {
    setLoading(true)
    fetchData()
  }, [fetchData])

  // Set up auto-refresh if requested.
  useEffect(() => {
    if (refreshInterval && enabled) {
      intervalRef.current = setInterval(fetchData, refreshInterval)
      return () => clearInterval(intervalRef.current)
    }
  }, [fetchData, refreshInterval, enabled])

  return { data, loading, error, refetch: fetchData }
}
