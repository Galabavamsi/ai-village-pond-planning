import { useEffect, useRef, useState } from "react";
import type { MultiPolygon, Polygon, Position } from "geojson";
import { ChevronLeft, Earth, ExternalLink, Info, X } from "lucide-react";
import { googleEarthLink, googleMapsLink, loadMaps3d } from "./google";
import type { Analysis, Site } from "./types";

/* The maps3d library is loaded at runtime and has no bundled typings. */
type Maps3dLibrary = any;
type Map3D = any;

const R = 6_371_000;
const latLngs = (ring: Position[]) => ring.map(([lng, lat]) => ({ lat, lng }));
const polygonsOf = (geometry: Polygon | MultiPolygon) => (geometry.type === "Polygon" ? [geometry.coordinates] : geometry.coordinates);
// Google rejects an empty innerCoordinates list, so holes are only passed when present.
const ringsOf = (rings: Position[][]) => (rings.length > 1
  ? { outerCoordinates: latLngs(rings[0]), innerCoordinates: rings.slice(1).map(latLngs) }
  : { outerCoordinates: latLngs(rings[0]) });

/** Camera range that frames the catchment with some context around it. */
function rangeFor(site: Site) {
  const points = polygonsOf(site.catchment.geometry).flatMap((rings) => rings[0]);
  const lats = points.map((point) => point[1]);
  const lons = points.map((point) => point[0]);
  const lat0 = (Math.min(...lats) + Math.max(...lats)) / 2;
  const height = ((Math.max(...lats) - Math.min(...lats)) * Math.PI / 180) * R;
  const width = ((Math.max(...lons) - Math.min(...lons)) * Math.PI / 180) * R * Math.cos(lat0 * Math.PI / 180);
  return Math.max(1500, Math.min(9000, 2.6 * Math.max(width, height)));
}

function camera(site: Site, heading = 20) {
  const [lng, lat] = site.location.coordinates;
  return { center: { lat, lng, altitude: site.elevation_m }, range: rangeFor(site), tilt: 62, heading };
}

export default function GoogleEarthView({ result, activeSite, googleKey, onSiteChange, onClose }: {
  result: Analysis;
  activeSite: Site;
  googleKey: string;
  onSiteChange: (id: string) => void;
  onClose: () => void;
}) {
  const hostRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<Map3D | null>(null);
  const libraryRef = useRef<Maps3dLibrary | null>(null);
  const firstSite = useRef(activeSite);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [message, setMessage] = useState("");

  useEffect(() => {
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const closeOnEscape = (event: KeyboardEvent) => { if (event.key === "Escape") onClose(); };
    window.addEventListener("keydown", closeOnEscape);
    return () => { document.body.style.overflow = previous; window.removeEventListener("keydown", closeOnEscape); };
  }, [onClose]);

  // Create the Google 3D map once; later site changes only move the camera.
  useEffect(() => {
    let cancelled = false;
    loadMaps3d(googleKey)
      .then((library: Maps3dLibrary) => {
        if (cancelled || !hostRef.current) return;
        libraryRef.current = library;
        const map = new library.Map3DElement({ ...camera(firstSite.current), mode: library.MapMode?.HYBRID ?? "HYBRID" });
        map.classList.add("earth-map");
        hostRef.current.appendChild(map);
        mapRef.current = map;
        setStatus("ready");
      })
      .catch((error: Error) => {
        if (cancelled) return;
        setStatus("error");
        setMessage(error.message);
      });
    return () => {
      cancelled = true;
      mapRef.current?.remove();
      mapRef.current = null;
    };
  }, [googleKey]);

  // Our analysis overlays, redrawn when the active site changes.
  useEffect(() => {
    const map = mapRef.current;
    const library = libraryRef.current;
    if (status !== "ready" || !map || !library) return;
    const { Polygon3DElement, Polyline3DElement, Marker3DElement, AltitudeMode } = library;
    const ground = AltitudeMode?.CLAMP_TO_GROUND ?? "CLAMP_TO_GROUND";
    map.querySelectorAll("[data-planner-overlay]").forEach((element: Element) => element.remove());
    const failures: string[] = [];
    // Each overlay is independent: a rejected element must not take down the view.
    const add = (create: () => HTMLElement) => {
      try {
        const element = create();
        element.dataset.plannerOverlay = "true";
        map.append(element);
      } catch (error) {
        failures.push(error instanceof Error ? error.message : String(error));
      }
    };
    for (const ring of result.selection.geometry.coordinates) {
      add(() => new Polyline3DElement({ path: latLngs(ring), strokeColor: "#ffffff", strokeWidth: 3, altitudeMode: ground, drawsOccludedSegments: true }));
    }
    result.recommendations.forEach((site, index) => {
      const active = site.site_id === activeSite.site_id;
      for (const rings of polygonsOf(site.catchment.geometry)) {
        add(() => new Polygon3DElement({
          ...ringsOf(rings), altitudeMode: ground,
          fillColor: active ? "rgba(22, 211, 204, 0.30)" : "rgba(201, 211, 221, 0.10)",
          strokeColor: active ? "#16d3cc" : "#c9d3dd", strokeWidth: active ? 3 : 1.5, drawsOccludedSegments: true,
        }));
      }
      for (const rings of polygonsOf(site.pond_region)) {
        add(() => new Polygon3DElement({
          ...ringsOf(rings), altitudeMode: ground,
          fillColor: active ? "rgba(40, 132, 232, 0.85)" : "rgba(40, 132, 232, 0.5)", strokeColor: "#9fd0ff", strokeWidth: 1.5,
          drawsOccludedSegments: true,
        }));
      }
      const [lng, lat] = site.location.coordinates;
      add(() => new Marker3DElement({ position: { lat, lng }, altitudeMode: ground, label: `Site ${String(index + 1).padStart(2, "0")}` }));
    });
    try {
      map.flyCameraTo?.({ endCamera: camera(activeSite, map.heading ?? 20), durationMillis: 1500 });
    } catch (error) {
      failures.push(error instanceof Error ? error.message : String(error));
    }
    if (failures.length) console.error("Google 3D overlays skipped:", failures.slice(0, 3).join(" | "));
  }, [status, result, activeSite]);

  const index = result.recommendations.findIndex((item) => item.site_id === activeSite.site_id) + 1;
  const [lon, lat] = activeSite.location.coordinates;
  return (
    <div className="terrain-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
      <section className="terrain-dialog" role="dialog" aria-modal="true" aria-label="Google 3D Earth view">
        <header className="terrain-header">
          <div className="terrain-header-title"><Earth size={21} /><div><strong>Google 3D Earth view</strong><span>Google terrain and imagery · this planner's ponds, catchments and sites on top</span></div></div>
          <button className="terrain-close" type="button" aria-label="Close Google 3D view" onClick={onClose}><X size={20} /></button>
        </header>
        <div className="terrain-layout">
          <div className="terrain-viewport earth-viewport" ref={hostRef} data-ready={status === "ready" ? "true" : "false"}>
            {status === "loading" ? <div className="earth-status">Loading Google 3D map…</div> : null}
            {status === "error" ? (
              <div className="terrain-fallback"><Info size={28} /><strong>Google 3D view unavailable</strong><p>{message} The 2D map and the planner's own 3D model still work.</p><button onClick={onClose}>Return to 2D map</button></div>
            ) : null}
          </div>
          <aside className="terrain-inspector">
            <div className="terrain-inspector-top"><span>SELECTED CANDIDATE</span><strong>Site {String(index).padStart(2, "0")}</strong></div>
            <div className="terrain-site-tabs" role="tablist" aria-label="Sites in the Google 3D view">
              {result.recommendations.map((candidate, candidateIndex) => (
                <button key={candidate.site_id} role="tab" aria-selected={candidate.site_id === activeSite.site_id} onClick={() => onSiteChange(candidate.site_id)}>{String(candidateIndex + 1).padStart(2, "0")}</button>
              ))}
            </div>
            <div className="terrain-measure"><span>Outlet ground</span><strong>{activeSite.elevation_m.toFixed(1)} <small>m</small></strong></div>
            <div className="terrain-measure"><span>Upstream catchment</span><strong>{activeSite.catchment.area_hectares.toFixed(1)} <small>ha</small></strong></div>
            <div className="terrain-measure"><span>Stored at {activeSite.pond.stage_m} m stage</span><strong>{Math.round(activeSite.pond.screening_storage_m3).toLocaleString("en-IN")} <small>m³</small></strong></div>
            <div className="terrain-key">
              <div><i className="earth-key--selection" /> Selected land (planner)</div>
              <div><i className="terrain-key--catchment" /> Active catchment (planner)</div>
              <div><i className="terrain-key--water" /> Screening pond (planner)</div>
              <div><i className="earth-key--google" /> Terrain, imagery, labels: Google Maps</div>
            </div>
            <div className="earth-links">
              <a href={googleEarthLink(lon, lat, activeSite.elevation_m)} target="_blank" rel="noreferrer"><ExternalLink size={14} /> Open in Google Earth</a>
              <a href={googleMapsLink(lon, lat)} target="_blank" rel="noreferrer"><ExternalLink size={14} /> Open in Google Maps</a>
            </div>
            <p className="terrain-caveat"><Info size={15} /> Google's 3D surface is for context only; every number comes from the planner's own Copernicus or contour grid. Coloured overlays are screening results, not surveyed boundaries.</p>
            <button className="terrain-back-button" type="button" onClick={onClose}><ChevronLeft size={16} /> Back to 2D map</button>
          </aside>
        </div>
      </section>
    </div>
  );
}
