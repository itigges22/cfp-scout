/**
 * Dashboard world map — dark Equal-Earth projection with one dot per
 * city that hosts upcoming AI events. Hovering a dot reveals the list
 * of conferences in that city; clicking a name navigates to the
 * conference detail page.
 *
 * Backed by GET /api/v1/conferences/stats/by-location, which only
 * returns rows that the Nominatim geocoder has resolved. Conferences
 * that don't have lat/lng yet simply don't appear on the map — the
 * "Geocode missing" admin button populates them in the background.
 */

import { useNavigate } from "@tanstack/react-router";
import { HelpCircle, Minus, Plus, RotateCcw } from "lucide-react";
import { useMemo, useState } from "react";
import {
  ComposableMap,
  Geographies,
  Geography,
  Marker,
  ZoomableGroup,
} from "react-simple-maps";

const WORLD_TOPO_URL = "/world-110m.json";

type AttendanceStatus = "planned" | "attended" | "new";

type LocationItem = {
  id: string;
  name: string;
  city: string | null;
  country: string | null;
  lat: number;
  lng: number;
  status: string;
  start_date: string | null;
  attendance_status?: AttendanceStatus;
};

type CityCluster = {
  key: string; // "city|country"
  city: string;
  country: string | null;
  lng: number;
  lat: number;
  conferences: LocationItem[];
  // Strongest attendance signal in the cluster: planned > attended > new.
  // Drives the marker color (green / yellow / red).
  rolled_status: AttendanceStatus;
};

// Marker color palette by attendance status. Light fill + saturated
// stroke so dots stay visible on the dark map background.
const STATUS_FILL: Record<AttendanceStatus, string> = {
  planned: "rgba(34, 197, 94, 0.85)",   // green-500
  attended: "rgba(234, 179, 8, 0.85)",  // amber-500
  new: "rgba(239, 68, 68, 0.85)",       // red-500
};
const STATUS_FILL_ACTIVE: Record<AttendanceStatus, string> = {
  planned: "rgba(74, 222, 128, 1)",     // green-400
  attended: "rgba(250, 204, 21, 1)",    // yellow-400
  new: "rgba(248, 113, 113, 1)",        // red-400
};
const STATUS_HALO: Record<AttendanceStatus, string> = {
  planned: "rgba(34, 197, 94, 0.18)",
  attended: "rgba(234, 179, 8, 0.18)",
  new: "rgba(239, 68, 68, 0.15)",
};

// Pick the strongest signal in a cluster of mixed-status events.
// A city with ONE planned event + 5 new events should glow green —
// the user already committed to going there.
function rollupStatus(items: LocationItem[]): AttendanceStatus {
  if (items.some((it) => it.attendance_status === "planned")) return "planned";
  if (items.some((it) => it.attendance_status === "attended")) return "attended";
  return "new";
}

export function WorldMap({ items }: { items: LocationItem[] }) {
  const navigate = useNavigate();
  const [hoverKey, setHoverKey] = useState<string | null>(null);
  const [pinnedKey, setPinnedKey] = useState<string | null>(null);
  const [showHelp, setShowHelp] = useState(false);
  // Default to a moderate zoom centered on the dense AI-event clusters
  // (Europe + US). zoom=1 fits the whole globe but leaves Europe so
  // cramped that the dots overlap. zoom=1.8 shows individual cities
  // without scrolling. Reset button goes back here.
  const DEFAULT_VIEW = { center: [0, 30] as [number, number], zoom: 1.8 };
  // Pan/zoom state driven by ZoomableGroup. Wheel / drag handled by
  // d3-zoom under the hood; we just hold the latest center + zoom so the
  // +/-/reset buttons can update them.
  const [view, setView] = useState<{ center: [number, number]; zoom: number }>(
    () => ({ ...DEFAULT_VIEW }),
  );
  const setZoom = (z: number) =>
    setView((v) => ({ ...v, zoom: Math.max(1, Math.min(8, z)) }));
  const isAtDefault =
    view.zoom === DEFAULT_VIEW.zoom &&
    view.center[0] === DEFAULT_VIEW.center[0] &&
    view.center[1] === DEFAULT_VIEW.center[1];

  // Cluster by (city, country) so 7 events in Boston render as one dot
  // sized by count, with a popover listing each event. We compute the
  // ``rolled_status`` in a second pass so cluster color reflects the
  // strongest signal in the cluster (one planned event in a city of
  // unseen events should still glow green).
  const clusters = useMemo<CityCluster[]>(() => {
    const m = new Map<string, CityCluster>();
    for (const it of items) {
      const city = it.city ?? "Unknown";
      const key = `${city}|${it.country ?? ""}`;
      const existing = m.get(key);
      if (existing) {
        existing.conferences.push(it);
      } else {
        m.set(key, {
          key,
          city,
          country: it.country,
          // Centroid of the first event in the cluster — close enough,
          // the per-conference offset is at most a few km.
          lat: it.lat,
          lng: it.lng,
          conferences: [it],
          rolled_status: "new", // filled in below
        });
      }
    }
    for (const cluster of m.values()) {
      cluster.rolled_status = rollupStatus(cluster.conferences);
    }
    return [...m.values()];
  }, [items]);

  const maxCount = Math.max(1, ...clusters.map((c) => c.conferences.length));
  const activeKey = pinnedKey ?? hoverKey;
  const activeCluster = activeKey
    ? clusters.find((c) => c.key === activeKey) ?? null
    : null;

  // Marker radius shrinks as the user zooms in — the SVG would otherwise
  // scale dots up with the rest of the geography, making them huge.
  const markerScale = 1 / view.zoom;

  return (
    <div className="relative flex h-full w-full overflow-hidden rounded-lg border border-border bg-surface-1">
      {/* Map fills its container — fixed viewBox + h/w 100% means the SVG
          scales to whatever height the parent gives it. preserveAspectRatio
          (default "xMidYMid meet") centers without distortion. */}
      <ComposableMap
        projection="geoEqualEarth"
        projectionConfig={{ scale: 170 }}
        width={980}
        height={460}
        style={{ width: "100%", height: "100%", display: "block" }}
        onClick={() => setPinnedKey(null)}
      >
        <ZoomableGroup
          center={view.center}
          zoom={view.zoom}
          minZoom={1}
          maxZoom={8}
          translateExtent={[[-200, -100], [1180, 560]]}
          onMoveEnd={({ coordinates, zoom }) =>
            setView({ center: coordinates as [number, number], zoom })
          }
        >
          <Geographies geography={WORLD_TOPO_URL}>
            {({ geographies }) =>
              geographies.map((geo) => (
                <Geography
                  key={geo.rsmKey}
                  geography={geo}
                  fill="rgba(35, 35, 40, 1)"
                  stroke="rgba(46, 46, 53, 1)"
                  strokeWidth={0.4}
                  style={{
                    default: { outline: "none" },
                    hover: { outline: "none" },
                    pressed: { outline: "none" },
                  }}
                />
              ))
            }
          </Geographies>
          {clusters.map((c) => {
            const count = c.conferences.length;
            const radius = (3 + Math.sqrt(count / maxCount) * 8) * markerScale;
            const strokeW = 0.6 * markerScale;
            const isActive = c.key === activeKey;
            return (
              <Marker
                key={c.key}
                coordinates={[c.lng, c.lat]}
                onMouseEnter={() => setHoverKey(c.key)}
                onMouseLeave={() => setHoverKey(null)}
                onClick={(e) => {
                  e.stopPropagation();
                  setPinnedKey(c.key === pinnedKey ? null : c.key);
                }}
              >
                {/* halo — color matches cluster's strongest attendance signal */}
                <circle
                  r={radius * 1.8}
                  fill={STATUS_HALO[c.rolled_status]}
                  pointerEvents="none"
                />
                <circle
                  r={radius}
                  fill={
                    isActive
                      ? STATUS_FILL_ACTIVE[c.rolled_status]
                      : STATUS_FILL[c.rolled_status]
                  }
                  stroke="rgba(255,255,255,0.85)"
                  strokeWidth={isActive ? strokeW * 1.6 : strokeW}
                  style={{ cursor: "pointer" }}
                />
              </Marker>
            );
          })}
        </ZoomableGroup>
      </ComposableMap>

      {/* Zoom controls — overlay top-right. Wheel + drag work on the
          map itself; these are the explicit affordance. */}
      <div className="absolute right-3 top-3 flex flex-col gap-1 rounded-md border border-border-strong bg-surface-2/95 p-1 shadow backdrop-blur">
        <button
          type="button"
          onClick={() => setZoom(view.zoom * 1.5)}
          disabled={view.zoom >= 8}
          aria-label="Zoom in"
          title="Zoom in (or scroll wheel up)"
          className="rounded p-1 text-fg hover:bg-surface-3 disabled:opacity-40"
        >
          <Plus className="h-3.5 w-3.5" />
        </button>
        <button
          type="button"
          onClick={() => setZoom(view.zoom / 1.5)}
          disabled={view.zoom <= 1}
          aria-label="Zoom out"
          title="Zoom out (or scroll wheel down)"
          className="rounded p-1 text-fg hover:bg-surface-3 disabled:opacity-40"
        >
          <Minus className="h-3.5 w-3.5" />
        </button>
        <button
          type="button"
          onClick={() => setView({ ...DEFAULT_VIEW })}
          disabled={isAtDefault}
          aria-label="Reset view"
          title="Reset zoom + center"
          className="rounded p-1 text-fg-muted hover:bg-surface-3 disabled:opacity-40"
        >
          <RotateCcw className="h-3.5 w-3.5" />
        </button>
      </div>

      {activeCluster && (
        <div className="pointer-events-auto absolute left-3 top-3 max-w-xs rounded-md border border-border-strong bg-surface-2/95 p-3 text-xs text-fg shadow-lg backdrop-blur">
          <div className="mb-2 flex items-baseline justify-between gap-3">
            <strong className="text-sm">
              {activeCluster.city}
              {activeCluster.country ? `, ${activeCluster.country}` : ""}
            </strong>
            <span className="text-fg-muted tabular-nums">
              {activeCluster.conferences.length} event
              {activeCluster.conferences.length === 1 ? "" : "s"}
            </span>
          </div>
          <ul className="flex max-h-48 flex-col gap-1 overflow-y-auto">
            {activeCluster.conferences.slice(0, 25).map((c) => (
              <li key={c.id}>
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    navigate({ to: "/conferences/$id", params: { id: c.id } });
                  }}
                  className="block w-full truncate rounded px-1.5 py-1 text-left text-xs hover:bg-surface-3"
                >
                  <span className="truncate">{c.name}</span>
                  {c.start_date && (
                    <span className="ml-1 text-fg-subtle">· {c.start_date}</span>
                  )}
                </button>
              </li>
            ))}
          </ul>
          {activeCluster.conferences.length > 25 && (
            <p className="mt-1 text-xs italic text-fg-subtle">
              + {activeCluster.conferences.length - 25} more — open /conferences and filter by city.
            </p>
          )}
        </div>
      )}
      {/* Status legend — bottom-left, away from zoom controls + hint
          text. Counts come from the cluster set so the user sees the
          relative breadth of each bucket at a glance. */}
      <div className="absolute bottom-3 left-3 rounded-md border border-border-strong bg-surface-2/95 px-3 py-2 text-xs text-fg shadow backdrop-blur">
        <div className="mb-1 text-xs font-semibold uppercase tracking-wider text-fg-muted">
          Attendance
        </div>
        <ul className="space-y-0.5">
          {(
            [
              { s: "planned" as const, label: "Planning to attend" },
              { s: "attended" as const, label: "Previously attended" },
              { s: "new" as const, label: "Never attended" },
            ]
          ).map(({ s, label }) => {
            const count = clusters.filter((c) => c.rolled_status === s).length;
            return (
              <li key={s} className="flex items-center gap-2">
                <span
                  className="inline-block size-2.5 rounded-full"
                  style={{ backgroundColor: STATUS_FILL[s] }}
                  aria-hidden
                />
                <span className="flex-1">{label}</span>
                <span className="tabular-nums text-fg-muted">{count}</span>
              </li>
            );
          })}
        </ul>
      </div>
      <div className="absolute left-3 top-3">
        <button
          type="button"
          onClick={() => setShowHelp((v) => !v)}
          className="rounded-full border border-border-strong bg-surface-2/95 p-1.5 text-fg-muted shadow backdrop-blur hover:bg-surface-3 hover:text-fg"
          aria-label="Map controls help"
        >
          <HelpCircle className="h-3.5 w-3.5" />
        </button>
        {showHelp && (
          <div className="absolute left-0 top-full mt-1.5 w-48 rounded-md border border-border-strong bg-surface-2/95 px-3 py-2 text-xs text-fg-muted shadow-lg backdrop-blur">
            <span className="inline-block w-10 font-bold text-fg">Drag</span> to pan<br />
            <span className="inline-block w-10 font-bold text-fg">Scroll</span> to zoom<br />
            <span className="inline-block w-10 font-bold text-fg">Click</span> a dot to pin<br />
            <span className="inline-block w-10 font-bold text-fg">Click</span> a name to open
          </div>
        )}
      </div>
    </div>
  );
}
