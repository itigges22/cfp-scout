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
import { Minus, Plus, RotateCcw } from "lucide-react";
import { useMemo, useState } from "react";
import {
  ComposableMap,
  Geographies,
  Geography,
  Marker,
  ZoomableGroup,
} from "react-simple-maps";

const WORLD_TOPO_URL = "/world-110m.json";

type LocationItem = {
  id: string;
  name: string;
  city: string | null;
  country: string | null;
  lat: number;
  lng: number;
  status: string;
  start_date: string | null;
};

type CityCluster = {
  key: string; // "city|country"
  city: string;
  country: string | null;
  lng: number;
  lat: number;
  conferences: LocationItem[];
};

export function WorldMap({ items }: { items: LocationItem[] }) {
  const navigate = useNavigate();
  const [hoverKey, setHoverKey] = useState<string | null>(null);
  const [pinnedKey, setPinnedKey] = useState<string | null>(null);
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
  // sized by count, with a popover listing each event.
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
        });
      }
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
                {/* halo */}
                <circle
                  r={radius * 1.8}
                  fill="rgba(238,0,0,0.15)"
                  pointerEvents="none"
                />
                <circle
                  r={radius}
                  fill={isActive ? "rgba(255,80,80,1)" : "rgba(238,0,0,0.85)"}
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
            <p className="mt-1 text-[10px] italic text-fg-subtle">
              + {activeCluster.conferences.length - 25} more — open /conferences and filter by city.
            </p>
          )}
        </div>
      )}
      <div className="pointer-events-none absolute bottom-2 right-3 text-[10px] uppercase tracking-wider text-fg-subtle">
        Drag to pan · scroll to zoom · click a dot to pin · click a name to open
      </div>
    </div>
  );
}
