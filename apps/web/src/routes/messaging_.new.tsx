/**
 * /messaging/new — create a structured messaging document.
 *
 * Owns the route + mutation; the actual form lives in
 * `components/messaging/MessagingForm.tsx` so /messaging/$id can reuse it
 * for edits.
 */

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useState } from "react";

import { MessagingForm } from "@/components/messaging/MessagingForm";
import { PageHeader } from "@/routes/dashboard";
import { messagingApi } from "@/lib/api";

export const Route = createFileRoute("/messaging_/new")({
  component: NewMessagingDocPage,
});

function NewMessagingDocPage() {
  const navigate = useNavigate();
  const [error, setError] = useState<string | null>(null);

  const queryClient = useQueryClient();
  const mutation = useMutation({
    mutationFn: (body: import("@/lib/api-types").MessagingDocumentCreate) =>
      messagingApi.create(body),
    onSuccess: () => {
      // Without this, /messaging served its 30s-stale cache on arrival and
      // the document you just created was invisible until a hard refresh.
      void queryClient.invalidateQueries({ queryKey: ["messaging"] });
      void navigate({ to: "/messaging" });
    },
    onError: (err) => setError(String((err as Error).message)),
  });

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="New messaging document"
        description="Structured product messaging fields. One per active positioning artifact."
      />
      <MessagingForm
        initial={null}
        submitting={mutation.isPending}
        error={error}
        onSubmit={(body) => {
          setError(null);
          mutation.mutate(body);
        }}
        onCancel={() => navigate({ to: "/messaging" })}
      />
    </div>
  );
}
