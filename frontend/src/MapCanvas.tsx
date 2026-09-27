import { useEffect, useRef, useState } from "react";
import type { Feature, FeatureCollection, Geometry, Polygon } from "geojson";
import * as maplibregl from "maplibre-gl";
import type { GeoJSONSource, Map as MapLibreMap, StyleSpecification } from "maplibre-gl";
import mapWorkerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";
import {
  TerraDraw,
  TerraDrawPolygonMode,
  TerraDrawRectangleMode,
  TerraDrawRenderMode,
} from "terra-draw";
import { TerraDrawMapLibreGLAdapter } from "terra-draw-maplibre-gl-adapter";
import { BASEMAPS, TERRAIN_TILES, basemapById } from "./basemaps";
import { apiFetch } from "./api";
import type { Analysis, Basemap, ContourCollection, DrawMode, MapFocus } from "./types";

interface Props {
  basemap: Basemap;
  terrain3d: boolean;
  terrainExaggeration: number;
  showContours: boolean;
  contourUrl: string | null;
  demContours: ContourCollection | null;
  focus: MapFocus | null;
  selection: Polygon | null;
  result: Analysis | null;
  activeSiteId: string | null;
  drawMode: DrawMode;
  onSelection: (polygon: Polygon) => void;
  onDrawComplete: () => void;
  onSiteClick: (siteId: string) => void;
}

const empty: FeatureCollection = { type: "FeatureCollection", features: [] };
const collection = (features: Feature[]): FeatureCollection => ({ type: "FeatureCollection", features });
const feature = (geometry: Geometry | null): FeatureCollection =>
  geometry ? collection([{ type: "Feature", properties: {}, geometry }]) : empty;

function setData(map: MapLibreMap, id: string, data: FeatureCollection) {
  (map.getSource(id) as GeoJSONSource | undefined)?.setData(data);
}

function initialStyle(): StyleSpecification {
  const sources: StyleSpecification["sources"] = {
    "terrain-dem": { type: "raster-dem", tiles: TERRAIN_TILES.tiles, encoding: TERRAIN_TILES.encoding, tileSize: 256, maxzoom: TERRAIN_TILES.maxzoom, attribution: TERRAIN_TILES.attribution },
    // A separate source for shading avoids resampling conflicts with the 3D mesh.
    "hillshade-dem": { type: "raster-dem", tiles: TERRAIN_TILES.tiles, encoding: TERRAIN_TILES.encoding, tileSize: 256, maxzoom: TERRAIN_TILES.maxzoom },
  };
  for (const item of BASEMAPS) {
    sources[`basemap-${item.id}`] = { type: "raster", tiles: item.tiles, tileSize: 256, maxzoom: item.maxzoom, attribution: item.attribution };
  }
  return {
    version: 8,
    name: "Village pond planner",
    sources,
    layers: [
      { id: "background", type: "background", paint: { "background-color": "#e9eee9" } },
      ...BASEMAPS.map((item) => ({
        id: `basemap-${item.id}`,
        type: "raster" as const,
        source: `basemap-${item.id}`,
        layout: { visibility: item.id === "topo" ? ("visible" as const) : ("none" as const) },
        paint: item.id === "satellite" ? { "raster-saturation": -0.05, "raster-contrast": 0.05 } : {},
      })),
      {
        id: "hillshade",
        type: "hillshade",
        source: "hillshade-dem",
        layout: { visibility: "none" },
        paint: { "hillshade-exaggeration": 0.45, "hillshade-shadow-color": "#1f2d2a", "hillshade-highlight-color": "#ffffff" },
      },
    ],
  };
}

export default function MapCanvas({
  basemap,
  terrain3d,
  terrainExaggeration,
  showContours,
  contourUrl,
  demContours,
  focus,
  selection,
  result,
  activeSiteId,
  drawMode,
  onSelection,
  onDrawComplete,
  onSiteClick,
}: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const drawRef = useRef<TerraDraw | null>(null);
  const [ready, setReady] = useState(false);
  const callbacks = useRef({ onSelection, onDrawComplete, onSiteClick });
  callbacks.current = { onSelection, onDrawComplete, onSiteClick };
  const initialFocus = useRef(focus);

  // The map is created exactly once; everything else updates it in place so
  // switching terrain source never drops the selection or the drawn state.
  useEffect(() => {
    if (!containerRef.current) return;
    maplibregl.setWorkerUrl(mapWorkerUrl);
    const start = initialFocus.current?.bounds;
    const map = new maplibregl.Map({
      container: containerRef.current,
      style: initialStyle(),
      center: start ? [(start[0] + start[2]) / 2, (start[1] + start[3]) / 2] : [81.3, 21.25],
      zoom: 13,
      minZoom: 1.5,
      maxZoom: 18.5,
      maxPitch: 75,
      attributionControl: false,
    });
    mapRef.current = map;
    map.addControl(new maplibregl.NavigationControl({ showCompass: true, visualizePitch: true }), "top-right");
    map.addControl(new maplibregl.GlobeControl(), "top-right");
    map.addControl(new maplibregl.ScaleControl({ maxWidth: 110, unit: "metric" }), "bottom-left");
    map.addControl(new maplibregl.AttributionControl({ compact: true }), "bottom-right");

    map.on("load", () => {
      // Keep the long data credits one click away instead of covering the map.
      containerRef.current?.querySelector(".maplibregl-ctrl-attrib")?.classList.remove("maplibregl-compact-show");
      if (start) map.fitBounds([[start[0], start[1]], [start[2], start[3]]], { padding: 55, duration: 0 });
      map.setSky({
        "sky-color": "#8cc7f0",
        "horizon-color": "#e8f3f5",
        "fog-color": "#e8f0ee",
        "sky-horizon-blend": 0.6,
        "horizon-fog-blend": 0.5,
        "fog-ground-blend": 0.4,
        "atmosphere-blend": ["interpolate", ["linear"], ["zoom"], 0, 1, 6, 0.6, 10, 0],
      });

      for (const id of ["contours-survey", "contours-dem", "selection", "catchments", "pond", "sites"]) {
        map.addSource(id, { type: "geojson", data: empty });
      }
      const contourPaint = (width: number) => ({
        "line-color": "#8a5a2b",
        "line-width": ["case", ["get", "major"], width * 2, width] as unknown as number,
        "line-opacity": ["case", ["get", "major"], 0.8, 0.38] as unknown as number,
      });
      for (const id of ["contours-survey", "contours-dem"]) {
        map.addLayer({ id: `${id}-lines`, type: "line", source: id, paint: contourPaint(0.6), layout: { "line-join": "round" } });
        map.addLayer({
          id: `${id}-labels`,
          type: "symbol",
          source: id,
          filter: ["==", ["get", "major"], true],
          minzoom: 13,
          layout: {
            "symbol-placement": "line",
            "text-field": ["concat", ["to-string", ["get", "elevation_m"]], " m"],
            "text-size": 10.5,
            "text-font": ["Open Sans Semibold"],
            "symbol-spacing": 320,
          },
          paint: { "text-color": "#6b4220", "text-halo-color": "#fdf8ee", "text-halo-width": 1.4 },
        });
      }
      map.addLayer({ id: "selection-fill", type: "fill", source: "selection", paint: { "fill-color": "#0e4f5c", "fill-opacity": 0.06 } });
      map.addLayer({ id: "selection-casing", type: "line", source: "selection", paint: { "line-color": "#ffffff", "line-width": 4.5, "line-opacity": 0.85 } });
      map.addLayer({ id: "selection-border", type: "line", source: "selection", paint: { "line-color": "#123c46", "line-width": 2.2, "line-dasharray": [2, 1.4] } });
      map.addLayer({
        id: "catchment-fill",
        type: "fill",
        source: "catchments",
        paint: {
          "fill-color": ["case", ["get", "active"], "#11a7a2", "#7c8ea3"],
          "fill-opacity": ["case", ["get", "active"], 0.3, 0.1],
        },
      });
      map.addLayer({
        id: "catchment-border",
        type: "line",
        source: "catchments",
        paint: {
          "line-color": ["case", ["get", "active"], "#05706f", "#56677b"],
          "line-width": ["case", ["get", "active"], 2.4, 1.2],
          "line-dasharray": ["case", ["get", "active"], ["literal", [1, 0]], ["literal", [2, 2]]],
        },
      });
      map.addLayer({ id: "pond-fill", type: "fill", source: "pond", paint: { "fill-color": "#1c6fd1", "fill-opacity": ["case", ["get", "active"], 0.78, 0.45] } });
      map.addLayer({ id: "pond-border", type: "line", source: "pond", paint: { "line-color": "#0b3f7a", "line-width": ["case", ["get", "active"], 2, 1] } });
      map.addLayer({
        id: "site-halos",
        type: "circle",
        source: "sites",
        filter: ["==", ["get", "active"], true],
        paint: { "circle-radius": 20, "circle-color": "#f28a3c", "circle-opacity": 0.25, "circle-pitch-alignment": "map" },
      });
      map.addLayer({
        id: "site-dots",
        type: "circle",
        source: "sites",
        paint: {
          "circle-radius": ["case", ["get", "active"], 11, 9],
          "circle-color": ["case", ["get", "active"], "#e8702a", "#ffffff"],
          "circle-stroke-color": ["case", ["get", "active"], "#ffffff", "#c35a1f"],
          "circle-stroke-width": 2.5,
        },
      });
      map.addLayer({
        id: "site-numbers",
        type: "symbol",
        source: "sites",
        layout: {
          "text-field": ["get", "rank"],
          "text-size": 11.5,
          "text-font": ["Open Sans Bold"],
          "text-allow-overlap": true,
          "text-ignore-placement": true,
        },
        paint: { "text-color": ["case", ["get", "active"], "#ffffff", "#9a4514"] },
      });
      map.addLayer({
        id: "site-labels",
        type: "symbol",
        source: "sites",
        layout: {
          "text-field": ["get", "label"],
          "text-size": 11.5,
          "text-offset": [0, -2.1],
          "text-font": ["Open Sans Semibold"],
          "text-allow-overlap": true,
        },
        paint: { "text-color": "#2c2a24", "text-halo-color": "#ffffff", "text-halo-width": 1.6 },
      });
      map.on("click", "site-dots", (event) => {
        const id = event.features?.[0]?.properties?.site_id;
        if (typeof id === "string") callbacks.current.onSiteClick(id);
      });
      map.on("mouseenter", "site-dots", () => { map.getCanvas().style.cursor = "pointer"; });
      map.on("mouseleave", "site-dots", () => { map.getCanvas().style.cursor = ""; });

      const draw = new TerraDraw({
        adapter: new TerraDrawMapLibreGLAdapter({ map }),
        modes: [
          new TerraDrawPolygonMode(),
          new TerraDrawRectangleMode({ drawInteraction: "click-drag" }),
          new TerraDrawRenderMode({ modeName: "idle", styles: {} }),
        ],
      });
      draw.start();
      draw.setMode("idle");
      draw.on("finish", (id, context) => {
        if (context.action !== "draw") return;
        const drawn = draw.getSnapshot().find((item) => item.id === id);
        if (drawn?.geometry.type === "Polygon") {
          callbacks.current.onSelection(drawn.geometry as Polygon);
          draw.clear();
          draw.setMode("idle");
          callbacks.current.onDrawComplete();
        }
      });
      drawRef.current = draw;
      setReady(true);
    });

    return () => {
      drawRef.current?.stop();
      drawRef.current = null;
      map.remove();
      mapRef.current = null;
      setReady(false);
    };
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;
    for (const item of BASEMAPS) {
      map.setLayoutProperty(`basemap-${item.id}`, "visibility", item.id === basemap ? "visible" : "none");
    }
    const style = basemapById(basemap);
    for (const id of ["contours-survey", "contours-dem"]) {
      map.setPaintProperty(`${id}-lines`, "line-color", style.contour);
      map.setPaintProperty(`${id}-labels`, "text-color", basemap === "satellite" ? "#ffe8b0" : "#6b4220");
      map.setPaintProperty(`${id}-labels`, "text-halo-color", style.contourLabelHalo);
    }
    map.setPaintProperty("selection-border", "line-color", style.outline);
    map.setPaintProperty("selection-casing", "line-color", basemap === "satellite" ? "#0b2530" : "#ffffff");
  }, [ready, basemap]);

  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;
    if (terrain3d) {
      map.setTerrain({ source: "terrain-dem", exaggeration: terrainExaggeration });
      map.setLayoutProperty("hillshade", "visibility", basemap === "topo" ? "none" : "visible");
    } else {
      map.setTerrain(null);
      map.setLayoutProperty("hillshade", "visibility", "none");
    }
  }, [ready, terrain3d, terrainExaggeration, basemap]);

  const lastTerrain3d = useRef(terrain3d);
  useEffect(() => {
    const map = mapRef.current;
    // Animate only when the 3D toggle changes, not when the map first loads.
    if (!ready || !map || lastTerrain3d.current === terrain3d) return;
    lastTerrain3d.current = terrain3d;
    map.easeTo(terrain3d ? { pitch: 62, bearing: map.getBearing() || -18, duration: 900 } : { pitch: 0, bearing: 0, duration: 700 });
  }, [ready, terrain3d]);

  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;
    for (const id of ["contours-survey", "contours-dem"]) {
      map.setLayoutProperty(`${id}-lines`, "visibility", showContours ? "visible" : "none");
      map.setLayoutProperty(`${id}-labels`, "visibility", showContours ? "visible" : "none");
    }
  }, [ready, showContours]);

  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;
    setData(map, "contours-survey", empty);
    if (!contourUrl) return;
    const controller = new AbortController();
    apiFetch(contourUrl, { signal: controller.signal })
      .then((response) => (response.ok ? response.json() : null))
      .then((data: FeatureCollection | null) => { if (data) setData(map, "contours-survey", data); })
      .catch(() => { /* contours are optional visual context */ });
    return () => controller.abort();
  }, [ready, contourUrl]);

  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;
    setData(map, "contours-dem", demContours ?? empty);
  }, [ready, demContours]);

  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map || !focus) return;
    const [west, south, east, north] = focus.bounds;
    map.fitBounds([[west, south], [east, north]], { padding: 70, maxZoom: 15.5, duration: 900, pitch: map.getPitch(), bearing: map.getBearing() });
  }, [ready, focus]);

  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;
    setData(map, "selection", feature(selection));
  }, [ready, selection]);

  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;
    const sites = result?.recommendations ?? [];
    const active = sites.find((site) => site.site_id === activeSiteId) ?? sites[0];
    const withActive = (geometry: Geometry, siteId: string, extra: Record<string, unknown> = {}): Feature => ({
      type: "Feature", geometry, properties: { site_id: siteId, active: siteId === active?.site_id, ...extra },
    });
    // Draw the active catchment last so it sits above the muted alternatives.
    const ordered = [...sites].sort((a, b) => Number(a.site_id === active?.site_id) - Number(b.site_id === active?.site_id));
    setData(map, "catchments", collection(ordered.map((site) => withActive(site.catchment.geometry, site.site_id))));
    setData(map, "pond", collection(ordered.map((site) => withActive(site.pond_region, site.site_id))));
    setData(map, "sites", collection(sites.map((site, index) => withActive(site.location, site.site_id, {
      rank: String(index + 1),
      label: site.site_id === active?.site_id ? `SITE ${String(index + 1).padStart(2, "0")}` : "",
    }))));
  }, [ready, result, activeSiteId]);

  useEffect(() => {
    const draw = drawRef.current;
    const map = mapRef.current;
    if (!ready || !draw || !map) return;
    draw.setMode(drawMode === "none" ? "idle" : drawMode);
    // Drawing on a tilted, terrain-draped map is imprecise; draw top-down.
    if (drawMode !== "none" && map.getPitch() > 1) map.easeTo({ pitch: 0, duration: 400 });
  }, [ready, drawMode]);

  return (
    <div
      className={`map-canvas ${drawMode !== "none" ? "map-canvas--drawing" : ""}`}
      ref={containerRef}
      data-ready={ready ? "true" : "false"}
      aria-label="Interactive terrain map"
    />
  );
}
