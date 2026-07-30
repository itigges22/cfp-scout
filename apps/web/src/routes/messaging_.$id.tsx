/**
 * /messaging/$id — edit a structured messaging document.
 *
 * Loads the existing row, hands it to the shared MessagingForm, and persists
 * via PUT. Flat-route (trailing underscore) so the parent /messaging list
 * page doesn't need an <Outlet />.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useState } from "react";

import { MessagingForm } from "@/components/messaging/MessagingForm";
import { Skeleton } from "@/components/ui/skeleton";
import { PageHeader } from "@/routes/dashboard";
import { ErrorBox } from "@/components/form";
import { messagingApi } from "@/lib/api";

export const Route = createFileRoute("/messaging_/$id")({
  component: EditMessagingDocPage,
});

function EditMessagingDocPage() {
  const { id } = Route.useParams();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [error, setError] = useState<string | null>(null);

  const query = useQuery({
    queryKey: ["messaging", id],
    queryFn: () => messagingApi.get(id),
  });

  const mutation = useMutation({
    mutationFn: (body: import("@/lib/api-types").MessagingDocumentUpdate) =>
      messagingApi.update(id, body),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["messaging"] });
      navigate({ to: "/messaging" });
    },
    onError: (err) => setError(String((err as Error).message)),
  });

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title={query.data ? `Edit "${query.data.title}"` : "Edit messaging document"}
        description="Updates re-embed the document so the matcher's Stage A picks up the changes."
      />
      {query.isLoading ? (
        <Skeleton className="h-96 w-full max-w-3xl" />
      ) : query.isError ? (
        <ErrorBox error={query.error} />
      ) : query.data ? (
        <MessagingForm
          initial={query.data}
          submitting={mutation.isPending}
          error={error}
          onSubmit={(body) => {
            setError(null);
            mutation.mutate(body);
          }}
          onCancel={() => navigate({ to: "/messaging" })}
        />
      ) : null}
    </div>
  );
}
