import { useEffect, useState } from "react";

/**
 * Debounces a changing value so downstream consumers (e.g. a list-filter
 * query) only fire after the user stops typing for `ms` milliseconds.
 *
 * Pair with TanStack Query's query keys for cheap incremental search.
 */
export function useDebouncedValue<T>(value: T, ms = 300): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const handle = window.setTimeout(() => setDebounced(value), ms);
    return () => window.clearTimeout(handle);
  }, [value, ms]);
  return debounced;
}
