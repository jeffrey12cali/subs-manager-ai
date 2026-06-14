import { useQuery } from "@tanstack/react-query";
import { getJob } from "@/api/client";

const STATUS_COLOR: Record<string, string> = {
  queued: "text-yellow-400",
  running: "text-blue-400",
  done: "text-green-400",
  failed: "text-red-400",
  cancelled: "text-neutral-400",
};

export function JobStatusBadge({ jobId }: { jobId: number }) {
  const { data } = useQuery({
    queryKey: ["job", jobId],
    queryFn: () => getJob(jobId),
    refetchInterval: (q) => {
      const status = q.state.data?.status;
      return status === "running" || status === "queued" ? 1500 : false;
    },
  });

  if (!data) return null;
  const color = STATUS_COLOR[data.status] ?? "text-neutral-400";
  return (
    <span className={`text-sm font-medium ${color}`}>
      {data.status}
      {data.status === "running" && ` ${data.progress}%`}
    </span>
  );
}
