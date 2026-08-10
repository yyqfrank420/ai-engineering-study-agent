const createInMemoryStorage = () => {
  const values = new Map<string, string>();

  return {
    getItem(key: string): string | null {
      return values.get(key) ?? null;
    },
    setItem(key: string, value: string): void {
      values.set(key, String(value));
    },
    removeItem(key: string): void {
      values.delete(key);
    },
    clear(): void {
      values.clear();
    },
    key(index: number): string | null {
      return Array.from(values.keys())[index] ?? null;
    },
    get length(): number {
      return values.size;
    },
  } as Storage;
};

if (typeof globalThis.localStorage === 'undefined') {
  const storage = createInMemoryStorage();
  Object.defineProperty(globalThis, 'localStorage', {
    configurable: true,
    value: storage,
    writable: true,
  });
}

if (typeof window !== 'undefined' && window.localStorage === undefined) {
  Object.defineProperty(window, 'localStorage', {
    configurable: true,
    value: globalThis.localStorage,
    writable: true,
  });
}
