import { Search, X, type LucideProps } from "lucide-react";
import { useEffect, useRef, useState, type ComponentType, type ReactNode } from "react";
import { KIND_ICON, LAYER_ACCENT, VIEW_ICON } from "../theme";
import type { ElementKind, LayerId } from "../generated/vocab";
import type { ViewDefinition } from "../data/manifest";
import { FilterGroup } from "./FilterGroup";
import type { FilterGroupModel } from "./groups";
import { KIND_GROUP, LAYER_GROUP, type FilterState } from "./state";

interface FilterRailProps {
  groups: FilterGroupModel[];
  filterState: FilterState;
  collapsed: Record<string, boolean>;
  searchTerm: string;
  activeView: ViewDefinition | null;
  onSearch: (term: string) => void;
  onToggleCollapse: (groupId: string) => void;
  onToggleOption: (groupId: string, value: string) => void;
  onSelectAll: (groupId: string, values: string[]) => void;
  onClearAll: (groupId: string, values: string[]) => void;
  onClear: () => void;
}

// Element-type rows carry the kind glyph; Layer rows carry the layer colour
// swatch. Other groups are label + count only.
function optionIconFor(groupId: string): ((value: string) => ReactNode) | undefined {
  if (groupId === KIND_GROUP) {
    return (value) => {
      const Icon = KIND_ICON[value as ElementKind] as ComponentType<LucideProps> | undefined;
      return Icon ? <Icon size={14} /> : null;
    };
  }
  if (groupId === LAYER_GROUP) {
    return (value) => (
      <span className="filter-swatch" style={{ background: LAYER_ACCENT[value as LayerId] }} />
    );
  }
  return undefined;
}

const EMPTY_SELECTION = new Set<string>();

// Element search drives a full relayout, so propagation is debounced hard:
// the input reflects keystrokes instantly, but the searchTerm that recomputes
// the graph only fires after the user pauses.
const SEARCH_DEBOUNCE_MS = 1000;

export function FilterRail({
  groups,
  filterState,
  collapsed,
  searchTerm,
  activeView,
  onSearch,
  onToggleCollapse,
  onToggleOption,
  onSelectAll,
  onClearAll,
  onClear,
}: FilterRailProps) {
  // Local, instantly-updated mirror of the search box; the debounced timer
  // propagates it to onSearch (which drives the relayout).
  const [localSearch, setLocalSearch] = useState(searchTerm);
  const searchTimer = useRef<number | undefined>(undefined);

  // Re-sync when searchTerm changes from outside this box (clear-all, view
  // switch) rather than from typing.
  useEffect(() => {
    setLocalSearch(searchTerm);
  }, [searchTerm]);

  useEffect(() => () => window.clearTimeout(searchTimer.current), []);

  const handleSearchChange = (value: string) => {
    setLocalSearch(value);
    window.clearTimeout(searchTimer.current);
    searchTimer.current = window.setTimeout(() => onSearch(value), SEARCH_DEBOUNCE_MS);
  };

  const handleSearchClear = () => {
    window.clearTimeout(searchTimer.current);
    setLocalSearch("");
    onSearch("");
  };

  // Mirror ViewTabs' icon resolution: the name is schema-validated data, but an
  // unrecognised one fails loudly here rather than rendering a blank panel.
  const ViewIcon = activeView ? VIEW_ICON[activeView.icon] : undefined;
  if (activeView && !ViewIcon) {
    throw new Error(
      `view '${activeView.id}': icon '${activeView.icon}' is not in VIEW_ICON (theme.ts)`,
    );
  }

  return (
    <aside className="filter-rail">
      <div className="filter-rail__search">
        <label className="search-box">
          <Search size={16} />
          <input
            value={localSearch}
            onChange={(event) => handleSearchChange(event.target.value)}
            placeholder="Search elements"
          />
          {localSearch ? (
            <button
              type="button"
              className="search-box__clear"
              onClick={handleSearchClear}
              aria-label="Clear search"
            >
              <X size={14} />
            </button>
          ) : null}
        </label>
      </div>

      {activeView && ViewIcon ? (
        <div className="filter-rail__description">
          <div className="filter-rail__description-head">
            <ViewIcon size={15} strokeWidth={2.2} aria-hidden />
            <span className="filter-rail__description-label">{activeView.label}</span>
          </div>
          <p className="filter-rail__description-text">{activeView.description}</p>
        </div>
      ) : null}

      <div className="filter-rail__groups">
        {groups.map((group) => (
          <FilterGroup
            key={group.id}
            group={group}
            selected={filterState.get(group.id) ?? EMPTY_SELECTION}
            collapsed={collapsed[group.id] ?? false}
            onToggleCollapse={() => onToggleCollapse(group.id)}
            onToggleOption={(value) => onToggleOption(group.id, value)}
            onSelectAll={(values) => onSelectAll(group.id, values)}
            onClearAll={(values) => onClearAll(group.id, values)}
            optionIcon={optionIconFor(group.id)}
          />
        ))}
      </div>

      <div className="filter-rail__footer">
        <button className="filter-rail__clear" onClick={onClear} type="button">
          <X size={16} />
          Reset filters
        </button>
      </div>
    </aside>
  );
}
