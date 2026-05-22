import { ChevronLeft, ChevronRight } from "lucide-react";

import { Button } from "@/components/ui/button";

interface PaginationProps {
  page: number;
  perPage: number;
  total: number;
  onPageChange: (page: number) => void;
}

export function Pagination({ page, perPage, total, onPageChange }: PaginationProps) {
  const totalPages = Math.max(1, Math.ceil(total / perPage));
  const from = total === 0 ? 0 : (page - 1) * perPage + 1;
  const to = Math.min(page * perPage, total);

  return (
    <div className="flex items-center justify-between gap-4 px-2 py-2 text-sm text-fg-muted">
      <span>
        {total === 0 ? "0 items" : `${from}–${to} of ${total}`}
      </span>
      <div className="flex items-center gap-2">
        <Button
          size="icon"
          variant="ghost"
          disabled={page <= 1}
          onClick={() => onPageChange(page - 1)}
          aria-label="previous page"
        >
          <ChevronLeft className="size-4" />
        </Button>
        <span className="tabular-nums">
          Page {page} of {totalPages}
        </span>
        <Button
          size="icon"
          variant="ghost"
          disabled={page >= totalPages}
          onClick={() => onPageChange(page + 1)}
          aria-label="next page"
        >
          <ChevronRight className="size-4" />
        </Button>
      </div>
    </div>
  );
}
