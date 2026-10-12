import { useState } from "react";
import type { SetStateAction } from "react";

// Tab-scoped drafts: never mix sessions/events or overwrite them during polling.
export function useSessionValue<T>(key: string, fallback: T) {
  const read = (): T => {
    try {
      const value = sessionStorage.getItem(`spark:${key}`);
      return value === null ? fallback : (JSON.parse(value) as T);
    } catch {
      return fallback;
    }
  };
  const [stored, setStored] = useState(() => ({ key, value: read() }));
  const value = stored.key === key ? stored.value : read();
  const setValue = (next: SetStateAction<T>) => {
    const updated =
      typeof next === "function" ? (next as (previous: T) => T)(value) : next;
    try {
      sessionStorage.setItem(`spark:${key}`, JSON.stringify(updated));
    } catch {
      /* Storage may be disabled; editing remains available. */
    }
    setStored({ key, value: updated });
  };
  return [value, setValue] as const;
}
