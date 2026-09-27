import type { Basemap } from "./types";

export interface BasemapDefinition {
  id: Basemap;
  label: string;
  tiles: string[];
  maxzoom: number;
  attribution: string;
  /** Contour and outline colours that stay legible on this background. */
  contour: string;
  contourLabelHalo: string;
  outline: string;
}

export const BASEMAPS: BasemapDefinition[] = [
  {
    id: "topo",
    label: "Topographic",
    tiles: ["a", "b", "c"].map((host) => `https://${host}.tile.opentopomap.org/{z}/{x}/{y}.png`),
    maxzoom: 17,
    attribution:
      'Map data © <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors, SRTM · style © <a href="https://opentopomap.org">OpenTopoMap</a> (CC-BY-SA)',
    contour: "#8a5a2b",
    contourLabelHalo: "#fdf8ee",
    outline: "#123c46",
  },
  {
    id: "satellite",
    label: "Satellite",
    // Sentinel-2 cloudless mosaic (10 m). CC BY-NC-SA 4.0: fine for academic,
    // non-commercial use; commercial deployments need an EOX licence.
    tiles: ["https://tiles.maps.eox.at/wmts/1.0.0/s2cloudless-2025_3857/default/g/{z}/{y}/{x}.jpg"],
    maxzoom: 15,
    attribution:
      '<a href="https://cloudless.eox.at">EOxCloudless 2025</a> by EOX IT Services GmbH (contains modified Copernicus Sentinel data 2025, CC BY-NC-SA 4.0)',
    contour: "#ffe29a",
    contourLabelHalo: "#2a2413",
    outline: "#ffffff",
  },
  {
    id: "streets",
    label: "Streets",
    tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
    maxzoom: 19,
    attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    contour: "#9a5b24",
    contourLabelHalo: "#ffffff",
    outline: "#123c46",
  },
];

/** Global Terrarium-encoded elevation tiles for 3D terrain and hillshade. */
export const TERRAIN_TILES = {
  tiles: ["https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"],
  encoding: "terrarium" as const,
  maxzoom: 15,
  attribution:
    '3D terrain: <a href="https://registry.opendata.aws/terrain-tiles/">Terrain Tiles on AWS</a> · SRTM and GMTED2010 courtesy of the U.S. Geological Survey · ETOPO1 courtesy NOAA',
};

export const basemapById = (id: Basemap) => BASEMAPS.find((item) => item.id === id) ?? BASEMAPS[0];
