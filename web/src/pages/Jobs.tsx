import { useQuery } from "@tanstack/react-query";
import { getJobs } from "@/api/client";

const STATUS_COLOR: Record<string, string> = {
  queued: "text-yellow-400",
  running: "text-blue-400",
  done: "text-green-400",
  failed: "text-red-400",
  cancelled: "text-neutral-400",
};

function relTime(iso: string | null) {
  if (!iso) return "—";
  const normalized = /[Z+\-]\d*$/.test(iso) ? iso : iso + "Z";
  const diff = Math.round((Date.now() - new Date(normalized).getTime()) / 1000);
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.round(diff / 60)}m ago`;
  return `${Math.round(diff / 3600)}h ago`;
}

export default function Jobs() {
  const { data: jobs = [], isLoading } = useQuery({
    queryKey: ["jobs"],
    queryFn: getJobs,
    refetchInterval: 3000,
  });

  const active = jobs.filter((j) => j.status === "running" || j.status === "queued");
  const finished = jobs.filter((j) => j.status !== "running" && j.status !== "queued");

  return (
    <div className="p-6 space-y-6 max-w-4xl">
      <h1 className="text-xl font-bold">Jobs</h1>

      {isLoading && <p className="text-neutral-400">Loading…</p>}

      {active.length > 0 && (
        <section className="space-y-2">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-neutral-400">
            Active
          </h2>
          {active.map((j) => (
            <div
              key={j.id}
              className="rounded border border-neutral-800 bg-neutral-900 p-3"
            >
              <div className="flex items-center gap-3">
                <span className="font-mono text-xs text-neutral-500">#{j.id}</span>
                <span className="text-sm font-medium">{j.type}</span>
                <span className={`text-sm ${STATUS_COLOR[j.status]}`}>
                  {j.status}
                  {j.status === "running" && ` ${j.progress}%`}
                </span>
                {j.status === "running" && (
                  <div className="flex-1 h-1 bg-neutral-800 rounded ml-2">
                    <div
                      className="h-1 bg-blue-500 rounded transition-all"
                      style={{ width: `${j.progress}%` }}
                    />
                  </div>
                )}
              </div>
            </div>
          ))}
        </section>
      )}

      {finished.length > 0 && (
        <section>
          <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-neutral-400">
            History
          </h2>
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-neutral-500 border-b border-neutral-800">
                <th className="pb-1 pr-4">#</th>
                <th className="pb-1 pr-4">Type</th>
                <th className="pb-1 pr-4">Status</th>
                <th className="pb-1 pr-4">Finished</th>
                <th className="pb-1">Error</th>
              </tr>
            </thead>
            <tbody>
              {finished.map((j) => (
                <tr key={j.id} className="border-b border-neutral-800">
                  <td className="py-2 pr-4 font-mono text-xs text-neutral-600">
                    {j.id}
                  </td>
                  <td className="py-2 pr-4">{j.type}</td>
                  <td className={`py-2 pr-4 ${STATUS_COLOR[j.status]}`}>
                    {j.status}
                  </td>
                  <td className="py-2 pr-4 text-xs text-neutral-500">
                    {relTime(j.finished_at)}
                  </td>
                  <td className="py-2 text-xs text-red-400 truncate max-w-xs">
                    {j.error ?? ""}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      {!isLoading && jobs.length === 0 && (
        <p className="text-neutral-500">No jobs yet. Trigger a scan from the Library page.</p>
      )}
    </div>
  );
}
