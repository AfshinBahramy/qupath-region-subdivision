"""Generate a curved-band example and figure entirely from synthetic geometry."""
import argparse
import json
from pathlib import Path
import sys

import numpy as np
from shapely.geometry import Polygon, mapping

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from segment_polygon import export_segments_geojson, subdivide


def curved_band():
    """An annular sector with densely sampled sides and two long, flat ends."""
    theta = np.linspace(0.15, 1.35, 401)
    outer = np.column_stack((1000 + 1080 * np.cos(theta), 1000 + 1080 * np.sin(theta)))
    inner = np.column_stack((1000 + 920 * np.cos(theta[::-1]), 1000 + 920 * np.sin(theta[::-1])))
    return Polygon(np.concatenate([outer, inner]))


def generate(output_dir):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Polygon as PolygonPatch

    output_dir = Path(output_dir)
    input_dir = output_dir / "input"
    segment_dir = output_dir / "output"
    files = [input_dir / "synthetic_band.geojson", segment_dir / "synthetic_band_segments.geojson",
             output_dir / "centerline.geojson", output_dir / "subdivision.png"]
    if any(path.exists() for path in files):
        raise FileExistsError("Synthetic example outputs already exist; choose a fresh directory.")
    polygon = curved_band()
    segments, centerline = subdivide(polygon)
    input_dir.mkdir(parents=True, exist_ok=True)
    segment_dir.mkdir(parents=True, exist_ok=True)
    props = {"name": "Synthetic curved band", "objectType": "annotation",
             "classification": {"name": "Synthetic band", "color": [0, 170, 200]}}
    with files[0].open("x", encoding="utf-8") as stream:
        json.dump({"type": "Feature", "geometry": mapping(polygon), "properties": props}, stream, indent=2)
        stream.write("\n")
    export_segments_geojson(segments, polygon, props, files[1])
    with files[2].open("x", encoding="utf-8") as stream:
        json.dump({"type": "Feature", "geometry": mapping(centerline),
                   "properties": {"name": "Synthetic centerline", "objectType": "annotation"}}, stream, indent=2)
        stream.write("\n")
    fig, ax = plt.subplots(figsize=(8, 6), layout="constrained")
    colors = plt.get_cmap("viridis")(np.linspace(0.12, 0.9, 5))
    for i, (segment, color) in enumerate(zip(segments, colors), 1):
        ax.add_patch(PolygonPatch(np.asarray(segment.exterior.coords), facecolor=color,
                                 edgecolor="white", linewidth=1.5))
        point = segment.representative_point()
        ax.text(point.x, point.y, str(i), ha="center", va="center", fontsize=12,
                bbox={"facecolor": "white", "edgecolor": "none", "alpha": 0.85})
    ax.plot(*centerline.xy, color="#c63b3b", linestyle="--", linewidth=1.5, label="Estimated centerline")
    ax.set(xlabel="Synthetic x (pixels)", ylabel="Synthetic y (pixels)",
           title="Five subdivisions of a synthetic curved band")
    ax.text(0.5, -0.15, "Equal centerline intervals; segment areas need not be equal. No research data.",
            ha="center", transform=ax.transAxes, fontsize=9)
    ax.set_aspect("equal")
    ax.autoscale_view()
    ax.invert_yaxis()
    ax.legend(loc="upper right")
    with files[3].open("xb") as stream:
        fig.savefig(stream, format="png", dpi=180)
    plt.close(fig)
    print("Synthetic example and figure generated.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output_dir", type=Path)
    generate(parser.parse_args().output_dir)
