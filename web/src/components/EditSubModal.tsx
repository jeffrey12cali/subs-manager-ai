import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { patchSub, renameSub } from "@/api/client";
import type { ExternalSub } from "@/api/client";

interface Props {
  sub: ExternalSub;
  movieId: number;
  onClose: () => void;
}

export function EditSubModal({ sub, movieId, onClose }: Props) {
  const qc = useQueryClient();
  const [language, setLanguage] = useState(sub.language ?? "");
  const [forced, setForced] = useState(sub.forced);
  const [sdh, setSdh] = useState(sub.sdh);
  const [customTag, setCustomTag] = useState(sub.custom_tag ?? "");
  const [error, setError] = useState<string | null>(null);

  const invalidate = () => qc.invalidateQueries({ queryKey: ["movie", movieId] });

  const save = useMutation({
    mutationFn: () =>
      patchSub(sub.id, {
        language: language || undefined,
        forced,
        sdh,
        customTag: customTag || undefined,
      }),
    onSuccess: () => { invalidate(); onClose(); },
    onError: (e: Error) => setError(e.message),
  });

  const rename = useMutation({
    mutationFn: () => renameSub(sub.id),
    onSuccess: () => { invalidate(); onClose(); },
    onError: (e: Error) => setError(e.message),
  });

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
      <div className="w-full max-w-md rounded-lg border border-neutral-700 bg-neutral-900 p-6 space-y-4 shadow-xl">
        <h2 className="text-lg font-semibold">Edit subtitle</h2>
        <p className="font-mono text-xs text-neutral-500">{sub.filename}</p>

        <div className="space-y-3">
          <label className="block">
            <span className="text-sm text-neutral-400">Language (BCP-47)</span>
            <input
              type="text"
              value={language}
              onChange={(e) => setLanguage(e.target.value)}
              className="mt-1 block w-full rounded border border-neutral-700 bg-neutral-800 px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-blue-500"
            />
          </label>

          <label className="block">
            <span className="text-sm text-neutral-400">Custom tag</span>
            <input
              type="text"
              value={customTag}
              onChange={(e) => setCustomTag(e.target.value)}
              placeholder="ai, director…"
              className="mt-1 block w-full rounded border border-neutral-700 bg-neutral-800 px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-blue-500"
            />
          </label>

          <div className="flex gap-6">
            <label className="flex items-center gap-2 text-sm cursor-pointer select-none">
              <input type="checkbox" checked={forced} onChange={(e) => setForced(e.target.checked)} className="accent-orange-500" />
              Forced
            </label>
            <label className="flex items-center gap-2 text-sm cursor-pointer select-none">
              <input type="checkbox" checked={sdh} onChange={(e) => setSdh(e.target.checked)} className="accent-purple-500" />
              SDH
            </label>
          </div>
        </div>

        {error && <p className="text-sm text-red-400">{error}</p>}

        <div className="flex items-center justify-between">
          <button
            onClick={() => rename.mutate()}
            disabled={rename.isPending || !sub.language}
            title={!sub.language ? "Set language first" : "Rename to Jellyfin convention"}
            className="text-sm text-neutral-400 hover:text-neutral-200 disabled:opacity-40"
          >
            {rename.isPending ? "Renaming…" : "→ Rename to convention"}
          </button>
          <div className="flex gap-3">
            <button onClick={onClose} className="rounded px-3 py-1.5 text-sm text-neutral-400 hover:text-neutral-200">
              Cancel
            </button>
            <button
              onClick={() => save.mutate()}
              disabled={save.isPending}
              className="rounded bg-blue-600 px-4 py-1.5 text-sm font-medium hover:bg-blue-500 disabled:opacity-50"
            >
              {save.isPending ? "Saving…" : "Save"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
