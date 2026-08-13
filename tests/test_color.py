from io import BytesIO

import numpy as np
from PIL import Image

from colorslice.color import (
    analyze_image_bytes,
    circular_distance,
    noise_filtered_histogram,
    rgb_to_oklch,
    salient_slice_coverage,
    slice_breadth,
    slice_coverage,
)


def test_oklch_primary_hues_are_perceptual():
    rgb = np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]])
    _, _, hue = rgb_to_oklch(rgb)
    assert circular_distance(float(hue[0]), 29.2) < 1.0
    assert circular_distance(float(hue[1]), 142.5) < 1.0
    assert circular_distance(float(hue[2]), 264.1) < 1.0


def test_image_profile_weights_hues_by_area_and_chroma():
    pixels = np.zeros((100, 100, 3), dtype=np.uint8)
    pixels[:, :75] = (255, 0, 0)
    pixels[:, 75:] = (0, 0, 255)
    image = Image.fromarray(pixels, mode="RGB")
    output = BytesIO()
    image.save(output, format="PNG")

    profile = analyze_image_bytes(output.getvalue())
    red_coverage = slice_coverage(profile.hue_histogram, center=30.0, span=60.0)
    blue_coverage = slice_coverage(profile.hue_histogram, center=265.0, span=60.0)
    red_area = slice_coverage(profile.area_hue_histogram, center=30.0, span=60.0)
    blue_area = slice_coverage(profile.area_hue_histogram, center=265.0, span=60.0)

    assert red_coverage > blue_coverage
    assert red_coverage > 0.60
    assert red_coverage + blue_coverage > 0.98
    assert red_area == 0.75
    assert blue_area == 0.25


def test_area_coverage_catches_a_visible_low_chroma_accent():
    pixels = np.zeros((100, 100, 3), dtype=np.uint8)
    pixels[:, :91] = (255, 175, 0)
    pixels[:, 91:] = (145, 205, 235)
    image = Image.fromarray(pixels, mode="RGB")
    output = BytesIO()
    image.save(output, format="PNG")

    profile = analyze_image_bytes(output.getvalue())
    chroma_coverage = slice_coverage(profile.hue_histogram, center=50.0, span=120.0)
    area_coverage = slice_coverage(
        profile.area_hue_histogram,
        center=50.0,
        span=120.0,
    )

    assert chroma_coverage > 0.95
    assert area_coverage == 0.91


def test_slice_coverage_wraps_across_zero_degrees():
    histogram = tuple(0.5 if index in {0, 71} else 0.0 for index in range(72))
    assert slice_coverage(histogram, center=0.0, span=20.0) == 1.0
    assert slice_coverage(histogram, center=180.0, span=20.0) == 0.0


def test_salient_coverage_ignores_tiny_isolated_hue_noise():
    histogram = [0.0] * 72
    histogram[6] = 0.9996
    histogram[40] = 0.0004

    filtered = noise_filtered_histogram(tuple(histogram))

    assert filtered[40] == 0.0
    assert salient_slice_coverage(tuple(histogram), center=32.5, span=15.0) == 1.0


def test_salient_coverage_preserves_a_small_coherent_hue_group():
    histogram = [0.0] * 72
    histogram[6] = 0.994
    for index in range(40, 45):
        histogram[index] = 0.0012

    coverage = salient_slice_coverage(tuple(histogram), center=32.5, span=15.0)

    assert coverage < 1.0


def test_sheltering_ancient_blue_group_survives_noise_filter():
    histogram = [0.0] * 72
    blue_group = {
        39: 0.000576,
        40: 0.000440,
        41: 0.000440,
        42: 0.000745,
        43: 0.000847,
        44: 0.001152,
        45: 0.000779,
        47: 0.000271,
    }
    for index, weight in blue_group.items():
        histogram[index] = weight
    histogram[17] = 1.0 - sum(blue_group.values())

    filtered = noise_filtered_histogram(tuple(histogram))

    assert filtered[44] > 0.0
    assert salient_slice_coverage(tuple(histogram), center=75.0, span=75.0) < 1.0


def test_slice_breadth_rewards_using_more_of_the_selected_arc():
    monochrome = tuple(1.0 if index == 18 else 0.0 for index in range(72))
    broad = tuple(1.0 / 3.0 if index in {10, 18, 26} else 0.0 for index in range(72))

    assert slice_coverage(monochrome, center=90.0, span=90.0) == 1.0
    assert slice_coverage(broad, center=90.0, span=90.0) == 1.0
    assert slice_breadth(broad, center=90.0, span=90.0) > 0.7
    assert slice_breadth(monochrome, center=90.0, span=90.0) == 0.0
