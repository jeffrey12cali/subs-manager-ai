/** Small coloured pill showing a BCP-47 language code. */
export function LangBadge({
  lang,
  variant = "external",
}: {
  lang: string;
  variant?: "external" | "embedded";
}) {
  if (variant === "embedded") {
    return (
      <span className="inline-block rounded bg-blue-900 px-1.5 py-0.5 text-xs font-mono uppercase text-blue-200 ring-1 ring-blue-700">
        {lang} <span className="text-[9px] opacity-70">emb</span>
      </span>
    );
  }
  return (
    <span className="inline-block rounded bg-neutral-700 px-1.5 py-0.5 text-xs font-mono uppercase text-neutral-200">
      {lang}
    </span>
  );
}

export function SubBadges({
  languages,
  unknownCount = 0,
  embeddedLanguages = [],
}: {
  languages: string[];
  unknownCount?: number;
  embeddedLanguages?: string[];
}) {
  const hasAnything = languages.length > 0 || unknownCount > 0 || embeddedLanguages.length > 0;

  if (!hasAnything) {
    return <span className="text-xs text-red-400">no subs</span>;
  }
  return (
    <div className="flex flex-wrap gap-1">
      {languages.map((l) => (
        <LangBadge key={`ext-${l}`} lang={l} variant="external" />
      ))}
      {unknownCount > 0 && (
        <span className="inline-block rounded bg-yellow-900 px-1.5 py-0.5 text-xs font-mono uppercase text-yellow-200 ring-1 ring-yellow-700">
          UN
        </span>
      )}
      {embeddedLanguages.map((l) => (
        <LangBadge key={`emb-${l}`} lang={l} variant="embedded" />
      ))}
    </div>
  );
}
