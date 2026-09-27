import type { Geometry, MultiPolygon, Polygon, Position } from "geojson";
import type { Analysis } from "./types";
import { apiFetch } from "./api";

const number = (value: number, digits = 0) => new Intl.NumberFormat("en-IN", { maximumFractionDigits: digits }).format(value);

export function download(name: string, content: BlobPart, type: string) {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function stamp(result: Analysis) {
  const [lon, lat] = result.recommendations[0]?.location.coordinates ?? [0, 0];
  return `${lat.toFixed(4)}N_${lon.toFixed(4)}E`;
}

export function resultsGeoJSON(result: Analysis) {
  const features = [
    { type: "Feature", properties: { kind: "study-area", area_hectares: result.selection.area_hectares }, geometry: result.selection.geometry },
    ...result.recommendations.flatMap((site, index) => {
      const common = { site_id: site.site_id, rank: index + 1 };
      return [
        { type: "Feature", properties: { ...common, kind: "catchment", area_hectares: site.catchment.area_hectares, touches_dem_boundary: site.catchment.touches_dem_boundary }, geometry: site.catchment.geometry },
        { type: "Feature", properties: { ...common, kind: "pond", stage_m: site.pond.stage_m, storage_m3: site.pond.screening_storage_m3, footprint_m2: site.pond.footprint_m2, embankment_length_m: site.pond.embankment_length_m }, geometry: site.pond_region },
        { type: "Feature", properties: { ...common, kind: "outlet", elevation_m: site.elevation_m, runoff_m3: site.water.potential_runoff_m3, collectable_m3: site.water.capturable_scenario_m3, land_status: site.land_status }, geometry: site.location },
      ];
    }),
  ];
  return {
    type: "FeatureCollection",
    properties: {
      generator: "Village Pond Planner",
      algorithm: result.analysis.algorithm_version,
      elevation_source: result.elevation.source,
      rainfall: result.rainfall,
      screening: result.water_screening.status,
      disclaimer: "Screening estimates only; not an engineering design or a land-eligibility decision.",
    },
    features,
  };
}

export function downloadResultsGeoJSON(result: Analysis) {
  download(`pond-sites_${stamp(result)}.geojson`, JSON.stringify(resultsGeoJSON(result), null, 1), "application/geo+json");
}

const escape = (text: string) => text.replace(/[<>&'"]/g, (char) => ({ "<": "&lt;", ">": "&gt;", "&": "&amp;", "'": "&apos;", '"': "&quot;" })[char] ?? char);
const ring = (positions: Position[]) => positions.map(([lon, lat]) => `${lon.toFixed(7)},${lat.toFixed(7)},0`).join(" ");

function polygonsKml(geometry: Polygon | MultiPolygon) {
  const polygons = geometry.type === "Polygon" ? [geometry.coordinates] : geometry.coordinates;
  const parts = polygons.map((rings) => {
    const [outer, ...holes] = rings;
    return `<Polygon><tessellate>1</tessellate><altitudeMode>clampToGround</altitudeMode><outerBoundaryIs><LinearRing><coordinates>${ring(outer)}</coordinates></LinearRing></outerBoundaryIs>${holes
      .map((hole) => `<innerBoundaryIs><LinearRing><coordinates>${ring(hole)}</coordinates></LinearRing></innerBoundaryIs>`)
      .join("")}</Polygon>`;
  });
  return parts.length === 1 ? parts[0] : `<MultiGeometry>${parts.join("")}</MultiGeometry>`;
}

function placemark(name: string, style: string, geometry: Geometry, description: string) {
  const body = geometry.type === "Point"
    ? `<Point><coordinates>${geometry.coordinates[0]},${geometry.coordinates[1]},0</coordinates></Point>`
    : polygonsKml(geometry as Polygon | MultiPolygon);
  return `<Placemark><name>${escape(name)}</name><styleUrl>#${style}</styleUrl><description>${escape(description)}</description>${body}</Placemark>`;
}

/** KML for Google Earth: study area, catchments, ponds and outlets, clamped to terrain. */
export function downloadResultsKml(result: Analysis) {
  const rain = `${number(result.rainfall.depth_mm, 1)} mm (${result.rainfall.source === "chirps" ? `CHIRPS v3, ${result.rainfall.period_label}` : "manual scenario"}), C = ${result.rainfall.runoff_coefficient}`;
  const sites = result.recommendations.map((site, index) => {
    const label = `Site ${String(index + 1).padStart(2, "0")}`;
    const summary = `${label}: outlet ${site.elevation_m} m; catchment ${number(site.catchment.area_hectares, 1)} ha; storage ${number(site.pond.screening_storage_m3)} m³ at ${site.pond.stage_m} m stage; runoff ${number(site.water.potential_runoff_m3)} m³; collectable ${number(site.water.capturable_scenario_m3)} m³; bund ≈ ${number(site.pond.embankment_length_m)} m. Rainfall ${rain}. Screening estimate — land status unverified.`;
    return `<Folder><name>${label}</name>${placemark(`${label} catchment`, "catchment", site.catchment.geometry, summary)}${placemark(`${label} pond`, "pond", site.pond_region, summary)}${placemark(label, "site", site.location, summary)}</Folder>`;
  });
  const kml = `<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2"><Document>
<name>Village pond screening ${escape(stamp(result))}</name>
<description>${escape(`Generated by Village Pond Planner (${result.analysis.algorithm_version}) from ${result.elevation.source}. Screening estimates, not an engineering design.`)}</description>
<Style id="area"><LineStyle><color>ffffffff</color><width>2.5</width></LineStyle><PolyStyle><color>1a5c4f0e</color></PolyStyle></Style>
<Style id="catchment"><LineStyle><color>ff6f7005</color><width>2</width></LineStyle><PolyStyle><color>55a2a711</color></PolyStyle></Style>
<Style id="pond"><LineStyle><color>ff7a3f0b</color><width>2</width></LineStyle><PolyStyle><color>c8d16f1c</color></PolyStyle></Style>
<Style id="site"><IconStyle><color>ff2a70e8</color><scale>1.2</scale><Icon><href>https://maps.google.com/mapfiles/kml/paddle/orange-circle.png</href></Icon></IconStyle></Style>
${placemark("Study area", "area", result.selection.geometry, `Selected land, ${number(result.selection.area_hectares, 1)} ha`)}
${sites.join("\n")}
</Document></kml>`;
  download(`pond-sites_${stamp(result)}.kml`, kml, "application/vnd.google-earth.kml+xml");
}

export async function downloadContourKml(body: { area: Polygon; source: string; dataset_id: string | null }) {
  const response = await apiFetch("/api/export/contours.kml", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    const detail = await response.json().catch(() => null);
    throw new Error(typeof detail?.detail === "string" ? detail.detail : "Contours could not be exported for this area.");
  }
  const disposition = response.headers.get("content-disposition") ?? "";
  const name = /filename="([^"]+)"/.exec(disposition)?.[1] ?? "contours.kml";
  download(name, await response.blob(), "application/vnd.google-earth.kml+xml");
}
