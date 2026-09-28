import { useEffect, useRef, useState } from "react";
import { Loader2, MapPin, Search, X } from "lucide-react";
import { GOOGLE_LOGO_ON_WHITE, placeLocation, placeSuggestions } from "./google";

export interface Place {
  label: string;
  detail: string;
  center: [number, number];
  bounds: [number, number, number, number] | null;
}

interface Suggestion {
  label: string;
  detail: string;
  provider: "google" | "photon";
  placeId?: string;
  place?: Place;
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
const cache = new Map<string, Suggestion[]>();

async function photonSuggestions(query: string, signal: AbortSignal): Promise<Suggestion[]> {
  const key = query.toLowerCase();
  const hit = cache.get(key);
  if (hit) return hit;
  const url = `${PHOTON_URL}?${new URLSearchParams({ q: query, limit: "6", lang: "en" })}`;
  const response = await fetch(url, { signal });
  if (!response.ok) throw new Error("Place search is unavailable right now.");
  const data = (await response.json()) as { features: PhotonFeature[] };
  const suggestions = data.features.map(({ geometry, properties }): Suggestion => {
    const detail = [properties.district ?? properties.city ?? properties.county, properties.state, properties.country]
      .filter((part, index, parts) => part && part !== properties.name && parts.indexOf(part) === index)
      .join(", ");
    const extent = properties.extent;
    const label = properties.name ?? detail ?? "Unnamed place";
    const place: Place = {
      label, detail, center: geometry.coordinates,
      // Photon extents are [west, north, east, south].
      bounds: extent ? [extent[0], extent[3], extent[2], extent[1]] : null,
    };
    return { label, detail: [properties.type, detail].filter(Boolean).join(" · "), provider: "photon", place };
  });
  cache.set(key, suggestions);
  return suggestions;
}

const newSessionToken = () => (crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`);

/** Place search: Google Places when a key is configured, Photon (OSM) otherwise or on failure. */
export default function PlaceSearch({ onPick, googleKey = null }: { onPick: (place: Place) => void; googleKey?: string | null }) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<Suggestion[]>([]);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [highlight, setHighlight] = useState(0);
  const boxRef = useRef<HTMLDivElement>(null);
  const sessionToken = useRef(newSessionToken());
  const picked = useRef<string | null>(null);

  useEffect(() => {
    const text = query.trim();
    if (text.length < 3 || text === picked.current) {
      setResults([]);
      setError(null);
      return;
    }
    const controller = new AbortController();
    // Debounced so typing sends at most a request or two per second.
    const timer = window.setTimeout(() => {
      setBusy(true);
      const search = googleKey
        ? placeSuggestions(googleKey, text, sessionToken.current, controller.signal)
            .then((places) => places.map((item): Suggestion => ({ ...item, provider: "google" })))
            .catch((cause: Error) => { if (cause.name === "AbortError") throw cause; return photonSuggestions(text, controller.signal); })
        : photonSuggestions(text, controller.signal);
      search
        .then((places) => { setResults(places); setError(places.length ? null : "No places found."); setHighlight(0); setOpen(true); })
        .catch((cause: Error) => { if (cause.name !== "AbortError") { setError(cause.message); setOpen(true); } })
        .finally(() => setBusy(false));
    }, googleKey ? 350 : 650);
    return () => { controller.abort(); window.clearTimeout(timer); };
  }, [query, googleKey]);

  useEffect(() => {
    const close = (event: MouseEvent) => { if (!boxRef.current?.contains(event.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);

  const pick = async (suggestion: Suggestion) => {
    setOpen(false);
    picked.current = suggestion.label;
    setQuery(suggestion.label);
    try {
      if (suggestion.place) {
        onPick(suggestion.place);
      } else if (suggestion.placeId && googleKey) {
        setBusy(true);
        const location = await placeLocation(googleKey, suggestion.placeId, sessionToken.current);
        onPick({ label: suggestion.label, detail: suggestion.detail, ...location });
      }
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not locate that place.");
      setOpen(true);
    } finally {
      setBusy(false);
      // A new token starts the next billable search session.
      sessionToken.current = newSessionToken();
    }
  };

  const provider = results[0]?.provider ?? (googleKey ? "google" : "photon");
  return (
    <div className="place-search" ref={boxRef}>
      <Search size={16} className="place-search-icon" />
      <input
        type="search"
        value={query}
        placeholder="Search a village or town…"
        aria-label="Search for a place"
        aria-expanded={open}
        aria-controls="place-results"
        role="combobox"
        onChange={(event) => { picked.current = null; setQuery(event.target.value); }}
        onFocus={() => results.length && setOpen(true)}
        onKeyDown={(event) => {
          if (event.key === "ArrowDown") { event.preventDefault(); setHighlight((value) => Math.min(results.length - 1, value + 1)); }
          if (event.key === "ArrowUp") { event.preventDefault(); setHighlight((value) => Math.max(0, value - 1)); }
          if (event.key === "Enter" && results[highlight]) { event.preventDefault(); void pick(results[highlight]); }
          if (event.key === "Escape") setOpen(false);
        }}
      />
      {busy ? <Loader2 size={15} className="place-search-busy" /> : query ? (
        <button type="button" className="place-search-clear" aria-label="Clear search" onClick={() => { picked.current = null; setQuery(""); setResults([]); setOpen(false); }}>
          <X size={14} />
        </button>
      ) : null}
      {open && (results.length || error) ? (
        <ul className="place-results" id="place-results" role="listbox">
          {results.map((place, index) => (
            <li key={`${place.provider}-${place.placeId ?? place.place?.center.join()}-${index}`} role="option" aria-selected={index === highlight}>
              <button type="button" className={index === highlight ? "is-highlighted" : ""} onMouseEnter={() => setHighlight(index)} onClick={() => void pick(place)}>
                <MapPin size={15} />
                <span><strong>{place.label}</strong><small>{place.detail}</small></span>
              </button>
            </li>
          ))}
          {error ? <li className="place-results-note">{error}</li> : null}
          <li className="place-results-note place-results-credit">
            {provider === "google"
              ? <><img src={GOOGLE_LOGO_ON_WHITE} alt="Google Maps" height={16} /> <span>Place results</span></>
              : "Search © OpenStreetMap contributors · Photon"}
          </li>
        </ul>
      ) : null}
    </div>
  );
}
