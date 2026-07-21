import { useState } from "react";
import { useParams, Link } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { getMovie, deleteSub, extractTrack, embedSub, transcribeVideo, translateSub, translateEmbedded, detectSubLanguage } from "@/api/client";
import type { ExternalSub, VideoFile } from "@/api/client";
import { LangBadge } from "@/components/LangBadge";
import { UploadModal } from "@/components/UploadModal";
import { EditSubModal } from "@/components/EditSubModal";

function fmt(secs: number | null) {
  if (!secs) return "—";
  const h = Math.floor(secs / 3600);
  const m = Math.floor((secs % 3600) / 60);
  return h > 0 ? `${h}h ${m}m` : `${m}m`;
}

interface VideoFileCardProps {
  vf: VideoFile;
  movieId: number;
  externalSubs: ExternalSub[];
}

const TEXT_CODECS = new Set(["subrip", "srt", "ass", "ssa", "webvtt", "vtt"]);

function VideoFileCard({ vf, movieId, externalSubs }: VideoFileCardProps) {
  const qc = useQueryClient();
  const [embedSubId, setEmbedSubId] = useState<string>("");
  const [whisperLang, setWhisperLang] = useState<string>("");
  const [mkvMsg, setMkvMsg] = useState<string | null>(null);
  const [embTransLangs, setEmbTransLangs] = useState<Record<number, string>>({});

  const extract = useMutation({
    mutationFn: (trackIndex: number) => extractTrack(vf.id!, trackIndex),
    onSuccess: (job) => {
      setMkvMsg(`Extract job ${job.id} → ${job.status}`);
      qc.invalidateQueries({ queryKey: ["movie", movieId] });
    },
    onError: (e: Error) => setMkvMsg(`Extract failed: ${e.message}`),
  });

  const translateEmb = useMutation({
    mutationFn: ({ trackIndex, targetLang }: { trackIndex: number; targetLang: string }) =>
      translateEmbedded(vf.id!, trackIndex, targetLang),
    onSuccess: (job) => {
      setMkvMsg(`Translate job ${job.id} → ${job.status}`);
      qc.invalidateQueries({ queryKey: ["movie", movieId] });
    },
    onError: (e: Error) => setMkvMsg(`Translate failed: ${e.message}`),
  });

  const embed = useMutation({
    mutationFn: () => embedSub(vf.id!, Number(embedSubId)),
    onSuccess: (job) => {
      setMkvMsg(`Embed job ${job.id} → ${job.status}`);
      qc.invalidateQueries({ queryKey: ["movie", movieId] });
    },
    onError: (e: Error) => setMkvMsg(`Embed failed: ${e.message}`),
  });

  const transcribe = useMutation({
    mutationFn: () => transcribeVideo(vf.id!, whisperLang || undefined),
    onSuccess: (job) => {
      setMkvMsg(`Transcribe job ${job.id} → ${job.status}`);
      qc.invalidateQueries({ queryKey: ["movie", movieId] });
    },
    onError: (e: Error) => setMkvMsg(`Transcribe failed: ${e.message}`),
  });

  const isMkv = vf.container === "mkv";

  return (
    <div className="rounded border border-neutral-800 bg-neutral-900 p-4">
      <div className="flex items-baseline gap-3">
        <span className="font-mono text-sm break-all">{vf.filename}</span>
        {vf.variant && (
          <span className="rounded bg-neutral-700 px-1.5 py-0.5 text-xs shrink-0">{vf.variant}</span>
        )}
        <span className="ml-auto text-xs text-neutral-500 shrink-0">
          {vf.container?.toUpperCase()} · {fmt(vf.duration)}
        </span>
      </div>

      {vf.embedded_subs.length > 0 ? (
        <div className="mt-2 space-y-1">
          <p className="text-xs text-neutral-500 font-medium">Embedded tracks</p>
          {vf.embedded_subs.map((es) => (
            <div key={es.id} className="flex items-center gap-2 text-xs">
              <span className="text-neutral-600">#{es.track_index}</span>
              <span className="font-mono text-neutral-400">{es.codec}</span>
              {es.language && <LangBadge lang={es.language} />}
              {es.title && <span className="text-neutral-500">{es.title}</span>}
              {es.default && <span className="rounded bg-green-900 px-1 text-green-300">default</span>}
              {es.forced && <span className="rounded bg-orange-900 px-1 text-orange-300">forced</span>}
              {isMkv && (
                <button
                  onClick={() => extract.mutate(es.track_index)}
                  disabled={extract.isPending}
                  className="ml-auto text-neutral-600 hover:text-blue-400 disabled:opacity-40"
                  title="Extract to sidecar file"
                >
                  {extract.isPending ? "…" : "↓ Extract"}
                </button>
              )}
              {isMkv && TEXT_CODECS.has(es.codec) && (
                <div className="flex items-center gap-1">
                  <input
                    type="text"
                    value={embTransLangs[es.track_index] ?? ""}
                    onChange={(e) =>
                      setEmbTransLangs((prev) => ({ ...prev, [es.track_index]: e.target.value }))
                    }
                    placeholder="→ lang"
                    className="w-14 rounded border border-neutral-700 bg-neutral-800 px-1 py-0.5 text-xs focus:outline-none"
                  />
                  <button
                    onClick={() =>
                      translateEmb.mutate({
                        trackIndex: es.track_index,
                        targetLang: embTransLangs[es.track_index] ?? "",
                      })
                    }
                    disabled={!embTransLangs[es.track_index] || translateEmb.isPending}
                    className="rounded bg-teal-900 px-1.5 py-0.5 text-xs hover:bg-teal-800 disabled:opacity-40"
                    title="Extract + translate with AI"
                  >
                    {translateEmb.isPending ? "…" : "→ Translate"}
                  </button>
                </div>
              )}
            </div>
          ))}
        </div>
      ) : (
        <p className="mt-1 text-xs text-neutral-700">No embedded subtitle tracks</p>
      )}

      {isMkv && externalSubs.length > 0 && (
        <div className="mt-3 flex items-center gap-2">
          <select
            value={embedSubId}
            onChange={(e) => setEmbedSubId(e.target.value)}
            className="flex-1 rounded border border-neutral-700 bg-neutral-800 px-2 py-1 text-xs focus:outline-none"
          >
            <option value="">— embed external sub —</option>
            {externalSubs.map((s) => (
              <option key={s.id} value={s.id}>
                {s.filename} {s.language ? `[${s.language}]` : ""}
              </option>
            ))}
          </select>
          <button
            onClick={() => embed.mutate()}
            disabled={!embedSubId || embed.isPending}
            className="rounded bg-neutral-700 px-2 py-1 text-xs hover:bg-neutral-600 disabled:opacity-40"
            title="Embed into MKV (original backed up)"
          >
            {embed.isPending ? "…" : "↑ Embed"}
          </button>
        </div>
      )}

      <div className="mt-3 flex items-center gap-2">
        <input
          type="text"
          value={whisperLang}
          onChange={(e) => setWhisperLang(e.target.value)}
          placeholder="lang (auto)"
          className="w-24 rounded border border-neutral-700 bg-neutral-800 px-2 py-1 text-xs focus:outline-none"
        />
        <button
          onClick={() => transcribe.mutate()}
          disabled={transcribe.isPending}
          className="rounded bg-indigo-700 px-3 py-1 text-xs font-medium hover:bg-indigo-600 disabled:opacity-40"
          title="Transcribe audio with Whisper"
        >
          {transcribe.isPending ? "Transcribing…" : "🎙 Transcribe"}
        </button>
      </div>

      {mkvMsg && (
        <p className="mt-2 text-xs text-blue-400">{mkvMsg}</p>
      )}
    </div>
  );
}

interface SubRowProps {
  sub: ExternalSub;
  movieId: number;
  onEdit: (sub: ExternalSub) => void;
}

function ExternalSubRow({ sub, movieId, onEdit }: SubRowProps) {
  const qc = useQueryClient();
  const [confirming, setConfirming] = useState(false);
  const [targetLang, setTargetLang] = useState("");
  const [translateMsg, setTranslateMsg] = useState<string | null>(null);
  const [detectError, setDetectError] = useState<string | null>(null);

  const del = useMutation({
    mutationFn: () => deleteSub(sub.id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["movie", movieId] }),
  });

  const detect = useMutation({
    mutationFn: () => detectSubLanguage(sub.id),
    onSuccess: () => {
      setDetectError(null);
      qc.invalidateQueries({ queryKey: ["movie", movieId] });
    },
    onError: (e: Error) => setDetectError(e.message),
  });

  const translate = useMutation({
    mutationFn: () => translateSub(sub.id, targetLang, sub.language ?? undefined),
    onSuccess: (job) => {
      setTranslateMsg(`Translate job ${job.id} → ${job.status}`);
      setTargetLang("");
      qc.invalidateQueries({ queryKey: ["movie", movieId] });
    },
    onError: (e: Error) => setTranslateMsg(`Translate failed: ${e.message}`),
  });

  const isProtected = sub.source === "preexisting";

  return (
    <tr className="border-b border-neutral-800 group">
      <td className="py-2 pr-3 font-mono text-xs text-neutral-400 break-all max-w-xs">
        {sub.rel_dir ? <span className="text-neutral-600">{sub.rel_dir}/</span> : null}
        {sub.filename}
      </td>
      <td className="py-2 pr-3">
        {sub.language
          ? <LangBadge lang={sub.language} />
          : <span className="text-xs text-neutral-600">unknown</span>}
        {sub.language_source === "manual" && (
          <span className="ml-1 text-xs text-blue-400" title="Manually set">✎</span>
        )}
        {!sub.language && (
          <button
            onClick={() => detect.mutate()}
            disabled={detect.isPending}
            className="ml-1 text-xs text-neutral-500 hover:text-blue-400 disabled:opacity-40"
            title="Detect language from subtitle content"
          >
            {detect.isPending ? "…" : "Detect"}
          </button>
        )}
        {detectError && <p className="mt-0.5 text-xs text-red-400">{detectError}</p>}
      </td>
      <td className="py-2 pr-3 text-xs space-x-1 whitespace-nowrap">
        {sub.forced && <span className="rounded bg-orange-900 px-1 text-orange-300">forced</span>}
        {sub.sdh && <span className="rounded bg-purple-900 px-1 text-purple-300">SDH</span>}
        {sub.custom_tag && <span className="rounded bg-neutral-800 px-1 text-neutral-400">{sub.custom_tag}</span>}
      </td>
      <td className="py-2 pr-3 text-xs text-neutral-600 capitalize">{sub.source}</td>
      <td className="py-2 text-xs whitespace-nowrap">
        <button
          onClick={() => onEdit(sub)}
          className="text-neutral-500 hover:text-neutral-200 mr-3"
          title="Edit"
        >
          Edit
        </button>
        {!isProtected && !confirming && (
          <button
            onClick={() => setConfirming(true)}
            className="text-neutral-500 hover:text-red-400"
            title="Delete (moves to trash)"
          >
            Delete
          </button>
        )}
        {!isProtected && confirming && (
          <span className="space-x-2">
            <button
              onClick={() => { del.mutate(); setConfirming(false); }}
              className="text-red-400 hover:text-red-300"
            >
              Confirm
            </button>
            <button
              onClick={() => setConfirming(false)}
              className="text-neutral-500 hover:text-neutral-300"
            >
              Cancel
            </button>
          </span>
        )}
        {isProtected && (
          <span className="text-neutral-700 text-xs" title="Preexisting files are protected">🔒</span>
        )}
      </td>
      <td className="py-2 text-xs">
        <div className="flex items-center gap-1">
          <input
            type="text"
            value={targetLang}
            onChange={(e) => setTargetLang(e.target.value)}
            placeholder="→ lang"
            className="w-16 rounded border border-neutral-700 bg-neutral-800 px-1.5 py-0.5 text-xs focus:outline-none"
          />
          <button
            onClick={() => translate.mutate()}
            disabled={!targetLang || translate.isPending}
            className="rounded bg-teal-800 px-2 py-0.5 hover:bg-teal-700 disabled:opacity-40"
            title="Translate with AI"
          >
            {translate.isPending ? "…" : "Translate"}
          </button>
        </div>
        {translateMsg && <p className="mt-0.5 text-teal-400">{translateMsg}</p>}
      </td>
    </tr>
  );
}

export default function Movie() {
  const { id } = useParams<{ id: string }>();
  const movieId = Number(id);
  const [showUpload, setShowUpload] = useState(false);
  const [editingSub, setEditingSub] = useState<ExternalSub | null>(null);

  const { data: movie, isLoading, error } = useQuery({
    queryKey: ["movie", movieId],
    queryFn: () => getMovie(movieId),
    enabled: !isNaN(movieId),
  });

  if (isLoading) return <div className="p-6 text-neutral-400">Loading…</div>;
  if (error || !movie) return <div className="p-6 text-red-400">Movie not found.</div>;

  return (
    <div className="p-6 space-y-6 max-w-4xl">
      <Link to="/" className="text-sm text-neutral-500 hover:text-neutral-300">← Library</Link>

      <div>
        <h1 className="text-2xl font-bold">{movie.title}</h1>
        {movie.year && <p className="text-neutral-500">{movie.year}</p>}
        <p className="mt-1 font-mono text-xs text-neutral-700 break-all">{movie.folder_path}</p>
      </div>

      {/* Video files */}
      <section className="space-y-2">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-neutral-400">
          Video files ({movie.video_files.length})
        </h2>
        {movie.video_files.length === 0
          ? <p className="text-sm text-neutral-600">No video files found. Run a scan.</p>
          : movie.video_files.map((vf) => (
              <VideoFileCard
                key={vf.id}
                vf={vf}
                movieId={movieId}
                externalSubs={movie.external_subs}
              />
            ))}
      </section>

      {/* External subtitles */}
      <section>
        <div className="flex items-center justify-between mb-2">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-neutral-400">
            External subtitles ({movie.external_subs.length})
          </h2>
          <button
            onClick={() => setShowUpload(true)}
            className="rounded bg-blue-600 px-3 py-1 text-xs font-medium hover:bg-blue-500"
          >
            + Upload SRT
          </button>
        </div>

        {movie.external_subs.length === 0 ? (
          <p className="text-sm text-neutral-600">No external subtitle files.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-neutral-500 border-b border-neutral-800">
                  <th className="pb-1 pr-3">File</th>
                  <th className="pb-1 pr-3">Language</th>
                  <th className="pb-1 pr-3">Flags</th>
                  <th className="pb-1 pr-3">Source</th>
                  <th className="pb-1 pr-3">Actions</th>
                  <th className="pb-1">Translate</th>
                </tr>
              </thead>
              <tbody>
                {movie.external_subs.map((s) => (
                  <ExternalSubRow
                    key={s.id}
                    sub={s}
                    movieId={movieId}
                    onEdit={setEditingSub}
                  />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* Phase 4+ actions */}
      <section className="rounded border border-dashed border-neutral-800 p-4 text-xs text-neutral-700 space-y-1">
        <p>Phase 4+: Extract / embed MKV tracks</p>
        <p>Phase 6+: Transcribe with Whisper</p>
        <p>Phase 7+: Translate with DeepSeek / llm-subtrans</p>
      </section>

      {showUpload && (
        <UploadModal movieId={movieId} onClose={() => setShowUpload(false)} />
      )}
      {editingSub && (
        <EditSubModal
          sub={editingSub}
          movieId={movieId}
          onClose={() => setEditingSub(null)}
        />
      )}
    </div>
  );
}
