#!/usr/bin/env python3
import argparse
import json
from pathlib import Path
import sys
import warnings

import numpy as np
from shapely.geometry import Polygon, LineString, Point, shape, mapping
from shapely.ops import unary_union
from shapely.ops import split
from scipy.interpolate import splprep, splev

N_DIVISIONS = 5


# ---- GeoJSON I/O ----

class SubdivisionError(ValueError):
    """Input or subdivision cannot produce a verified polygon partition."""


def validate_polygon(polygon):
    """Reject unsupported geometry rather than silently dropping components/holes."""
    if not isinstance(polygon, Polygon) or polygon.is_empty:
        raise SubdivisionError("Expected one non-empty Polygon, not a MultiPolygon.")
    if not polygon.is_valid or polygon.area <= 0:
        raise SubdivisionError("Polygon must be valid and have positive area.")
    if polygon.interiors:
        raise SubdivisionError("Polygons with holes are not supported by this centerline method.")


def load_geojson(filepath):
    """Read one Polygon geometry, Feature, or single-feature FeatureCollection."""
    with Path(filepath).open(encoding="utf-8") as stream:
        raw = json.load(stream)
    if not isinstance(raw, dict):
        raise SubdivisionError("GeoJSON must be an object.")
    if raw.get("type") == "FeatureCollection":
        features = raw.get("features", [])
        if len(features) != 1:
            raise SubdivisionError("Export exactly one polygon per input file.")
        raw = features[0]
    if raw.get("type") == "Feature":
        geom, props = raw.get("geometry"), raw.get("properties") or {}
    else:
        geom, props = raw, {}
    polygon = shape(geom)
    validate_polygon(polygon)
    return polygon, list(polygon.exterior.coords), props


def validate_partition(segments, polygon, expected, tolerance=1e-8):
    """Require the expected count, valid pieces, coverage, and no positive-area overlap."""
    validate_polygon(polygon)
    if len(segments) != expected:
        raise SubdivisionError(
            f"Expected {expected} segments, got {len(segments)}. "
            "Review the boundary cut edges or use a manual centerline."
        )
    for segment in segments:
        if not isinstance(segment, Polygon) or segment.is_empty or not segment.is_valid or segment.area <= 0:
            raise SubdivisionError("Subdivision produced an empty, invalid, or non-Polygon segment.")
    area_tolerance = polygon.area * tolerance
    combined = unary_union(segments)
    if combined.symmetric_difference(polygon).area > area_tolerance:
        raise SubdivisionError("Subdivision does not cover the original polygon within tolerance.")
    for i, segment in enumerate(segments):
        for other in segments[i + 1:]:
            if segment.intersection(other).area > area_tolerance:
                raise SubdivisionError("Subdivision contains overlapping segments.")


def export_segments_geojson(segments, polygon, props, output_path, expected=N_DIVISIONS):
    """Export only a verified partition; exclusive creation refuses existing files."""
    validate_partition(segments, polygon, expected)
    classification = props.get("classification") or {}
    class_name = classification.get("name", "Region")
    color = classification.get("color", [0, 170, 200])
    if not isinstance(color, list) or len(color) != 3:
        color = [0, 170, 200]
    features = []
    for i, segment in enumerate(segments, 1):
        name = f"{class_name}-{i}"
        features.append({
            "type": "Feature",
            "geometry": mapping(segment),
            "properties": {
                "name": name,
                "objectType": "annotation",
                "classification": {"name": class_name, "color": color},
                "segment_number": i,
                "area": segment.area,
                "percentage_of_total": 100 * segment.area / polygon.area,
            },
        })
    payload = json.dumps({"type": "FeatureCollection", "features": features}, indent=2, allow_nan=False)
    with Path(output_path).open("x", encoding="utf-8") as stream:
        stream.write(payload + "\n")
    return len(features)


# ---- Geometry ----

def find_cut_edges(coords):
    """Find the two longest boundary edges (the manual cut locations)."""
    coords = np.array(coords)
    n = len(coords)

    edges = []
    for i in range(n):
        j = (i + 1) % n
        dist = np.linalg.norm(coords[j] - coords[i])
        edges.append((i, j, coords[i], coords[j], dist))

    edges.sort(key=lambda e: e[4], reverse=True)
    top2 = edges[:2]

    midpoints = [(e[2] + e[3]) / 2 for e in top2]
    return top2, midpoints


def create_smooth_centerline(polygon, ep1, ep2):
    """Create centerline by averaging two resampled boundary sides."""
    boundary = polygon.boundary
    num_samples = 2000
    distances = np.linspace(0, boundary.length, num_samples)
    bpts = np.array([boundary.interpolate(d).coords[0] for d in distances])

    idx1 = np.argmin([np.linalg.norm(p - ep1) for p in bpts])
    idx2 = np.argmin([np.linalg.norm(p - ep2) for p in bpts])

    if idx1 > idx2:
        idx1, idx2 = idx2, idx1
        ep1, ep2 = ep2, ep1

    side1 = bpts[idx1:idx2 + 1]
    side2 = np.concatenate([bpts[idx2:], bpts[:idx1 + 1]])[::-1]

    def resample(points, n):
        if len(points) < 2:
            return points
        d = np.zeros(len(points))
        for i in range(1, len(points)):
            d[i] = d[i-1] + np.linalg.norm(points[i] - points[i-1])
        if d[-1] == 0:
            return np.repeat(points[0:1], n, axis=0)
        targets = np.linspace(0, d[-1], n)
        out = []
        for t in targets:
            idx = np.searchsorted(d, t)
            if idx == 0:
                out.append(points[0])
            elif idx >= len(points):
                out.append(points[-1])
            else:
                frac = (t - d[idx-1]) / (d[idx] - d[idx-1] + 1e-10)
                out.append(points[idx-1] * (1 - frac) + points[idx] * frac)
        return np.array(out)

    n_pts = 100
    s1 = resample(side1, n_pts)
    s2 = resample(side2, n_pts)

    center = [(s1[i] + s2[i]) / 2 for i in range(n_pts)]
    center[0], center[-1] = ep1, ep2

    return LineString(center)


def smooth_centerline(centerline, smooth_factor=0.001, lock_n=3):
    """B-spline smooth the centerline while locking endpoints."""
    coords = np.array(centerline.coords)
    if len(coords) < 2 * lock_n + 1:
        return centerline

    start, end = coords[:lock_n].copy(), coords[-lock_n:].copy()
    try:
        tck, _ = splprep([coords[:, 0], coords[:, 1]], s=smooth_factor, k=min(3, len(coords)-1))
        smooth = np.array(splev(np.linspace(0, 1, len(coords)), tck)).T
        smooth[:lock_n], smooth[-lock_n:] = start, end
        return LineString(smooth)
    except Exception as exc:
        warnings.warn(f"Centerline smoothing failed; using the unsmoothed line: {exc}", RuntimeWarning)
        return centerline


def create_perpendicular_lines(centerline, polygon, n_divisions):
    """Create perpendicular cut lines at equal intervals along the centerline."""
    cl_coords = np.array(centerline.coords)
    cl_len = centerline.length

    bbox = polygon.bounds
    line_len = 2 * np.sqrt((bbox[2] - bbox[0])**2 + (bbox[3] - bbox[1])**2)

    lines = []
    for i in range(1, n_divisions):
        pt = centerline.interpolate((i / n_divisions) * cl_len)
        pt_xy = np.array([pt.x, pt.y])

        # Find closest centerline vertex for tangent
        dists = [np.linalg.norm(pt_xy - cl_coords[j]) for j in range(len(cl_coords) - 1)]
        idx = np.argmin(dists)

        tangent = cl_coords[idx + 1] - cl_coords[idx]
        tangent /= (np.linalg.norm(tangent) + 1e-10)
        perp = np.array([-tangent[1], tangent[0]])

        lines.append(LineString([pt_xy - perp * line_len, pt_xy + perp * line_len]))

    return lines


def split_polygon(polygon, centerline, n_divisions):
    """Split polygon into n_divisions using perpendicular cuts along centerline."""
    validate_polygon(polygon)
    if n_divisions < 2:
        raise SubdivisionError("At least two segments are required.")
    if centerline.is_empty or not centerline.is_valid or centerline.length <= 0:
        raise SubdivisionError("Centerline must be valid and have positive length.")
    perp_lines = create_perpendicular_lines(centerline, polygon, n_divisions)
    start_pt = Point(centerline.coords[0])

    current = polygon
    segments = []

    for i, line in enumerate(perp_lines):
        try:
            result = split(current, line)
            polys = list(result.geoms) if hasattr(result, 'geoms') else [result]
            valid = [(start_pt.distance(p.centroid), p) for p in polys if p.area > 0]

            if len(valid) >= 2:
                valid.sort(key=lambda x: x[0])
                segments.append(valid[0][1])
                current = max([v[1] for v in valid[1:]], key=lambda x: x.area)
            else:
                raise SubdivisionError(f"Cut {i + 1} did not split the remaining polygon into two pieces.")
        except Exception as exc:
            raise SubdivisionError(f"Cut {i + 1} failed; no subdivision will be exported: {exc}") from exc

    if not current.is_empty and current.area > 0:
        segments.append(current)

    validate_partition(segments, polygon, n_divisions)
    return segments


# ---- Per-file processing ----

def subdivide(polygon, n_divisions=N_DIVISIONS):
    """Apply the original endpoint/centerline/cut method and validate its result."""
    validate_polygon(polygon)
    _, midpoints = find_cut_edges(list(polygon.exterior.coords))
    if len(midpoints) != 2 or np.linalg.norm(midpoints[0] - midpoints[1]) == 0:
        raise SubdivisionError("Could not identify two distinct cut-edge midpoints.")
    centerline = create_smooth_centerline(polygon, midpoints[0], midpoints[1])
    centerline = smooth_centerline(centerline)
    return split_polygon(polygon, centerline, n_divisions), centerline


def process_file(filepath, output_dir, n_divisions=N_DIVISIONS):
    polygon, _, props = load_geojson(filepath)
    segments, _ = subdivide(polygon, n_divisions)
    output_path = Path(output_dir) / f"{Path(filepath).stem}_segments.geojson"
    export_segments_geojson(segments, polygon, props, output_path, n_divisions)
    print(f"Exported {len(segments)} segments: {output_path.name}")
    return output_path


def main(argv=None):
    parser = argparse.ArgumentParser(description="Subdivide simple curved-band polygons along their centerline.")
    parser.add_argument("input_dir", type=Path, help="Folder containing one polygon per JSON/GeoJSON file")
    parser.add_argument("output_dir", type=Path, help="Separate output folder; existing files are never overwritten")
    parser.add_argument("--segments", type=int, default=N_DIVISIONS, help="Number of segments (default: 5)")
    args = parser.parse_args(argv)
    try:
        if args.segments < 2:
            raise SubdivisionError("--segments must be at least 2.")
        if not args.input_dir.is_dir():
            raise SubdivisionError("Input directory does not exist.")
        if args.input_dir.resolve() == args.output_dir.resolve():
            raise SubdivisionError("Input and output directories must be different.")
        files = sorted(p for p in args.input_dir.iterdir()
                       if p.is_file() and p.suffix.lower() in {".json", ".geojson"})
        if not files:
            raise SubdivisionError("Input directory contains no JSON/GeoJSON files.")
        targets = [args.output_dir / f"{p.stem}_segments.geojson" for p in files]
        if len(set(targets)) != len(targets):
            raise SubdivisionError("Input names map to duplicate output names; rename the inputs.")
        if any(p.exists() for p in targets):
            raise FileExistsError("An output already exists. Choose a fresh output directory.")
        # Preflight all geometry before writing any output for a malformed batch.
        for filepath in files:
            polygon, _, _ = load_geojson(filepath)
            subdivide(polygon, args.segments)
        args.output_dir.mkdir(parents=True, exist_ok=True)
        for filepath in files:
            process_file(filepath, args.output_dir, args.segments)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
