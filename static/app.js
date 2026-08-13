const TAU = Math.PI * 2;
const WHEEL_SEGMENT_COUNT = 24;
const WHEEL_SEGMENT_SIZE = 360 / WHEEL_SEGMENT_COUNT;
const WHEEL_SEGMENT_GAP = 1.15;
const WHEEL_CONTINUOUS_STEP = 1;
const WHEEL_CONTINUOUS_OVERLAP = 0.12;
const WHEEL_DARK_LIGHTNESS = 0.35;
const WHEEL_LIGHT_LIGHTNESS = 0.90;
const WHEEL_DARK_END = 0.10;
const WHEEL_VIVID_END = 0.70;
const WHEEL_PEAK_SEARCH_STEPS = 100;

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

const WHEEL_SEGMENT_RAMPS = Array.from(
  { length: WHEEL_SEGMENT_COUNT },
  (_, segment) => wheelRamp((segment + 0.5) * WHEEL_SEGMENT_SIZE),
);

function hueName(hue) {
  const names = [
    [15, "red"], [45, "vermilion"], [75, "orange"], [105, "amber"],
    [140, "yellow"], [170, "green"], [205, "cyan"], [240, "azure"],
    [275, "blue"], [310, "violet"], [340, "magenta"], [360, "crimson"],
  ];
  const normalized = ((hue % 360) + 360) % 360;
  return names.find(([boundary]) => normalized < boundary)?.[1] || "red";
}

const normalizedSegment = (segment) => (
  (segment % WHEEL_SEGMENT_COUNT) + WHEEL_SEGMENT_COUNT
) % WHEEL_SEGMENT_COUNT;

const normalizeHue = (hue) => ((hue % 360) + 360) % 360;

const clockwiseSpan = (start, end) => normalizeHue(end - start);

const circularDistance = (first, second) => Math.abs(
  ((first - second + 540) % 360) - 180,
);

const themeColor = (name) => getComputedStyle(document.documentElement)
  .getPropertyValue(name)
  .trim();

class ColorWheel {
  constructor(canvas, onChange) {
    this.canvas = canvas;
    this.context = canvas.getContext("2d");
    this.centerHue = 75;
    this.span = 120;
    this.mode = "standard";
    this.customStart = 15;
    this.customEnd = 135;
    this.activeBoundary = null;
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
        this.mode === "custom"
        && (event.currentTarget === wheelCenter || pointer.radiusRatio < 0.48)
      ) return;
      this.dragging = true;
      if (this.mode === "custom") {
        this.activeBoundary = circularDistance(pointer.hue, this.customStart)
          <= circularDistance(pointer.hue, this.customEnd)
          ? "start"
          : "end";
      }
      this.canvas.setPointerCapture(event.pointerId);
      this.updateFromPointer(event);
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
      if (!["ArrowLeft", "ArrowRight"].includes(event.key)) return;
      event.preventDefault();
      const direction = event.key === "ArrowRight" ? 1 : -1;
      if (this.mode === "custom") {
        this.adjustBoundary(this.activeBoundary || "end", direction);
        return;
      }
      this.centerHue = normalizeHue(
        (Math.round(this.centerHue / WHEEL_SEGMENT_SIZE) + direction)
        * WHEEL_SEGMENT_SIZE,
      );
      this.draw();
      this.onChange(this.state(), true);
    });
  }

  state() {
    return {
      center: this.centerHue,
      span: this.span,
      mode: this.mode,
      start: this.mode === "custom"
        ? this.customStart
        : normalizeHue(this.centerHue - this.span / 2),
      end: this.mode === "custom"
        ? this.customEnd
        : normalizeHue(this.centerHue + this.span / 2),
    };
  }

  selectedSegments() {
    const count = Math.round(this.span / WHEEL_SEGMENT_SIZE);
    const start = Math.round((this.centerHue - this.span / 2) / WHEEL_SEGMENT_SIZE);
    return Array.from({ length: count }, (_, index) => normalizedSegment(start + index));
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
      this.setCustomBoundary(this.activeBoundary, Math.round(hue));
    } else {
      this.centerHue = normalizeHue(
        Math.round(hue / WHEEL_SEGMENT_SIZE) * WHEEL_SEGMENT_SIZE,
      );
    }
    this.draw();
    this.onChange(this.state(), false);
  }

  updateCustomGeometry() {
    this.span = clockwiseSpan(this.customStart, this.customEnd);
    this.centerHue = normalizeHue(this.customStart + this.span / 2);
  }

  setCustomBoundary(edge, hue) {
    let nextHue = normalizeHue(Math.round(hue));
    if (edge === "start") {
      if (nextHue === this.customEnd) nextHue = normalizeHue(this.customEnd - 1);
      this.customStart = nextHue;
    } else {
      if (nextHue === this.customStart) nextHue = normalizeHue(this.customStart + 1);
      this.customEnd = nextHue;
    }
    this.updateCustomGeometry();
  }

  adjustBoundary(edge, delta) {
    this.activeBoundary = edge;
    const currentHue = edge === "start" ? this.customStart : this.customEnd;
    this.setCustomBoundary(edge, currentHue + delta);
    this.draw();
    this.onChange(this.state(), true);
  }

  activateCustom() {
    if (this.mode !== "custom") {
      this.customStart = normalizeHue(Math.round(this.centerHue - this.span / 2));
      this.customEnd = normalizeHue(Math.round(this.centerHue + this.span / 2));
    }
    this.mode = "custom";
    this.activeBoundary = "end";
    this.updateCustomGeometry();
    this.draw();
  }

  setStandardSpan(span) {
    this.mode = "standard";
    this.span = span;
    this.centerHue = normalizeHue(
      Math.round(this.centerHue / WHEEL_SEGMENT_SIZE) * WHEEL_SEGMENT_SIZE,
    );
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

  segmentGradient(segment, innerRadius, outerRadius) {
    return this.gradientFromRamp(
      WHEEL_SEGMENT_RAMPS[segment],
      innerRadius,
      outerRadius,
    );
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

  drawSegmentedWheel(innerRadius, outerRadius, ink) {
    const segmentFills = Array.from(
      { length: WHEEL_SEGMENT_COUNT },
      (_, segment) => this.segmentGradient(segment, innerRadius, outerRadius),
    );
    for (let segment = 0; segment < WHEEL_SEGMENT_COUNT; segment += 1) {
      const startHue = segment * WHEEL_SEGMENT_SIZE + WHEEL_SEGMENT_GAP / 2;
      const endHue = (segment + 1) * WHEEL_SEGMENT_SIZE - WHEEL_SEGMENT_GAP / 2;
      this.drawArcSegment(
        startHue,
        endHue,
        innerRadius,
        outerRadius,
        segmentFills[segment],
      );
    }
    this.selectedSegments().forEach((segment) => {
      const startHue = segment * WHEEL_SEGMENT_SIZE + WHEEL_SEGMENT_GAP / 2;
      const endHue = (segment + 1) * WHEEL_SEGMENT_SIZE - WHEEL_SEGMENT_GAP / 2;
      this.drawArcSegment(
        startHue,
        endHue,
        innerRadius - 3,
        outerRadius + 1,
        segmentFills[segment],
        ink,
        4,
      );
    });
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
    for (let offset = 0; offset < this.span; offset += WHEEL_CONTINUOUS_STEP) {
      const degree = normalizeHue(this.customStart + offset);
      this.drawArcSegment(
        degree - overlap,
        degree + WHEEL_CONTINUOUS_STEP + overlap,
        innerRadius - 3,
        outerRadius + 1,
        fills[degree],
      );
    }
    const center = this.canvas.width / 2;
    const start = (this.customStart - 90) * Math.PI / 180;
    const end = (this.customStart + this.span - 90) * Math.PI / 180;
    this.context.strokeStyle = ink;
    this.context.lineWidth = 4;
    this.context.beginPath();
    this.context.arc(center, center, outerRadius + 1, start, end);
    this.context.stroke();
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
    if (this.mode === "custom") {
      this.drawContinuousWheel(innerRadius, outerRadius, ink);
    } else {
      this.drawSegmentedWheel(innerRadius, outerRadius, ink);
    }

    context.save();
    context.shadowColor = themeColor("--wheel-shadow");
    context.shadowBlur = 24;
    context.fillStyle = paper;
    context.beginPath();
    context.arc(center, center, innerRadius - 2, 0, TAU);
    context.fill();
    context.restore();

    const boundaries = this.mode === "custom"
      ? [this.customStart, this.customEnd]
      : [this.centerHue - this.span / 2, this.centerHue + this.span / 2];
    boundaries.forEach((hue) => {
      const radians = (hue - 90) * Math.PI / 180;
      const innerX = center + (innerRadius - 8) * Math.cos(radians);
      const innerY = center + (innerRadius - 8) * Math.sin(radians);
      const outerX = center + (outerRadius + 2) * Math.cos(radians);
      const outerY = center + (outerRadius + 2) * Math.sin(radians);
      context.strokeStyle = ink;
      context.lineWidth = 5;
      context.beginPath();
      context.moveTo(innerX, innerY);
      context.lineTo(outerX, outerY);
      context.stroke();
      context.fillStyle = paper;
      context.strokeStyle = ink;
      context.lineWidth = 4;
      context.beginPath();
      context.arc(outerX, outerY, this.mode === "custom" ? 15 : 13, 0, TAU);
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
  const hueReadout = document.querySelector("#hue-readout");
  const hueRangeName = document.querySelector("#hue-range-name");
  const wheelActionLabel = document.querySelector(".wheel-action-label");
  const wheelCenter = document.querySelector("#wheel-center");
  const customControls = document.querySelector("#custom-controls");
  const customAngle = document.querySelector("#custom-angle");
  const customPercent = document.querySelector("#custom-percent");
  const customStart = document.querySelector("#custom-start");
  const customEnd = document.querySelector("#custom-end");
  let requestTimer;
  let activeRequest;
  let resultGeneration = 0;
  const responseCache = new Map();

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
  };

  const prefetchAdjacentResults = async (params, signal) => {
    if (params.get("mode") === "custom") return;
    await whenIdle();
    const center = Number(params.get("center"));
    if (!Number.isFinite(center)) return;
    const urls = [-WHEEL_SEGMENT_SIZE, WHEEL_SEGMENT_SIZE].map((offset) => {
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
    hueReadout.textContent = `${Math.round(state.center)}°`;
    const matchingHalfSpan = state.mode === "custom"
      ? state.span / 2
      : (state.span - WHEEL_SEGMENT_SIZE) / 2;
    hueRangeName.textContent = `${hueName(state.center - matchingHalfSpan)} — ${hueName(
      state.center + matchingHalfSpan,
    )}`;
    const isCustom = state.mode === "custom";
    customControls.hidden = !isCustom;
    wheelActionLabel.textContent = isCustom ? "DRAG AN EDGE" : "DRAG TO ROTATE";
    canvas.setAttribute(
      "aria-label",
      isCustom
        ? "Continuous color wheel with independently adjustable boundaries"
        : "24-segment color wheel",
    );
    wheelCenter.setAttribute(
      "aria-label",
      isCustom ? "Selected custom hue range" : "Drag the wheel to choose a hue",
    );
    wheelCenter.classList.toggle("custom-mode", isCustom);
    if (isCustom) {
      const percentage = Number((state.span / 3.6).toFixed(1));
      customAngle.textContent = `${state.span}°`;
      customPercent.textContent = `${percentage}% of wheel`;
      customStart.textContent = `${state.start}°`;
      customEnd.textContent = `${state.end}°`;
    }
  };

  const loadResults = async ({ immediate = false } = {}) => {
    window.clearTimeout(requestTimer);
    const run = async () => {
      activeRequest?.abort();
      activeRequest = new AbortController();
      resultGeneration += 1;
      const generation = resultGeneration;
      const results = document.querySelector("#art-results");
      results.classList.add("is-loading");
      const params = new URLSearchParams(new FormData(form));
      const url = `/artworks?${params.toString()}`;
      try {
        results.innerHTML = await fetchResults(url, activeRequest.signal);
        results.classList.remove("is-loading");
        void loadRemainingResults(params, generation, activeRequest.signal);
        void prefetchAdjacentResults(params, activeRequest.signal);
      } catch (error) {
        if (error.name !== "AbortError") console.error(error);
      } finally {
        if (!activeRequest.signal.aborted) results.classList.remove("is-loading");
      }
    };
    requestTimer = window.setTimeout(run, immediate ? 0 : 180);
  };

  const wheel = new ColorWheel(canvas, (state, finished) => {
    updateReadout(state);
    if (finished) loadResults({ immediate: true });
  });
  updateReadout(wheel.state());
  const initialParams = new URLSearchParams(new FormData(form));
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
      loadResults({ immediate: true });
    });
  });

  document.querySelectorAll("[data-custom-edge]").forEach((button) => {
    button.addEventListener("click", () => {
      wheel.adjustBoundary(
        button.dataset.customEdge,
        Number(button.dataset.customDelta),
      );
    });
  });

  form.querySelectorAll('input[name="source"]').forEach((checkbox) => {
    checkbox.addEventListener("change", () => {
      const selected = form.querySelectorAll('input[name="source"]:checked');
      if (!selected.length) checkbox.checked = true;
      loadResults({ immediate: true });
    });
  });
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initializePalette);
} else {
  initializePalette();
}
