/**
 * Optional Google Maps Platform layers. Everything here is used only when the
 * server supplies a browser key in /api/config, and every caller falls back to
 * the open data sources when a request fails or the quota is exhausted.
 *
 * Google content is used for display only: nothing is cached, stored or
 * analysed, and the Google Maps logo and data attribution stay visible
 * (https://developers.google.com/maps/documentation/tile/policies).
 */
import logoOutline from "./assets/google-maps-logo-outline.svg";
import logoGray from "./assets/google-maps-logo-gray.svg";

export const GOOGLE_LOGO_ON_IMAGERY = logoOutline;
export const GOOGLE_LOGO_ON_WHITE = logoGray;

export interface GoogleTiles {
  url: string;
  session: string;
  maxzoom: number;
}

const TILE_API = "https://tile.googleapis.com";
const sessions = new Map<string, Promise<GoogleTiles | null>>();

/** A Map Tiles API session for satellite imagery with road and place labels. */
export function satelliteTiles(key: string): Promise<GoogleTiles | null> {
  const cached = sessions.get(key);
  if (cached) return cached;
  const request = fetch(`${TILE_API}/v1/createSession?key=${encodeURIComponent(key)}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mapType: "satellite", language: "en-US", region: "IN", layerTypes: ["layerRoadmap"] }),
  })
    .then(async (response) => {
      if (!response.ok) return null;
      const body = (await response.json()) as { session?: string };
      if (!body.session) return null;
      return {
        session: body.session,
        url: `${TILE_API}/v1/2dtiles/{z}/{x}/{y}?session=${body.session}&key=${encodeURIComponent(key)}`,
        maxzoom: 19,
      };
    })
    .catch(() => null);
  sessions.set(key, request);
  return request;
}

/** The copyright string Google requires for the tiles in this viewport. */
export async function viewportCopyright(key: string, tiles: GoogleTiles, bounds: [number, number, number, number], zoom: number, signal?: AbortSignal) {
  const [west, south, east, north] = bounds;
  const params = new URLSearchParams({
    session: tiles.session, key, zoom: String(Math.max(0, Math.min(22, Math.round(zoom)))),
    north: String(Math.min(85, north)), south: String(Math.max(-85, south)),
    east: String(Math.min(180, east)), west: String(Math.max(-180, west)),
  });
  const response = await fetch(`${TILE_API}/tile/v1/viewport?${params}`, { signal });
  if (!response.ok) throw new Error("viewport attribution unavailable");
  const body = (await response.json()) as { copyright?: string };
  return body.copyright ?? "Imagery and map data © Google";
}

export interface GooglePlace {
  placeId: string;
  label: string;
  detail: string;
}

/** Places API (New) autocomplete; a session token groups keystrokes and the final lookup. */
export async function placeSuggestions(key: string, input: string, sessionToken: string, signal: AbortSignal): Promise<GooglePlace[]> {
  const response = await fetch("https://places.googleapis.com/v1/places:autocomplete", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Goog-Api-Key": key },
    body: JSON.stringify({ input, sessionToken, languageCode: "en" }),
    signal,
  });
  if (!response.ok) throw new Error("Google place search is unavailable.");
  const body = (await response.json()) as {
    suggestions?: { placePrediction?: { placeId: string; structuredFormat?: { mainText?: { text: string }; secondaryText?: { text: string } }; text?: { text: string } } }[];
  };
  return (body.suggestions ?? [])
    .map((item) => item.placePrediction)
    .filter((item): item is NonNullable<typeof item> => !!item)
    .map((item) => ({
      placeId: item.placeId,
      label: item.structuredFormat?.mainText?.text ?? item.text?.text ?? "Place",
      detail: item.structuredFormat?.secondaryText?.text ?? "",
    }));
}

export async function placeLocation(key: string, placeId: string, sessionToken: string) {
  const response = await fetch(`https://places.googleapis.com/v1/places/${encodeURIComponent(placeId)}?sessionToken=${encodeURIComponent(sessionToken)}`, {
    headers: { "X-Goog-Api-Key": key, "X-Goog-FieldMask": "location,viewport" },
  });
  if (!response.ok) throw new Error("Place details are unavailable.");
  const body = (await response.json()) as {
    location?: { latitude: number; longitude: number };
    viewport?: { low: { latitude: number; longitude: number }; high: { latitude: number; longitude: number } };
  };
  if (!body.location) throw new Error("Place has no location.");
  const bounds: [number, number, number, number] | null = body.viewport
    ? [body.viewport.low.longitude, body.viewport.low.latitude, body.viewport.high.longitude, body.viewport.high.latitude]
    : null;
  return { center: [body.location.longitude, body.location.latitude] as [number, number], bounds };
}

let mapsLibrary: Promise<unknown> | null = null;

/** Load the Maps JavaScript API once, only when the 3D Earth view is opened. */
export function loadMaps3d(key: string): Promise<unknown> {
  if (mapsLibrary) return mapsLibrary;
  mapsLibrary = new Promise((resolve, reject) => {
    const scope = window as unknown as Record<string, unknown>;
    const callback = "__pondPlannerMapsReady";
    scope[callback] = () => {
      const google = scope.google as { maps: { importLibrary: (name: string) => Promise<unknown> } };
      google.maps.importLibrary("maps3d").then(resolve, reject);
    };
    scope.gm_authFailure = () => reject(new Error("Google rejected the Maps key or its daily quota is used up."));
    const script = document.createElement("script");
    script.src = `https://maps.googleapis.com/maps/api/js?key=${encodeURIComponent(key)}&v=beta&loading=async&callback=${callback}`;
    script.async = true;
    script.onerror = () => reject(new Error("Google Maps could not be loaded (network)."));
    document.head.appendChild(script);
  }).catch((error) => {
    mapsLibrary = null;
    throw error;
  });
  return mapsLibrary;
}

/** Deep links that open a point in Google's own apps; they need no API key. */
export function googleMapsLink(lon: number, lat: number) {
  return `https://www.google.com/maps/@?api=1&map_action=map&center=${lat.toFixed(6)},${lon.toFixed(6)}&zoom=17&basemap=satellite`;
}

export function googleEarthLink(lon: number, lat: number, elevation: number) {
  return `https://earth.google.com/web/@${lat.toFixed(6)},${lon.toFixed(6)},${Math.round(elevation)}a,1800d,35y,0h,55t,0r`;
}
