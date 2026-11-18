const BASE = "/api";

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    ...init,
  });
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json() as Promise<T>;
}

// ---------- types ----------

export interface Health {
  status: string;
}

export interface Library {
  id: string;
  name: string;
  type: "movies" | "series";
  root: string;
}

export interface EmbeddedSub {
  id: number;
  video_file_id: number;
  track_index: number;
  codec: string;
  language: string | null;
  title: string | null;
  default: boolean;
  forced: boolean;
}

export interface ExternalSub {
  id: number;
  movie_id: number;
  path: string;
  filename: string;
  rel_dir: string;
  language: string | null;
  language_source: string;
  format: string;
  forced: boolean;
  sdh: boolean;
  custom_tag: string | null;
  source: string;
  created_at: string;
}

export interface VideoFile {
  id: number;
  movie_id: number;
  filename: string;
  variant: string | null;
  container: string | null;
  duration: number | null;
  video_codec: string | null;
  embedded_subs: EmbeddedSub[];
}

export interface MovieSummary {
  id: number;
  title: string;
  year: number | null;
  folder_path: string;
  kind: "movie" | "episode";
  library_id: string | null;
  season_number: number | null;
  episode_number: number | null;
  episode_label: string | null;
  video_count: number;
  external_sub_count: number;
  external_sub_languages: string[];
  unknown_sub_count: number;
  embedded_sub_count: number;
  embedded_sub_languages: string[];
  has_subs: boolean;
  video_formats: string[];
  subtitle_formats: string[];
}

export interface MovieDetail {
  id: number;
  title: string;
  year: number | null;
  folder_path: string;
  kind: "movie" | "episode";
  library_id: string | null;
  series_id: number | null;
  series_title: string | null;
  season_number: number | null;
  episode_number: number | null;
  episode_label: string | null;
  scanned_at: string | null;
  video_files: VideoFile[];
  external_subs: ExternalSub[];
}

export interface EpisodeSummary {
  id: number;
  title: string;
  episode_label: string | null;
  season_number: number | null;
  episode_number: number | null;
  video_count: number;
  external_sub_count: number;
  external_sub_languages: string[];
  unknown_sub_count: number;
  embedded_sub_count: number;
  embedded_sub_languages: string[];
  has_subs: boolean;
  video_formats: string[];
  subtitle_formats: string[];
}

export interface SeasonGroup {
  season_number: number | null;
  episodes: EpisodeSummary[];
}

export interface SeriesSummary {
  id: number;
  library_id: string;
  title: string;
  year: number | null;
  folder_path: string;
  episode_count: number;
  video_count: number;
  external_sub_count: number;
  external_sub_languages: string[];
  unknown_sub_count: number;
  embedded_sub_count: number;
  embedded_sub_languages: string[];
  has_subs: boolean;
}

export interface SeriesDetail {
  id: number;
  library_id: string;
  title: string;
  year: number | null;
  folder_path: string;
  scanned_at: string | null;
  season_groups: SeasonGroup[];
  other_videos: EpisodeSummary[];
}

export interface Job {
  id: number;
  type: string;
  status: string;
  progress: number;
  log: string;
  error: string | null;
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
}

// ---------- endpoints ----------

async function apiForm<T>(path: string, method: string, body: FormData): Promise<T> {
  const r = await fetch(`${BASE}${path}`, { method, body });
  if (!r.ok) {
    const err = await r.json().catch(() => ({ detail: r.statusText }));
    throw new Error(err.detail ?? r.statusText);
  }
  return r.json() as Promise<T>;
}

export const getHealth = () => api<Health>("/health");
export const getLibraries = () => api<Library[]>("/libraries");
export const getMovies = (missingSubs = false, libraryId?: string) => {
  const q = new URLSearchParams({ missing_subs: String(missingSubs) });
  if (libraryId) q.set("library", libraryId);
  return api<MovieSummary[]>(`/movies/?${q}`);
};
export const getMovie = (id: number) => api<MovieDetail>(`/movies/${id}`);
export const getSeries = (libraryId?: string) => {
  const q = libraryId ? `?library=${encodeURIComponent(libraryId)}` : "";
  return api<SeriesSummary[]>(`/series/${q}`);
};
export const getSeriesDetail = (id: number) => api<SeriesDetail>(`/series/${id}`);
export const getJobs = () => api<Job[]>("/jobs/");
export const getJob = (id: number) => api<Job>(`/jobs/${id}`);
export const triggerScan = (libraryId?: string) => {
  const q = libraryId ? `?library=${encodeURIComponent(libraryId)}` : "";
  return api<{ job_ids: number[]; roots: string[] }>(`/library/scan${q}`, {
    method: "POST",
  });
};

export interface UploadSubParams {
  movieId: number;
  file: File;
  language: string;
  forced?: boolean;
  sdh?: boolean;
  customTag?: string;
  forceOverwrite?: boolean;
}

export function uploadSub(p: UploadSubParams): Promise<ExternalSub> {
  const fd = new FormData();
  fd.append("file", p.file);
  fd.append("language", p.language);
  if (p.forced) fd.append("forced", "true");
  if (p.sdh) fd.append("sdh", "true");
  if (p.customTag) fd.append("custom_tag", p.customTag);
  if (p.forceOverwrite) fd.append("force_overwrite", "true");
  return apiForm<ExternalSub>(`/movies/${p.movieId}/subs/upload`, "POST", fd);
}

export const deleteSub = (id: number) =>
  api<{ ok: boolean }>(`/subs/${id}`, { method: "DELETE" });

export interface PatchSubParams {
  language?: string;
  forced?: boolean;
  sdh?: boolean;
  customTag?: string;
}

export function patchSub(id: number, params: PatchSubParams): Promise<ExternalSub> {
  const q = new URLSearchParams();
  if (params.language !== undefined) q.set("language", params.language);
  if (params.forced !== undefined) q.set("forced", String(params.forced));
  if (params.sdh !== undefined) q.set("sdh", String(params.sdh));
  if (params.customTag !== undefined) q.set("custom_tag", params.customTag);
  return api<ExternalSub>(`/subs/${id}?${q}`, { method: "PATCH" });
}

export const renameSub = (id: number) =>
  api<ExternalSub>(`/subs/${id}/rename`, { method: "POST" });

export const detectSubLanguage = (id: number) =>
  api<ExternalSub>(`/subs/${id}/detect-language`, { method: "POST" });

export const extractTrack = (videoFileId: number, trackIndex: number) =>
  api<Job>(`/video-files/${videoFileId}/extract/${trackIndex}`, { method: "POST" });

export const embedSub = (videoFileId: number, subId: number) =>
  api<Job>(`/video-files/${videoFileId}/embed`, {
    method: "POST",
    body: JSON.stringify({ sub_id: subId }),
  });

export const transcribeVideo = (videoFileId: number, language?: string) => {
  const q = language ? `?language=${encodeURIComponent(language)}` : "";
  return api<Job>(`/video-files/${videoFileId}/transcribe${q}`, { method: "POST" });
};

export const translateSub = (subId: number, targetLanguage: string, sourceLanguage?: string) =>
  api<Job>(`/subs/${subId}/translate`, {
    method: "POST",
    body: JSON.stringify({ target_language: targetLanguage, source_language: sourceLanguage ?? null }),
  });

export const translateEmbedded = (
  videoFileId: number,
  trackIndex: number,
  targetLanguage: string,
  sourceLanguage?: string,
) =>
  api<Job>(`/video-files/${videoFileId}/translate-embedded/${trackIndex}`, {
    method: "POST",
    body: JSON.stringify({ target_language: targetLanguage, source_language: sourceLanguage ?? null }),
  });
