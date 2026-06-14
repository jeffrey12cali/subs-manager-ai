import { useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { uploadSub } from "@/api/client";

interface Props {
  movieId: number;
  onClose: () => void;
}

export function UploadModal({ movieId, onClose }: Props) {
  const qc = useQueryClient();
  const fileRef = useRef<HTMLInputElement>(null);
  const [language, setLanguage] = useState("en");
  const [forced, setForced] = useState(false);
  const [sdh, setSdh] = useState(false);
  const [customTag, setCustomTag] = useState("");
  const [error, setError] = useState<string | null>(null);

  const upload = useMutation({
    mutationFn: () => {
      const file = fileRef.current?.files?.[0];
      if (!file) throw new Error("No file selected.");
      return uploadSub({
        movieId,
        file,
        language,
        forced,
        sdh,
        customTag: customTag || undefined,
      });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["movie", movieId] });
      onClose();
    },
    onError: (e: Error) => setError(e.message),
  });

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
      <div className="w-full max-w-md rounded-lg border border-neutral-700 bg-neutral-900 p-6 space-y-4 shadow-xl">
        <h2 className="text-lg font-semibold">Upload subtitle</h2>

        <div className="space-y-3">
          <label className="block">
            <span className="text-sm text-neutral-400">SRT file</span>
            <input
              ref={fileRef}
              type="file"
              accept=".srt,.ass,.vtt"
              className="mt-1 block w-full text-sm file:mr-3 file:rounded file:bg-neutral-700 file:px-3 file:py-1 file:text-sm file:text-neutral-100 file:border-0 file:hover:bg-neutral-600"
            />
          </label>

          <label className="block">
            <span className="text-sm text-neutral-400">Language (BCP-47)</span>
            <input
              type="text"
              value={language}
              onChange={(e) => setLanguage(e.target.value)}
              placeholder="en, es, fr, zh…"
              className="mt-1 block w-full rounded border border-neutral-700 bg-neutral-800 px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-blue-500"
            />
          </label>

          <label className="block">
            <span className="text-sm text-neutral-400">Custom tag (optional)</span>
            <input
              type="text"
              value={customTag}
              onChange={(e) => setCustomTag(e.target.value)}
              placeholder="ai, director, commentary…"
              className="mt-1 block w-full rounded border border-neutral-700 bg-neutral-800 px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-blue-500"
            />
          </label>

          <div className="flex gap-6">
            <label className="flex items-center gap-2 text-sm cursor-pointer select-none">
              <input
                type="checkbox"
                checked={forced}
                onChange={(e) => setForced(e.target.checked)}
                className="accent-orange-500"
              />
              Forced
            </label>
            <label className="flex items-center gap-2 text-sm cursor-pointer select-none">
              <input
                type="checkbox"
                checked={sdh}
                onChange={(e) => setSdh(e.target.checked)}
                className="accent-purple-500"
              />
              SDH / CC
            </label>
          </div>
        </div>

        {error && <p className="text-sm text-red-400">{error}</p>}

        <div className="flex justify-end gap-3">
          <button
            onClick={onClose}
            className="rounded px-3 py-1.5 text-sm text-neutral-400 hover:text-neutral-200"
          >
            Cancel
          </button>
          <button
            onClick={() => upload.mutate()}
            disabled={upload.isPending}
            className="rounded bg-blue-600 px-4 py-1.5 text-sm font-medium hover:bg-blue-500 disabled:opacity-50"
          >
            {upload.isPending ? "Uploading…" : "Upload"}
          </button>
        </div>
      </div>
    </div>
  );
}
