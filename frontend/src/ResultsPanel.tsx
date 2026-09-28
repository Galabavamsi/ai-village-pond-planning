import { useState } from "react";
import {
  AlertTriangle,
  Check,
  ChevronDown,
  CloudRain,
  Download,
  Droplets,
  Earth,
  ExternalLink,
  FileCode2,
  Info,
  MapPinned,
  Ruler,
  Waves,
} from "lucide-react";
import StageChart, { RainBars } from "./StageChart";
import { downloadResultsGeoJSON, downloadResultsKml } from "./exporters";
import { googleEarthLink, googleMapsLink } from "./google";
import type { Analysis, Site } from "./types";

export const compact = (value: number, digits = 0) =>
  new Intl.NumberFormat("en-IN", { maximumFractionDigits: digits }).format(value);
const hemi = (value: number, positive: string, negative: string) => `${Math.abs(value).toFixed(5)}° ${value >= 0 ? positive : negative}`;
const siteLabel = (index: number) => `Site ${String(index + 1).padStart(2, "0")}`;
// Mission Amrit Sarovar (MoRD, phase 2): plains ponds of at least 1 acre and
// about 10,000 m³. MGNREGA model farm pond: 20 × 20 m top, 3 m deep, ≈ 880 m³.
const AMRIT_SAROVAR_AREA_M2 = 4047;
const AMRIT_SAROVAR_STORAGE_M3 = 10_000;
const FARM_POND_M3 = 880;

function Metric({ icon, label, value, unit, note, variant }: {
  icon: React.ReactNode; label: string; value: string; unit?: string; note?: string; variant?: "teal" | "blue" | "orange";
}) {
  return (
    <div className={`metric metric--${variant ?? "plain"}`}>
      <div className="metric-top"><span className="metric-icon">{icon}</span><span>{label}</span></div>
      <div className="metric-value">{value}<small>{unit}</small></div>
      {note ? <p>{note}</p> : null}
    </div>
  );
}

function EmptyResults({ loading }: { loading: boolean }) {
  return (
    <aside className="results-panel">
      <div className="panel-heading">
        <div><span className="eyebrow">PLANNING OUTPUT</span><h2>Analysis results</h2></div>
        <span className="status-pill status-pill--muted">{loading ? "Running" : "Pending"}</span>
      </div>
      <div className="results-empty">
        <div className={`empty-illustration ${loading ? "empty-illustration--busy" : ""}`}>
          <div className="empty-ring empty-ring--one" /><div className="empty-ring empty-ring--two" />
          <MapPinned size={35} strokeWidth={1.55} />
        </div>
        <span className="eyebrow">{loading ? "WORKING" : "READY WHEN YOU ARE"}</span>
        <h3>{loading ? "Reading the terrain…" : "Find the best place to hold water."}</h3>
        <p>
          {loading
            ? "Fetching elevation, rainfall and mapped features, routing flow and testing up to 40 outlets. Usually 5–15 seconds."
            : "Search or pick a place, draw the land, set a rainfall scenario, then run the analysis to compare pond sites, their catchments and water volumes."}
        </p>
        <div className="empty-steps">
          <span><Check size={14} /> Pond site</span><span><Check size={14} /> Catchment</span><span><Check size={14} /> Water volume</span>
        </div>
      </div>
      <div className="results-footnote"><Info size={16} /><span>These are early-stage screening estimates. Field survey and land records are required before construction.</span></div>
    </aside>
  );
}

export default function ResultsPanel({ result, activeSite, onSiteChange, loading, onExportContours, exporting }: {
  result: Analysis | null;
  activeSite: Site | null;
  onSiteChange: (id: string) => void;
  loading: boolean;
  onExportContours: () => void;
  exporting: boolean;
}) {
  const [showAllLimits, setShowAllLimits] = useState(false);
  if (!result || !activeSite) return <EmptyResults loading={loading} />;
  const unverified = result.water_screening.status === "unavailable";
  const index = result.recommendations.findIndex((item) => item.site_id === activeSite.site_id);
  const { water, pond, catchment } = activeSite;
  const maxWater = Math.max(water.potential_runoff_m3, pond.screening_storage_m3, 1);
  const pct = (value: number) => `${Math.min(100, (value / maxWater) * 100)}%`;
  const rainfallLabel = result.rainfall.source === "chirps"
    ? `CHIRPS v3 · ${result.rainfall.period === "month" ? result.rainfall.month : `${result.rainfall.period_label} ${result.rainfall.months[0]?.slice(0, 4)}`}`
    : result.rainfall.source === "manual-fallback" ? "Manual fallback (CHIRPS unavailable)" : "Manual scenario";

  return (
    <aside className={`results-panel ${loading ? "results-panel--stale" : ""}`}>
      <div className="panel-heading">
        <div><span className="eyebrow">PLANNING OUTPUT</span><h2>Analysis results</h2></div>
        <span className={`status-pill ${unverified ? "status-pill--caution" : ""}`}>
          <span className="live-dot" /> {unverified ? "Partly screened" : "Screened"}
        </span>
      </div>
      <div className="result-scroll">
        <div className="site-picker-heading">
          <span>{unverified ? "UNVERIFIED TERRAIN CANDIDATES" : "RANKED POND CANDIDATES"}</span>
          <span>best of {result.analysis.candidates_evaluated} outlets</span>
        </div>
        <table className="site-table">
          <thead>
            <tr><th scope="col">Site</th><th scope="col">Catchment</th><th scope="col">Storage</th><th scope="col">Collectable</th></tr>
          </thead>
          <tbody>
            {result.recommendations.map((site, siteIndex) => (
              <tr key={site.site_id} className={site.site_id === activeSite.site_id ? "is-active" : ""} onClick={() => onSiteChange(site.site_id)}>
                <th scope="row">
                  <button type="button" aria-pressed={site.site_id === activeSite.site_id} onClick={(event) => { event.stopPropagation(); onSiteChange(site.site_id); }}>
                    <span className="site-rank-dot">{siteIndex + 1}</span>{siteLabel(siteIndex)}
                  </button>
                </th>
                <td>{compact(site.catchment.area_hectares, 1)} ha</td>
                <td>{compact(site.pond.screening_storage_m3)} m³</td>
                <td><strong>{compact(site.water.capturable_scenario_m3)} m³</strong></td>
              </tr>
            ))}
          </tbody>
        </table>

        <div className="site-summary">
          <div className="site-marker"><MapPinned size={19} /></div>
          <div>
            <strong>{unverified ? "Unverified terrain site" : "Suggested pond site"} {String(index + 1).padStart(2, "0")}</strong>
            <span>{hemi(activeSite.location.coordinates[1], "N", "S")}, {hemi(activeSite.location.coordinates[0], "E", "W")} · {activeSite.elevation_m.toFixed(1)} m</span>
          </div>
          <span className="site-rank">#{index + 1}</span>
        </div>
        <div className="site-links" aria-label="Open this site in Google's apps">
          <a href={googleMapsLink(activeSite.location.coordinates[0], activeSite.location.coordinates[1])} target="_blank" rel="noreferrer">
            <ExternalLink size={13} /> Google Maps satellite
          </a>
          <a href={googleEarthLink(activeSite.location.coordinates[0], activeSite.location.coordinates[1], activeSite.elevation_m)} target="_blank" rel="noreferrer">
            <ExternalLink size={13} /> Google Earth
          </a>
        </div>

        <div className={`screening-note ${unverified ? "screening-note--warning" : ""}`}>
          <Info size={15} />
          <span>
            {unverified
              ? "Mapped-water and built-land check unavailable. This site could overlap an existing waterway or road; check the satellite view and the field."
              : `Off mapped water, roads, buildings and drainage lines over ${compact(result.parameters.max_catchment_ha)} ha.${activeSite.site_screening.distance_to_water_exclusion_m === null ? "" : ` ${compact(activeSite.site_screening.distance_to_water_exclusion_m)} m beyond the mapped-water setback.`} Verify on site.`}
          </span>
        </div>

        {activeSite.notes.length ? (
          <ul className="site-notes">
            {activeSite.notes.map((note) => <li key={note}><AlertTriangle size={14} /> {note}</li>)}
          </ul>
        ) : null}

        <div className="metric-grid">
          <Metric icon={<Waves size={17} />} label="Catchment area" value={compact(catchment.area_hectares, 1)} unit="ha" note="Land draining to outlet" variant="teal" />
          <Metric icon={<Droplets size={17} />} label="Collectable water" value={compact(water.capturable_scenario_m3)} unit="m³" note={water.limited_by === "storage" ? "Limited by pond size" : "Limited by runoff"} variant="orange" />
          <Metric icon={<CloudRain size={17} />} label="Runoff potential" value={compact(water.potential_runoff_m3)} unit="m³" note={`${compact(result.rainfall.depth_mm, 0)} mm × C ${result.rainfall.runoff_coefficient}`} />
          <Metric icon={<Ruler size={17} />} label="Pond storage" value={compact(pond.screening_storage_m3)} unit="m³" note={`${pond.stage_m} m stage · ${compact(pond.footprint_m2 / 10_000, 2)} ha water`} variant="blue" />
        </div>

        <section className="balance-section" aria-label="Water balance">
          <div className="section-line"><div><span className="eyebrow">WATER BALANCE</span><h3>How much could be held?</h3></div></div>
          <div className="balance-row">
            <div><span><i className="swatch swatch--teal" /> Runoff potential</span><strong>{compact(water.potential_runoff_m3)} m³</strong></div>
            <div className="bar-track"><i className="bar-fill bar-fill--teal" style={{ width: pct(water.potential_runoff_m3) }} /></div>
          </div>
          <div className="balance-row">
            <div><span><i className="swatch swatch--blue" /> Pond storage at {pond.stage_m} m</span><strong>{compact(pond.screening_storage_m3)} m³</strong></div>
            <div className="bar-track"><i className="bar-fill bar-fill--blue" style={{ width: pct(pond.screening_storage_m3) }} /></div>
          </div>
          <div className="balance-row">
            <div><span><i className="swatch swatch--orange" /> Illustrative collectable</span><strong>{compact(water.capturable_scenario_m3)} m³</strong></div>
            <div className="bar-track"><i className="bar-fill bar-fill--orange" style={{ width: pct(water.capturable_scenario_m3) }} /></div>
          </div>
          <p className="balance-note">
            The smaller of runoff and storage{water.fill_ratio ? ` · runoff is ${compact(water.fill_ratio, 1)}× storage` : ""}. One fill, not an annual yield.
          </p>
        </section>

        <div className="pond-facts">
          <div><span>Crest level</span><strong>{pond.crest_elevation_m.toFixed(1)} m</strong></div>
          <div><span>Mean depth</span><strong>{pond.mean_depth_m.toFixed(1)} m</strong></div>
          <div><span>Bund length ≈</span><strong>{compact(pond.embankment_length_m)} m</strong></div>
          <div><span>m³ per m bund</span><strong>{compact(pond.screening_storage_m3 / Math.max(pond.embankment_length_m, 1))}</strong></div>
          <div className="pond-facts-wide">
            <span>Benchmarks</span>
            <strong>
              {pond.footprint_m2 >= AMRIT_SAROVAR_AREA_M2 && pond.screening_storage_m3 >= AMRIT_SAROVAR_STORAGE_M3
                ? "Meets the Amrit Sarovar plains size (≥ 1 acre, ~10,000 m³)"
                : "Below the Amrit Sarovar plains size (≥ 1 acre, ~10,000 m³)"}
              {` · ≈ ${compact(pond.screening_storage_m3 / FARM_POND_M3)} MGNREGA farm ponds`}
            </strong>
          </div>
        </div>

        {pond.stage_curve?.length ? <StageChart curve={pond.stage_curve} selectedStage={pond.stage_m} runoff={water.potential_runoff_m3} /> : null}

        <section className="data-section">
          <span className="eyebrow">DATA & CONFIDENCE</span>
          <div className="data-row"><span>Elevation</span><strong>{result.elevation.source}</strong></div>
          <div className="data-row"><span>Analysis grid</span><strong>~{compact(result.elevation.analysis_cell_m)} m cells · {result.elevation.minimum_m.toFixed(0)}–{result.elevation.maximum_m.toFixed(0)} m</strong></div>
          <div className="data-row"><span>Rainfall</span><strong>{rainfallLabel} · {compact(result.rainfall.depth_mm)} mm</strong></div>
          {Object.keys(result.rainfall.monthly_mm).length > 1 ? <RainBars monthly={result.rainfall.monthly_mm} /> : null}
          <div className="data-row">
            <span>Map screening</span>
            <strong>{unverified ? "Unavailable · terrain only" : `${result.water_screening.provider ?? "OSM"} · ${compact(result.water_screening.feature_count)} water, ${compact(result.water_screening.land_feature_count)} built`}</strong>
          </div>
          <div className="data-row"><span>Land status</span><strong className="unverified">Unverified</strong></div>
        </section>

        <section className="export-section">
          <span className="eyebrow">TAKE IT FURTHER</span>
          <div className="export-buttons">
            <button type="button" onClick={() => downloadResultsKml(result)}><Earth size={16} /> Google Earth KML</button>
            <button type="button" onClick={() => downloadResultsGeoJSON(result)}><FileCode2 size={16} /> GeoJSON</button>
            <button type="button" onClick={onExportContours} disabled={exporting}><Download size={16} /> {exporting ? "Tracing…" : "Contours KML"}</button>
          </div>
          <p>KML opens in Google Earth's 3D globe; GeoJSON loads in QGIS. Contour KML is traced from the analysis DEM.</p>
        </section>

        <details className="limitations" open={showAllLimits} onToggle={(event) => setShowAllLimits((event.target as HTMLDetailsElement).open)}>
          <summary>Methods & limitations <ChevronDown size={16} /></summary>
          <div>
            <p><strong>Flow:</strong> fill local sinks (priority-flood), route each cell to its steepest lower neighbour (D8), and collect every upstream cell for each outlet.</p>
            <p><strong>Pond:</strong> an embankment at the outlet raises water {pond.stage_m} m; only cells that drain to the outlet and lie below that crest within {compact(result.parameters.pond_search_radius_m)} m are stored. Lower ground outside the catchment sets the bund length.</p>
            <p><strong>Ranking:</strong> {result.analysis.candidates_evaluated} separated outlets are compared by collectable volume, then storage per metre of bund.</p>
            <p><strong>Runoff:</strong> rain depth ÷ 1,000 × catchment m² × runoff coefficient. Presets follow the CGWB Manual on Artificial Recharge ranges.</p>
            <p><strong>Benchmarks:</strong> Mission Amrit Sarovar phase-2 guidelines (plains: ≥ 1 acre, ~10,000 m³) and the MGNREGA model farm pond (20 × 20 × 3 m, ≈ 880 m³).</p>
            {result.limitations.map((item) => <p key={item}>• {item}</p>)}
          </div>
        </details>
      </div>
    </aside>
  );
}
