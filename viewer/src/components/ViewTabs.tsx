import type { ViewDefinition } from "../data/manifest";
import { VIEW_ICON } from "../theme";

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
      {views.map((view) => {
        // The icon name is data (authored in the view YAML, schema-validated as
        // PascalCase). Resolve it against VIEW_ICON, the explicit allow-list in
        // theme.ts; an unrecognised name fails loudly here rather than rendering
        // a blank tab — matching theme.ts, there is no default glyph.
        const Icon = VIEW_ICON[view.icon];
        if (!Icon) {
          throw new Error(
            `view '${view.id}': icon '${view.icon}' is not in VIEW_ICON (theme.ts)`,
          );
        }
        return (
          <button
            key={view.id}
            type="button"
            className={`view-tab${view.id === activeViewId ? " view-tab--active" : ""}`}
            aria-current={view.id === activeViewId}
            title={view.description}
            onClick={() => onSelect(view.id)}
          >
            <Icon size={15} strokeWidth={2.2} aria-hidden />
            {view.label}
          </button>
        );
      })}
    </nav>
  );
}
