/**
 * Minimal markdown renderer for agent replies.
 *
 * The agent emits markdown (bold names, bullet lists, headings). Plain
 * `<p className="whitespace-pre-wrap">` showed `**Sarah**` literally
 * instead of bolding. ReactMarkdown + remark-gfm handles bullets,
 * **bold**, *italic*, `code`, headings, links, and GitHub-flavored
 * markdown extras (tables, strikethrough, autolinks).
 *
 * Tailwind classes are applied per-element so output blends with the
 * chat-bubble container's font/color rather than fighting it.
 */

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

export function MarkdownText({ children }: { children: string }) {
  return (
    <div className="prose prose-sm max-w-none text-inherit [&_a]:text-accent [&_a]:underline">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          // Tighter spacing than prose defaults so chat bubbles stay compact.
          p: ({ children }) => <p className="mb-2 last:mb-0 leading-relaxed">{children}</p>,
          ul: ({ children }) => (
            <ul className="mb-2 list-disc pl-5 last:mb-0 [&>li]:mb-0.5">{children}</ul>
          ),
          ol: ({ children }) => (
            <ol className="mb-2 list-decimal pl-5 last:mb-0 [&>li]:mb-0.5">{children}</ol>
          ),
          li: ({ children }) => <li className="leading-relaxed">{children}</li>,
          h1: ({ children }) => (
            <h1 className="mb-1 mt-2 text-base font-semibold first:mt-0">{children}</h1>
          ),
          h2: ({ children }) => (
            <h2 className="mb-1 mt-2 text-sm font-semibold first:mt-0">{children}</h2>
          ),
          h3: ({ children }) => (
            <h3 className="mb-1 mt-1.5 text-sm font-semibold first:mt-0">{children}</h3>
          ),
          strong: ({ children }) => <strong className="font-semibold">{children}</strong>,
          em: ({ children }) => <em className="italic">{children}</em>,
          code: ({ children }) => (
            <code className="rounded bg-surface-3 px-1 py-0.5 font-mono text-xs">
              {children}
            </code>
          ),
          pre: ({ children }) => (
            <pre className="mb-2 overflow-x-auto rounded bg-surface-3 p-2 font-mono text-xs">
              {children}
            </pre>
          ),
          a: ({ href, children }) => (
            <a href={href} target="_blank" rel="noreferrer noopener">
              {children}
            </a>
          ),
          // GFM table styling.
          table: ({ children }) => (
            <div className="mb-2 overflow-x-auto">
              <table className="min-w-full border-collapse text-xs">{children}</table>
            </div>
          ),
          th: ({ children }) => (
            <th className="border border-border-subtle bg-surface-3 px-1.5 py-0.5 text-left font-semibold">
              {children}
            </th>
          ),
          td: ({ children }) => (
            <td className="border border-border-subtle px-1.5 py-0.5">{children}</td>
          ),
        }}
      >
        {children}
      </ReactMarkdown>
    </div>
  );
}
