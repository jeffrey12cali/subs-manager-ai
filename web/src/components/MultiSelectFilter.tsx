interface Props {
  label: string;
  options: string[];
  selected: Set<string>;
  onChange: (next: Set<string>) => void;
}

/** Dropdown of checkboxes for multi-select filtering, e.g. by format or language. */
export function MultiSelectFilter({ label, options, selected, onChange }: Props) {
  if (options.length === 0) return null;

  const toggle = (opt: string) => {
    const next = new Set(selected);
    if (next.has(opt)) next.delete(opt);
    else next.add(opt);
    onChange(next);
  };

  return (
    <details className="relative">
      <summary className="flex list-none items-center gap-1.5 rounded border border-neutral-700 bg-neutral-800 px-3 py-1.5 text-sm cursor-pointer select-none hover:border-neutral-600">
        {label}
        {selected.size > 0 && (
          <span className="rounded-full bg-blue-600 px-1.5 text-xs font-medium leading-4">
            {selected.size}
          </span>
        )}
      </summary>
      <div className="absolute z-10 mt-1 min-w-[9rem] rounded border border-neutral-700 bg-neutral-900 p-2 shadow-xl">
        <div className="max-h-56 space-y-0.5 overflow-y-auto">
          {options.map((opt) => (
            <label
              key={opt}
              className="flex items-center gap-2 rounded px-1.5 py-1 text-sm font-mono uppercase cursor-pointer select-none hover:bg-neutral-800"
            >
              <input
                type="checkbox"
                className="accent-blue-500"
                checked={selected.has(opt)}
                onChange={() => toggle(opt)}
              />
              {opt}
            </label>
          ))}
        </div>
        {selected.size > 0 && (
          <button
            type="button"
            onClick={() => onChange(new Set())}
            className="mt-1 w-full rounded px-1.5 py-1 text-left text-xs text-neutral-400 hover:text-neutral-200"
          >
            Clear
          </button>
        )}
      </div>
    </details>
  );
}
