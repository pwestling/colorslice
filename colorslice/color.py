from dataclasses import dataclass
from io import BytesIO
import math

import numpy as np
from PIL import Image, ImageOps

from colorslice.models import HUE_BIN_COUNT


HUE_NOISE_BIN_FLOOR = 0.0011
HUE_NOISE_GROUP_FLOOR = 0.004
HUE_NOISE_GROUP_RADIUS = 3


@dataclass(frozen=True, slots=True)
class ColorProfile:
    hue_histogram: tuple[float, ...]
    area_hue_histogram: tuple[float, ...]
    dominant_hue: float
    colorfulness: float


def _srgb_to_linear(rgb: np.ndarray) -> np.ndarray:
    return np.where(
        rgb <= 0.04045,
        rgb / 12.92,
        ((rgb + 0.055) / 1.055) ** 2.4,
    )


def rgb_to_oklch(rgb: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Convert an array of sRGB triples in [0, 1] to OKLCH arrays."""
    linear = _srgb_to_linear(rgb)
    red, green, blue = np.moveaxis(linear, -1, 0)

    long = 0.4122214708 * red + 0.5363325363 * green + 0.0514459929 * blue
    medium = 0.2119034982 * red + 0.6806995451 * green + 0.1073969566 * blue
    short = 0.0883024619 * red + 0.2817188376 * green + 0.6299787005 * blue

    long_root = np.cbrt(long)
    medium_root = np.cbrt(medium)
    short_root = np.cbrt(short)

    lightness = (
        0.2104542553 * long_root
        + 0.7936177850 * medium_root
        - 0.0040720468 * short_root
    )
    a_axis = (
        1.9779984951 * long_root
        - 2.4285922050 * medium_root
        + 0.4505937099 * short_root
    )
    b_axis = (
        0.0259040371 * long_root
        + 0.7827717662 * medium_root
        - 0.8086757660 * short_root
    )
    chroma = np.sqrt(a_axis**2 + b_axis**2)
    hue = np.mod(np.degrees(np.arctan2(b_axis, a_axis)), 360.0)
    return lightness, chroma, hue


def analyze_image_bytes(
    content: bytes,
    *,
    bins: int = HUE_BIN_COUNT,
    sample_size: int = 220,
    chroma_floor: float = 0.025,
) -> ColorProfile:
    """Create chroma- and area-weighted OKLCH hue profiles for an image."""
    with Image.open(BytesIO(content)) as opened:
        image = ImageOps.exif_transpose(opened).convert("RGB")
        image.thumbnail((sample_size, sample_size), Image.Resampling.LANCZOS)
        rgb = np.asarray(image, dtype=np.float64) / 255.0

    lightness, chroma, hue = rgb_to_oklch(rgb)
    meaningful = (
        (chroma >= chroma_floor)
        & (lightness >= 0.06)
        & (lightness <= 0.97)
    )
    total_pixels = meaningful.size
    meaningful_count = int(np.count_nonzero(meaningful))
    if meaningful_count == 0:
        return ColorProfile(
            hue_histogram=tuple(0.0 for _ in range(bins)),
            area_hue_histogram=tuple(0.0 for _ in range(bins)),
            dominant_hue=0.0,
            colorfulness=0.0,
        )

    selected_hues = hue[meaningful]
    selected_chroma = chroma[meaningful]
    histogram, _ = np.histogram(
        selected_hues,
        bins=bins,
        range=(0.0, 360.0),
        weights=selected_chroma,
    )
    histogram_total = float(histogram.sum())
    normalized = histogram / histogram_total if histogram_total else histogram
    area_histogram, _ = np.histogram(
        selected_hues,
        bins=bins,
        range=(0.0, 360.0),
    )
    area_histogram_total = float(area_histogram.sum())
    normalized_area = (
        area_histogram / area_histogram_total
        if area_histogram_total
        else area_histogram
    )
    dominant_index = int(np.argmax(normalized))
    dominant_hue = (dominant_index + 0.5) * (360.0 / bins)
    chromatic_fraction = meaningful_count / total_pixels
    average_chroma = float(selected_chroma.mean())
    colorfulness = min(1.0, chromatic_fraction * average_chroma / 0.15)

    return ColorProfile(
        hue_histogram=tuple(float(value) for value in normalized),
        area_hue_histogram=tuple(float(value) for value in normalized_area),
        dominant_hue=dominant_hue,
        colorfulness=colorfulness,
    )


def circular_distance(first: float, second: float) -> float:
    return abs((first - second + 180.0) % 360.0 - 180.0)


def slice_coverage(
    histogram: tuple[float, ...],
    center: float,
    span: float,
) -> float:
    """Return the histogram mass inside a circular hue slice."""
    if not histogram:
        return 0.0
    bin_width = 360.0 / len(histogram)
    half_span = span / 2.0
    return sum(
        weight
        for index, weight in enumerate(histogram)
        if circular_distance((index + 0.5) * bin_width, center) <= half_span
    )


def noise_filtered_histogram(
    histogram: tuple[float, ...],
) -> tuple[float, ...]:
    """Discard hue evidence too small and isolated to be visually meaningful."""
    if not histogram:
        return ()

    total = sum(histogram)
    if total <= 0.0:
        return tuple(0.0 for _ in histogram)

    normalized = tuple(weight / total for weight in histogram)
    bin_count = len(normalized)
    kept = []
    for index, weight in enumerate(normalized):
        group_weight = sum(
            normalized[(index + offset) % bin_count]
            for offset in range(-HUE_NOISE_GROUP_RADIUS, HUE_NOISE_GROUP_RADIUS + 1)
        )
        kept.append(
            weight
            if weight >= HUE_NOISE_BIN_FLOOR
            and group_weight >= HUE_NOISE_GROUP_FLOOR
            else 0.0
        )

    kept_total = sum(kept)
    if kept_total <= 0.0:
        return normalized
    return tuple(weight / kept_total for weight in kept)


def salient_slice_coverage(
    histogram: tuple[float, ...],
    center: float,
    span: float,
) -> float:
    """Return coverage after removing isolated, sub-perceptual hue noise."""
    coverage = slice_coverage(noise_filtered_histogram(histogram), center, span)
    return 1.0 if math.isclose(coverage, 1.0, abs_tol=1e-12) else coverage


def slice_breadth(
    histogram: tuple[float, ...],
    center: float,
    span: float,
) -> float:
    """Measure how fully an artwork uses the selected hue arc."""
    if not histogram or span <= 0.0:
        return 0.0

    histogram = noise_filtered_histogram(histogram)
    bin_width = 360.0 / len(histogram)
    half_span = span / 2.0
    inside = []
    for index, weight in enumerate(histogram):
        hue = (index + 0.5) * bin_width
        offset = (hue - center + 180.0) % 360.0 - 180.0
        if abs(offset) <= half_span and weight > 0.0:
            inside.append((offset, weight))

    inside_total = sum(weight for _, weight in inside)
    if inside_total <= 0.0:
        return 0.0

    normalized = [(offset, weight / inside_total) for offset, weight in inside]

    def weighted_quantile(quantile: float) -> float:
        cumulative = 0.0
        for offset, weight in normalized:
            cumulative += weight
            if cumulative >= quantile:
                return offset
        return normalized[-1][0]

    central_width = max(0.0, weighted_quantile(0.90) - weighted_quantile(0.10))
    width_score = min(1.0, central_width / span)

    entropy = -sum(weight * math.log(weight) for _, weight in normalized)
    available_bins = max(2, round(span / bin_width) + 1)
    entropy_score = min(1.0, entropy / math.log(available_bins))
    return 0.65 * width_score + 0.35 * entropy_score


def rank_score(
    histogram: tuple[float, ...],
    area_histogram: tuple[float, ...],
    center: float,
    span: float,
    colorfulness: float,
) -> float:
    coverage = min(
        salient_slice_coverage(histogram, center, span),
        salient_slice_coverage(area_histogram, center, span),
    )
    if coverage <= 0.0:
        return 0.0
    breadth = slice_breadth(histogram, center, span)
    return 0.65 * breadth + 0.30 * coverage + 0.05 * colorfulness


def hue_name(center: float) -> str:
    names = (
        (15.0, "red"),
        (45.0, "vermilion"),
        (75.0, "orange"),
        (105.0, "yellow"),
        (140.0, "chartreuse"),
        (170.0, "green"),
        (205.0, "cyan"),
        (240.0, "azure"),
        (275.0, "blue"),
        (310.0, "violet"),
        (340.0, "magenta"),
        (360.0, "crimson"),
    )
    normalized = center % 360.0
    for boundary, name in names:
        if normalized < boundary:
            return name
    return "red"
