import { useEffect, useRef, useState } from "react";
import { Loader2, MapPin, Search, X } from "lucide-react";

export interface Place {
  label: string;
  detail: string;
  center: [number, number];
  bounds: [number, number, number, number] | null;
}

interface PhotonFeature {
  geometry: { coordinates: [number, number] };
  properties: {
    name?: string; city?: string; district?: string; county?: string; state?: string; country?: string;
    type?: string; extent?: [number, number, number, number];
  };
}

const PHOTON_URL = "https://photon.komoot.io/api/";
// Photon's public server asks for fair use; identical queries are answered locally.
const cache = new Map<string, Place[]>();

async function searchPlaces(query: string, signal: AbortSignal): Promise<Place[]> {
  const key = query.toLowerCase();
  const hit = cache.get(key);
  if (hit) return hit;
  const url = `${PHOTON_URL}?${new URLSearchParams({ q: query, limit: "6", lang: "en" })}`;
  const response = await fetch(url, { signal });
  if (!response.ok) throw new Error("Place search is unavailable right now.");
  const data = (await response.json()) as { features: PhotonFeature[] };
  const places = data.features.map(({ geometry, properties }): Place => {
    const detail = [properties.district ?? properties.city ?? properties.county, properties.state, properties.country]
      .filter((part, index, parts) => part && part !== properties.name && parts.indexOf(part) === index)
      .join(", ");
    const extent = properties.extent;
    return {
      label: properties.name ?? detail ?? "Unnamed place",
      detail: [properties.type, detail].filter(Boolean).join(" · "),
      center: geometry.coordinates,
      // Photon extents are [west, north, east, south].
      bounds: extent ? [extent[0], extent[3], extent[2], extent[1]] : null,
    };
  });
  cache.set(key, places);
  return places;
}

export default function PlaceSearch({ onPick }: { onPick: (place: Place) => void }) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<Place[]>([]);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [highlight, setHighlight] = useState(0);
  const boxRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const text = query.trim();
    if (text.length < 3) {
      setResults([]);
      setError(null);
      return;
    }
    const controller = new AbortController();
    // Debounced so typing sends at most a request or two per second.
    const timer = window.setTimeout(() => {
      setBusy(true);
      searchPlaces(text, controller.signal)
        .then((places) => { setResults(places); setError(places.length ? null : "No places found."); setHighlight(0); setOpen(true); })
        .catch((cause: Error) => { if (cause.name !== "AbortError") { setError(cause.message); setOpen(true); } })
        .finally(() => setBusy(false));
    }, 650);
    return () => { controller.abort(); window.clearTimeout(timer); };
  }, [query]);

  useEffect(() => {
    const close = (event: MouseEvent) => { if (!boxRef.current?.contains(event.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);

  const pick = (place: Place) => {
    onPick(place);
    setQuery(place.label);
    setOpen(false);
  };

  return (
    <div className="place-search" ref={boxRef}>
      <Search size={16} className="place-search-icon" />
      <input
        type="search"
        value={query}
        placeholder="Search a village, town or landmark…"
        aria-label="Search for a place"
        aria-expanded={open}
        aria-controls="place-results"
        role="combobox"
        onChange={(event) => setQuery(event.target.value)}
        onFocus={() => results.length && setOpen(true)}
        onKeyDown={(event) => {
          if (event.key === "ArrowDown") { event.preventDefault(); setHighlight((value) => Math.min(results.length - 1, value + 1)); }
          if (event.key === "ArrowUp") { event.preventDefault(); setHighlight((value) => Math.max(0, value - 1)); }
          if (event.key === "Enter" && results[highlight]) { event.preventDefault(); pick(results[highlight]); }
          if (event.key === "Escape") setOpen(false);
        }}
      />
      {busy ? <Loader2 size={15} className="place-search-busy" /> : query ? (
        <button type="button" className="place-search-clear" aria-label="Clear search" onClick={() => { setQuery(""); setResults([]); setOpen(false); }}>
          <X size={14} />
        </button>
      ) : null}
      {open && (results.length || error) ? (
        <ul className="place-results" id="place-results" role="listbox">
          {results.map((place, index) => (
            <li key={`${place.label}-${place.center.join()}`} role="option" aria-selected={index === highlight}>
              <button type="button" className={index === highlight ? "is-highlighted" : ""} onMouseEnter={() => setHighlight(index)} onClick={() => pick(place)}>
                <MapPin size={15} />
                <span><strong>{place.label}</strong><small>{place.detail}</small></span>
              </button>
            </li>
          ))}
          {error ? <li className="place-results-note">{error}</li> : null}
          <li className="place-results-note">Search © OpenStreetMap contributors · Photon</li>
        </ul>
      ) : null}
    </div>
  );
}
