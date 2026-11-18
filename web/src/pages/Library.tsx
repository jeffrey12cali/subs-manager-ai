import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { getLibraries, getMovies, getSeries, triggerScan } from "@/api/client";
import type { MovieSummary, SeriesSummary } from "@/api/client";
import { SubBadges } from "@/components/LangBadge";
import { JobStatusBadge } from "@/components/JobStatus";
import { MultiSelectFilter } from "@/components/MultiSelectFilter";

function movieLanguages(m: MovieSummary): string[] {
  return Array.from(new Set([...m.external_sub_languages, ...m.embedded_sub_languages]));
}

function seriesLanguages(s: SeriesSummary): string[] {
  return Array.from(new Set([...s.external_sub_languages, ...s.embedded_sub_languages]));
}

export default function Library() {
  const qc = useQueryClient();
  const [searchParams, setSearchParams] = useSearchParams();
  const [missingSubs, setMissingSubs] = useState(false);
  const [scanJobIds, setScanJobIds] = useState<number[]>([]);
  const [search, setSearch] = useState("");
  const [videoFormats, setVideoFormats] = useState<Set<string>>(new Set());
  const [subFormats, setSubFormats] = useState<Set<string>>(new Set());
  const [languages, setLanguages] = useState<Set<string>>(new Set());

  const { data: libraries = [], isLoading: librariesLoading } = useQuery({
    queryKey: ["libraries"],
    queryFn: getLibraries,
  });

  const requestedId = searchParams.get("library");
  const activeLibrary =
    libraries.find((lib) => lib.id === requestedId) ?? libraries[0] ?? null;
  const isMovieLibrary = activeLibrary?.type === "movies";

  useEffect(() => {
    if (activeLibrary && requestedId !== activeLibrary.id) {
      setSearchParams({ library: activeLibrary.id }, { replace: true });
    }
  }, [activeLibrary, requestedId, setSearchParams]);

  const { data: movies = [], isLoading: moviesLoading, error: moviesError } = useQuery({
    queryKey: ["movies", missingSubs, activeLibrary?.id],
    queryFn: () => getMovies(missingSubs, activeLibrary?.id),
    enabled: isMovieLibrary,
  });

  const { data: series = [], isLoading: seriesLoading, error: seriesError } = useQuery({
    queryKey: ["series", activeLibrary?.id],
    queryFn: () => getSeries(activeLibrary?.id),
    enabled: activeLibrary?.type === "series",
  });

  const scan = useMutation({
    mutationFn: (libraryId: string) => triggerScan(libraryId),
    onSuccess: (res) => {
      setScanJobIds(res.job_ids);
      setTimeout(() => {
        qc.invalidateQueries({ queryKey: ["movies"] });
        qc.invalidateQueries({ queryKey: ["series"] });
      }, 3000);
    },
  });

  const scanAll = useMutation({
    mutationFn: () => triggerScan(),
    onSuccess: (res) => {
      setScanJobIds(res.job_ids);
      setTimeout(() => {
        qc.invalidateQueries({ queryKey: ["movies"] });
        qc.invalidateQueries({ queryKey: ["series"] });
      }, 3000);
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
  const languageOptions = useMemo(() => {
    const values = isMovieLibrary
      ? movies.flatMap(movieLanguages)
      : series.flatMap(seriesLanguages);
    return Array.from(new Set(values)).sort();
  }, [movies, series, isMovieLibrary]);

  const filtersActive =
    search.trim() !== "" ||
    languages.size > 0 ||
    (isMovieLibrary && (videoFormats.size > 0 || subFormats.size > 0));

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

  const filteredSeries = useMemo(() => {
    const q = search.trim().toLowerCase();
    return series.filter((s) => {
      if (q && !s.title.toLowerCase().includes(q) && !String(s.year ?? "").includes(q)) {
        return false;
      }
      if (languages.size > 0 && !seriesLanguages(s).some((l) => languages.has(l))) {
        return false;
      }
      return true;
    });
  }, [series, search, languages]);

  const isLoading = librariesLoading || moviesLoading || seriesLoading;
  const error = moviesError || seriesError;
  const items = isMovieLibrary ? filteredMovies : filteredSeries;
  const totalItems = isMovieLibrary ? movies.length : series.length;
  const libraryType = activeLibrary?.type === "series" ? "series" : "movies";

  function selectLibrary(libraryId: string) {
    setSearchParams({ library: libraryId });
  }

  return (
    <div className="p-6 space-y-4">
      {/* toolbar */}
      <div className="flex flex-wrap items-center gap-4">
        <h1 className="text-xl font-bold">Library</h1>

        <select
          value={activeLibrary?.id ?? ""}
          onChange={(e) => selectLibrary(e.target.value)}
          className="rounded border border-neutral-700 bg-neutral-800 px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-blue-500"
          aria-label="Library"
        >
          {libraries.map((lib) => (
            <option key={lib.id} value={lib.id}>
              {lib.name} ({lib.type})
            </option>
          ))}
        </select>

        <span className="text-xs text-neutral-500">
          {activeLibrary ? `${totalItems} ${libraryType === "series" ? "series" : "items"}` : ""}
        </span>

        {isMovieLibrary && (
          <label className="flex items-center gap-2 text-sm text-neutral-400 cursor-pointer select-none">
            <input
              type="checkbox"
              className="accent-blue-500"
              checked={missingSubs}
              onChange={(e) => setMissingSubs(e.target.checked)}
            />
            Missing subs only
          </label>
        )}

        <div className="ml-auto flex items-center gap-2">
          <button
            onClick={() => activeLibrary && scan.mutate(activeLibrary.id)}
            disabled={!activeLibrary || scan.isPending || scanAll.isPending}
            className="rounded bg-blue-600 px-3 py-1.5 text-sm font-medium hover:bg-blue-500 disabled:opacity-50"
          >
            {scan.isPending ? "Scanning…" : "Scan now"}
          </button>
          <button
            onClick={() => scanAll.mutate()}
            disabled={scanAll.isPending || scan.isPending || libraries.length === 0}
            className="rounded border border-neutral-700 px-3 py-1.5 text-sm font-medium hover:bg-neutral-800 disabled:opacity-50"
          >
            {scanAll.isPending ? "Scanning…" : "Scan all"}
          </button>
        </div>
      </div>

      {/* search + filters */}
      <div className="flex flex-wrap items-center gap-2">
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder={isMovieLibrary ? "Search movies…" : "Search series…"}
          className="min-w-[12rem] flex-1 rounded border border-neutral-700 bg-neutral-800 px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-blue-500"
        />
        {isMovieLibrary && (
          <>
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
          </>
        )}
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
        <div className="flex flex-wrap gap-2 text-sm text-neutral-400">
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

      {!isLoading && libraries.length === 0 && (
        <div className="rounded border border-dashed border-neutral-700 p-12 text-center text-neutral-500">
          No libraries are configured. Add `LIBRARIES` to `.env`, restart the
          API, and click Scan all.
        </div>
      )}

      {!isLoading && libraries.length > 0 && totalItems === 0 && (
        <div className="rounded border border-dashed border-neutral-700 p-12 text-center text-neutral-500">
          {isMovieLibrary
            ? missingSubs
              ? "All movies have subtitles."
              : "This library is empty. Click Scan now to scan it."
            : "No series found in this library. Click Scan now to scan it."}
        </div>
      )}

      {!isLoading && totalItems > 0 && items.length === 0 && (
        <div className="rounded border border-dashed border-neutral-700 p-12 text-center text-neutral-500">
          No {isMovieLibrary ? "movies" : "series"} match your search or filters.
        </div>
      )}

      {/* grid */}
      <ul className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
        {isMovieLibrary
          ? filteredMovies.map((m) => (
              <li key={m.id}>
                <Link
                  to={`/movies/${m.id}`}
                  className="block rounded border border-neutral-800 bg-neutral-900 p-4 hover:border-neutral-600 transition-colors"
                >
                  <div className="flex items-start justify-between gap-2">
                    <div>
                      <p className="font-medium leading-tight">{m.title}</p>
                      {m.year && <p className="text-sm text-neutral-500">{m.year}</p>}
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
            ))
          : filteredSeries.map((s) => (
              <li key={s.id}>
                <Link
                  to={`/series/${s.id}`}
                  className="block rounded border border-neutral-800 bg-neutral-900 p-4 hover:border-neutral-600 transition-colors"
                >
                  <div className="flex items-start justify-between gap-2">
                    <div>
                      <p className="font-medium leading-tight">{s.title}</p>
                      {s.year && <p className="text-sm text-neutral-500">{s.year}</p>}
                    </div>
                    <span className="shrink-0 text-xs text-neutral-600">
                      {s.episode_count} episode{s.episode_count !== 1 ? "s" : ""}
                    </span>
                  </div>
                  <div className="mt-2">
                    <SubBadges
                      languages={s.external_sub_languages}
                      unknownCount={s.unknown_sub_count}
                      embeddedLanguages={s.embedded_sub_languages}
                    />
                  </div>
                </Link>
              </li>
            ))}
      </ul>
    </div>
  );
}
