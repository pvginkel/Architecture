import { ChevronLeft, ChevronRight } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
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
//
// The strip never wraps; once the tabs outgrow the canvas width it scrolls
// horizontally, with a chevron at each end to nudge it. Each chevron shows only
// when there is room to scroll that way (so a wide canvas shows neither), and
// the active tab is kept in view when it changes.
export function ViewTabs({ views, activeViewId, onSelect }: ViewTabsProps) {
  const stripRef = useRef<HTMLDivElement>(null);
  const [canScroll, setCanScroll] = useState({ left: false, right: false });

  const sync = useCallback(() => {
    const el = stripRef.current;
    if (!el) {
      return;
    }
    const max = el.scrollWidth - el.clientWidth;
    setCanScroll({
      left: el.scrollLeft > 1,
      right: el.scrollLeft < max - 1,
    });
  }, []);

  // Recompute the scroll affordances on scroll and whenever the strip resizes
  // (window resize, rail collapse) or the view set changes.
  useEffect(() => {
    const el = stripRef.current;
    if (!el) {
      return;
    }
    sync();
    el.addEventListener("scroll", sync, { passive: true });
    const observer = new ResizeObserver(sync);
    observer.observe(el);
    return () => {
      el.removeEventListener("scroll", sync);
      observer.disconnect();
    };
  }, [sync, views]);

  // Bring the active tab into view when it changes from elsewhere (parent
  // bridge, restored selection) so the current view is never left off-screen.
  useEffect(() => {
    if (!activeViewId) {
      return;
    }
    stripRef.current
      ?.querySelector(`[data-view-id="${activeViewId}"]`)
      ?.scrollIntoView({ inline: "nearest", block: "nearest" });
  }, [activeViewId]);

  const nudge = useCallback((direction: 1 | -1) => {
    const el = stripRef.current;
    if (!el) {
      return;
    }
    el.scrollBy({ left: direction * el.clientWidth * 0.7, behavior: "smooth" });
  }, []);

  return (
    <nav className="view-tabs" aria-label="Views">
      {canScroll.left ? (
        <button
          type="button"
          className="view-tabs__scroll view-tabs__scroll--left"
          aria-label="Scroll views left"
          onClick={() => nudge(-1)}
        >
          <ChevronLeft size={16} strokeWidth={2.4} aria-hidden />
        </button>
      ) : null}
      <div className="view-tabs__strip" ref={stripRef}>
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
              data-view-id={view.id}
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
      </div>
      {canScroll.right ? (
        <button
          type="button"
          className="view-tabs__scroll view-tabs__scroll--right"
          aria-label="Scroll views right"
          onClick={() => nudge(1)}
        >
          <ChevronRight size={16} strokeWidth={2.4} aria-hidden />
        </button>
      ) : null}
    </nav>
  );
}
