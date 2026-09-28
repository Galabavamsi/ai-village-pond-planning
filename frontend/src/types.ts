import type { FeatureCollection, LineString, MultiPolygon, Point, Polygon } from "geojson";

export type TerrainSource = "sample" | "upload" | "copernicus";
export type RainfallPeriod = "monsoon" | "annual" | "month";

export interface ExampleArea {
  id: string;
  name: string;
  region: string;
  source: TerrainSource;
  bbox: [number, number, number, number] | null;
  note: string;
}

export interface Config {
  sample_bounds: [number, number, number, number];
  sources: string[];
  default_rainfall_month: string;
  default_rainfall_year: number;
  default_rainfall_period: RainfallPeriod;
  default_max_catchment_ha: number;
  /** Browser key for the optional Google layers; null when not configured. */
  google_maps_key?: string | null;
  examples: ExampleArea[];
}

export interface UploadedDataset {
  dataset_id: string;
  filename: string;
  bounds: [number, number, number, number];
  contour_features: number;
  elevation_min_m: number;
  elevation_max_m: number;
  analysis_cell_m: number;
  contour_url: string;
  expires_in_seconds: number;
}

export interface TerrainPreview {
  rows: number;
  columns: number;
  x_m: number[];
  y_m: number[];
  elevation_m: number[];
  origin_lon: number;
  origin_lat: number;
  minimum_m: number;
  maximum_m: number;
  source: string;
}

export interface StageRow {
  stage_m: number;
  area_m2: number;
  storage_m3: number;
  embankment_length_m: number;
}

export interface Site {
  site_id: string;
  rank: number;
  location: Point;
  pond_region: Polygon | MultiPolygon;
  elevation_m: number;
  catchment: {
    area_m2: number;
    area_hectares: number;
    flow_accumulation_cells: number;
    geometry: Polygon | MultiPolygon;
    touches_dem_boundary: boolean;
  };
  pond: {
    footprint_m2: number;
    stage_m: number;
    screening_storage_m3: number;
    crest_elevation_m: number;
    max_depth_m: number;
    mean_depth_m: number;
    embankment_length_m: number;
    stage_curve: StageRow[];
  };
  water: {
    potential_runoff_m3: number;
    capturable_scenario_m3: number;
    fill_ratio: number | null;
    limited_by: "runoff" | "storage";
  };
  site_screening: {
    distance_to_water_exclusion_m: number | null;
    distance_to_built_exclusion_m: number | null;
    mapped_water_excluded: boolean;
    mapped_infrastructure_excluded: boolean;
    major_channel_excluded: boolean;
  };
  notes: string[];
  land_status: string;
  ranking_basis: string;
}

export type ContourCollection = FeatureCollection<LineString, { elevation_m: number; major: boolean }> & {
  interval_m?: number;
};

export interface Analysis {
  analysis: { status: string; algorithm_version: string; kind: string; candidates_evaluated: number };
  selection: { geometry: Polygon; area_hectares: number };
  elevation: {
    source: string;
    source_key: TerrainSource;
    nominal_resolution_m: number;
    analysis_cell_m: number;
    grid_rows: number;
    grid_columns: number;
    minimum_m: number;
    maximum_m: number;
  };
  parameters: {
    max_catchment_ha: number;
    min_catchment_ha: number;
    pond_search_radius_m: number;
    stage_m: number;
    candidate_separation_m: number;
  };
  terrain_preview: TerrainPreview;
  contours: ContourCollection;
  rainfall: {
    source: "chirps" | "manual" | "manual-fallback";
    period: RainfallPeriod;
    period_label: string;
    month: string | null;
    months: string[];
    monthly_mm: Record<string, number>;
    depth_mm: number;
    runoff_coefficient: number;
    citation_url: string | null;
  };
  water_screening: {
    status: "mapped-water-excluded" | "unavailable";
    feature_count: number;
    land_feature_count: number;
    provider: string | null;
    setback_m: number;
    source_url: string;
    note: string;
  };
  recommendations: Site[];
  limitations: string[];
}

export type DrawMode = "none" | "polygon" | "rectangle";
export type Basemap = "topo" | "satellite" | "streets";

export interface MapFocus {
  bounds: [number, number, number, number];
  key: number;
}
