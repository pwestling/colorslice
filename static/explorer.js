(() => {
  const SEARCH_DELAY = 180;
  const BIN_DEGREES = 5;

  function seededRandom(seed) {
    const value = Math.sin(seed * 12.9898 + 78.233) * 43758.5453;
    return value - Math.floor(value);
  }

  function createCanvas(width, height) {
    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    return canvas;
  }

  function pixelAt(imageData, x, y) {
    const safeX = Math.max(0, Math.min(imageData.width - 1, Math.round(x)));
    const safeY = Math.max(0, Math.min(imageData.height - 1, Math.round(y)));
    const offset = (safeY * imageData.width + safeX) * 4;
    return [
      imageData.data[offset],
      imageData.data[offset + 1],
      imageData.data[offset + 2],
    ];
  }

  function pixelLuminance(imageData, x, y) {
    const [red, green, blue] = pixelAt(imageData, x, y);
    return red * 0.2126 + green * 0.7152 + blue * 0.0722;
  }

  function colorDifference(first, second) {
    return Math.sqrt(
      (first[0] - second[0]) ** 2
      + (first[1] - second[1]) ** 2
      + (first[2] - second[2]) ** 2,
    );
  }

  function simplifiedBrushColor(pixel, seed) {
    const luminance = pixel[0] * 0.2126 + pixel[1] * 0.7152 + pixel[2] * 0.0722;
    const stepped = Math.round(luminance / 17) * 17;
    const valueScale = luminance > 4 ? stepped / luminance : 1;
    const jitter = 0.94 + seededRandom(seed) * 0.12;
    return pixel.map((channel) => (
      Math.max(0, Math.min(255, Math.round(
        channel * (0.52 + valueScale * 0.48) * jitter,
      )))
    ));
  }

  function strokePath(context, startX, startY, controlX, controlY, endX, endY) {
    context.beginPath();
    context.moveTo(startX, startY);
    context.quadraticCurveTo(controlX, controlY, endX, endY);
    context.stroke();
  }

  function surfaceDirection(reference, x, y, brushWidth, seed) {
    const neighborhood = Math.max(2, brushWidth * 0.22);
    const gradientStep = Math.max(1, brushWidth * 0.055);
    let tensorXX = 0;
    let tensorXY = 0;
    let tensorYY = 0;
    for (let offsetY = -1; offsetY <= 1; offsetY += 1) {
      for (let offsetX = -1; offsetX <= 1; offsetX += 1) {
        const sampleX = x + offsetX * neighborhood;
        const sampleY = y + offsetY * neighborhood;
        const gradientX = (
          pixelLuminance(reference, sampleX + gradientStep, sampleY)
          - pixelLuminance(reference, sampleX - gradientStep, sampleY)
        );
        const gradientY = (
          pixelLuminance(reference, sampleX, sampleY + gradientStep)
          - pixelLuminance(reference, sampleX, sampleY - gradientStep)
        );
        const weight = offsetX === 0 && offsetY === 0 ? 2 : 1;
        tensorXX += gradientX * gradientX * weight;
        tensorXY += gradientX * gradientY * weight;
        tensorYY += gradientY * gradientY * weight;
      }
    }

    const energy = tensorXX + tensorYY;
    const separation = Math.hypot(tensorXX - tensorYY, 2 * tensorXY);
    const coherence = energy > 0.001 ? separation / energy : 0;
    if (energy > 18) {
      return {
        angle: 0.5 * Math.atan2(2 * tensorXY, tensorXX - tensorYY) + Math.PI / 2,
        coherence,
      };
    }

    const slowFlow = (
      Math.sin((x + y * 0.38) / Math.max(36, brushWidth * 4.5)) * 0.34
      + Math.sin(y / Math.max(52, brushWidth * 6.5)) * 0.18
      + (seededRandom(Math.floor(seed / 97)) - 0.5) * 0.08
    );
    return { angle: slowFlow, coherence: 0.2 };
  }

  function quadraticPoint(start, control, end, progress) {
    const inverse = 1 - progress;
    return (
      inverse * inverse * start
      + 2 * inverse * progress * control
      + progress * progress * end
    );
  }

  function drawBrushStroke(context, x, y, angle, brushWidth, pixel, seed) {
    const widthRandom = seededRandom(seed + 1);
    const width = brushWidth * (0.42 + widthRandom * 1.05);
    const shapeRandom = seededRandom(seed + 2);
    let lengthRatio;
    if (shapeRandom < 0.24) {
      lengthRatio = 0.9 + seededRandom(seed + 3) * 1.15;
    } else if (shapeRandom < 0.76) {
      lengthRatio = 2.1 + seededRandom(seed + 3) * 2.4;
    } else {
      lengthRatio = 4.6 + seededRandom(seed + 3) * 2.2;
    }
    const length = Math.min(
      width * lengthRatio,
      brushWidth * 6.2,
      context.canvas.width * 0.38,
    );
    const tangentX = Math.cos(angle);
    const tangentY = Math.sin(angle);
    const normalX = -tangentY;
    const normalY = tangentX;
    const bend = (seededRandom(seed + 4) - 0.5) * width * 1.15;
    const startX = x - tangentX * length / 2;
    const startY = y - tangentY * length / 2;
    const endX = x + tangentX * length / 2;
    const endY = y + tangentY * length / 2;
    const controlX = x + normalX * bend;
    const controlY = y + normalY * bend;
    const [red, green, blue] = simplifiedBrushColor(pixel, seed + 5);
    const leftEdge = [];
    const rightEdge = [];
    const segments = 7;
    for (let index = 0; index <= segments; index += 1) {
      const progress = index / segments;
      const pointX = quadraticPoint(startX, controlX, endX, progress);
      const pointY = quadraticPoint(startY, controlY, endY, progress);
      const derivativeX = (
        2 * (1 - progress) * (controlX - startX)
        + 2 * progress * (endX - controlX)
      );
      const derivativeY = (
        2 * (1 - progress) * (controlY - startY)
        + 2 * progress * (endY - controlY)
      );
      const derivativeLength = Math.max(0.001, Math.hypot(derivativeX, derivativeY));
      const localNormalX = -derivativeY / derivativeLength;
      const localNormalY = derivativeX / derivativeLength;
      const edgeVariation = 0.78 + seededRandom(seed + 20 + index) * 0.34;
      const halfWidth = width * edgeVariation / 2;
      leftEdge.push([
        pointX + localNormalX * halfWidth,
        pointY + localNormalY * halfWidth,
      ]);
      rightEdge.push([
        pointX - localNormalX * halfWidth,
        pointY - localNormalY * halfWidth,
      ]);
    }

    context.beginPath();
    context.moveTo(leftEdge[0][0], leftEdge[0][1]);
    leftEdge.slice(1).forEach(([pointX, pointY]) => context.lineTo(pointX, pointY));
    rightEdge.slice().reverse().forEach(
      ([pointX, pointY]) => context.lineTo(pointX, pointY),
    );
    context.closePath();
    context.fillStyle = `rgb(${red} ${green} ${blue})`;
    context.globalAlpha = 0.91 + seededRandom(seed + 6) * 0.07;
    context.fill();

    const bristleCount = 2 + Math.floor(seededRandom(seed + 7) * 3);
    const bristleLift = seededRandom(seed + 8) > 0.5 ? 20 : -17;
    context.lineCap = "butt";
    context.lineWidth = Math.max(0.6, width * 0.035);
    context.strokeStyle = `rgb(${Math.max(0, Math.min(255, red + bristleLift))} ${Math.max(0, Math.min(255, green + bristleLift))} ${Math.max(0, Math.min(255, blue + bristleLift))})`;
    context.globalAlpha = 0.16;
    for (let bristle = 0; bristle < bristleCount; bristle += 1) {
      const distribution = (bristle + 1) / (bristleCount + 1) - 0.5;
      const offset = (
        distribution * width * 0.7
        + (seededRandom(seed + 30 + bristle) - 0.5) * width * 0.09
      );
      strokePath(
        context,
        startX + normalX * offset,
        startY + normalY * offset,
        controlX + normalX * offset,
        controlY + normalY * offset,
        endX + normalX * offset,
        endY + normalY * offset,
      );
    }
    context.globalAlpha = 1;
  }

  function blurredReference(image, width, height, blurRadius) {
    const canvas = createCanvas(width, height);
    const context = canvas.getContext("2d", { willReadFrequently: true });
    context.filter = `blur(${blurRadius}px)`;
    context.drawImage(image, 0, 0, width, height);
    context.filter = "none";
    return { canvas, data: context.getImageData(0, 0, width, height) };
  }

  function paintStrokeLayer(context, reference, layerIndex, brushWidth, threshold) {
    const current = context.getImageData(
      0,
      0,
      context.canvas.width,
      context.canvas.height,
    );
    const spacing = Math.max(4, Math.round(brushWidth * 0.62));
    let row = 0;
    for (let baseY = 0; baseY < context.canvas.height + spacing; baseY += spacing) {
      let column = 0;
      for (let baseX = 0; baseX < context.canvas.width + spacing; baseX += spacing) {
        const seed = layerIndex * 1_000_003 + row * 10_007 + column * 1_009;
        const x = baseX + (seededRandom(seed) - 0.5) * spacing * 0.8;
        const y = baseY + (seededRandom(seed + 1) - 0.5) * spacing * 0.8;
        const referencePixel = pixelAt(reference, x, y);
        if (
          layerIndex > 0
          && colorDifference(referencePixel, pixelAt(current, x, y)) < threshold
        ) {
          column += 1;
          continue;
        }

        const direction = surfaceDirection(reference, x, y, brushWidth, seed);
        const angleJitter = (
          (seededRandom(seed + 3) - 0.5)
          * (0.06 + (1 - direction.coherence) * 0.12)
        );
        drawBrushStroke(
          context,
          x,
          y,
          direction.angle + angleJitter,
          brushWidth,
          referencePixel,
          seed,
        );
        column += 1;
      }
      row += 1;
    }
  }

  async function waitForImage(image) {
    if (image.complete && image.naturalWidth) return;
    if (typeof image.decode === "function") {
      await image.decode();
      return;
    }
    await new Promise((resolve, reject) => {
      image.addEventListener("load", resolve, { once: true });
      image.addEventListener("error", reject, { once: true });
    });
  }

  async function renderPainterlyImage(image, canvas) {
    await waitForImage(image);
    if (canvas.dataset.renderedSource === image.currentSrc) return;

    const displayWidth = Math.max(image.getBoundingClientRect().width, 360);
    const targetWidth = Math.min(
      image.naturalWidth,
      640,
      Math.round(displayWidth * Math.min(window.devicePixelRatio || 1, 1.5)),
    );
    const scale = targetWidth / image.naturalWidth;
    canvas.width = targetWidth;
    canvas.height = Math.round(image.naturalHeight * scale);

    const context = canvas.getContext("2d", { willReadFrequently: true });
    const broadBrush = Math.max(28, targetWidth / 13.5);
    const layers = [
      { width: broadBrush, threshold: 0 },
      { width: broadBrush * 0.62, threshold: 46 },
      { width: broadBrush * 0.34, threshold: 37 },
      { width: broadBrush * 0.17, threshold: 32 },
    ];
    const underpainting = blurredReference(
      image,
      canvas.width,
      canvas.height,
      broadBrush * 0.7,
    );
    context.drawImage(underpainting.canvas, 0, 0);

    for (const [index, layer] of layers.entries()) {
      const reference = blurredReference(
        image,
        canvas.width,
        canvas.height,
        Math.max(1, layer.width * 0.42),
      );
      paintStrokeLayer(
        context,
        reference.data,
        index,
        layer.width,
        layer.threshold,
      );
      await new Promise((resolve) => requestAnimationFrame(resolve));
    }

    canvas.dataset.renderedSource = image.currentSrc;
  }

  async function setArtworkImageMode(detail, mode, selectedButton) {
    const image = detail.querySelector(".explorer-artwork-image");
    const canvas = detail.querySelector(".explorer-artwork-canvas");
    const buttons = detail.querySelectorAll(".artwork-view-mode");
    if (!image || !canvas || !buttons.length) return;

    if (mode === "painterly") {
      selectedButton.disabled = true;
      selectedButton.textContent = "Rendering…";
      selectedButton.setAttribute("aria-busy", "true");
      await new Promise((resolve) => requestAnimationFrame(resolve));
      try {
        await renderPainterlyImage(image, canvas);
      } catch (error) {
        console.error(error);
        mode = "original";
      } finally {
        selectedButton.disabled = false;
        selectedButton.textContent = "Painterly";
        selectedButton.removeAttribute("aria-busy");
      }
    }

    image.classList.toggle("hue-mode", mode === "hue");
    image.hidden = mode === "painterly";
    canvas.hidden = mode !== "painterly";
    buttons.forEach((button) => {
      const active = button.dataset.imageMode === mode;
      button.classList.toggle("active", active);
      button.setAttribute("aria-pressed", String(active));
    });
  }

  function drawHueHistogram(canvas) {
    const histogram = (canvas.dataset.histogram || "")
      .split(",")
      .map(Number)
      .filter(Number.isFinite);
    if (!histogram.length) return;

    const context = canvas.getContext("2d");
    const size = canvas.width;
    const center = size / 2;
    const innerRadius = size * 0.22;
    const baselineRadius = size * 0.30;
    const maximumRadius = size * 0.46;
    const maximum = Math.max(...histogram, Number.EPSILON);
    const paper = themeColor("--paper");
    const line = themeColor("--line");
    const muted = themeColor("--muted");

    context.clearRect(0, 0, size, size);
    histogram.forEach((weight, index) => {
      const start = (index * BIN_DEGREES - 90) * Math.PI / 180;
      const end = ((index + 1) * BIN_DEGREES - 90) * Math.PI / 180;
      const hue = (index + 0.5) * BIN_DEGREES;
      const color = peakChromaColor(hue);

      context.globalAlpha = 0.16;
      context.fillStyle = color;
      context.beginPath();
      context.arc(center, center, baselineRadius, start, end);
      context.arc(center, center, innerRadius, end, start, true);
      context.closePath();
      context.fill();

      if (weight <= 0) return;
      const amplitude = Math.sqrt(weight / maximum);
      const radius = baselineRadius
        + (maximumRadius - baselineRadius) * amplitude;
      context.globalAlpha = 0.96;
      context.fillStyle = color;
      context.beginPath();
      context.arc(center, center, radius, start, end);
      context.arc(center, center, innerRadius, end, start, true);
      context.closePath();
      context.fill();
    });

    context.globalAlpha = 1;
    context.strokeStyle = line;
    context.lineWidth = 2;
    [innerRadius, baselineRadius, maximumRadius].forEach((radius) => {
      context.beginPath();
      context.arc(center, center, radius, 0, Math.PI * 2);
      context.stroke();
    });
    context.fillStyle = paper;
    context.beginPath();
    context.arc(center, center, innerRadius - 1, 0, Math.PI * 2);
    context.fill();
    context.fillStyle = muted;
    context.font = `600 ${Math.round(size * 0.021)}px "DM Sans", sans-serif`;
    context.textAlign = "center";
    context.textBaseline = "middle";
    context.fillText("HUE", center, center);
  }

  function initializeExplorer() {
    const paletteView = document.querySelector("#palette-view");
    const explorerView = document.querySelector("#explorer-view");
    const viewButtons = document.querySelectorAll(".view-option");
    const form = document.querySelector("#artwork-search-form");
    const input = document.querySelector("#artwork-search-input");
    const setFilter = document.querySelector("#artwork-set-filter");
    const randomButton = document.querySelector("#random-artwork");
    const results = document.querySelector("#explorer-results");
    const detail = document.querySelector("#explorer-detail");
    if (
      !paletteView
      || !explorerView
      || !form
      || !input
      || !setFilter
      || !randomButton
      || !results
      || !detail
    ) return;

    let searchTimer;
    let searchRequest;
    let detailRequest;

    const syncViewUrl = (view) => {
      const url = new URL(window.location.href);
      if (view === "art") {
        ["center", "span", "mode", "ranges"].forEach(
          (parameter) => url.searchParams.delete(parameter),
        );
        url.searchParams.set("view", "art");
      } else {
        ["view", "art", "q", "set_code"].forEach(
          (parameter) => url.searchParams.delete(parameter),
        );
        const mode = document.querySelector("#mode-input")?.value || "standard";
        if (mode === "custom") {
          url.searchParams.set("mode", "custom");
          url.searchParams.set(
            "ranges",
            document.querySelector("#ranges-input")?.value || "",
          );
        } else {
          url.searchParams.set(
            "center",
            String(Math.round(Number(document.querySelector("#center-input")?.value || 75))),
          );
          url.searchParams.set(
            "span",
            document.querySelector("#span-input")?.value || "120",
          );
        }
      }
      window.history.replaceState(null, "", url);
    };

    const showView = (view, sync = true) => {
      const showingArt = view === "art";
      paletteView.hidden = showingArt;
      explorerView.hidden = !showingArt;
      viewButtons.forEach((button) => {
        const active = button.dataset.view === view;
        button.classList.toggle("active", active);
        button.setAttribute("aria-selected", String(active));
      });
      if (sync) syncViewUrl(view);
      if (showingArt) {
        input.focus({ preventScroll: true });
      } else {
        window.colorsliceActivatePalette?.();
      }
    };

    const searchUrlState = (clearArtwork) => {
      const url = new URL(window.location.href);
      url.searchParams.set("view", "art");
      if (input.value.trim()) {
        url.searchParams.set("q", input.value.trim());
      } else {
        url.searchParams.delete("q");
      }
      if (setFilter.value) {
        url.searchParams.set("set_code", setFilter.value);
      } else {
        url.searchParams.delete("set_code");
      }
      if (clearArtwork) url.searchParams.delete("art");
      window.history.replaceState(null, "", url);
    };

    const renderHistogram = () => {
      const canvas = detail.querySelector("#artwork-hue-wheel");
      if (canvas) drawHueHistogram(canvas);
    };

    const loadArtwork = async (artworkId, { scroll = false } = {}) => {
      detailRequest?.abort();
      detailRequest = new AbortController();
      detail.classList.add("is-loading");
      detail.setAttribute("aria-busy", "true");
      try {
        const response = await fetch(
          `/explore/artwork?id=${encodeURIComponent(artworkId)}`,
          {
            signal: detailRequest.signal,
            headers: { "HX-Request": "true" },
          },
        );
        if (!response.ok) throw new Error(`Artwork request failed: ${response.status}`);
        detail.innerHTML = await response.text();
        requestAnimationFrame(renderHistogram);
        const url = new URL(window.location.href);
        url.searchParams.set("view", "art");
        url.searchParams.set("art", artworkId);
        window.history.replaceState(null, "", url);
        if (scroll) detail.scrollIntoView({ behavior: "smooth", block: "start" });
      } catch (error) {
        if (error.name !== "AbortError") console.error(error);
      } finally {
        detail.classList.remove("is-loading");
        detail.removeAttribute("aria-busy");
      }
    };

    const runSearch = async ({ clearArtwork = true } = {}) => {
      window.clearTimeout(searchTimer);
      searchRequest?.abort();
      const query = input.value.trim();
      const setCode = setFilter.value;
      searchUrlState(clearArtwork);
      if (clearArtwork) {
        detailRequest?.abort();
        detail.innerHTML = '<p class="explorer-empty">Select an artwork.</p>';
      }
      if (query.length < 2 && !setCode) {
        results.innerHTML = "";
        return;
      }

      searchRequest = new AbortController();
      results.classList.add("is-loading");
      results.setAttribute("aria-busy", "true");
      const params = new URLSearchParams({ q: query, set_code: setCode });
      try {
        const response = await fetch(`/explore/search?${params}`, {
          signal: searchRequest.signal,
          headers: { "HX-Request": "true" },
        });
        if (!response.ok) throw new Error(`Search request failed: ${response.status}`);
        results.innerHTML = await response.text();
      } catch (error) {
        if (error.name !== "AbortError") console.error(error);
      } finally {
        results.classList.remove("is-loading");
        results.removeAttribute("aria-busy");
      }
    };

    const queueSearch = () => {
      window.clearTimeout(searchTimer);
      searchTimer = window.setTimeout(() => void runSearch(), SEARCH_DELAY);
    };

    viewButtons.forEach((button) => {
      button.addEventListener("click", () => showView(button.dataset.view));
    });
    input.addEventListener("input", queueSearch);
    setFilter.addEventListener("change", () => void runSearch());
    randomButton.addEventListener("click", async () => {
      const originalLabel = randomButton.textContent;
      randomButton.disabled = true;
      randomButton.textContent = "Choosing…";
      input.value = "";
      results.innerHTML = "";
      searchUrlState(true);
      try {
        const params = new URLSearchParams({ set_code: setFilter.value });
        const response = await fetch(`/explore/random?${params}`, {
          headers: { "HX-Request": "true" },
        });
        if (!response.ok) throw new Error(`Random artwork request failed: ${response.status}`);
        const artwork = await response.json();
        await loadArtwork(artwork.id);
      } catch (error) {
        console.error(error);
        detail.innerHTML = '<p class="explorer-empty">No artwork found.</p>';
      } finally {
        randomButton.disabled = false;
        randomButton.textContent = originalLabel;
      }
    });
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      void runSearch();
    });
    results.addEventListener("click", (event) => {
      const button = event.target.closest(".explorer-result");
      if (button) void loadArtwork(button.dataset.artworkId, { scroll: true });
    });
    detail.addEventListener("click", (event) => {
      const button = event.target.closest(".artwork-view-mode");
      if (!button) return;
      void setArtworkImageMode(detail, button.dataset.imageMode, button);
    });
    const params = new URLSearchParams(window.location.search);
    const initialView = (
      params.get("view") === "art"
      || params.get("mode") === "art"
      || params.has("art")
    ) ? "art" : "palette";
    if (params.get("mode") === "art") params.delete("mode");
    input.value = params.get("q") || "";
    const initialSet = params.get("set_code") || "";
    if ([...setFilter.options].some((option) => option.value === initialSet)) {
      setFilter.value = initialSet;
    }
    showView(initialView, false);
    if (initialView === "art") {
      syncViewUrl("art");
      if (input.value.trim().length >= 2 || setFilter.value) {
        void runSearch({ clearArtwork: false });
      }
      const artworkId = params.get("art");
      if (artworkId) void loadArtwork(artworkId);
    }

    window.matchMedia("(prefers-color-scheme: dark)")
      .addEventListener("change", renderHistogram);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initializeExplorer);
  } else {
    initializeExplorer();
  }
})();
