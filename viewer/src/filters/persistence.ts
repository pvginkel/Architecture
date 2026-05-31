// Per-manifest collapsed-state persistence. Keyed by a hash of the ?src URL so
// different manifests remember their own collapse state independently. Only
// collapsed state lives here — selections are owned by views (Plan 4).

const STORAGE_PREFIX = "arch-viewer:collapsed:";

/** FNV-1a — a small stable string hash, no dependency. */
function hashSrc(src: string): string {
  let hash = 0x811c9dc5;
  for (let i = 0; i < src.length; i++) {
    hash ^= src.charCodeAt(i);
    hash = Math.imul(hash, 0x01000193);
  }
  return (hash >>> 0).toString(36);
}

function keyFor(src: string): string {
  return `${STORAGE_PREFIX}${hashSrc(src)}`;
}

export type CollapsedState = Record<string, boolean>;

export function loadCollapsed(src: string): CollapsedState {
  const raw = window.localStorage.getItem(keyFor(src));
  if (raw === null) {
    return {};
  }
  return JSON.parse(raw) as CollapsedState;
}

export function saveCollapsed(src: string, state: CollapsedState): void {
  window.localStorage.setItem(keyFor(src), JSON.stringify(state));
}
