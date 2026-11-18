import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { getSeriesDetail } from "@/api/client";
import type { EpisodeSummary } from "@/api/client";
import { SubBadges } from "@/components/LangBadge";

function EpisodeRow({ episode }: { episode: EpisodeSummary }) {
  return (
    <Link
      to={`/episodes/${episode.id}`}
      className="flex items-center gap-3 rounded border border-neutral-800 bg-neutral-900 px-3 py-2 hover:border-neutral-600 transition-colors"
    >
      <span className="w-24 shrink-0 font-mono text-xs text-neutral-400">
        {episode.episode_label ?? "—"}
      </span>
      <span className="min-w-0 flex-1 text-sm text-neutral-300">
        {episode.episode_number === null
          ? "Other video"
          : `Episode ${episode.episode_number}`}
      </span>
      <span className="shrink-0 text-xs text-neutral-600">
        {episode.video_count} file{episode.video_count !== 1 ? "s" : ""}
      </span>
      <span className="shrink-0">
        <SubBadges
          languages={episode.external_sub_languages}
          unknownCount={episode.unknown_sub_count}
          embeddedLanguages={episode.embedded_sub_languages}
        />
      </span>
    </Link>
  );
}

export default function Series() {
  const { id } = useParams<{ id: string }>();
  const seriesId = Number(id);

  const { data: series, isLoading, error } = useQuery({
    queryKey: ["series-detail", seriesId],
    queryFn: () => getSeriesDetail(seriesId),
    enabled: !isNaN(seriesId),
  });

  if (isLoading) return <div className="p-6 text-neutral-400">Loading…</div>;
  if (error || !series) return <div className="p-6 text-red-400">Series not found.</div>;

  const totalEpisodes = series.season_groups.reduce(
    (total, group) => total + group.episodes.length,
    series.other_videos.length,
  );

  return (
    <div className="p-6 space-y-6 max-w-4xl">
      <Link
        to={`/?library=${encodeURIComponent(series.library_id)}`}
        className="text-sm text-neutral-500 hover:text-neutral-300"
      >
        ← Library
      </Link>

      <div>
        <h1 className="text-2xl font-bold">{series.title}</h1>
        {series.year && <p className="text-neutral-500">{series.year}</p>}
        <p className="mt-1 font-mono text-xs text-neutral-700 break-all">
          {series.folder_path}
        </p>
        <p className="mt-1 text-xs text-neutral-500">
          {totalEpisodes} episode{totalEpisodes !== 1 ? "s" : ""}
        </p>
      </div>

      {totalEpisodes === 0 && (
        <div className="rounded border border-dashed border-neutral-700 p-8 text-center text-neutral-500">
          No episodes found. Run a scan.
        </div>
      )}

      {series.season_groups.map((group) => (
        <section key={group.season_number ?? "unknown"} className="space-y-2">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-neutral-400">
            {group.season_number === null ? "Episodes" : `Season ${group.season_number}`}
          </h2>
          <div className="space-y-1">
            {group.episodes.map((episode) => (
              <EpisodeRow key={episode.id} episode={episode} />
            ))}
          </div>
        </section>
      ))}

      {series.other_videos.length > 0 && (
        <section className="space-y-2">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-neutral-400">
            Other videos
          </h2>
          <div className="space-y-1">
            {series.other_videos.map((episode) => (
              <EpisodeRow key={episode.id} episode={episode} />
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
