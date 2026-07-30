import { useEffect } from "react";

/**
 * Warn before the browser unloads while in-flight or unreviewed work exists.
 *
 * Born from the GTM-upload flow: extraction runs 20–60s and nothing is
 * persisted until the operator confirms the review — so a mid-flight
 * refresh aborted the request and threw the work away with no trace. The
 * browser's native leave prompt is the only thing that can intercept a
 * refresh or tab-close; in-app navigation is separately discouraged by
 * visible copy at the call sites.
 */
export function useUnsavedWorkWarning(active: boolean): void {
  useEffect(() => {
    if (!active) return;
    const warn = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      // Chrome requires returnValue to be set for the prompt to appear.
      e.returnValue = "";
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [active]);
}
