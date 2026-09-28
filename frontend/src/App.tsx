import { Component, lazy, Suspense, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import type { Polygon } from "geojson";
import {
  ArrowRight,
  CircleHelp,
  Compass,
  Database,
  Download,
  Earth,
  ExternalLink,
  Globe2,
  Info,
  Layers3,
  Map as MapIcon,
  MapPinned,
  Menu,
  Mountain,
  MousePointer2,
  Pentagon,
  RotateCcw,
  Satellite,
  ScanLine,
  SlidersHorizontal,
  Sparkles,
  Spline,
  UploadCloud,
  X,
} from "lucide-react";
import MapCanvas from "./MapCanvas";
import { apiFetch } from "./api";
import PlaceSearch, { type Place } from "./PlaceSearch";
import ResultsPanel, { compact } from "./ResultsPanel";
import { downloadContourKml } from "./exporters";
import { satelliteTiles, type GoogleTiles } from "./google";
import type { Analysis, Basemap, Config, DrawMode, ExampleArea, MapFocus, RainfallPeriod, TerrainSource, UploadedDataset } from "./types";

const TerrainInspector = lazy(() => import("./TerrainInspector"));
const GoogleEarthView = lazy(() => import("./GoogleEarthView"));

/** Keeps an optional, third-party-backed view from ever blanking the whole planner. */
class OptionalFeature extends Component<{ children: ReactNode; fallback: () => void }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  componentDidCatch(error: unknown) { console.error("Optional view failed:", error); this.props.fallback(); }
  render() { return this.state.failed ? null : this.props.children; }
}

type Bounds = [number, number, number, number];
const EARTH_RADIUS = 6_371_000;
// Seasonal runoff fractions within the ranges of the CGWB Manual on Artificial
// Recharge (volumetric and Barlow tables); local measurements should replace them.
const RUNOFF_PRESETS = [
  { label: "Forest", value: 0.15, hint: "Tree cover (CGWB range 0.05–0.2)" },
  { label: "Paddy", value: 0.2, hint: "Flat bunded cropland (Barlow: 10–20%)" },
  { label: "Scrub", value: 0.25, hint: "Grass, scrub and fallow land" },
  { label: "Hilly", value: 0.35, hint: "Hills and plains with little cultivation (Barlow: 35%)" },
  { label: "Rocky", value: 0.5, hint: "Bare or rocky slopes (about 0.4–0.7)" },
  { label: "Built-up", value: 0.75, hint: "Roofs, roads and paved yards" },
];

const now = new Date();
const latestCompletedMonth = () => {
  const day = new Date(now.getFullYear(), now.getMonth() - 1, 1);
  return `${day.getFullYear()}-${String(day.getMonth() + 1).padStart(2, "0")}`;
};
// A Jun–Sep season is complete from October; a calendar year from January.
const latestMonsoonYear = now.getMonth() >= 9 ? now.getFullYear() : now.getFullYear() - 1;
const latestAnnualYear = now.getFullYear() - 1;

function boxPolygon([west, south, east, north]: Bounds): Polygon {
  return { type: "Polygon", coordinates: [[[west, south], [east, south], [east, north], [west, north], [west, south]]] };
}

function insetPolygon(bounds: Bounds, fraction = 0.08): Polygon {
  const [west, south, east, north] = bounds;
  const x = (east - west) * fraction;
  const y = (north - south) * fraction;
  return boxPolygon([west + x, south + y, east - x, north - y]);
}

function polygonBounds(polygon: Polygon): Bounds {
  const points = polygon.coordinates[0];
  const xs = points.map((point) => point[0]);
  const ys = points.map((point) => point[1]);
  return [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)];
}

function covers(outer: Bounds, polygon: Polygon) {
  const [west, south, east, north] = polygonBounds(polygon);
  return west >= outer[0] && east <= outer[2] && south >= outer[1] && north <= outer[3];
}

function squareAround([lon, lat]: [number, number], sideMetres: number): Bounds {
  const dLat = (sideMetres / 2 / EARTH_RADIUS) * (180 / Math.PI);
  const dLon = dLat / Math.cos((lat * Math.PI) / 180);
  return [lon - dLon, lat - dLat, lon + dLon, lat + dLat];
}

/** Equirectangular area and span; the server repeats this check. */
function measure(polygon: Polygon) {
  const ring = polygon.coordinates[0];
  const lat0 = ring.reduce((sum, point) => sum + point[1], 0) / ring.length;
  const k = (Math.PI / 180) * EARTH_RADIUS;
  const xy = ring.map(([lon, lat]) => [lon * k * Math.cos((lat0 * Math.PI) / 180), lat * k]);
  let twice = 0;
  for (let i = 0; i < xy.length - 1; i++) twice += xy[i][0] * xy[i + 1][1] - xy[i + 1][0] * xy[i][1];
  const xs = xy.map((point) => point[0]);
  const ys = xy.map((point) => point[1]);
  const width = Math.max(...xs) - Math.min(...xs);
  const height = Math.max(...ys) - Math.min(...ys);
  const hectares = Math.abs(twice) / 2 / 10_000;
  const problem = hectares < 0.25 ? "Area is under 0.25 ha; draw a larger area."
    : hectares > 10_000 ? "Area is over 10,000 ha; draw a smaller area."
      : Math.max(width, height) > 20_000 ? "Area is wider than 20 km; draw a smaller area." : null;
  return { hectares, width, height, problem };
}

function StepTitle({ number, title, description }: { number: string; title: string; description?: string }) {
  return (
    <div className="step-heading">
      <span className="step-number">{number}</span>
      <div><h3>{title}</h3>{description ? <p>{description}</p> : null}</div>
    </div>
  );
}

function hostLabel() {
  const host = window.location.hostname;
  return ["localhost", "127.0.0.1", "::1", ""].includes(host) ? "Local server" : host;
}

export default function App() {
  const [config, setConfig] = useState<Config | null>(null);
  const [configError, setConfigError] = useState<string | null>(null);
  const [selection, setSelection] = useState<Polygon | null>(null);
  const [focus, setFocus] = useState<MapFocus | null>(null);
  const [drawMode, setDrawMode] = useState<DrawMode>("none");
  const [source, setSource] = useState<TerrainSource>("sample");
  const [uploaded, setUploaded] = useState<UploadedDataset | null>(null);
  const [uploading, setUploading] = useState(false);
  const uploadInputRef = useRef<HTMLInputElement>(null);
  const [rainSource, setRainSource] = useState<"chirps" | "manual">("chirps");
  const [period, setPeriod] = useState<RainfallPeriod>("monsoon");
  const [year, setYear] = useState(Math.min(2025, latestMonsoonYear));
  const [month, setMonth] = useState("2025-08");
  const [rainfallMm, setRainfallMm] = useState(900);
  const [coefficient, setCoefficient] = useState(0.35);
  const [stage, setStage] = useState(2.5);
  const [maxCatchment, setMaxCatchment] = useState(100);
  const [basemap, setBasemap] = useState<Basemap>("topo");
  const [terrain3d, setTerrain3d] = useState(false);
  const [exaggeration, setExaggeration] = useState(2);
  const [showContours, setShowContours] = useState(true);
  const [result, setResult] = useState<Analysis | null>(null);
  const [activeSiteId, setActiveSiteId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [controlsOpen, setControlsOpen] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);
  const [terrainOpen, setTerrainOpen] = useState(false);
  const [earthOpen, setEarthOpen] = useState(false);
  const [googleTiles, setGoogleTiles] = useState<GoogleTiles | null>(null);
  const [examplesOpen, setExamplesOpen] = useState(false);
  const focusKey = useRef(0);

  const flyTo = (bounds: Bounds) => setFocus({ bounds, key: ++focusKey.current });

  useEffect(() => {
    apiFetch("/api/config")
      .then(async (response) => {
        if (!response.ok) throw new Error("Could not reach the analysis server.");
        return response.json() as Promise<Config>;
      })
      .then((data) => {
        setConfig(data);
        setSelection(insetPolygon(data.sample_bounds));
        setFocus({ bounds: data.sample_bounds, key: ++focusKey.current });
        setMonth(data.default_rainfall_month);
        setPeriod(data.default_rainfall_period ?? "monsoon");
        setYear(Math.min(data.default_rainfall_year ?? latestMonsoonYear, latestMonsoonYear));
        setMaxCatchment(data.default_max_catchment_ha ?? 100);
        // Optional: Google imagery replaces Sentinel-2 when the key and quota allow.
        if (data.google_maps_key) void satelliteTiles(data.google_maps_key).then(setGoogleTiles);
      })
      .catch((cause: Error) => setConfigError(cause.message));
  }, []);

  useEffect(() => {
    if (!helpOpen) return;
    const close = (event: KeyboardEvent) => { if (event.key === "Escape") setHelpOpen(false); };
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [helpOpen]);

  const coverage: Bounds | null = source === "sample" ? config?.sample_bounds ?? null : source === "upload" ? uploaded?.bounds ?? null : null;
  const stats = useMemo(() => (selection ? measure(selection) : null), [selection]);

  const clearResult = () => {
    setResult(null);
    setActiveSiteId(null);
    setTerrainOpen(false);
    setError(null);
  };

  const resetSample = () => {
    if (!config) return;
    setSelection(insetPolygon(config.sample_bounds));
    setSource("sample");
    setDrawMode("none");
    setNotice(null);
    flyTo(config.sample_bounds);
    clearResult();
  };

  const chooseSource = (next: TerrainSource) => {
    setSource(next);
    clearResult();
    setNotice(null);
    const bounds = next === "sample" ? config?.sample_bounds : next === "upload" ? uploaded?.bounds : null;
    if (bounds && selection && !covers(bounds, selection)) {
      setSelection(insetPolygon(bounds));
      flyTo(bounds);
      setNotice(`The selection was moved inside the ${next === "sample" ? "supplied contour map" : "uploaded contours"}.`);
    }
  };

  const pickExample = (example: ExampleArea) => {
    setExamplesOpen(false);
    setDrawMode("none");
    if (example.source === "sample" || !example.bbox) {
      resetSample();
      return;
    }
    setSource("copernicus");
    setSelection(boxPolygon(example.bbox));
    flyTo(example.bbox);
    setNotice(`${example.name}: ${example.note}`);
    clearResult();
  };

  const pickPlace = (place: Place) => {
    const square = squareAround(place.center, 2000);
    setSource("copernicus");
    setSelection(boxPolygon(square));
    flyTo(square);
    setNotice(`A 2 km square around ${place.label} is selected on Copernicus GLO-30. Draw to refine it.`);
    clearResult();
  };

  const uploadContours = async (file: File) => {
    if (!/\.(kml|kmz)$/i.test(file.name)) { setError("Choose a KML or KMZ contour file."); return; }
    if (file.size > 20 * 1024 * 1024) { setError("Contour upload must be 20 MB or smaller."); return; }
    setUploading(true);
    setError(null);
    try {
      const form = new FormData();
      form.append("contour_map", file);
      const response = await apiFetch("/api/terrain-upload", { method: "POST", body: form });
      const body = await response.json();
      if (!response.ok) throw new Error(typeof body.detail === "string" ? body.detail : "Could not read the contour file.");
      const dataset = body as UploadedDataset;
      setUploaded(dataset);
      setSelection(insetPolygon(dataset.bounds));
      setSource("upload");
      flyTo(dataset.bounds);
      clearResult();
      setDrawMode("none");
      setControlsOpen(false);
      setNotice(null);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not upload contours.");
    } finally {
      setUploading(false);
    }
  };

  const selectArea = (polygon: Polygon) => {
    setSelection(polygon);
    clearResult();
    setControlsOpen(false);
    setNotice(null);
    if (coverage && !covers(coverage, polygon)) {
      setSource("copernicus");
      setNotice("This area is outside the contour survey, so Copernicus GLO-30 (global 30 m elevation) will be used.");
    }
  };

  const areaProblem = stats?.problem ?? null;
  const analyze = async () => {
    if (!selection || loading || (source === "upload" && !uploaded)) return;
    if (areaProblem) { setError(areaProblem); return; }
    setLoading(true);
    setError(null);
    setControlsOpen(false);
    try {
      const response = await apiFetch("/api/analyze-area", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          area: selection,
          source,
          dataset_id: source === "upload" ? uploaded?.dataset_id : null,
          rainfall_source: rainSource,
          rainfall_period: period,
          rainfall_month: month,
          rainfall_year: year,
          rainfall_mm: rainfallMm,
          runoff_coefficient: coefficient,
          stage_m: stage,
          max_catchment_ha: maxCatchment,
        }),
      });
      const body = await response.json();
      if (!response.ok) throw new Error(typeof body.detail === "string" ? body.detail : "Analysis failed. Check the selected area and inputs.");
      const analysis = body as Analysis;
      setResult(analysis);
      setActiveSiteId(analysis.recommendations[0]?.site_id ?? null);
    } catch (cause) {
      setResult(null);
      setError(cause instanceof Error ? cause.message : "Could not run the analysis.");
    } finally {
      setLoading(false);
    }
  };

  const exportContours = async () => {
    if (!selection || exporting) return;
    setExporting(true);
    setError(null);
    try {
      await downloadContourKml({ area: selection, source, dataset_id: source === "upload" ? uploaded?.dataset_id ?? null : null });
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not export contours.");
    } finally {
      setExporting(false);
    }
  };

  const googleKey = config?.google_maps_key ?? null;
  const activeSite = result?.recommendations.find((item) => item.site_id === activeSiteId) ?? result?.recommendations[0] ?? null;
  const surveyUrl = source === "upload" && uploaded ? uploaded.contour_url : source === "sample" ? "/api/sample-contours" : null;
  const demContours = result && result.elevation.source_key === "copernicus" ? result.contours : null;
  const contourLabel = surveyUrl ? (source === "sample" ? "Supplied contours (1 m)" : "Uploaded contours") : demContours ? `DEM contours (${demContours.interval_m ?? "auto"} m)` : null;
  const years = (last: number) => Array.from({ length: last - 1980 }, (_, index) => last - index);

  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="brand">
          <div className="brand-symbol"><Spline size={22} strokeWidth={2.2} /></div>
          <div><strong>Village Pond Planner</strong><span>TERRAIN & WATER INTELLIGENCE</span></div>
        </div>
        <div className="header-center"><span className="header-divider" />Planning workspace<span className="workspace-pill">Phase 3</span></div>
        <nav className="header-actions">
          <button className="header-link" onClick={() => setHelpOpen(true)}><CircleHelp size={17} /> How it works</button>
          <a className="header-link" href="/docs" target="_blank" rel="noreferrer"><ExternalLink size={16} /> API docs</a>
          <span className="local-badge" title="Where this planner is served from"><span className="live-dot" /> {hostLabel()}</span>
        </nav>
        <button className="mobile-menu" aria-label="Open study area controls" onClick={() => setControlsOpen(true)}><Menu size={22} /></button>
      </header>

      <div className="workspace">
        <aside className={`controls-panel ${controlsOpen ? "controls-panel--open" : ""}`}>
          <div className="controls-heading">
            <div><span className="eyebrow">01 / FIELD WORKSPACE</span><h2>Study area</h2><p>Define the land you want to evaluate.</p></div>
            <button className="mobile-close" aria-label="Close controls" onClick={() => setControlsOpen(false)}><X size={21} /></button>
          </div>
          <div className="controls-scroll">
            <section className="control-section">
              <StepTitle number="01" title="Choose your area" description="Search above the map, pick an example, or draw." />
              <div className="draw-buttons">
                <button className={drawMode === "polygon" ? "draw-button draw-button--active" : "draw-button"} onClick={() => { setDrawMode("polygon"); setControlsOpen(false); }}>
                  <Pentagon size={17} /><span>Draw polygon</span>
                </button>
                <button className={drawMode === "rectangle" ? "draw-button draw-button--active" : "draw-button"} onClick={() => { setDrawMode("rectangle"); setControlsOpen(false); }}>
                  <ScanLine size={17} /><span>Draw rectangle</span>
                </button>
              </div>
              <div className="example-picker">
                <button type="button" className="text-button" aria-expanded={examplesOpen} onClick={() => setExamplesOpen((value) => !value)}>
                  <MapPinned size={15} /> Example areas with real terrain
                </button>
                {examplesOpen && config ? (
                  <ul className="example-list">
                    {config.examples.map((example) => (
                      <li key={example.id}>
                        <button type="button" onClick={() => pickExample(example)}>
                          <strong>{example.name}</strong>
                          <small>{example.region}</small>
                          <span>{example.source === "sample" ? "Supplied KML" : "Copernicus GLO-30"}</span>
                        </button>
                      </li>
                    ))}
                  </ul>
                ) : null}
              </div>
              <button className="text-button" onClick={resetSample}><RotateCcw size={15} /> Use supplied sample contours</button>
              {stats ? (
                <p className={`control-hint ${areaProblem ? "control-hint--error" : ""}`}>
                  {areaProblem ?? `Selected ${compact(stats.hectares, stats.hectares < 10 ? 1 : 0)} ha · ${compact(stats.width / 1000, 1)} × ${compact(stats.height / 1000, 1)} km. Draw again to replace it.`}
                </p>
              ) : <p className="control-hint">Draw a closed area on the map to continue.</p>}
            </section>

            <section className="control-section">
              <StepTitle number="02" title="Terrain source" description="Elevation used for flow routing." />
              <div className="option-list">
                {([
                  ["sample", <Layers3 size={18} key="i" />, "Supplied contours", "Khapri, beside IIT Bhilai · that area only"],
                  ["copernicus", <Database size={18} key="i" />, "Copernicus GLO-30", "30 m satellite DEM · anywhere on Earth"],
                  ["upload", <UploadCloud size={18} key="i" />, "Uploaded contours", uploaded ? uploaded.filename : "Your KML/KMZ survey"],
                ] as const).map(([value, icon, title, detail]) => (
                  <label key={value} className={source === value ? "option-row option-row--selected" : "option-row"}>
                    <input type="radio" name="source" checked={source === value} disabled={value === "upload" && !uploaded} onChange={() => chooseSource(value)} />
                    <span className="option-icon">{icon}</span>
                    <span className="option-text"><strong>{title}</strong><small>{detail}</small></span>
                    <span className="radio-indicator" />
                  </label>
                ))}
              </div>
              <input
                ref={uploadInputRef}
                className="visually-hidden"
                type="file"
                accept=".kml,.kmz,application/vnd.google-earth.kml+xml,application/vnd.google-earth.kmz"
                aria-label="Upload contour KML or KMZ"
                onChange={(event) => {
                  const file = event.currentTarget.files?.[0];
                  event.currentTarget.value = "";
                  if (file) void uploadContours(file);
                }}
              />
              <div className="source-actions">
                <button className="upload-action" type="button" disabled={uploading} onClick={() => uploadInputRef.current?.click()}>
                  {uploading ? <span className="spinner" /> : <UploadCloud size={16} />}
                  {uploading ? "Reading contour file…" : uploaded ? "Replace contour file" : "Upload KML or KMZ"}
                </button>
                <button className="upload-action upload-action--secondary" type="button" disabled={!selection || exporting || !!areaProblem} onClick={exportContours} title="Trace real contour lines for the selected area and download them as KML">
                  {exporting ? <span className="spinner" /> : <Download size={16} />}
                  {exporting ? "Tracing contours…" : "Get contour KML"}
                </button>
              </div>
              {uploaded ? (
                <p className="upload-summary">{uploaded.contour_features.toLocaleString()} contour lines · {uploaded.elevation_min_m}–{uploaded.elevation_max_m} m · kept for 2 hours</p>
              ) : <p className="upload-summary">"Get contour KML" traces real contours for any selected area; the file opens in Google Earth and can be uploaded here.</p>}
            </section>

            <section className="control-section">
              <StepTitle number="03" title="Rainfall scenario" description="Water delivered to the pond." />
              <div className="segmented">
                <button className={rainSource === "chirps" ? "segmented--active" : ""} onClick={() => setRainSource("chirps")}>CHIRPS v3 history</button>
                <button className={rainSource === "manual" ? "segmented--active" : ""} onClick={() => setRainSource("manual")}>Enter rainfall</button>
              </div>
              {rainSource === "chirps" ? (
                <>
                  <div className="segmented segmented--small" role="group" aria-label="Rainfall period">
                    {([["monsoon", "Jun–Sep"], ["annual", "Full year"], ["month", "One month"]] as const).map(([value, label]) => (
                      <button key={value} className={period === value ? "segmented--active" : ""} onClick={() => {
                        setPeriod(value);
                        if (value === "annual") setYear((current) => Math.min(current, latestAnnualYear));
                        if (value === "monsoon") setYear((current) => Math.min(current, latestMonsoonYear));
                      }}>{label}</button>
                    ))}
                  </div>
                  {period === "month" ? (
                    <label className="field-label">
                      Historical month
                      <input type="month" value={month} min="1981-01" max={latestCompletedMonth()} onChange={(event) => setMonth(event.target.value)} />
                      <small>Satellite + gauge monthly total on a 0.05° (~5 km) grid.</small>
                    </label>
                  ) : (
                    <label className="field-label">
                      {period === "monsoon" ? "Monsoon season of" : "Calendar year"}
                      <select value={year} onChange={(event) => setYear(Number(event.target.value))}>
                        {years(period === "monsoon" ? latestMonsoonYear : latestAnnualYear).map((value) => <option key={value} value={value}>{value}</option>)}
                      </select>
                      <small>{period === "monsoon" ? "Sum of June–September CHIRPS totals; most Indian runoff falls then." : "Sum of 12 monthly CHIRPS totals."}</small>
                    </label>
                  )}
                </>
              ) : (
                <label className="field-label">
                  Rainfall depth <span>mm</span>
                  <input type="number" min="0" max="5000" step="10" value={rainfallMm} onChange={(event) => setRainfallMm(Math.max(0, Math.min(5000, Number(event.target.value) || 0)))} />
                  <small>Assumed total for the period you want to plan for.</small>
                </label>
              )}
            </section>

            <section className="control-section control-section--last">
              <StepTitle number="04" title="Land cover & pond" description="Runoff fraction and embankment height." />
              <div className="preset-chips" role="group" aria-label="Runoff coefficient presets">
                {RUNOFF_PRESETS.map((preset) => (
                  <button key={preset.label} type="button" title={preset.hint} className={Math.abs(coefficient - preset.value) < 0.001 ? "chip chip--active" : "chip"} onClick={() => setCoefficient(preset.value)}>
                    {preset.label} <small>{preset.value}</small>
                  </button>
                ))}
              </div>
              <label className="field-label field-label--range">
                <span>Runoff coefficient <strong>{coefficient.toFixed(2)}</strong></span>
                <input type="range" min="0.05" max="0.95" step="0.05" value={coefficient} onChange={(event) => setCoefficient(Number(event.target.value))} />
                <small>Fraction of rainfall that runs off the catchment.</small>
              </label>
              <label className="field-label field-label--range">
                <span>Pond water stage <strong>{stage.toFixed(1)} m</strong></span>
                <input type="range" min="0.5" max="6" step="0.5" value={stage} onChange={(event) => setStage(Number(event.target.value))} />
                <small>Embankment height above the outlet ground; sets pond size.</small>
              </label>
              <details className="advanced">
                <summary>Advanced</summary>
                <label className="field-label field-label--range">
                  <span>Largest catchment for a small pond <strong>{maxCatchment} ha</strong></span>
                  <input type="range" min="10" max="500" step="10" value={maxCatchment} onChange={(event) => setMaxCatchment(Number(event.target.value))} />
                  <small>Bigger drainage lines are treated as streams needing an engineered spillway.</small>
                </label>
              </details>
            </section>
          </div>
          <div className="controls-footer">
            {error ? <div className="error-message" role="alert"><Info size={16} />{error}</div> : null}
            <button className="analyze-button" onClick={analyze} disabled={!selection || loading || !!areaProblem}>
              {loading ? <span className="spinner" /> : <Sparkles size={18} />} {loading ? "Analyzing terrain…" : "Analyze selected area"} <ArrowRight size={18} />
            </button>
            <p>Terrain-based screening · not an engineering design</p>
          </div>
        </aside>

        <main className="map-stage">
          <div className="map-topline">
            <div className="map-location">
              <span className="map-location-icon"><Compass size={19} /></span>
              <div>
                <strong>Terrain explorer</strong>
                <span>{source === "sample" ? "Supplied contours · Khapri, near IIT Bhilai" : source === "upload" ? `Uploaded survey · ${uploaded?.filename ?? "contours"}` : "Copernicus GLO-30 · global"}</span>
              </div>
            </div>
            <PlaceSearch onPick={pickPlace} googleKey={googleKey} />
            <div className="map-topline-right">
              {result ? (
                <>
                  {googleKey ? <button className="terrain-open-button" type="button" onClick={() => setEarthOpen(true)}><Earth size={16} /> Google 3D Earth</button> : null}
                  <button className="terrain-open-button" type="button" onClick={() => setTerrainOpen(true)}><Mountain size={16} /> Inspect 3D model</button>
                </>
              ) : (
                <span className="map-topline-badge"><span className="live-dot" /> {loading ? "Analyzing…" : "Ready"}</span>
              )}
            </div>
          </div>
          {config ? (
            <MapCanvas
              basemap={basemap}
              terrain3d={terrain3d}
              terrainExaggeration={exaggeration}
              showContours={showContours}
              contourUrl={surveyUrl}
              demContours={demContours}
              focus={focus}
              selection={selection}
              result={result}
              activeSiteId={activeSite?.site_id ?? null}
              drawMode={drawMode}
              onSelection={selectArea}
              onDrawComplete={() => setDrawMode("none")}
              onSiteClick={setActiveSiteId}
              googleKey={googleKey}
              googleTiles={googleTiles}
            />
          ) : (
            <div className="map-loading">{configError ?? "Loading the study area…"}</div>
          )}
          <div className="map-toolbar" role="toolbar" aria-label="Map view">
            <div className="map-toolbar-group" role="group" aria-label="Basemap">
              {([["topo", <MapIcon size={15} key="i" />, "Topo"], ["satellite", <Satellite size={15} key="i" />, "Satellite"], ["streets", <Globe2 size={15} key="i" />, "Streets"]] as const).map(([value, icon, label]) => (
                <button key={value} type="button" aria-pressed={basemap === value} className={basemap === value ? "is-active" : ""} onClick={() => setBasemap(value)}
                  title={value === "satellite" ? (googleTiles ? "Google satellite imagery with labels" : "Sentinel-2 cloudless imagery (10 m)") : undefined}>{icon}<span>{label}</span></button>
              ))}
            </div>
            <div className="map-toolbar-group" role="group" aria-label="Layers">
              <button type="button" aria-pressed={terrain3d} className={terrain3d ? "is-active" : ""} onClick={() => setTerrain3d((value) => !value)} title="Tilt the map over real 3D terrain"><Mountain size={15} /><span>3D</span></button>
              <button type="button" aria-pressed={showContours} className={showContours ? "is-active" : ""} onClick={() => setShowContours((value) => !value)} title="Show contour lines"><Layers3 size={15} /><span>Contours</span></button>
            </div>
            {terrain3d ? (
              <label className="map-toolbar-range">
                Relief {exaggeration}×
                <input type="range" min="1" max="5" step="0.5" value={exaggeration} onChange={(event) => setExaggeration(Number(event.target.value))} />
              </label>
            ) : null}
          </div>
          {notice ? (
            <div className="map-notice" role="status">
              <Info size={16} /> <span>{notice}</span>
              <button type="button" aria-label="Dismiss" onClick={() => setNotice(null)}><X size={14} /></button>
            </div>
          ) : null}
          {drawMode !== "none" ? (
            <div className="drawing-tip">
              <MousePointer2 size={17} />
              {drawMode === "polygon" ? "Click around the land; click the first point to finish." : "Drag across the land to draw a rectangle."}
              <button onClick={() => setDrawMode("none")}>Cancel</button>
            </div>
          ) : null}
          <div className="map-legend">
            <span><i className="legend-swatch legend-swatch--area" />Selected land</span>
            {result ? <span><i className="legend-swatch legend-swatch--catchment" />Catchment</span> : null}
            {result && result.recommendations.length > 1 ? <span><i className="legend-swatch legend-swatch--other" />Other options</span> : null}
            {result ? <span><i className="legend-swatch legend-swatch--pond" />Pond</span> : null}
            {result ? <span><i className="legend-swatch legend-swatch--site" />Outlet</span> : null}
            {showContours && contourLabel ? <span><i className="legend-swatch legend-swatch--contour" />{contourLabel}</span> : null}
          </div>
          <div className="map-mobile-actions">
            <button onClick={() => setControlsOpen(true)}><SlidersHorizontal size={17} /> Study area</button>
            <button onClick={() => setDrawMode("polygon")}><Pentagon size={17} /> Draw</button>
            {result ? <button onClick={() => setTerrainOpen(true)}><Mountain size={17} /> 3D model</button> : null}
            {result && googleKey ? <button onClick={() => setEarthOpen(true)}><Earth size={17} /> Google 3D</button> : null}
          </div>
        </main>
        <ResultsPanel result={result} activeSite={activeSite} onSiteChange={setActiveSiteId} loading={loading} onExportContours={exportContours} exporting={exporting} />
      </div>
      <div className="mobile-analyze-bar">
        <button onClick={analyze} disabled={!selection || loading || !!areaProblem}>
          {loading ? "Analyzing terrain…" : "Analyze selected area"} <ArrowRight size={18} />
        </button>
      </div>
      {controlsOpen ? <div className="mobile-scrim" onClick={() => setControlsOpen(false)} /> : null}
      {helpOpen ? (
        <div className="modal-backdrop" onClick={() => setHelpOpen(false)}>
          <div className="help-modal" role="dialog" aria-modal="true" aria-label="How it works" onClick={(event) => event.stopPropagation()}>
            <button className="modal-close" aria-label="Close" onClick={() => setHelpOpen(false)} autoFocus><X size={20} /></button>
            <span className="eyebrow">HOW IT WORKS</span>
            <h2>From terrain to a pond shortlist.</h2>
            <div className="help-steps">
              <div><span>01</span><strong>Choose land</strong><p>Search a place or pick an example, then draw a polygon or rectangle. Outside the supplied contours the global Copernicus GLO-30 DEM is used; you can also upload a KML/KMZ contour map.</p></div>
              <div><span>02</span><strong>Route the rain</strong><p>Sinks are filled and each cell drains to its steepest lower neighbour (D8). Up to 40 separated outlets off mapped water, roads and buildings are tested.</p></div>
              <div><span>03</span><strong>Hold the water</strong><p>An embankment at each outlet stores water only over land that drains to it. Sites are ranked by the smaller of CHIRPS or manual runoff and that storage.</p></div>
            </div>
            <div className="help-warning"><Info size={18} /> Results are planning indicators, not a pond design. 3D views exaggerate relief; verify land ownership, drainage and soil on site.</div>
            <button className="help-action" onClick={() => setHelpOpen(false)}>Explore the map <ArrowRight size={16} /></button>
          </div>
        </div>
      ) : null}
      {terrainOpen && result && activeSite ? (
        <Suspense fallback={<div className="terrain-loading">Preparing 3D terrain…</div>}>
          <TerrainInspector result={result} activeSite={activeSite} onSiteChange={setActiveSiteId} onClose={() => setTerrainOpen(false)} googleKey={googleKey} googleTiles={googleTiles} />
        </Suspense>
      ) : null}
      {earthOpen && result && activeSite && googleKey ? (
        <Suspense fallback={<div className="terrain-loading">Opening Google 3D Earth…</div>}>
          <OptionalFeature fallback={() => setEarthOpen(false)}>
            <GoogleEarthView result={result} activeSite={activeSite} googleKey={googleKey} onSiteChange={setActiveSiteId} onClose={() => setEarthOpen(false)} />
          </OptionalFeature>
        </Suspense>
      ) : null}
    </div>
  );
}
