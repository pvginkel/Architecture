import { ChevronDown, ChevronUp, Search, X } from "lucide-react";
import { useState, type ReactNode } from "react";
import type { FilterGroupModel, FilterOption } from "./groups";

// A group with this many options gets the large-group treatment (search +
// selected-summary + nested scroll + Select All); fewer is a plain list.
const LARGE_GROUP_THRESHOLD = 8;

interface FilterGroupProps {
  group: FilterGroupModel;
  selected: Set<string>;
  collapsed: boolean;
  onToggleCollapse: () => void;
  onToggleOption: (value: string) => void;
  onSelectAll: (values: string[]) => void;
  optionIcon?: (value: string) => ReactNode;
}

function OptionRow({
  option,
  checked,
  icon,
  onToggle,
}: {
  option: FilterOption;
  checked: boolean;
  icon?: ReactNode;
  onToggle: () => void;
}) {
  return (
    <label className="filter-option">
      <input type="checkbox" checked={checked} onChange={onToggle} />
      {icon ? (
        <span className="filter-option__icon" aria-hidden="true">
          {icon}
        </span>
      ) : null}
      <span className="filter-option__label">{option.label}</span>
      <span className="filter-option__count">{option.count}</span>
    </label>
  );
}

export function FilterGroup({
  group,
  selected,
  collapsed,
  onToggleCollapse,
  onToggleOption,
  onSelectAll,
  optionIcon,
}: FilterGroupProps) {
  const [search, setSearch] = useState("");
  const [selectedOpen, setSelectedOpen] = useState(false);

  const isLarge = group.options.length >= LARGE_GROUP_THRESHOLD;
  const term = search.trim().toLowerCase();
  const visibleOptions =
    isLarge && term
      ? group.options.filter((option) => option.label.toLowerCase().includes(term))
      : group.options;
  const selectedOptions = group.options.filter((option) => selected.has(option.value));

  const renderRow = (option: FilterOption) => (
    <OptionRow
      key={option.value}
      option={option}
      checked={selected.has(option.value)}
      icon={optionIcon?.(option.value)}
      onToggle={() => onToggleOption(option.value)}
    />
  );

  return (
    <section className="filter-group">
      <button
        className="filter-group__header"
        onClick={onToggleCollapse}
        aria-expanded={!collapsed}
        type="button"
      >
        <span>{group.title}</span>
        <span className="filter-group__chevron" aria-hidden="true">
          {collapsed ? <ChevronDown size={16} /> : <ChevronUp size={16} />}
        </span>
      </button>

      {collapsed ? null : isLarge ? (
        <div className="filter-group__body filter-group__body--large">
          <label className="filter-group__search">
            <Search size={13} />
            <input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search"
            />
            {search ? (
              <button
                type="button"
                className="search-box__clear"
                onClick={() => setSearch("")}
                aria-label="Clear search"
              >
                <X size={13} />
              </button>
            ) : null}
          </label>

          <button
            className="filter-group__selected"
            onClick={() => setSelectedOpen((open) => !open)}
            type="button"
          >
            <span>Selected ({selectedOptions.length})</span>
            <span className="filter-group__chevron" aria-hidden="true">
              {selectedOpen ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
            </span>
          </button>
          {selectedOpen && selectedOptions.length > 0 ? (
            <div className="filter-group__selected-list">{selectedOptions.map(renderRow)}</div>
          ) : null}

          <div className="filter-group__scroll">
            {visibleOptions.length > 0 ? (
              visibleOptions.map(renderRow)
            ) : (
              <p className="filter-group__empty">No matches</p>
            )}
          </div>

          <button
            className="filter-group__selectall"
            onClick={() => onSelectAll(visibleOptions.map((option) => option.value))}
            disabled={visibleOptions.length === 0}
            type="button"
          >
            Select All
          </button>
        </div>
      ) : (
        <div className="filter-group__body">{group.options.map(renderRow)}</div>
      )}
    </section>
  );
}
