/** Shared presentation only: all analytical coordinates remain WGS84 lon/lat. */
export const EMPTY = { type: "FeatureCollection", features: [] };
const CARTO_KEY = __CARTO_KEY_JSON__;
export const CARTO_STYLE =
  "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json";
export const POINT_LIMIT = 5000,
  FILE_LIMIT = 2 * 1024 * 1024;
export function escapeHTML(value) {
  return String(value).replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
}
export function withinBudget(count, limit) {
  return Number.isFinite(count) && count >= 0 && count <= limit;
}
export async function loadWithRetry(load, element) {
  for (;;) {
    try {
      return await load();
    } catch {
      element.replaceChildren(
        document.createTextNode("Dataset unavailable. Check connectivity. "),
      );
      const button = document.createElement("button");
      button.textContent = "Retry dataset";
      element.append(button);
      await new Promise((resolve) => (button.onclick = resolve));
      element.textContent = "Loading dataset…";
    }
  }
}
export function normalizePoint(lon, lat) {
  if (
    lon === "" ||
    lat === "" ||
    lon == null ||
    lat == null ||
    !Number.isFinite(+lon) ||
    !Number.isFinite(+lat) ||
    Math.abs(+lat) > 90
  )
    throw new Error(
      "Enter a finite longitude and latitude between −90 and 90.",
    );
  return [((((+lon + 180) % 360) + 360) % 360) - 180, +lat];
}
export function cartoRequest(url) {
  // Custom protocols (notably pmtiles://https://…) must remain byte-for-byte intact.
  if (!/^https?:\/\//.test(url)) return { url };
  const parsed = new URL(
    url,
    globalThis.location?.href || "https://localhost/",
  );
  if (
    parsed.hostname === "cartocdn.com" ||
    parsed.hostname.endsWith(".cartocdn.com")
  )
    parsed.searchParams.set("key", CARTO_KEY);
  return { url: parsed.href };
}
export function createGeneration() {
  let generation = 0,
    abort;
  return {
    next() {
      abort?.abort();
      abort = new AbortController();
      const id = ++generation;
      return {
        signal: abort.signal,
        current: () => id === generation && !abort.signal.aborted,
      };
    },
    cancel() {
      generation++;
      abort?.abort();
    },
  };
}
export const yieldFrame = () =>
  new Promise((resolve) => setTimeout(resolve, 0));
function csvRow(row) {
  const fields = [];
  let word = "",
    quote = false;
  for (let i = 0; i < row.length; i++) {
    const c = row[i];
    if (c === '"') {
      if (quote && row[i + 1] === '"') {
        word += '"';
        i++;
      } else quote = !quote;
    } else if (c === "," && !quote) {
      fields.push(word);
      word = "";
    } else word += c;
  }
  if (quote) throw new Error("Unclosed CSV quote.");
  fields.push(word);
  return fields;
}
export function parsePoints(text, { limit = POINT_LIMIT } = {}) {
  if (new TextEncoder().encode(text).length > FILE_LIMIT)
    throw new Error("File exceeds 2 MB limit.");
  let rows = [];
  if (text.trimStart().startsWith("{")) {
    const gj = JSON.parse(text);
    const features =
      gj.type === "FeatureCollection"
        ? gj.features
        : gj.type === "Feature"
          ? [gj]
          : [{ geometry: gj }];
    for (const f of features) {
      const g = f.geometry;
      if (g?.type === "Point") rows.push(g.coordinates);
      else if (g?.type === "MultiPoint") rows.push(...g.coordinates);
      else rows.push([]);
      if (rows.length > limit) throw new Error(`Maximum ${limit} points.`);
    }
  } else {
    const lines = text.trim().split(/\r?\n/);
    const first = csvRow(lines[0]).map((c) => c.trim().toLowerCase());
    const lon = first.findIndex((c) => ["lon", "lng", "longitude"].includes(c)),
      lat = first.findIndex((c) => ["lat", "latitude"].includes(c));
    const header = lon >= 0 || lat >= 0;
    if (header && (lon < 0 || lat < 0))
      throw new Error("CSV header needs both longitude and latitude.");
    rows = lines
      .slice(header ? 1 : 0)
      .filter((l) => l.trim())
      .map((l) => {
        const c = csvRow(l);
        return [c[header ? lon : 0]?.trim(), c[header ? lat : 1]?.trim()];
      });
  }
  if (rows.length > limit) throw new Error(`Maximum ${limit} points.`);
  let invalid = 0;
  const points = [];
  for (const row of rows) {
    try {
      points.push(normalizePoint(row[0], row[1]));
    } catch {
      invalid++;
    }
  }
  if (!points.length)
    throw new Error("No valid points. Use lon,lat CSV or GeoJSON Points.");
  return { points, invalid };
}
export async function queryPoints(points, query, task) {
  const results = [];
  for (let i = 0; i < points.length; i++) {
    if (i % 64 === 0) {
      await yieldFrame();
      if (!task.current()) return null;
    }
    results.push(await query(points[i], { signal: task.signal }));
  }
  return task.current() ? results : null;
}
const node = (tag, cls, text) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text) n.textContent = text;
  return n;
};
const json = (value) =>
  JSON.stringify(
    value,
    (_, v) => (typeof v === "bigint" ? v.toString() : v),
    2,
  );
export function createMapDemo({
  container,
  initialView,
  adapter = {},
  limits = {},
}) {
  const canvas = document.getElementById(container),
    frame = canvas.parentElement;
  frame.className = "map-demo";
  canvas.className = "demo-canvas";
  const tools = frame.querySelector(".panel,.coverpanel");
  frame.insertAdjacentHTML(
    "afterbegin",
    `<div class="demo-toolbar"><fieldset><legend>Projection</legend><button data-projection="globe">Globe</button><button data-projection="mercator">Flat (Mercator)</button></fieldset><button class="demo-reset">Reset view</button></div><form class="demo-query"><label>Longitude <input name="longitude" inputmode="decimal" required value="${initialView.center[0]}"></label><label>Latitude <input name="latitude" inputmode="decimal" required value="${initialView.center[1]}"></label><button type="submit">Inspect point</button><label>Presets <select name="preset"><option value="">Choose a place</option></select></label></form>`,
  );
  const body = node("div", "demo-body"),
    side = node("aside", "demo-side");
  side.setAttribute("aria-label", "Map inspector");
  body.append(canvas, side);
  frame.append(body);
  side.innerHTML =
    '<h3>Layers</h3><label><input type="checkbox" class="demo-visible" checked> Demo layers</label><label>Opacity <input class="demo-opacity" type="range" min="0" max="100" value="100"></label><div class="demo-result" aria-live="polite"><h3>Selected point</h3>Select a point using the map or coordinates.</div><div class="demo-actions"><button data-action="copy">Copy result</button><button data-action="coordinates">Copy coordinates</button><button data-action="clear">Clear selection</button></div>';
  let output = side.querySelector(".demo-result");
  const existing = tools?.querySelector("#result");
  if (existing) {
    existing.className = "demo-result";
    existing.setAttribute("aria-live", "polite");
    output.replaceWith(existing);
    output = existing;
  }
  if (tools) {
    tools.classList.remove("min");
    tools.querySelector("#seg-proj")?.parentElement.remove();
    const details = node("details", "demo-tools");
    details.append(node("summary", null, "Layers and tools"), tools);
    side.append(details);
  }
  const status = node("div", "demo-status", "Loading map…");
  status.setAttribute("role", "status");
  frame.append(status);
  const layerStatus = tools?.querySelector("#status,#stats,#cover-status");
  if (layerStatus) {
    layerStatus.className = "demo-status demo-layer-status";
    layerStatus.setAttribute("role", "status");
    frame.append(layerStatus);
  }
  const selectTask = createGeneration(),
    batchTask = createGeneration(),
    tasks = new Map();
  let point = null,
    lastResult = null,
    marker = null,
    destroyed = false,
    loaded = false;
  const projectionKey =
    container === "map" ? "projection" : `${container}-projection`;
  const projection = () => {
    const value = new URL(location.href).searchParams.get(projectionKey);
    return value === "globe" || value === "mercator"
      ? value
      : initialView.projection || "globe";
  };
  const map = new maplibregl.Map({
    container,
    style: CARTO_STYLE,
    transformRequest: cartoRequest,
    center: initialView.center,
    zoom: initialView.zoom,
    maxTileCacheSize: 80,
    canvasContextAttributes: { preserveDrawingBuffer: false },
  });
  map.addControl(new maplibregl.NavigationControl(), "top-left");
  const uiProjection = () => {
    const p = projection();
    frame
      .querySelectorAll("[data-projection]")
      .forEach((b) =>
        b.setAttribute("aria-pressed", String(b.dataset.projection === p)),
      );
    return p;
  };
  uiProjection();
  map.on("style.load", () => {
    map.setProjection({ type: uiProjection() });
    // CARTO interleaves some labels and geometry. Group labels at the top so
    // analytical fills stay above ALL basemap geometry, below ONLY labels.
    for (const layer of map.getStyle().layers) {
      if (layer.type === "symbol") map.moveLayer(layer.id);
    }
  });
  const notify = (message) => {
    status.textContent = message;
  };
  function present(result) {
    lastResult = result;
    if (adapter.describeResult) {
      adapter.describeResult(result, output);
      return;
    }
    output.replaceChildren(node("h3", null, "Selected point"));
    const table = node("table");
    for (const [key, value] of Object.entries(result ?? {})) {
      const tr = node("tr"),
        th = node("th", null, key),
        td = node(
          "td",
          null,
          value == null
            ? "Unknown"
            : typeof value === "object"
              ? json(value)
              : String(value),
        );
      tr.append(th, td);
      table.append(tr);
    }
    output.append(table);
  }
  async function select(lon, lat, { fly = false } = {}) {
    const task = selectTask.next();
    try {
      point = normalizePoint(lon, lat);
      frame.querySelector("[name=longitude]").value = point[0].toFixed(6);
      frame.querySelector("[name=latitude]").value = point[1].toFixed(6);
      marker?.remove();
      marker = new maplibregl.Marker({ element: node("div", "demo-marker") })
        .setLngLat(point)
        .addTo(map);
      if (fly) map.jumpTo({ center: point });
      if (!loaded) {
        notify("Map is loading. Inspect again when ready.");
        return;
      }
      notify("Inspecting point…");
      const result = await adapter.queryPoint(point, { signal: task.signal });
      if (task.current()) {
        present(result);
        notify("Point ready.");
      }
    } catch (e) {
      if (task.current()) notify(e.message);
    }
  }
  function clear() {
    selectTask.cancel();
    point = null;
    lastResult = null;
    marker?.remove();
    marker = null;
    adapter.clearSelection?.();
    output.replaceChildren(
      node("h3", null, "Selected point"),
      node("p", null, "Select a point using the map or coordinates."),
    );
    notify("Selection cleared.");
  }
  const opacity = new Map();
  let previousVisible = true;
  function applyLayers() {
    const visible = side.querySelector(".demo-visible").checked,
      factor = +side.querySelector(".demo-opacity").value / 100;
    for (const layer of map.getStyle()?.layers || []) {
      if (
        !(
          (adapter.layers || []).includes(layer.id) || layer.id === "demo-batch"
        )
      )
        continue;
      map.setLayoutProperty(
        layer.id,
        "visibility",
        visible ? "visible" : "none",
      );
      const prop = {
        fill: "fill-opacity",
        line: "line-opacity",
        circle: "circle-opacity",
      }[layer.type];
      if (prop) {
        if (!opacity.has(layer.id))
          opacity.set(layer.id, map.getPaintProperty(layer.id, prop) ?? 1);
        map.setPaintProperty(layer.id, prop, [
          "*",
          factor,
          opacity.get(layer.id),
        ]);
      }
    }
    if (previousVisible !== visible) {
      previousVisible = visible;
      adapter.setVisible?.(visible);
    }
  }
  const originalAdd = map.addLayer.bind(map);
  map.addLayer = (layer, before) => {
    // CARTO's vector labels remain legible above analytical fills/lines.
    const labels = map.getStyle()?.layers.find((item) => item.type === "symbol")?.id;
    const result = originalAdd(layer, before ?? labels);
    if (
      (adapter.layers || []).includes(layer.id) ||
      layer.id === "demo-batch"
    ) {
      opacity.delete(layer.id);
      applyLayers();
    }
    return result;
  };
  side.querySelector(".demo-visible").onchange = applyLayers;
  side.querySelector(".demo-opacity").oninput = applyLayers;
  frame.querySelector(".demo-query").onsubmit = (e) => {
    e.preventDefault();
    select(
      frame.querySelector("[name=longitude]").value,
      frame.querySelector("[name=latitude]").value,
      { fly: true },
    );
  };
  frame.querySelector(".demo-reset").onclick = () => {
    map.jumpTo({ ...initialView, bearing: 0, pitch: 0 });
    notify("View reset.");
  };
  frame.querySelectorAll("[data-projection]").forEach(
    (b) =>
      (b.onclick = () => {
        const url = new URL(location.href);
        url.searchParams.set(projectionKey, b.dataset.projection);
        history.pushState(null, "", url);
        map.setProjection({ type: uiProjection() });
      }),
  );
  const pop = () => {
    if (loaded) map.setProjection({ type: uiProjection() });
  };
  addEventListener("popstate", pop);
  const preset = frame.querySelector("[name=preset]");
  for (const [i, p] of (adapter.presets || []).entries()) {
    const option = node("option", null, p.name);
    option.value = String(i);
    preset.append(option);
  }
  preset.onchange = () => {
    if (preset.value === "") return;
    const p = adapter.presets[+preset.value];
    map.jumpTo({ center: p.center, zoom: p.zoom ?? initialView.zoom });
    select(...p.center);
  };
  side.querySelector("[data-action=clear]").onclick = clear;
  for (const action of ["copy", "coordinates"])
    side.querySelector(`[data-action=${action}]`).onclick = async () => {
      if (!point) {
        notify("Select a point first.");
        return;
      }
      try {
        await navigator.clipboard.writeText(
          action === "copy" ? json(lastResult) : point.join(", "),
        );
        notify("Copied.");
      } catch {
        notify("Clipboard unavailable. Select and copy the inspector text.");
      }
    };
  map.on("load", () => {
    loaded = true;
    notify("Map ready.");
  });
  map.on("click", (e) => {
    if (adapter.acceptClick?.(e) === false) return;
    select(e.lngLat.lng, e.lngLat.lat);
  });
  map.on("error", () => {
    status.replaceChildren(
      node(
        "span",
        null,
        "Basemap or overlay resource unavailable. Check connectivity and source access. ",
      ),
    );
    const retry = node("button", null, "Retry map");
    retry.onclick = () => location.reload();
    status.append(retry);
  });
  if (adapter.queryBatch) {
    const upload = node("details", "demo-batch");
    upload.innerHTML =
      '<summary>Point dataset</summary><p>CSV lon,lat or GeoJSON Points. Files stay on this device. Maximum 5,000 points / 2 MB; invalid rows are counted.</p><input type="file" accept=".csv,.json,.geojson,.txt" aria-label="Open point dataset"><div class="demo-actions"><button class="batch-sample">Sample points</button><button class="batch-clear">Clear dataset</button></div>';
    side.append(upload);
    async function run(points, invalid = 0) {
      const task = batchTask.next();
      if (!loaded) {
        notify("Wait for the map to load.");
        return;
      }
      notify("Classifying point dataset…");
      try {
        const results = await queryPoints(points, adapter.queryBatch, task);
        if (!results) return;
        const features = results.map((r, i) => ({
          type: "Feature",
          properties: { color: adapter.pointColor?.(r) || "#b83f25" },
          geometry: { type: "Point", coordinates: points[i] },
        }));
        if (!map.getSource("demo-batch")) {
          map.addSource("demo-batch", { type: "geojson", data: EMPTY });
          map.addLayer({
            id: "demo-batch",
            type: "circle",
            source: "demo-batch",
            paint: {
              "circle-color": ["get", "color"],
              "circle-radius": 4,
              "circle-stroke-color": "#fff",
              "circle-stroke-width": 1,
            },
          });
        }
        map
          .getSource("demo-batch")
          .setData({ type: "FeatureCollection", features });
        notify(
          `${results.length} points classified; ${invalid} invalid rows skipped.`,
        );
      } catch (e) {
        if (task.current()) notify(e.message);
      }
    }
    upload.querySelector("input").onchange = async (e) => {
      const file = e.target.files[0];
      const task = batchTask.next();
      if (!file) return;
      try {
        if (file.size > FILE_LIMIT) throw new Error("File exceeds 2 MB limit.");
        const text = await file.text();
        if (!task.current()) return;
        const parsed = parsePoints(text, {
          limit: limits.points || POINT_LIMIT,
        });
        await run(parsed.points, parsed.invalid);
      } catch (e) {
        if (task.current()) notify(e.message);
      } finally {
        e.target.value = "";
      }
    };
    upload.querySelector(".batch-sample").onclick = () =>
      run((adapter.presets || []).map((p) => p.center));
    upload.querySelector(".batch-clear").onclick = () => {
      batchTask.cancel();
      map.getSource("demo-batch")?.setData(EMPTY);
      notify("Point dataset cleared.");
    };
  }
  const dispose = () => {
    if (destroyed) return;
    destroyed = true;
    selectTask.cancel();
    batchTask.cancel();
    for (const t of tasks.values()) t.cancel();
    removeEventListener("popstate", pop);
    adapter.dispose?.();
    map.remove();
  };
  addEventListener("pagehide", (event) => {
    if (!event.persisted) dispose();
  });
  return {
    map,
    select,
    clear,
    present,
    notify,
    refreshSelection: () => point && select(...point),
    applyLayers,
    setPaint(id, property, value) {
      map.setPaintProperty(id, property, value);
      if (property.endsWith("-opacity")) {
        opacity.set(id, value);
        applyLayers();
      }
    },
    task(name) {
      if (!tasks.has(name)) tasks.set(name, createGeneration());
      return tasks.get(name).next();
    },
    cancel(name) {
      tasks.get(name)?.cancel();
    },
    destroy: dispose,
  };
}
