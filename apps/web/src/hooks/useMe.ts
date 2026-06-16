import { useQuery } from "@tanstack/react-query";

interface MeResult {
  email: string;
  /** Display-friendly label — username part before "@", or the full value if no "@". */
  label: string;
}

async function fetchMe(): Promise<MeResult> {
  const res = await fetch("/api/v1/me");
  if (!res.ok) return { email: "", label: "" };
  const data = (await res.json()) as { email: string };
  const email = data.email ?? "";
  const label = email.includes("@") ? (email.split("@")[0] ?? email) : email;
  return { email, label };
}

export function useMe(): MeResult {
  const q = useQuery({
    queryKey: ["me"],
    queryFn: fetchMe,
    staleTime: Infinity,
  });
  return q.data ?? { email: "", label: "" };
}
