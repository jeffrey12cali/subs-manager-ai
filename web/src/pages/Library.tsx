import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { getMovies, triggerScan } from "@/api/client";
import type { MovieSummary } from "@/api/client";
import { SubBadges } from "@/components/LangBadge";
import { JobStatusBadge } from "@/components/JobStatus";
import { MultiSelectFilter } from "@/components/MultiSelectFilter";

function movieLanguages(m: MovieSummary): string[] {
  return Array.from(new Set([...m.external_sub_languages, ...m.embedded_sub_languages]));
}

export default function Library() {
  const qc = useQueryClient();
  const [missingSubs, setMissingSubs] = useState(false);
  const [scanJobIds, setScanJobIds] = useState<number[]>([]);
  const [search, setSearch] = useState("");
  const [videoFormats, setVideoFormats] = useState<Set<string>>(new Set());
  const [subFormats, setSubFormats] = useState<Set<string>>(new Set());
  const [languages, setLanguages] = useState<Set<string>>(new Set());

  const { data: movies = [], isLoading, error } = useQuery({
    queryKey: ["movies", missingSubs],
    queryFn: () => getMovies(missingSubs),
  });

  const scan = useMutation({
    mutationFn: triggerScan,
    onSuccess: (res) => {
      setScanJobIds(res.job_ids);
      setTimeout(() => qc.invalidateQueries({ queryKey: ["movies"] }), 3000);
    },
  });

  const videoFormatOptions = useMemo(
    () => Array.from(new Set(movies.flatMap((m) => m.video_formats))).sort(),
    [movies],
  );
  const subFormatOptions = useMemo(
    () => Array.from(new Set(movies.flatMap((m) => m.subtitle_formats))).sort(),
    [movies],
  );
  const languageOptions = useMemo(
    () => Array.from(new Set(movies.flatMap(movieLanguages))).sort(),
    [movies],
  );

  const filtersActive =
    search.trim() !== "" || videoFormats.size > 0 || subFormats.size > 0 || languages.size > 0;

  const filteredMovies = useMemo(() => {
    const q = search.trim().toLowerCase();
    return movies.filter((m) => {
      if (q && !m.title.toLowerCase().includes(q) && !String(m.year ?? "").includes(q)) {
        return false;
      }
      if (videoFormats.size > 0 && !m.video_formats.some((f) => videoFormats.has(f))) {
        return false;
      }
      if (subFormats.size > 0 && !m.subtitle_formats.some((f) => subFormats.has(f))) {
        return false;
      }
      if (languages.size > 0 && !movieLanguages(m).some((l) => languages.has(l))) {
        return false;
      }
      return true;
    });
  }, [movies, search, videoFormats, subFormats, languages]);

  return (
    <div className="p-6 space-y-4">
      {/* toolbar */}
      <div className="flex items-center gap-4">
        <h1 className="text-xl font-bold flex-1">Library</h1>

        <label className="flex items-center gap-2 text-sm text-neutral-400 cursor-pointer select-none">
          <input
            type="checkbox"
            className="accent-blue-500"
            checked={missingSubs}
            onChange={(e) => setMissingSubs(e.target.checked)}
          />
          Missing subs only
        </label>

        <button
          onClick={() => scan.mutate()}
          disabled={scan.isPending}
          className="rounded bg-blue-600 px-3 py-1.5 text-sm font-medium hover:bg-blue-500 disabled:opacity-50"
        >
          {scan.isPending ? "Scanning…" : "Scan now"}
        </button>
      </div>

      {/* search + filters */}
      <div className="flex flex-wrap items-center gap-2">
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search titles…"
          className="min-w-[12rem] flex-1 rounded border border-neutral-700 bg-neutral-800 px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-blue-500"
        />
        <MultiSelectFilter
          label="Video format"
          options={videoFormatOptions}
          selected={videoFormats}
          onChange={setVideoFormats}
        />
        <MultiSelectFilter
          label="Subtitle format"
          options={subFormatOptions}
          selected={subFormats}
          onChange={setSubFormats}
        />
        <MultiSelectFilter
          label="Language"
          options={languageOptions}
          selected={languages}
          onChange={setLanguages}
        />
        {filtersActive && (
          <button
            onClick={() => {
              setSearch("");
              setVideoFormats(new Set());
              setSubFormats(new Set());
              setLanguages(new Set());
            }}
            className="rounded px-2 py-1.5 text-sm text-neutral-400 hover:text-neutral-200"
          >
            Clear all
          </button>
        )}
      </div>

      {/* scan job status pills */}
      {scanJobIds.length > 0 && (
        <div className="flex gap-2 text-sm text-neutral-400">
          Scan jobs:
          {scanJobIds.map((id) => (
            <span key={id} className="flex items-center gap-1">
              #{id} <JobStatusBadge jobId={id} />
            </span>
          ))}
        </div>
      )}

      {isLoading && <p className="text-neutral-400">Loading…</p>}
      {error && <p className="text-red-400">Failed to load library.</p>}

      {!isLoading && movies.length === 0 && (
        <div className="rounded border border-dashed border-neutral-700 p-12 text-center text-neutral-500">
          {missingSubs
            ? "All movies have subtitles."
            : "Library is empty. Add a library root and click Scan now."}
        </div>
      )}

      {!isLoading && movies.length > 0 && filteredMovies.length === 0 && (
        <div className="rounded border border-dashed border-neutral-700 p-12 text-center text-neutral-500">
          No movies match your search or filters.
        </div>
      )}

      {/* grid */}
      <ul className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
        {filteredMovies.map((m) => (
          <li key={m.id}>
            <Link
              to={`/movies/${m.id}`}
              className="block rounded border border-neutral-800 bg-neutral-900 p-4 hover:border-neutral-600 transition-colors"
            >
              <div className="flex items-start justify-between gap-2">
                <div>
                  <p className="font-medium leading-tight">{m.title}</p>
                  {m.year && (
                    <p className="text-sm text-neutral-500">{m.year}</p>
                  )}
                </div>
                <span className="shrink-0 text-xs text-neutral-600">
                  {m.video_count} file{m.video_count !== 1 ? "s" : ""}
                </span>
              </div>
              <div className="mt-2">
                <SubBadges
                  languages={m.external_sub_languages}
                  unknownCount={m.unknown_sub_count}
                  embeddedLanguages={m.embedded_sub_languages}
                />
              </div>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
