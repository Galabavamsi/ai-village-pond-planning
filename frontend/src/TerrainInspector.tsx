import { useEffect, useMemo, useRef, useState } from "react";
import type { MultiPolygon, Polygon, Position } from "geojson";
import { ChevronLeft, Info, Minus, Mountain, Plus, RotateCcw, X } from "lucide-react";
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import type { Analysis, Site, TerrainPreview } from "./types";

const R = 6_371_000;
const RAD = Math.PI / 180;
const IMAGERY_URL = "https://tiles.maps.eox.at/wmts/1.0.0/s2cloudless-2025_3857/default/g/{z}/{y}/{x}.jpg";
type LocalRing = [number, number][];
type LocalPolygon = LocalRing[];
type SceneApi = { reset: () => void; zoom: (factor: number) => void };
type Surface = "relief" | "imagery";

// Hypsometric ramp: lowland green → dry plain → upland ochre → rock.
const RAMP: [number, string][] = [[0, "#4f8f5e"], [0.25, "#8fbf7a"], [0.5, "#d9d6a0"], [0.75, "#c49a62"], [1, "#efe7dc"]];

function rampColor(t: number, target: THREE.Color) {
  for (let i = 1; i < RAMP.length; i++) {
    if (t <= RAMP[i][0]) {
      const [t0, c0] = RAMP[i - 1];
      const [t1, c1] = RAMP[i];
      return target.set(c0).lerp(new THREE.Color(c1), (t - t0) / (t1 - t0));
    }
  }
  return target.set(RAMP[RAMP.length - 1][1]);
}

function localPoint(lon: number, lat: number, data: TerrainPreview): [number, number] {
  return [(lon - data.origin_lon) * RAD * R * Math.cos(data.origin_lat * RAD), (lat - data.origin_lat) * RAD * R];
}

function lonLat(x: number, y: number, data: TerrainPreview): [number, number] {
  return [data.origin_lon + x / (R * Math.cos(data.origin_lat * RAD)) / RAD, data.origin_lat + y / R / RAD];
}

function localPolygons(geometry: Polygon | MultiPolygon, data: TerrainPreview): LocalPolygon[] {
  const polygons = geometry.type === "Polygon" ? [geometry.coordinates] : geometry.coordinates;
  return polygons.map((rings) => rings.map((ring) => ring.map((point) => localPoint(point[0], point[1], data))));
}

function inRing(x: number, y: number, ring: LocalRing): boolean {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i];
    const [xj, yj] = ring[j];
    if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

const inPolygons = (x: number, y: number, polygons: LocalPolygon[]) =>
  polygons.some((rings) => inRing(x, y, rings[0]) && !rings.slice(1).some((hole) => inRing(x, y, hole)));

function bracket(values: number[], target: number): [number, number] {
  if (target <= values[0]) return [0, 0];
  if (target >= values[values.length - 1]) return [values.length - 2, 1];
  let low = 0;
  let high = values.length - 1;
  while (high - low > 1) {
    const mid = (high + low) >>> 1;
    if (values[mid] <= target) low = mid;
    else high = mid;
  }
  return [low, (target - values[low]) / (values[high] - values[low])];
}

function terrainHeight(data: TerrainPreview, x: number, y: number): number {
  const [c, tx] = bracket(data.x_m, x);
  const [r, ty] = bracket(data.y_m, y);
  const at = (row: number, col: number) => data.elevation_m[row * data.columns + col];
  const south = at(r, c) * (1 - tx) + at(r, c + 1) * tx;
  const north = at(r + 1, c) * (1 - tx) + at(r + 1, c + 1) * tx;
  return south * (1 - ty) + north * ty;
}

/** Relief drawn at ~12% of the map width: readable without spiking flat plains. */
export function defaultExaggeration(data: TerrainPreview) {
  const span = Math.max(data.x_m[data.columns - 1] - data.x_m[0], data.y_m[data.rows - 1] - data.y_m[0]);
  const relief = Math.max(1, data.maximum_m - data.minimum_m);
  return Math.max(1, Math.min(30, Math.round((0.12 * span) / relief)));
}

function disposeTree(root: THREE.Object3D) {
  root.traverse((object) => {
    if (object instanceof THREE.Mesh || object instanceof THREE.Line || object instanceof THREE.LineSegments || object instanceof THREE.Sprite) {
      object.geometry.dispose();
      const materials = Array.isArray(object.material) ? object.material : [object.material];
      materials.forEach((material) => { (material as THREE.MeshBasicMaterial).map?.dispose(); material.dispose(); });
    }
  });
}

function numberSprite(text: string, active: boolean, size: number) {
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = 64;
  const context = canvas.getContext("2d")!;
  context.fillStyle = active ? "#e8702a" : "#ffffff";
  context.strokeStyle = active ? "#ffffff" : "#c35a1f";
  context.lineWidth = 6;
  context.beginPath();
  context.arc(32, 32, 26, 0, Math.PI * 2);
  context.fill();
  context.stroke();
  context.fillStyle = active ? "#ffffff" : "#9a4514";
  context.font = "bold 30px Manrope, Arial, sans-serif";
  context.textAlign = "center";
  context.textBaseline = "middle";
  context.fillText(text, 32, 34);
  const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: new THREE.CanvasTexture(canvas), depthTest: false }));
  sprite.scale.set(size, size, 1);
  sprite.renderOrder = 10;
  return sprite;
}

/** Mosaic Sentinel-2 cloudless tiles over the grid extent and return per-vertex UVs. */
async function imageryTexture(data: TerrainPreview, signal: AbortSignal) {
  const [west, south] = lonLat(data.x_m[0], data.y_m[0], data);
  const [east, north] = lonLat(data.x_m[data.columns - 1], data.y_m[data.rows - 1], data);
  const tileX = (lon: number, z: number) => ((lon + 180) / 360) * 2 ** z;
  const tileY = (lat: number, z: number) => ((1 - Math.log(Math.tan(lat * RAD) + 1 / Math.cos(lat * RAD)) / Math.PI) / 2) * 2 ** z;
  let z = 15;
  while (z > 8 && (Math.floor(tileX(east, z)) - Math.floor(tileX(west, z)) + 1) * (Math.floor(tileY(south, z)) - Math.floor(tileY(north, z)) + 1) > 36) z--;
  const x0 = Math.floor(tileX(west, z));
  const x1 = Math.floor(tileX(east, z));
  const y0 = Math.floor(tileY(north, z));
  const y1 = Math.floor(tileY(south, z));
  const canvas = document.createElement("canvas");
  canvas.width = (x1 - x0 + 1) * 256;
  canvas.height = (y1 - y0 + 1) * 256;
  const context = canvas.getContext("2d")!;
  context.fillStyle = "#6f7d6a";
  context.fillRect(0, 0, canvas.width, canvas.height);
  const jobs: Promise<boolean>[] = [];
  for (let x = x0; x <= x1; x++) {
    for (let y = y0; y <= y1; y++) {
      jobs.push(new Promise((resolve) => {
        const image = new Image();
        image.crossOrigin = "anonymous";
        image.onload = () => { context.drawImage(image, (x - x0) * 256, (y - y0) * 256); resolve(true); };
        image.onerror = () => resolve(false);
        image.src = IMAGERY_URL.replace("{z}", String(z)).replace("{x}", String(x)).replace("{y}", String(y));
        signal.addEventListener("abort", () => { image.src = ""; resolve(false); });
      }));
    }
  }
  const loaded = (await Promise.all(jobs)).filter(Boolean).length;
  if (!loaded || signal.aborted) throw new Error("Satellite imagery could not be loaded.");
  const uv = new Float32Array(data.rows * data.columns * 2);
  for (let r = 0; r < data.rows; r++) {
    for (let c = 0; c < data.columns; c++) {
      const [lon, lat] = lonLat(data.x_m[c], data.y_m[r], data);
      const index = r * data.columns + c;
      uv[index * 2] = (tileX(lon, z) - x0) / (x1 - x0 + 1);
      uv[index * 2 + 1] = 1 - (tileY(lat, z) - y0) / (y1 - y0 + 1);
    }
  }
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.anisotropy = 4;
  return { texture, uv };
}

interface SceneState {
  scene: THREE.Scene;
  terrainGroup: THREE.Group;
  geometry: THREE.BufferGeometry;
  material: THREE.MeshLambertMaterial;
  reliefColors: Float32Array;
  camera: THREE.OrthographicCamera;
  draw: () => void;
  centerX: number;
  centerY: number;
  span: number;
  relief: number;
  overlay: THREE.Group | null;
  markers: THREE.Group | null;
  markerHeights: number[];
  imagery: THREE.Texture | null;
}

function TerrainScene({ result, site, exaggeration, surface, apiRef, onFailure, onImageryError }: {
  result: Analysis;
  site: Site;
  exaggeration: number;
  surface: Surface;
  apiRef: React.RefObject<SceneApi | null>;
  onFailure: (message: string) => void;
  onImageryError: (message: string | null) => void;
}) {
  const data = result.terrain_preview;
  const mountRef = useRef<HTMLDivElement>(null);
  const stateRef = useRef<SceneState | null>(null);
  const [version, setVersion] = useState(0);

  useEffect(() => {
    const mount = mountRef.current;
    if (!mount) return;
    if (data.elevation_m.length !== data.rows * data.columns || data.rows < 2 || data.columns < 2) {
      onFailure("The elevation grid is incomplete; use the 2D map instead.");
      return;
    }
    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false, powerPreference: "low-power" });
    } catch {
      onFailure("3D is unavailable in this browser. The 2D map and analysis remain available.");
      return;
    }
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5));
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    mount.appendChild(renderer.domElement);
    const scene = new THREE.Scene();
    scene.background = new THREE.Color("#143038");
    scene.add(new THREE.HemisphereLight(0xffffff, 0x51685f, 1.9));
    const sun = new THREE.DirectionalLight(0xfff4e0, 2.4);
    sun.position.set(-0.7, 1.1, 0.6);
    scene.add(sun);
    const terrainGroup = new THREE.Group();
    scene.add(terrainGroup);
    const centerX = (data.x_m[0] + data.x_m[data.columns - 1]) / 2;
    const centerY = (data.y_m[0] + data.y_m[data.rows - 1]) / 2;
    const span = Math.max(data.x_m[data.columns - 1] - data.x_m[0], data.y_m[data.rows - 1] - data.y_m[0]);
    const relief = Math.max(1, data.maximum_m - data.minimum_m);
    const positions = new Float32Array(data.rows * data.columns * 3);
    const reliefColors = new Float32Array(data.rows * data.columns * 3);
    const color = new THREE.Color();
    for (let r = 0; r < data.rows; r++) {
      for (let c = 0; c < data.columns; c++) {
        const index = r * data.columns + c;
        const z = data.elevation_m[index];
        positions[index * 3] = data.x_m[c] - centerX;
        positions[index * 3 + 1] = z - data.minimum_m;
        positions[index * 3 + 2] = -(data.y_m[r] - centerY);
        rampColor(Math.max(0, Math.min(1, (z - data.minimum_m) / relief)), color);
        reliefColors.set([color.r, color.g, color.b], index * 3);
      }
    }
    const indices = new Uint32Array((data.rows - 1) * (data.columns - 1) * 6);
    let cursor = 0;
    for (let r = 0; r < data.rows - 1; r++) {
      for (let c = 0; c < data.columns - 1; c++) {
        const a = r * data.columns + c;
        indices.set([a, a + 1, a + data.columns, a + 1, a + data.columns + 1, a + data.columns], cursor);
        cursor += 6;
      }
    }
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
    geometry.setAttribute("color", new THREE.BufferAttribute(reliefColors.slice(), 3));
    geometry.setIndex(new THREE.BufferAttribute(indices, 1));
    geometry.computeVertexNormals();
    const material = new THREE.MeshLambertMaterial({ vertexColors: true, side: THREE.DoubleSide });
    terrainGroup.add(new THREE.Mesh(geometry, material));

    // A thin skirt marks the edge of the measured surface without inventing strata.
    const floor = -Math.max(1.5, relief * 0.06);
    const skirt: number[] = [];
    const addEdge = (a: number, b: number) => {
      const [ax, ay, az] = [positions[a * 3], positions[a * 3 + 1], positions[a * 3 + 2]];
      const [bx, by, bz] = [positions[b * 3], positions[b * 3 + 1], positions[b * 3 + 2]];
      skirt.push(ax, ay, az, bx, by, bz, ax, floor, az, bx, by, bz, bx, floor, bz, ax, floor, az);
    };
    for (let c = 0; c < data.columns - 1; c++) {
      addEdge(c, c + 1);
      addEdge((data.rows - 1) * data.columns + c, (data.rows - 1) * data.columns + c + 1);
    }
    for (let r = 0; r < data.rows - 1; r++) {
      addEdge(r * data.columns, (r + 1) * data.columns);
      addEdge(r * data.columns + data.columns - 1, (r + 1) * data.columns + data.columns - 1);
    }
    const skirtGeometry = new THREE.BufferGeometry();
    skirtGeometry.setAttribute("position", new THREE.Float32BufferAttribute(skirt, 3));
    terrainGroup.add(new THREE.Mesh(skirtGeometry, new THREE.MeshBasicMaterial({ color: "#3d5a52", side: THREE.DoubleSide })));
    terrainGroup.scale.y = exaggeration;

    const camera = new THREE.OrthographicCamera(-1, 1, 1, -1, 1, span * 20);
    const target = new THREE.Vector3(0, relief * exaggeration * 0.3, 0);
    const home = () => camera.position.set(span * 0.75, span * 0.8, span * 1.05);
    home();
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.target.copy(target);
    controls.minZoom = 0.5;
    controls.maxZoom = 6;
    controls.maxPolarAngle = Math.PI * 0.48;
    controls.update();
    let frame = 0;
    const draw = () => {
      if (frame) return;
      frame = requestAnimationFrame(() => {
        frame = 0;
        renderer.render(scene, camera);
        mount.dataset.ready = "true";
      });
    };
    const resize = () => {
      const width = Math.max(1, mount.clientWidth);
      const height = Math.max(1, mount.clientHeight);
      const aspect = width / height;
      const halfY = (span * 0.67) / Math.min(1, aspect);
      camera.left = -halfY * aspect;
      camera.right = halfY * aspect;
      camera.top = halfY;
      camera.bottom = -halfY;
      camera.updateProjectionMatrix();
      renderer.setSize(width, height, false);
      draw();
    };
    const observer = new ResizeObserver(resize);
    observer.observe(mount);
    controls.addEventListener("change", draw);
    const lost = (event: Event) => {
      event.preventDefault();
      onFailure("3D rendering was interrupted. Close this view to continue on the 2D map.");
    };
    renderer.domElement.addEventListener("webglcontextlost", lost);
    stateRef.current = {
      scene, terrainGroup, geometry, material, reliefColors, camera, draw, centerX, centerY, span, relief,
      overlay: null, markers: null, markerHeights: [], imagery: null,
    };
    apiRef.current = {
      reset: () => {
        home();
        camera.zoom = 1;
        camera.updateProjectionMatrix();
        controls.target.copy(target);
        controls.update();
        draw();
      },
      zoom: (factor) => {
        camera.zoom = Math.max(controls.minZoom, Math.min(controls.maxZoom, camera.zoom * factor));
        camera.updateProjectionMatrix();
        draw();
      },
    };
    resize();
    setVersion((value) => value + 1);
    return () => {
      observer.disconnect();
      controls.removeEventListener("change", draw);
      controls.dispose();
      renderer.domElement.removeEventListener("webglcontextlost", lost);
      if (frame) cancelAnimationFrame(frame);
      disposeTree(scene);
      stateRef.current?.imagery?.dispose();
      renderer.dispose();
      renderer.forceContextLoss();
      renderer.domElement.remove();
      stateRef.current = null;
      apiRef.current = null;
    };
  }, [data, apiRef, onFailure]);

  // Satellite drape, loaded lazily and kept for the life of the scene.
  useEffect(() => {
    const state = stateRef.current;
    if (!state || surface !== "imagery" || state.imagery) return;
    const controller = new AbortController();
    imageryTexture(data, controller.signal)
      .then(({ texture, uv }) => {
        const current = stateRef.current;
        if (!current || controller.signal.aborted) { texture.dispose(); return; }
        current.geometry.setAttribute("uv", new THREE.BufferAttribute(uv, 2));
        current.imagery = texture;
        onImageryError(null);
        setVersion((value) => value + 1);
      })
      .catch((cause: Error) => { if (!controller.signal.aborted) onImageryError(cause.message); });
    return () => controller.abort();
  }, [data, surface, version, onImageryError]);

  // Surface colouring, catchment tint and draped overlays for the active site.
  useEffect(() => {
    const state = stateRef.current;
    if (!state) return;
    const useImagery = surface === "imagery" && !!state.imagery;
    state.material.map = useImagery ? state.imagery : null;
    state.material.needsUpdate = true;
    const catchment = localPolygons(site.catchment.geometry, data);
    const colors = state.geometry.getAttribute("color") as THREE.BufferAttribute;
    const tint = new THREE.Color(useImagery ? "#7fe7e2" : "#1aa5a0");
    const blend = useImagery ? 0.35 : 0.5;
    for (let r = 0; r < data.rows; r++) {
      for (let c = 0; c < data.columns; c++) {
        const i = r * data.columns + c;
        const base = useImagery ? [1, 1, 1] : [state.reliefColors[i * 3], state.reliefColors[i * 3 + 1], state.reliefColors[i * 3 + 2]];
        const k = inPolygons(data.x_m[c], data.y_m[r], catchment) ? blend : 0;
        colors.setXYZ(i, base[0] * (1 - k) + tint.r * k, base[1] * (1 - k) + tint.g * k, base[2] * (1 - k) + tint.b * k);
      }
    }
    colors.needsUpdate = true;

    if (state.overlay) { state.terrainGroup.remove(state.overlay); disposeTree(state.overlay); }
    const overlay = new THREE.Group();
    const lift = Math.max(0.15, state.relief * 0.004);
    const drape = (ring: Position[] | LocalRing, local: boolean) => ring.map((point) => {
      const [x, y] = local ? (point as [number, number]) : localPoint(point[0], point[1], data);
      return new THREE.Vector3(x - state.centerX, terrainHeight(data, x, y) - data.minimum_m + lift, -(y - state.centerY));
    });
    const contourMaterial = new THREE.LineBasicMaterial({ color: useImagery ? "#ffe8a8" : "#6b4a2a", transparent: true, opacity: useImagery ? 0.55 : 0.45 });
    const majorMaterial = new THREE.LineBasicMaterial({ color: useImagery ? "#fff3cc" : "#4a2f16", transparent: true, opacity: 0.85 });
    for (const line of result.contours?.features ?? []) {
      overlay.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(drape(line.geometry.coordinates, false)), line.properties.major ? majorMaterial : contourMaterial));
    }
    for (const ring of result.selection.geometry.coordinates) {
      overlay.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(drape(ring, false)), new THREE.LineBasicMaterial({ color: "#ffffff" })));
    }
    for (const rings of catchment) {
      for (const ring of rings) {
        overlay.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(drape(ring, true)), new THREE.LineBasicMaterial({ color: useImagery ? "#8ff5ef" : "#06706c" })));
      }
    }
    const waterLevel = site.pond.crest_elevation_m - data.minimum_m + lift;
    for (const rings of localPolygons(site.pond_region, data)) {
      if (!rings[0]?.length) continue;
      const shape = new THREE.Shape();
      rings[0].forEach(([x, y], index) => (index ? shape.lineTo(x - state.centerX, y - state.centerY) : shape.moveTo(x - state.centerX, y - state.centerY)));
      for (const hole of rings.slice(1)) {
        const path = new THREE.Path();
        hole.forEach(([x, y], index) => (index ? path.lineTo(x - state.centerX, y - state.centerY) : path.moveTo(x - state.centerX, y - state.centerY)));
        shape.holes.push(path);
      }
      const pondGeometry = new THREE.ShapeGeometry(shape);
      pondGeometry.rotateX(-Math.PI / 2);
      const surfaceMesh = new THREE.Mesh(pondGeometry, new THREE.MeshBasicMaterial({ color: "#2a86d6", transparent: true, opacity: 0.82, side: THREE.DoubleSide, depthWrite: false }));
      surfaceMesh.position.y = waterLevel;
      overlay.add(surfaceMesh);
    }
    state.terrainGroup.add(overlay);
    state.overlay = overlay;

    if (state.markers) { state.scene.remove(state.markers); disposeTree(state.markers); }
    const markers = new THREE.Group();
    const heights: number[] = [];
    result.recommendations.forEach((candidate, index) => {
      const active = candidate.site_id === site.site_id;
      const [x, y] = localPoint(candidate.location.coordinates[0], candidate.location.coordinates[1], data);
      const marker = new THREE.Group();
      const stemHeight = state.span * (active ? 0.06 : 0.04);
      const stem = new THREE.Mesh(new THREE.CylinderGeometry(state.span * 0.0018, state.span * 0.0018, stemHeight, 8), new THREE.MeshBasicMaterial({ color: active ? "#f1a36d" : "#ffffff" }));
      stem.position.y = stemHeight / 2;
      marker.add(stem);
      const badge = numberSprite(String(index + 1), active, state.span * (active ? 0.045 : 0.034));
      badge.position.y = stemHeight + state.span * 0.015;
      marker.add(badge);
      marker.position.set(x - state.centerX, 0, -(y - state.centerY));
      heights.push(candidate.elevation_m - data.minimum_m);
      markers.add(marker);
    });
    state.scene.add(markers);
    state.markers = markers;
    state.markerHeights = heights;
    markers.children.forEach((child, index) => { child.position.y = heights[index] * state.terrainGroup.scale.y; });
    state.draw();
  }, [data, site, result, surface, version]);

  useEffect(() => {
    const state = stateRef.current;
    if (!state) return;
    state.terrainGroup.scale.y = exaggeration;
    state.markers?.children.forEach((child, index) => { child.position.y = (state.markerHeights[index] ?? 0) * exaggeration; });
    state.draw();
  }, [exaggeration, version]);

  return <div className="terrain-scene" ref={mountRef} role="img" aria-label={`3D elevation surface from ${data.source}; selected pond site at ${site.elevation_m} metres`} />;
}

export default function TerrainInspector({ result, activeSite, onSiteChange, onClose }: {
  result: Analysis;
  activeSite: Site;
  onSiteChange: (id: string) => void;
  onClose: () => void;
}) {
  const initial = useMemo(() => defaultExaggeration(result.terrain_preview), [result.terrain_preview]);
  const [exaggeration, setExaggeration] = useState(initial);
  const [surface, setSurface] = useState<Surface>("relief");
  const [sceneError, setSceneError] = useState<string | null>(null);
  const [imageryError, setImageryError] = useState<string | null>(null);
  const apiRef = useRef<SceneApi | null>(null);
  useEffect(() => {
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const closeOnEscape = (event: KeyboardEvent) => { if (event.key === "Escape") onClose(); };
    window.addEventListener("keydown", closeOnEscape);
    return () => { document.body.style.overflow = previous; window.removeEventListener("keydown", closeOnEscape); };
  }, [onClose]);
  const index = result.recommendations.findIndex((item) => item.site_id === activeSite.site_id) + 1;
  const preview = result.terrain_preview;
  return (
    <div className="terrain-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
      <section className="terrain-dialog" role="dialog" aria-modal="true" aria-label="3D terrain inspection">
        <header className="terrain-header">
          <div className="terrain-header-title"><Mountain size={21} /><div><strong>3D terrain inspection</strong><span>The exact elevation grid used for routing · illustrative pond stage</span></div></div>
          <button className="terrain-close" type="button" aria-label="Close 3D view" onClick={onClose}><X size={20} /></button>
        </header>
        <div className="terrain-layout">
          <div className="terrain-viewport">
            {sceneError ? (
              <div className="terrain-fallback"><Info size={28} /><strong>3D view unavailable</strong><p>{sceneError}</p><button onClick={onClose}>Return to 2D map</button></div>
            ) : (
              <TerrainScene result={result} site={activeSite} exaggeration={exaggeration} surface={surface} apiRef={apiRef} onFailure={setSceneError} onImageryError={setImageryError} />
            )}
            <div className="terrain-instructions">Drag to orbit · right-drag to pan · scroll or pinch to zoom</div>
            <div className="terrain-view-controls">
              <button type="button" aria-label="Zoom in 3D" onClick={() => apiRef.current?.zoom(1.3)}><Plus size={18} /></button>
              <button type="button" aria-label="Zoom out 3D" onClick={() => apiRef.current?.zoom(1 / 1.3)}><Minus size={18} /></button>
              <button type="button" aria-label="Reset 3D view" onClick={() => apiRef.current?.reset()}><RotateCcw size={17} /></button>
            </div>
          </div>
          <aside className="terrain-inspector">
            <div className="terrain-inspector-top"><span>SELECTED CANDIDATE</span><strong>Site {String(index).padStart(2, "0")}</strong></div>
            <div className="terrain-site-tabs" role="tablist" aria-label="3D pond sites">
              {result.recommendations.map((candidate, candidateIndex) => (
                <button key={candidate.site_id} role="tab" aria-selected={candidate.site_id === activeSite.site_id} onClick={() => onSiteChange(candidate.site_id)}>{String(candidateIndex + 1).padStart(2, "0")}</button>
              ))}
            </div>
            <div className="segmented segmented--small terrain-surface" role="group" aria-label="Surface">
              <button className={surface === "relief" ? "segmented--active" : ""} onClick={() => setSurface("relief")}>Elevation colours</button>
              <button className={surface === "imagery" ? "segmented--active" : ""} onClick={() => setSurface("imagery")}>Satellite drape</button>
            </div>
            {surface === "imagery" && imageryError ? <p className="terrain-caveat">{imageryError} Elevation colours are shown instead.</p> : null}
            <div className="terrain-measure"><span>Outlet ground</span><strong>{activeSite.elevation_m.toFixed(1)} <small>m</small></strong></div>
            <div className="terrain-measure"><span>Water surface (crest)</span><strong>{activeSite.pond.crest_elevation_m.toFixed(1)} <small>m</small></strong></div>
            <div className="terrain-measure"><span>Upstream catchment</span><strong>{activeSite.catchment.area_hectares.toFixed(1)} <small>ha</small></strong></div>
            <div className="terrain-measure"><span>Stored at this stage</span><strong>{Math.round(activeSite.pond.screening_storage_m3).toLocaleString("en-IN")} <small>m³</small></strong></div>
            <label className="terrain-range">
              <span>Vertical exaggeration <strong>{exaggeration}×</strong></span>
              <input type="range" min="1" max="40" step="1" value={exaggeration} onChange={(event) => setExaggeration(Number(event.target.value))} />
              <small>Auto-set to {initial}× for {Math.round(preview.maximum_m - preview.minimum_m)} m of relief.</small>
            </label>
            <div className="terrain-key">
              <div><i className="terrain-key--relief" /> Elevation {preview.minimum_m.toFixed(0)}–{preview.maximum_m.toFixed(0)} m</div>
              <div><i className="terrain-key--contour" /> Contours every {result.contours?.interval_m ?? "–"} m</div>
              <div><i className="terrain-key--catchment" /> Contributing catchment</div>
              <div><i className="terrain-key--water" /> Pond at crest level</div>
              <div><i className="terrain-key--marker" /> Numbered outlets</div>
            </div>
            <p className="terrain-caveat"><Info size={15} /> Relief is exaggerated. This is the {result.elevation.source_key === "copernicus" ? "30 m satellite surface model" : "contour-interpolated grid"}, not an excavation design; verify land and soil on site.</p>
            <button className="terrain-back-button" type="button" onClick={onClose}><ChevronLeft size={16} /> Back to 2D map</button>
          </aside>
        </div>
      </section>
    </div>
  );
}
