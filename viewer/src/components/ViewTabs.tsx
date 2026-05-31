import type { ViewDefinition } from "../data/manifest";

interface ViewTabsProps {
  views: ViewDefinition[];
  activeViewId: string | null;
  onSelect: (viewId: string) => void;
}

// The strip of curated-view tabs across the top of the canvas. List order is
// authoritative (Landscape first, Everything last) — the collector emits them
// already ordered, so this just renders them in sequence.
export function ViewTabs({ views, activeViewId, onSelect }: ViewTabsProps) {
  return (
    <nav className="view-tabs" aria-label="Views">
      {views.map((view) => (
        <button
          key={view.id}
          type="button"
          className={`view-tab${view.id === activeViewId ? " view-tab--active" : ""}`}
          aria-current={view.id === activeViewId}
          title={view.description}
          onClick={() => onSelect(view.id)}
        >
          {view.label}
        </button>
      ))}
    </nav>
  );
}
