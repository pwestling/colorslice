(() => {
  const SEARCH_DELAY = 180;
  const BIN_DEGREES = 5;

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
      const button = event.target.closest(".hue-mode-toggle");
      if (!button) return;
      const image = detail.querySelector(".explorer-artwork-image");
      if (!image) return;
      const active = image.classList.toggle("hue-mode");
      button.classList.toggle("active", active);
      button.setAttribute("aria-pressed", String(active));
      button.textContent = active ? "Original" : "Hue mode";
    });
    paletteView.addEventListener("click", (event) => {
      const card = event.target.closest(".art-card[data-artwork-id]");
      if (
        !card
        || event.button !== 0
        || event.metaKey
        || event.ctrlKey
        || event.shiftKey
        || event.altKey
      ) return;
      event.preventDefault();
      input.value = "";
      setFilter.value = "";
      results.innerHTML = "";
      showView("art");
      void loadArtwork(card.dataset.artworkId, { scroll: true });
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
