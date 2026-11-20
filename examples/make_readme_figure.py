#!/usr/bin/env python3
"""Render the synthetic README example using the production subdivision algorithm."""
import argparse
import json
from pathlib import Path
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import LinearSegmentedColormap, to_rgb
from matplotlib.patches import FancyArrowPatch
from matplotlib.patches import Polygon as PolygonPatch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from segment_polygon import (N_DIVISIONS, create_perpendicular_lines,
                             export_segments_geojson, find_cut_edges,
                             load_geojson, subdivide)

N_SEGMENTS = N_DIVISIONS

# Colors: an eosin-to-hematoxylin ramp for segments, teal for cuts.
INK = "#1d2433"
MUTED = "#5d6677"
OUTLINE = "#4a4260"
TISSUE = "#f4e6ee"
CUT = "#0e7c86"
CENTER = "#3a2e7d"
ARROW = "#a6abb6"
RAMP = LinearSegmentedColormap.from_list(
    "he_ramp", ["#f2b3cd", "#b88cc6", "#4e4a9e"]
)

plt.rcParams.update(
    {
        "font.family": "sans-serif",
        "font.sans-serif": ["Fira Sans", "Source Sans 3", "Helvetica Neue",
                            "Arial", "DejaVu Sans"],
        "svg.fonttype": "none",
    }
)


# ---------------------------------------------------------------- drawing
def text_color(fill):
    r, g, b = to_rgb(fill)
    return INK if (0.2126 * r + 0.7152 * g + 0.0722 * b) > 0.5 else "white"


def draw_region(ax, ring, face, edge, lw):
    ax.add_patch(PolygonPatch(ring, closed=True, facecolor=face,
                              edgecolor=edge, linewidth=lw, joinstyle="round"))


def render(ring, result, png_path):
    pad = 0.05 * np.ptp(ring, axis=0).max()
    lo, hi = ring.min(axis=0) - pad, ring.max(axis=0) + pad
    hi[1] += 0.07 * (hi[1] - lo[1])                    # room for "cut end" labels
    data_aspect = (hi[1] - lo[1]) / (hi[0] - lo[0])

    fig_w, margin, gap = 10.0, 0.12, 0.5               # inches
    head, foot = 0.78, 0.30                            # title block, footer block
    panel_w = (fig_w - 2 * margin - 2 * gap) / 3
    panel_h = panel_w * data_aspect
    fig_h = head + panel_h + foot
    fig = plt.figure(figsize=(fig_w, fig_h), dpi=200)
    bottom, top = foot / fig_h, (foot + panel_h) / fig_h
    axes = [fig.add_axes([(margin + i * (panel_w + gap)) / fig_w, bottom,
                          panel_w / fig_w, panel_h / fig_h]) for i in range(3)]
    for ax in axes:
        ax.set_xlim(lo[0], hi[0])
        ax.set_ylim(hi[1], lo[1])                      # image y points down
        ax.set_aspect("equal", adjustable="datalim")
        ax.axis("off")

    titles = [("1  Input annotation", "Two longest edges become the cut ends"),
              ("2  Centerline and cuts", "Cuts at equal intervals along the centerline"),
              ("3  Five segments", "Numbered along the centerline")]
    for ax, (title, subtitle) in zip(axes, titles):
        x0 = ax.get_position().x0
        fig.text(x0, 1 - 0.30 / fig_h, title, fontsize=13.5, fontweight="semibold",
                 color=INK, va="baseline")
        fig.text(x0, 1 - 0.56 / fig_h, subtitle, fontsize=10.5, color=MUTED, va="baseline")

    # Panel 1: input polygon and the two cut ends.
    ax = axes[0]
    draw_region(ax, ring, TISSUE, OUTLINE, 1.2)
    for a, b in result["ends"]:
        ax.plot(*np.array([a, b]).T, color=CUT, lw=3.4, solid_capstyle="round",
                zorder=3)
        ax.annotate("cut end", xy=(a + b) / 2, xytext=(0, -13),
                    textcoords="offset points", ha="center", va="top",
                    fontsize=10, color=CUT, fontweight="medium")

    # Panel 2: production centerline and perpendicular cuts clipped to the input.
    ax = axes[1]
    draw_region(ax, ring, "#fbf6f9", OUTLINE, 1.0)
    for cut in result["cuts"]:
        ax.plot(*np.asarray(cut.coords).T, color=CUT, lw=2.4, solid_capstyle="butt",
                zorder=4)
    center = result["centerline"]
    ax.plot(center[:, 0], center[:, 1], color=CENTER, lw=2.2, zorder=5,
            solid_capstyle="round")
    ax.scatter(*center[[0, -1]].T, s=30, color=CENTER, zorder=6,
               edgecolor="white", linewidth=1.0)
    ax.scatter(*result["cut_points"].T, s=20, color="white", zorder=6,
               edgecolor=CENTER, linewidth=1.3)

    # Panel 3: the five numbered segments.
    ax = axes[2]
    colors = [RAMP(v) for v in np.linspace(0.0, 1.0, N_SEGMENTS)]
    for seg, color in zip(result["segments"], colors):
        draw_region(ax, seg, color, "white", 1.8)
    draw_region(ax, ring, "none", OUTLINE, 1.2)
    for feature, p, color in zip(result["features"], result["label_points"], colors):
        props = feature["properties"]
        ax.text(*p, str(props["segment_number"]), ha="center", va="center", fontsize=13,
                fontweight="semibold", color=text_color(color), zorder=6)

    # Arrows between panels.
    y_mid = bottom + 0.45 * (top - bottom)
    for left_ax, right_ax in zip(axes[:-1], axes[1:]):
        x0 = left_ax.get_position().x1 + 0.008
        x1 = right_ax.get_position().x0 - 0.008
        fig.add_artist(FancyArrowPatch((x0, y_mid), (x1, y_mid),
                                       transform=fig.transFigure,
                                       arrowstyle="-|>", mutation_scale=13,
                                       lw=1.3, color=ARROW))

    fig.text(1 - margin / fig_w, 0.08 / fig_h, "Synthetic annotation, no tissue data.",
             fontsize=9, color=MUTED, ha="right")
    with Path(png_path).open("xb") as stream:
        fig.savefig(stream, format="png", dpi=200, facecolor="white",
                    metadata={"Software": "Matplotlib", "Description": "Synthetic polygon subdivision"})
    plt.close(fig)


def generate(input_path, output_dir):
    """Render only verified production results; refuse to overwrite any output."""
    output_dir = Path(output_dir)
    png_path = output_dir / "subdivision_example.png"
    geojson_path = output_dir / "synthetic_band_segments.geojson"
    if png_path.exists() or geojson_path.exists():
        raise FileExistsError("Figure outputs already exist; choose a fresh output directory.")
    polygon, _, props = load_geojson(input_path)
    segments, centerline = subdivide(polygon)
    edges, _ = find_cut_edges(list(polygon.exterior.coords))
    cuts = create_perpendicular_lines(centerline, polygon, N_SEGMENTS)
    clipped_cuts = []
    for cut in cuts:
        clipped = cut.intersection(polygon)
        clipped_cuts.extend(list(clipped.geoms) if hasattr(clipped, "geoms") else [clipped])
    output_dir.mkdir(parents=True, exist_ok=True)
    export_segments_geojson(segments, polygon, props, geojson_path)
    features = json.loads(geojson_path.read_text(encoding="utf-8"))["features"]
    result = {
        "ends": [(edge[2], edge[3]) for edge in edges],
        "centerline": np.asarray(centerline.coords),
        "cuts": clipped_cuts,
        "cut_points": np.array([centerline.interpolate(k * centerline.length / N_SEGMENTS).coords[0]
                                 for k in range(1, N_SEGMENTS)]),
        "segments": [np.asarray(segment.exterior.coords) for segment in segments],
        "features": features,
        "label_points": [(segment.centroid if segment.covers(segment.centroid)
                          else segment.representative_point()).coords[0] for segment in segments],
    }
    render(np.asarray(polygon.exterior.coords), result, png_path)
    print(f"Wrote {png_path} and {geojson_path}")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("examples/readme/synthetic_band.geojson"))
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    generate(args.input, args.output_dir)
