const TAU = Math.PI * 2;
const WHEEL_CONTINUOUS_STEP = 1;
const WHEEL_CONTINUOUS_OVERLAP = 0.12;
const FIXED_MATCH_EDGE_INSET = 7.5;
const ADJACENT_PREFETCH_DEGREES = 1;
const WHEEL_DARK_LIGHTNESS = 0.35;
const WHEEL_LIGHT_LIGHTNESS = 0.90;
const WHEEL_DARK_END = 0.10;
const WHEEL_VIVID_END = 0.70;
const WHEEL_PEAK_SEARCH_STEPS = 100;
const IMAGE_PALETTE_UPLOAD_LIMIT = 3_500_000;
const IMAGE_PALETTE_MAX_DIMENSION = 1000;

// Approximate OKLCH positions sampled from GOLDEN Heavy Body Acrylic 1:1 tint
// swatches, where transparent paints reveal their undertones. Mixtures and hue
// replacements are identified as such instead of being assigned one pigment.
// Source: https://goldenartistcolors.com/products/golden-artist-acrylics/heavy-body/technical-chart
const ARTIST_PIGMENTS = [
  { name: "Pyrrole red", code: "PR254", hue: 13.8, color: "#e75b71" },
  { name: "Cadmium red medium", code: "PR108", hue: 18.2, color: "#dd7479" },
  { name: "Red oxide", code: "PR101", hue: 24.0, color: "#a15a56" },
  { name: "Pyrrole orange", code: "PO73", hue: 25.4, color: "#fe7b73" },
  { name: "Cadmium red light", code: "PR108", hue: 26.4, color: "#fb756b" },
  { name: "Cadmium orange", code: "PO20", hue: 41.6, color: "#fc895c" },
  { name: "Burnt sienna", code: "PBr7", hue: 54.9, color: "#c39373" },
  { name: "Burnt umber", code: "PBr7", hue: 59.6, color: "#8b7a6d" },
  { name: "Yellow ochre", code: "PY42", hue: 77.0, color: "#eec588" },
  { name: "Raw sienna", code: "PBr7", hue: 77.9, color: "#f1c175" },
  { name: "Nickel azo yellow", code: "PY150", hue: 94.3, color: "#f6d34c" },
  { name: "Raw umber", code: "PBr7", hue: 101.6, color: "#8a8980" },
  { name: "Benzimidazolone yellow medium", code: "PY154", hue: 103.3, color: "#fdee60" },
  { name: "Cadmium yellow medium", code: "PY35", hue: 104.1, color: "#fcec32" },
  { name: "Benzimidazolone yellow light", code: "PY175", hue: 106.1, color: "#fbf471" },
  { name: "Cadmium yellow light", code: "PY35", hue: 108.1, color: "#fcf965" },
  { name: "Green gold", code: "PY129", hue: 111.4, color: "#c6cb47" },
  { name: "Sap green hue", code: "hue", hue: 130.9, color: "#7c9e5c" },
  { name: "Chromium oxide green", code: "PG17", hue: 145.6, color: "#7bab7d" },
  { name: "Phthalo green yellow shade", code: "PG36", hue: 155.7, color: "#03b66b" },
  { name: "Phthalo green blue shade", code: "PG7", hue: 156.6, color: "#03a060" },
  { name: "Permanent green light", code: "mix", hue: 163.1, color: "#06b27d" },
  { name: "Viridian green hue", code: "hue", hue: 170.0, color: "#60b599" },
  { name: "Cobalt green", code: "PG26", hue: 178.7, color: "#90bab0" },
  { name: "Cobalt teal", code: "PG50", hue: 203.9, color: "#76dbe5" },
  { name: "Turquoise phthalo", code: "mix", hue: 207.0, color: "#038f9d" },
  { name: "Cobalt turquoise", code: "PG50", hue: 214.4, color: "#6eb2c2" },
  { name: "Manganese blue hue", code: "hue", hue: 219.6, color: "#4cccef" },
  { name: "Cerulean blue deep", code: "PB36", hue: 243.1, color: "#6fa3cc" },
  { name: "Primary cyan", code: "mix", hue: 244.8, color: "#0793e5" },
  { name: "Phthalo blue green shade", code: "PB15:3", hue: 250.9, color: "#0376ce" },
  { name: "Phthalo blue red shade", code: "PB15:1", hue: 253.4, color: "#0570cf" },
  { name: "Cerulean blue", code: "PB36", hue: 257.6, color: "#81b0f4" },
  { name: "Cobalt blue", code: "PB28", hue: 264.0, color: "#6f98ef" },
  { name: "Ultramarine blue", code: "PB29", hue: 267.6, color: "#577bea" },
  { name: "Dioxazine purple", code: "PV23", hue: 297.7, color: "#634895" },
  { name: "Ultramarine violet", code: "PV15", hue: 306.6, color: "#c7b0e0" },
  { name: "Cobalt violet hue", code: "hue", hue: 327.9, color: "#af7bad" },
  { name: "Quinacridone violet", code: "PV19", hue: 331.7, color: "#a4689c" },
  { name: "Quinacridone magenta", code: "PR122", hue: 342.4, color: "#d45cac" },
  { name: "Quinacridone red", code: "PR209", hue: 356.3, color: "#e66099" },
];
const PIGMENT_CLUSTER_DEGREES = 5;

const clamp = (value, minimum, maximum) => Math.min(maximum, Math.max(minimum, value));

function linearToSrgb(value) {
  const converted = value <= 0.0031308
    ? 12.92 * value
    : 1.055 * Math.pow(value, 1 / 2.4) - 0.055;
  return converted;
}

function oklchChannels(lightness, chroma, hue) {
  const radians = hue * Math.PI / 180;
  const a = chroma * Math.cos(radians);
  const b = chroma * Math.sin(radians);
  const lRoot = lightness + 0.3963377774 * a + 0.2158037573 * b;
  const mRoot = lightness - 0.1055613458 * a - 0.0638541728 * b;
  const sRoot = lightness - 0.0894841775 * a - 1.291485548 * b;
  const l = lRoot ** 3;
  const m = mRoot ** 3;
  const s = sRoot ** 3;
  return [
    linearToSrgb(4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s),
    linearToSrgb(-1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s),
    linearToSrgb(-0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s),
  ];
}

function channelsInGamut(channels) {
  return channels.every((channel) => channel >= 0 && channel <= 1);
}

function rgbString(channels) {
  const [red, green, blue] = channels.map((channel) => clamp(channel, 0, 1));
  return `rgb(${Math.round(red * 255)} ${Math.round(green * 255)} ${Math.round(blue * 255)})`;
}

function maximumChromaAtLightness(lightness, hue) {
  let low = 0;
  let high = 0.5;
  for (let attempt = 0; attempt < 20; attempt += 1) {
    const candidate = (low + high) / 2;
    if (channelsInGamut(oklchChannels(lightness, candidate, hue))) {
      low = candidate;
    } else {
      high = candidate;
    }
  }
  return low;
}

function maximumChromaColorAtLightness(lightness, hue) {
  const chroma = maximumChromaAtLightness(lightness, hue);
  return rgbString(oklchChannels(lightness, chroma, hue));
}

function peakChromaColor(hue) {
  let bestLightness = 0.5;
  let bestChroma = 0;
  for (let step = 1; step < WHEEL_PEAK_SEARCH_STEPS; step += 1) {
    const lightness = step / WHEEL_PEAK_SEARCH_STEPS;
    const chroma = maximumChromaAtLightness(lightness, hue);
    if (chroma > bestChroma) {
      bestLightness = lightness;
      bestChroma = chroma;
    }
  }
  return rgbString(oklchChannels(bestLightness, bestChroma, hue));
}

function wheelRamp(hue) {
  const vividColor = peakChromaColor(hue);
  return [
    {
      position: 0,
      color: maximumChromaColorAtLightness(WHEEL_DARK_LIGHTNESS, hue),
    },
    { position: WHEEL_DARK_END, color: vividColor },
    { position: WHEEL_VIVID_END, color: vividColor },
    {
      position: 1,
      color: maximumChromaColorAtLightness(WHEEL_LIGHT_LIGHTNESS, hue),
    },
  ];
}

function hueName(hue) {
  const names = [
    [15, "red"], [45, "vermilion"], [75, "orange"], [105, "amber"],
    [140, "yellow"], [170, "green"], [205, "cyan"], [240, "azure"],
    [275, "blue"], [310, "violet"], [340, "magenta"], [360, "crimson"],
  ];
  const normalized = ((hue % 360) + 360) % 360;
  return names.find(([boundary]) => normalized < boundary)?.[1] || "red";
}

const normalizeHue = (hue) => ((hue % 360) + 360) % 360;

const clockwiseSpan = (start, end) => normalizeHue(end - start);

const circularDistance = (first, second) => Math.abs(
  ((first - second + 540) % 360) - 180,
);

const themeColor = (name) => getComputedStyle(document.documentElement)
  .getPropertyValue(name)
  .trim();

async function imagePaletteUpload(file) {
  if (file.size <= IMAGE_PALETTE_UPLOAD_LIMIT) return file;

  const objectUrl = URL.createObjectURL(file);
  try {
    const image = new Image();
    image.decoding = "async";
    image.src = objectUrl;
    await new Promise((resolve, reject) => {
      image.addEventListener("load", resolve, { once: true });
      image.addEventListener("error", reject, { once: true });
    });
    const scale = Math.min(
      1,
      IMAGE_PALETTE_MAX_DIMENSION / Math.max(image.naturalWidth, image.naturalHeight),
    );
    const canvas = document.createElement("canvas");
    canvas.width = Math.max(1, Math.round(image.naturalWidth * scale));
    canvas.height = Math.max(1, Math.round(image.naturalHeight * scale));
    const context = canvas.getContext("2d");
    context.fillStyle = "#ffffff";
    context.fillRect(0, 0, canvas.width, canvas.height);
    context.drawImage(image, 0, 0, canvas.width, canvas.height);
    const blob = await new Promise((resolve) => {
      canvas.toBlob(resolve, "image/jpeg", 0.9);
    });
    if (!blob) throw new Error("Image conversion failed.");
    return blob;
  } finally {
    URL.revokeObjectURL(objectUrl);
  }
}

function sectionsFromUrl(value) {
  if (!value) return [];
  return value.split(",").slice(0, 4).flatMap((rawSection) => {
    const [rawStart, rawEnd, ...extra] = rawSection.split(":");
    const start = Number(rawStart);
    const end = Number(rawEnd);
    if (
      extra.length
      || !Number.isFinite(start)
      || !Number.isFinite(end)
    ) return [];
    const normalizedStart = normalizeHue(Math.round(start));
    const normalizedEnd = normalizeHue(Math.round(end));
    const span = clockwiseSpan(normalizedStart, normalizedEnd);
    if (span < 1 || span > 359) return [];
    return [{ start: normalizedStart, end: normalizedEnd }];
  });
}

function sliceStateFromUrl() {
  const params = new URLSearchParams(window.location.search);
  if (params.get("mode") === "custom") {
    const sections = sectionsFromUrl(params.get("ranges"));
    if (sections.length) return { mode: "custom", sections };
  }

  if (!params.has("center") || !params.has("span")) return null;
  const center = Number(params.get("center"));
  const span = Number(params.get("span"));
  if (!Number.isFinite(center) || ![90, 120].includes(span)) return null;
  return {
    mode: "standard",
    center: normalizeHue(Math.round(center)),
    span,
  };
}

function syncSliceUrl(state) {
  const url = new URL(window.location.href);
  if (
    url.searchParams.get("view") === "art"
    || url.searchParams.get("mode") === "art"
  ) return;
  ["center", "span", "mode", "ranges"].forEach(
    (parameter) => url.searchParams.delete(parameter),
  );
  if (state.mode === "custom") {
    url.searchParams.set("mode", "custom");
    url.searchParams.set(
      "ranges",
      state.sections.map((section) => `${section.start}:${section.end}`).join(","),
    );
  } else {
    url.searchParams.set("center", String(Math.round(state.center)));
    url.searchParams.set("span", String(state.span));
  }
  window.history.replaceState(null, "", url);
}

class ColorWheel {
  constructor(canvas, onChange) {
    this.canvas = canvas;
    this.context = canvas.getContext("2d");
    this.centerHue = 75;
    this.span = 120;
    this.mode = "standard";
    this.customSections = [{ id: 1, start: 15, end: 135 }];
    this.activeSectionId = 1;
    this.nextSectionId = 2;
    this.activeBoundary = null;
    this.dragMode = null;
    this.dragOriginHue = 0;
    this.dragOriginStart = 0;
    this.dragOriginEnd = 0;
    this.dragOriginCenter = 0;
    this.continuousFills = null;
    this.onChange = onChange;
    this.dragging = false;
    this.resizeObserver = new ResizeObserver(() => this.draw());
    this.resizeObserver.observe(canvas);
    this.themeQuery = window.matchMedia("(prefers-color-scheme: dark)");
    this.themeQuery.addEventListener("change", () => this.draw());
    this.bindEvents();
    this.draw();
  }

  bindEvents() {
    const wheelCenter = document.querySelector("#wheel-center");
    const start = (event) => {
      const pointer = this.pointerDetails(event);
      if (
        event.currentTarget === wheelCenter
        || pointer.radiusRatio < 0.48
      ) return;
      const hit = this.selectionHit(pointer.hue);
      if (!hit) return;
      this.activeBoundary = hit.edge;
      this.dragMode = this.mode === "custom" && hit.edge ? "boundary" : "move";
      this.dragOriginHue = Math.round(pointer.hue);
      this.dragOriginCenter = this.centerHue;
      if (this.mode === "custom") {
        this.activeSectionId = hit.section.id;
        this.dragOriginStart = hit.section.start;
        this.dragOriginEnd = hit.section.end;
      }
      this.dragging = true;
      this.canvas.setPointerCapture(event.pointerId);
      if (this.dragMode === "boundary") {
        this.updateFromPointer(event);
      } else {
        this.draw();
        this.onChange(this.state(), false);
      }
    };
    const move = (event) => {
      if (this.dragging) this.updateFromPointer(event);
    };
    const finish = (event) => {
      if (!this.dragging) return;
      this.dragging = false;
      if (this.canvas.hasPointerCapture(event.pointerId)) {
        this.canvas.releasePointerCapture(event.pointerId);
      }
      if (this.mode === "custom") this.mergeCustomSections();
      this.onChange(this.state(), true);
    };
    this.canvas.addEventListener("pointerdown", start);
    this.canvas.addEventListener("pointermove", move);
    this.canvas.addEventListener("pointerup", finish);
    this.canvas.addEventListener("pointercancel", finish);
    wheelCenter?.addEventListener("pointerdown", start);
    wheelCenter?.addEventListener("pointermove", move);
    wheelCenter?.addEventListener("pointerup", finish);
    wheelCenter?.addEventListener("pointercancel", finish);
    this.canvas.addEventListener("keydown", (event) => {
      if (
        this.mode === "custom"
        && ["Backspace", "Delete"].includes(event.key)
      ) {
        event.preventDefault();
        this.removeActiveSection();
        return;
      }
      if (!["ArrowLeft", "ArrowRight"].includes(event.key)) return;
      event.preventDefault();
      const direction = event.key === "ArrowRight" ? 1 : -1;
      if (this.mode === "custom") {
        this.adjustBoundary(this.activeBoundary || "end", direction);
        return;
      }
      this.centerHue = normalizeHue(Math.round(this.centerHue) + direction);
      this.draw();
      this.onChange(this.state(), true);
    });
  }

  state() {
    const activeSection = this.activeSection();
    return {
      center: this.centerHue,
      span: this.span,
      mode: this.mode,
      start: this.mode === "custom"
        ? activeSection.start
        : normalizeHue(this.centerHue - this.span / 2),
      end: this.mode === "custom"
        ? activeSection.end
        : normalizeHue(this.centerHue + this.span / 2),
      totalSpan: this.mode === "custom" ? this.uniqueCustomSpan() : this.span,
      activeSectionId: this.activeSectionId,
      sections: this.mode === "custom"
        ? this.customSections.map((section) => ({ ...section }))
        : [],
    };
  }

  restore(state) {
    if (state.mode === "custom") {
      this.mode = "custom";
      this.customSections = state.sections.map((section) => ({
        id: this.nextSectionId++,
        start: section.start,
        end: section.end,
      }));
      this.activeSectionId = this.customSections[0].id;
      this.activeBoundary = "end";
      this.mergeCustomSections();
      this.updateCustomGeometry();
    } else {
      this.mode = "standard";
      this.centerHue = state.center;
      this.span = state.span;
      this.activeBoundary = null;
    }
    this.draw();
  }

  activeSection() {
    return this.customSections.find(
      (section) => section.id === this.activeSectionId,
    ) || this.customSections[0];
  }

  hueInsideSection(hue, section) {
    return clockwiseSpan(section.start, hue) <= clockwiseSpan(
      section.start,
      section.end,
    );
  }

  selectionSections() {
    if (this.mode === "custom") return this.customSections;
    return [{
      id: 0,
      start: normalizeHue(this.centerHue - this.span / 2),
      end: normalizeHue(this.centerHue + this.span / 2),
    }];
  }

  selectionHit(hue) {
    const sections = this.selectionSections();
    const boundaryHits = sections.flatMap((section) => [
      { section, edge: "start", distance: circularDistance(hue, section.start) },
      { section, edge: "end", distance: circularDistance(hue, section.end) },
    ]).filter((hit) => hit.distance <= 10);
    boundaryHits.sort((first, second) => (
      Number(second.section.id === this.activeSectionId)
      - Number(first.section.id === this.activeSectionId)
      || first.distance - second.distance
    ));
    if (boundaryHits.length) return boundaryHits[0];

    const activeSection = this.mode === "custom"
      ? this.activeSection()
      : sections[0];
    if (activeSection && this.hueInsideSection(hue, activeSection)) {
      return { section: activeSection, edge: null };
    }
    const section = sections.find(
      (candidate) => this.hueInsideSection(hue, candidate),
    );
    return section ? { section, edge: null } : null;
  }

  pointerDetails(event) {
    const bounds = this.canvas.getBoundingClientRect();
    const x = event.clientX - bounds.left - bounds.width / 2;
    const y = event.clientY - bounds.top - bounds.height / 2;
    return {
      hue: normalizeHue(Math.atan2(y, x) * 180 / Math.PI + 90),
      radiusRatio: Math.hypot(x, y) / (Math.min(bounds.width, bounds.height) / 2),
    };
  }

  updateFromPointer(event) {
    const { hue } = this.pointerDetails(event);
    if (this.mode === "custom") {
      if (this.dragMode === "move") {
        const delta = Math.round(hue) - this.dragOriginHue;
        const section = this.activeSection();
        section.start = normalizeHue(this.dragOriginStart + delta);
        section.end = normalizeHue(this.dragOriginEnd + delta);
        this.updateCustomGeometry();
      } else {
        this.setCustomBoundary(this.activeBoundary, Math.round(hue));
      }
    } else {
      const delta = Math.round(hue) - this.dragOriginHue;
      this.centerHue = normalizeHue(this.dragOriginCenter + delta);
    }
    this.draw();
    this.onChange(this.state(), false);
  }

  updateCustomGeometry() {
    const section = this.activeSection();
    this.span = clockwiseSpan(section.start, section.end);
    this.centerHue = normalizeHue(section.start + this.span / 2);
  }

  setCustomBoundary(edge, hue) {
    const section = this.activeSection();
    let nextHue = normalizeHue(Math.round(hue));
    if (edge === "start") {
      if (nextHue === section.end) nextHue = normalizeHue(section.end - 1);
      section.start = nextHue;
    } else {
      if (nextHue === section.start) nextHue = normalizeHue(section.start + 1);
      section.end = nextHue;
    }
    this.updateCustomGeometry();
  }

  adjustBoundary(edge, delta) {
    this.activeBoundary = edge;
    const section = this.activeSection();
    const currentHue = edge === "start" ? section.start : section.end;
    this.setCustomBoundary(edge, currentHue + delta);
    this.mergeCustomSections();
    this.draw();
    this.onChange(this.state(), true);
  }

  customMask() {
    return Array.from(
      { length: 360 },
      (_, degree) => this.customSections.some(
        (section) => this.hueInsideSection(degree + 0.5, section),
      ),
    );
  }

  uniqueCustomSpan() {
    return this.customMask().filter(Boolean).length;
  }

  mergeCustomSections() {
    if (this.customSections.length < 2) return;
    const mask = this.customMask();
    const covered = mask.filter(Boolean).length;
    if (covered === 360) return;
    const firstGap = mask.findIndex((value) => !value);
    const runs = [];
    let runStart = null;
    for (let offset = 1; offset <= 360; offset += 1) {
      const degree = (firstGap + offset) % 360;
      if (mask[degree] && runStart === null) runStart = degree;
      if (!mask[degree] && runStart !== null) {
        runs.push({ start: runStart, end: degree });
        runStart = null;
      }
    }
    if (runs.length >= this.customSections.length) return;

    const previousCenter = normalizeHue(
      this.activeSection().start
      + clockwiseSpan(this.activeSection().start, this.activeSection().end) / 2,
    );
    this.customSections = runs.map((run) => ({
      id: this.nextSectionId++,
      start: run.start,
      end: run.end,
    }));
    const active = this.customSections.find(
      (section) => this.hueInsideSection(previousCenter, section),
    ) || this.customSections[0];
    this.activeSectionId = active.id;
    this.updateCustomGeometry();
    this.draw();
  }

  addSection() {
    if (this.customSections.length >= 4) return;
    const mask = this.customMask();
    const firstCovered = mask.findIndex(Boolean);
    if (firstCovered < 0) return;

    let bestStart = 0;
    let bestLength = 0;
    let currentStart = null;
    for (let offset = 1; offset <= 360; offset += 1) {
      const degree = (firstCovered + offset) % 360;
      if (!mask[degree] && currentStart === null) currentStart = degree;
      if (mask[degree] && currentStart !== null) {
        const length = (degree - currentStart + 360) % 360;
        if (length > bestLength) {
          bestStart = currentStart;
          bestLength = length;
        }
        currentStart = null;
      }
    }
    if (bestLength < 1) return;
    const width = Math.min(30, bestLength);
    const start = normalizeHue(bestStart + Math.floor((bestLength - width) / 2));
    const section = {
      id: this.nextSectionId++,
      start,
      end: normalizeHue(start + width),
    };
    this.customSections.push(section);
    this.activeSectionId = section.id;
    this.activeBoundary = "end";
    this.updateCustomGeometry();
    this.draw();
    this.onChange(this.state(), true);
  }

  removeActiveSection() {
    if (this.customSections.length <= 1) return;
    const index = this.customSections.findIndex(
      (section) => section.id === this.activeSectionId,
    );
    this.customSections.splice(index, 1);
    this.activeSectionId = this.customSections[Math.max(0, index - 1)].id;
    this.activeBoundary = "end";
    this.updateCustomGeometry();
    this.draw();
    this.onChange(this.state(), true);
  }

  activateCustom() {
    if (this.mode !== "custom") {
      const section = this.activeSection();
      section.start = normalizeHue(Math.round(this.centerHue - this.span / 2));
      section.end = normalizeHue(Math.round(this.centerHue + this.span / 2));
      this.customSections = [section];
      this.activeSectionId = section.id;
    }
    this.mode = "custom";
    this.activeBoundary = "end";
    this.updateCustomGeometry();
    this.draw();
  }

  setStandardSpan(span) {
    this.mode = "standard";
    this.span = span;
    this.centerHue = normalizeHue(Math.round(this.centerHue));
    this.activeBoundary = null;
    this.draw();
  }

  gradientFromRamp(ramp, innerRadius, outerRadius) {
    const center = this.canvas.width / 2;
    const gradient = this.context.createRadialGradient(
      center,
      center,
      innerRadius,
      center,
      center,
      outerRadius,
    );
    ramp.forEach(({ position, color }) => gradient.addColorStop(position, color));
    return gradient;
  }

  continuousGradients(innerRadius, outerRadius) {
    if (!this.continuousFills) {
      this.continuousFills = Array.from(
        { length: 360 },
        (_, degree) => this.gradientFromRamp(
          wheelRamp(degree + WHEEL_CONTINUOUS_STEP / 2),
          innerRadius,
          outerRadius,
        ),
      );
    }
    return this.continuousFills;
  }

  drawArcSegment(
    startHue,
    endHue,
    innerRadius,
    outerRadius,
    fillStyle,
    strokeStyle = null,
    lineWidth = 0,
  ) {
    const start = (startHue - 90) * Math.PI / 180;
    const end = (endHue - 90) * Math.PI / 180;
    const center = this.canvas.width / 2;
    const context = this.context;
    context.beginPath();
    context.arc(center, center, outerRadius, start, end);
    context.arc(center, center, innerRadius, end, start, true);
    context.closePath();
    context.fillStyle = fillStyle;
    context.fill();
    if (strokeStyle) {
      context.strokeStyle = strokeStyle;
      context.lineWidth = lineWidth;
      context.stroke();
    }
  }

  drawContinuousWheel(innerRadius, outerRadius, ink) {
    const fills = this.continuousGradients(innerRadius, outerRadius);
    const overlap = WHEEL_CONTINUOUS_OVERLAP;
    for (let degree = 0; degree < 360; degree += WHEEL_CONTINUOUS_STEP) {
      this.drawArcSegment(
        degree - overlap,
        degree + WHEEL_CONTINUOUS_STEP + overlap,
        innerRadius,
        outerRadius,
        fills[degree],
      );
    }
    const center = this.canvas.width / 2;
    const sections = [...this.selectionSections()].sort((first, second) => (
      Number(first.id === this.activeSectionId)
      - Number(second.id === this.activeSectionId)
    ));
    sections.forEach((section) => {
      const span = clockwiseSpan(section.start, section.end);
      for (let offset = 0; offset < span; offset += WHEEL_CONTINUOUS_STEP) {
        const degree = normalizeHue(section.start + offset);
        this.drawArcSegment(
          degree - overlap,
          degree + WHEEL_CONTINUOUS_STEP + overlap,
          innerRadius - 3,
          outerRadius + 1,
          fills[degree],
        );
      }
      const start = (section.start - 90) * Math.PI / 180;
      const end = (section.start + span - 90) * Math.PI / 180;
      this.context.strokeStyle = ink;
      this.context.lineWidth = (
        this.mode === "standard" || section.id === this.activeSectionId
      ) ? 5 : 2;
      this.context.beginPath();
      this.context.arc(center, center, outerRadius + 1, start, end);
      this.context.stroke();
    });
  }

  draw() {
    const size = this.canvas.width;
    const center = size / 2;
    const outerRadius = size * 0.485;
    const innerRadius = size * 0.29;
    const context = this.context;
    const ink = themeColor("--ink");
    const paper = themeColor("--paper");
    const line = themeColor("--line");
    context.clearRect(0, 0, size, size);
    this.drawContinuousWheel(innerRadius, outerRadius, ink);

    context.save();
    context.shadowColor = themeColor("--wheel-shadow");
    context.shadowBlur = 24;
    context.fillStyle = paper;
    context.beginPath();
    context.arc(center, center, innerRadius - 2, 0, TAU);
    context.fill();
    context.restore();

    const boundaries = this.selectionSections().flatMap((section) => [
      {
        hue: section.start,
        active: this.mode === "standard" || section.id === this.activeSectionId,
      },
      {
        hue: section.end,
        active: this.mode === "standard" || section.id === this.activeSectionId,
      },
    ]);
    boundaries.forEach(({ hue, active }) => {
      const radians = (hue - 90) * Math.PI / 180;
      const handleCenterRadius = outerRadius - 6;
      const innerX = center + (innerRadius - 8) * Math.cos(radians);
      const innerY = center + (innerRadius - 8) * Math.sin(radians);
      const outerX = center + handleCenterRadius * Math.cos(radians);
      const outerY = center + handleCenterRadius * Math.sin(radians);
      context.strokeStyle = ink;
      context.lineWidth = active ? 5 : 2;
      context.beginPath();
      context.moveTo(innerX, innerY);
      context.lineTo(outerX, outerY);
      context.stroke();
      context.fillStyle = paper;
      context.strokeStyle = ink;
      context.lineWidth = active ? 4 : 2;
      context.beginPath();
      context.arc(outerX, outerY, active ? 15 : 9, 0, TAU);
      context.fill();
      context.stroke();
    });

    context.strokeStyle = line;
    context.lineWidth = 2;
    context.beginPath();
    context.arc(center, center, outerRadius, 0, TAU);
    context.stroke();
  }
}

function initializePalette() {
  const canvas = document.querySelector("#color-wheel");
  const form = document.querySelector("#palette-controls");
  if (!canvas || !form) return;

  const centerInput = document.querySelector("#center-input");
  const spanInput = document.querySelector("#span-input");
  const modeInput = document.querySelector("#mode-input");
  const rangesInput = document.querySelector("#ranges-input");
  const hueReadout = document.querySelector("#hue-readout");
  const hueRangeName = document.querySelector("#hue-range-name");
  const wheelActionLabel = document.querySelector(".wheel-action-label");
  const wheelCenter = document.querySelector("#wheel-center");
  const wheelShell = document.querySelector(".wheel-shell");
  const pigmentGuide = document.querySelector("#pigment-guide");
  const pigmentGuideToggle = document.querySelector("#pigment-guide-toggle");
  const pigmentShelf = document.querySelector("#pigment-shelf");
  const pigmentShelfList = document.querySelector("#pigment-shelf-list");
  const imagePaletteButton = document.querySelector("#image-palette-button");
  const imagePaletteButtonLabel = document.querySelector("#image-palette-button-label");
  const imagePaletteInput = document.querySelector("#image-palette-input");
  const imagePaletteFeedback = document.querySelector("#image-palette-feedback");
  const imagePalettePreview = document.querySelector("#image-palette-preview");
  const imagePaletteStatus = document.querySelector("#image-palette-status");
  const pigmentPopover = document.querySelector("#pigment-popover");
  const pigmentPopoverTitle = document.querySelector("#pigment-popover-title");
  const pigmentPopoverList = document.querySelector("#pigment-popover-list");
  const pigmentPopoverClose = document.querySelector("#pigment-popover-close");
  const customControls = document.querySelector("#custom-controls");
  const customAngle = document.querySelector("#custom-angle");
  const customPercent = document.querySelector("#custom-percent");
  const customSectionCount = document.querySelector("#custom-section-count");
  const addCustomSection = document.querySelector("#add-custom-section");
  const customLoadingStatus = document.querySelector("#custom-loading-status");
  const customLoadingMessage = document.querySelector("#custom-loading-message");
  let requestTimer;
  let activeRequest;
  let resultGeneration = 0;
  const responseCache = new Map();
  const serverParams = new URLSearchParams(new FormData(form));

  const averagePigmentHue = (pigments) => {
    const vectors = pigments.reduce((total, pigment) => {
      const radians = pigment.hue * Math.PI / 180;
      return {
        x: total.x + Math.cos(radians),
        y: total.y + Math.sin(radians),
      };
    }, { x: 0, y: 0 });
    return normalizeHue(Math.atan2(vectors.y, vectors.x) * 180 / Math.PI);
  };

  const pigmentClusters = [...ARTIST_PIGMENTS]
    .sort((first, second) => first.hue - second.hue)
    .reduce((clusters, pigment) => {
      const current = clusters.at(-1);
      if (
        current
        && circularDistance(pigment.hue, averagePigmentHue(current))
          <= PIGMENT_CLUSTER_DEGREES
      ) {
        current.push(pigment);
      } else {
        clusters.push([pigment]);
      }
      return clusters;
    }, []);

  const createPigmentEntry = (pigment, className) => {
    const entry = document.createElement("span");
    const swatch = document.createElement("span");
    const name = document.createElement("span");
    const code = document.createElement("small");
    entry.className = className;
    entry.style.setProperty("--pigment-color", pigment.color);
    entry.title = `${pigment.name} · ${pigment.code} · approximately ${Math.round(
      pigment.hue,
    )}°`;
    swatch.className = "pigment-swatch";
    swatch.setAttribute("aria-hidden", "true");
    name.textContent = pigment.name;
    code.textContent = pigment.code;
    entry.append(swatch, name, code);
    return entry;
  };

  const pigmentMarkers = ARTIST_PIGMENTS.map((pigment) => {
    const radians = (pigment.hue - 90) * Math.PI / 180;
    const tick = document.createElement("span");
    const tickRadius = 48.8;

    tick.className = "pigment-tick";
    tick.style.left = `${50 + Math.cos(radians) * tickRadius}%`;
    tick.style.top = `${50 + Math.sin(radians) * tickRadius}%`;
    tick.style.setProperty("--pigment-color", pigment.color);
    tick.setAttribute("aria-hidden", "true");
    pigmentGuide.append(tick);
    return { pigment, tick };
  });

  let activePigmentLabel;
  const closePigmentPopover = (restoreFocus = false) => {
    pigmentPopover.hidden = true;
    document.querySelectorAll(".pigment-label[aria-expanded]").forEach((label) => {
      label.setAttribute("aria-expanded", "false");
    });
    if (restoreFocus && activePigmentLabel) activePigmentLabel.focus();
    activePigmentLabel = undefined;
  };

  const openPigmentPopover = (pigments, label) => {
    activePigmentLabel = label;
    document.querySelectorAll(".pigment-label[aria-expanded]").forEach((otherLabel) => {
      otherLabel.setAttribute("aria-expanded", String(otherLabel === label));
    });
    const hue = Math.round(averagePigmentHue(pigments));
    const pigmentWord = pigments.length === 1 ? "pigment" : "pigments";
    pigmentPopoverTitle.textContent = `${pigments.length} ${pigmentWord} near ${hue}°`;
    pigmentPopoverList.replaceChildren(...pigments.map((pigment) => (
      createPigmentEntry(pigment, "pigment-popover-item")
    )));
    pigmentPopover.hidden = false;
    pigmentPopoverClose.focus({ preventScroll: true });
  };

  const pigmentLabels = pigmentClusters.map((pigments) => {
    const label = document.createElement("button");
    label.type = "button";
    label.className = "pigment-label";
    label.hidden = true;
    label.setAttribute("aria-expanded", "false");
    label.setAttribute("aria-controls", "pigment-popover");
    const marker = { pigments, label, activePigments: [] };
    label.addEventListener("click", () => {
      if (marker.activePigments.length) openPigmentPopover(marker.activePigments, label);
    });
    pigmentGuide.append(label);
    return marker;
  });

  const updatePigmentGuide = (state) => {
    const sections = state.mode === "custom"
      ? state.sections
      : [{ start: state.start, end: state.end }];
    const pigmentIsSelected = (pigment) => sections.some((section) => (
        clockwiseSpan(section.start, pigment.hue)
        <= clockwiseSpan(section.start, section.end)
    ));
    const selectedPigments = ARTIST_PIGMENTS.filter(pigmentIsSelected)
      .sort((first, second) => first.hue - second.hue);

    pigmentMarkers.forEach(({ pigment, tick }) => {
      const selected = pigmentIsSelected(pigment);
      tick.classList.toggle("selected", selected);
    });

    const visibleLabels = pigmentLabels.filter((marker) => {
      marker.activePigments = marker.pigments.filter(pigmentIsSelected);
      marker.label.hidden = marker.activePigments.length === 0;
      return marker.activePigments.length > 0;
    });
    const labelRadii = [56, 68, 80, 92];
    const placedLabelBounds = [];
    const boundsOverlap = (candidate) => placedLabelBounds.some((placed) => (
      candidate.left < placed.right + 5
      && candidate.right > placed.left - 5
      && candidate.top < placed.bottom + 5
      && candidate.bottom > placed.top - 5
    ));
    visibleLabels.forEach((marker) => {
      const { label, activePigments } = marker;
      const hue = averagePigmentHue(activePigments);
      const radians = (hue - 90) * Math.PI / 180;
      label.style.setProperty("--pigment-color", activePigments[0].color);
      label.replaceChildren();
      if (activePigments.length === 1) {
        const entry = createPigmentEntry(activePigments[0], "pigment-label-entry");
        label.append(...entry.childNodes);
        label.title = entry.title;
        label.setAttribute("aria-label", entry.title);
      } else {
        const swatch = document.createElement("span");
        const count = document.createElement("span");
        const hueText = document.createElement("small");
        swatch.className = "pigment-swatch pigment-cluster-swatch";
        swatch.setAttribute("aria-hidden", "true");
        swatch.style.background = `linear-gradient(135deg, ${activePigments.map(
          (pigment) => pigment.color,
        ).join(", ")})`;
        count.textContent = `${activePigments.length} pigments`;
        hueText.textContent = `${Math.round(hue)}°`;
        label.append(swatch, count, hueText);
        label.title = activePigments.map((pigment) => pigment.name).join(", ");
        label.setAttribute(
          "aria-label",
          `${activePigments.length} pigments near ${Math.round(hue)} degrees. Show list.`,
        );
      }
      let labelBounds;
      for (const radius of labelRadii) {
        label.style.left = `${50 + Math.cos(radians) * radius}%`;
        label.style.top = `${50 + Math.sin(radians) * radius}%`;
        labelBounds = label.getBoundingClientRect();
        if (!boundsOverlap(labelBounds)) break;
      }
      placedLabelBounds.push(labelBounds);
    });

    pigmentShelfList.replaceChildren(...selectedPigments.map((pigment) => (
      createPigmentEntry(pigment, "pigment-shelf-item")
    )));
    closePigmentPopover();
  };

  pigmentPopoverClose.addEventListener("click", () => closePigmentPopover(true));
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !pigmentPopover.hidden) closePigmentPopover(true);
  });

  const fetchResults = async (url, signal) => {
    if (responseCache.has(url)) return responseCache.get(url);
    const response = await fetch(url, {
      signal,
      headers: { "HX-Request": "true" },
    });
    if (!response.ok) throw new Error(`Artwork request failed: ${response.status}`);
    const html = await response.text();
    responseCache.set(url, html);
    return html;
  };

  const whenIdle = () => new Promise((resolve) => {
    if ("requestIdleCallback" in window) {
      window.requestIdleCallback(resolve, { timeout: 250 });
    } else {
      window.setTimeout(resolve, 20);
    }
  });

  const loadRemainingResults = async (params, generation, signal) => {
    const grid = document.querySelector("#art-results .art-grid");
    if (!grid) return;
    let offset = Number(grid.dataset.nextOffset || 0);
    while (offset && generation === resultGeneration) {
      await whenIdle();
      const pageParams = new URLSearchParams(params);
      pageParams.set("offset", String(offset));
      const url = `/artworks/page?${pageParams.toString()}`;
      try {
        const html = await fetchResults(url, signal);
        if (generation !== resultGeneration) return;
        const template = document.createElement("template");
        template.innerHTML = html.trim();
        const page = template.content.firstElementChild;
        if (!page) return;
        grid.append(...page.children);
        offset = Number(page.dataset.nextOffset || 0);
        grid.dataset.nextOffset = String(offset || "");
      } catch (error) {
        if (error.name !== "AbortError") console.error(error);
        return;
      }
    }
    if (generation === resultGeneration) {
      const button = document.querySelector("#art-results .show-more-images");
      if (button) button.disabled = false;
    }
  };

  const appendRelaxedResults = async (button) => {
    const results = document.querySelector("#art-results");
    const heading = results.querySelector(".results-heading");
    const grid = results.querySelector(".art-grid");
    if (!heading || !grid) return;

    const generation = resultGeneration;
    const params = new URLSearchParams(new FormData(form));
    params.set("maximum_coverage", heading.dataset.relaxedCutoff || "1");
    params.set("offset", button.dataset.relaxedOffset || "0");
    const url = `/artworks/more?${params.toString()}`;
    button.disabled = true;
    button.textContent = "Loading…";
    try {
      const html = await fetchResults(url, activeRequest?.signal);
      if (generation !== resultGeneration) return;
      const template = document.createElement("template");
      template.innerHTML = html.trim();
      const page = template.content.firstElementChild;
      if (!page) return;
      const returned = Number(page.dataset.returned || 0);
      if (returned) {
        results.querySelector(".empty-state")?.remove();
        grid.append(...page.children);
      }
      const nextOffset = page.dataset.nextOffset;
      if (!nextOffset) {
        button.closest(".show-more-control")?.remove();
        return;
      }
      button.dataset.relaxedOffset = nextOffset;
    } catch (error) {
      if (error.name !== "AbortError") console.error(error);
    } finally {
      if (button.isConnected) {
        button.disabled = false;
        button.textContent = "Show more images";
      }
    }
  };

  const prefetchAdjacentResults = async (params, signal) => {
    if (params.get("mode") === "custom") return;
    await whenIdle();
    const center = Number(params.get("center"));
    if (!Number.isFinite(center)) return;
    const urls = [
      -ADJACENT_PREFETCH_DEGREES,
      ADJACENT_PREFETCH_DEGREES,
    ].map((offset) => {
      const adjacentParams = new URLSearchParams(params);
      const adjacentCenter = (center + offset + 360) % 360;
      adjacentParams.set("center", adjacentCenter.toFixed(1));
      return `/artworks?${adjacentParams.toString()}`;
    });
    await Promise.allSettled(urls.map((url) => fetchResults(url, signal)));
  };

  const updateReadout = (state) => {
    centerInput.value = state.center.toFixed(1);
    spanInput.value = String(state.span);
    modeInput.value = state.mode;
    rangesInput.value = state.mode === "custom"
      ? state.sections.map((section) => `${section.start}:${section.end}`).join(",")
      : "";
    hueReadout.textContent = `${Math.round(state.center)}°`;
    const matchingHalfSpan = state.mode === "custom"
      ? state.span / 2
      : state.span / 2 - FIXED_MATCH_EDGE_INSET;
    hueRangeName.textContent = `${hueName(state.center - matchingHalfSpan)} — ${hueName(
      state.center + matchingHalfSpan,
    )}`;
    const isCustom = state.mode === "custom";
    document.querySelectorAll(".slice-option").forEach((option) => {
      const active = isCustom
        ? option.dataset.mode === "custom"
        : Number(option.dataset.span) === state.span;
      option.classList.toggle("active", active);
    });
    customControls.hidden = !isCustom;
    wheelActionLabel.textContent = isCustom
      ? "DRAG EDGES OR SLICES"
      : "DRAG SLICE TO MOVE";
    canvas.setAttribute(
      "aria-label",
      isCustom
        ? "Continuous color wheel. Drag an edge to resize, drag a selected section to move, and press Delete to remove the selected section"
        : "Continuous color wheel. Drag either edge or the selected slice to move it one degree at a time",
    );
    wheelCenter.setAttribute(
      "aria-label",
      isCustom ? "Selected custom hue range" : "Selected fixed hue range",
    );
    if (isCustom) {
      const percentage = Number((state.totalSpan / 3.6).toFixed(1));
      customAngle.textContent = `${state.totalSpan}°`;
      customPercent.textContent = `${percentage}% of wheel`;
      customSectionCount.textContent = `${state.sections.length} ${
        state.sections.length === 1 ? "section" : "sections"
      }`;
      addCustomSection.disabled = state.sections.length >= 4 || state.totalSpan >= 359;
    }
    updatePigmentGuide(state);
  };

  const loadResults = async ({ immediate = false } = {}) => {
    window.clearTimeout(requestTimer);
    const run = async () => {
      activeRequest?.abort();
      const request = new AbortController();
      activeRequest = request;
      resultGeneration += 1;
      const generation = resultGeneration;
      const results = document.querySelector("#art-results");
      results.classList.add("is-loading");
      results.setAttribute("aria-busy", "true");
      const params = new URLSearchParams(new FormData(form));
      const customSearch = params.get("mode") === "custom";
      customLoadingStatus.hidden = !customSearch;
      customLoadingMessage.textContent = customSearch ? "Finding matches…" : "";
      wheelShell.classList.toggle("is-searching", customSearch);
      const url = `/artworks?${params.toString()}`;
      try {
        results.innerHTML = await fetchResults(url, request.signal);
        void loadRemainingResults(params, generation, request.signal);
        void prefetchAdjacentResults(params, request.signal);
      } catch (error) {
        if (error.name !== "AbortError") console.error(error);
      } finally {
        if (activeRequest === request) {
          results.classList.remove("is-loading");
          results.removeAttribute("aria-busy");
          customLoadingStatus.hidden = true;
          customLoadingMessage.textContent = "";
          wheelShell.classList.remove("is-searching");
        }
      }
    };
    requestTimer = window.setTimeout(run, immediate ? 0 : 180);
  };

  const wheel = new ColorWheel(canvas, (state, finished) => {
    updateReadout(state);
    if (finished) {
      syncSliceUrl(state);
      loadResults({ immediate: true });
    }
  });
  const urlState = sliceStateFromUrl();
  if (urlState) wheel.restore(urlState);
  updateReadout(wheel.state());
  syncSliceUrl(wheel.state());
  const initialParams = new URLSearchParams(new FormData(form));
  let paletteHydrated = false;
  window.colorsliceActivatePalette = () => {
    if (paletteHydrated) return;
    paletteHydrated = true;
    if (initialParams.toString() === serverParams.toString()) {
      responseCache.set(
        `/artworks?${initialParams.toString()}`,
        document.querySelector("#art-results").innerHTML,
      );
      activeRequest = new AbortController();
      resultGeneration += 1;
      void loadRemainingResults(
        initialParams,
        resultGeneration,
        activeRequest.signal,
      );
      void prefetchAdjacentResults(initialParams, activeRequest.signal);
    } else {
      loadResults({ immediate: true });
    }
  };
  const initialUrlParams = new URLSearchParams(window.location.search);
  const startsInExplorer = (
    initialUrlParams.get("view") === "art"
    || initialUrlParams.get("mode") === "art"
    || initialUrlParams.has("art")
  );
  if (!startsInExplorer) window.colorsliceActivatePalette();

  document.querySelectorAll(".slice-option").forEach((button) => {
    button.addEventListener("click", () => {
      document.querySelectorAll(".slice-option").forEach(
        (option) => option.classList.remove("active"),
      );
      button.classList.add("active");
      if (button.dataset.mode === "custom") {
        wheel.activateCustom();
      } else {
        wheel.setStandardSpan(Number(button.dataset.span));
      }
      updateReadout(wheel.state());
      syncSliceUrl(wheel.state());
      loadResults({ immediate: true });
    });
  });

  let imagePalettePreviewUrl;
  const setImagePaletteStatus = (message, isError = false) => {
    imagePaletteStatus.textContent = message;
    imagePaletteStatus.hidden = !message;
    imagePaletteStatus.classList.toggle("is-error", isError);
    imagePaletteFeedback.hidden = !message && imagePalettePreview.hidden;
  };
  const setImagePalettePreview = (file) => {
    if (imagePalettePreviewUrl) URL.revokeObjectURL(imagePalettePreviewUrl);
    imagePalettePreviewUrl = file ? URL.createObjectURL(file) : undefined;
    imagePalettePreview.src = imagePalettePreviewUrl || "";
    imagePalettePreview.alt = file ? `Preview of ${file.name}` : "";
    imagePalettePreview.hidden = !file;
    imagePaletteFeedback.hidden = !file && imagePaletteStatus.hidden;
  };
  imagePaletteButton.addEventListener("click", () => imagePaletteInput.click());
  imagePaletteInput.addEventListener("change", async () => {
    const file = imagePaletteInput.files?.[0];
    if (!file) return;
    setImagePalettePreview();
    if (!["image/jpeg", "image/png", "image/webp"].includes(file.type)) {
      setImagePaletteStatus("Use a JPEG, PNG, or WebP image.", true);
      imagePaletteInput.value = "";
      return;
    }

    setImagePalettePreview(file);
    imagePaletteButton.disabled = true;
    imagePaletteButton.setAttribute("aria-busy", "true");
    imagePaletteButtonLabel.textContent = "Analyzing…";
    setImagePaletteStatus(`Analyzing ${file.name}…`);
    try {
      const upload = await imagePaletteUpload(file);
      const body = new FormData();
      body.append("image", upload, file.name);
      const response = await fetch("/palette/from-image", {
        method: "POST",
        body,
      });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.error || "The image could not be analyzed.");
      }
      const sections = Array.isArray(payload.ranges)
        ? payload.ranges.slice(0, 4).filter((range) => (
          Number.isFinite(range.start) && Number.isFinite(range.end)
        ))
        : [];
      if (!sections.length) throw new Error("No distinct hues were found in that image.");

      wheel.restore({ mode: "custom", sections });
      const state = wheel.state();
      updateReadout(state);
      syncSliceUrl(state);
      loadResults({ immediate: true });
      const sectionWord = sections.length === 1 ? "slice" : "slices";
      setImagePaletteStatus(
        `${file.name} · ${payload.coverage}% hue coverage · ${sections.length} ${sectionWord}`,
      );
    } catch (error) {
      const message = error instanceof Error
        ? error.message
        : "The image could not be analyzed.";
      setImagePaletteStatus(message, true);
    } finally {
      imagePaletteButton.disabled = false;
      imagePaletteButton.removeAttribute("aria-busy");
      imagePaletteButtonLabel.textContent = "From image";
      imagePaletteInput.value = "";
    }
  });

  addCustomSection.addEventListener("click", () => wheel.addSection());
  pigmentGuideToggle.addEventListener("click", () => {
    const visible = pigmentGuide.hidden;
    pigmentGuide.hidden = !visible;
    pigmentShelf.hidden = !visible;
    if (!visible) closePigmentPopover();
    pigmentGuideToggle.classList.toggle("active", visible);
    pigmentGuideToggle.setAttribute("aria-pressed", String(visible));
    wheelShell.classList.toggle("show-pigments", visible);
    if (visible) updatePigmentGuide(wheel.state());
  });
  document.querySelector("#art-results").addEventListener("click", (event) => {
    const button = event.target.closest(".show-more-images");
    if (button) void appendRelaxedResults(button);
  });
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initializePalette);
} else {
  initializePalette();
}
