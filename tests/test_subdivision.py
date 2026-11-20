import json
from itertools import combinations

import pytest
from shapely.geometry import LineString, MultiPolygon, Polygon, box, mapping, shape
from shapely.ops import unary_union

from examples.generate_example import curved_band
from segment_polygon import (SubdivisionError, export_segments_geojson, load_geojson,
                             main, process_file, split_polygon, subdivide, validate_partition)


def write_feature(path, polygon=None):
    polygon = curved_band() if polygon is None else polygon
    path.write_text(json.dumps({"type": "Feature", "geometry": mapping(polygon),
                                "properties": {"classification": {"name": "Synthetic band"}}}))


def test_curved_band_partition_and_export(tmp_path):
    """Check actual geometric coverage and overlap, including the exported polygons."""
    polygon = curved_band()
    segments, _ = subdivide(polygon)
    assert len(segments) == 5
    assert all(s.is_valid and not s.is_empty and s.area > 0 for s in segments)
    tolerance = polygon.area * 1e-8
    assert unary_union(segments).symmetric_difference(polygon).area <= tolerance
    assert all(a.intersection(b).area <= tolerance for a, b in combinations(segments, 2))
    output = tmp_path / "segments.geojson"
    export_segments_geojson(segments, polygon, {"classification": {"name": "Synthetic band"}}, output)
    features = json.loads(output.read_text())["features"]
    exported = [shape(f["geometry"]) for f in features]
    assert [f["properties"]["segment_number"] for f in features] == [1, 2, 3, 4, 5]
    assert all(f["properties"]["objectType"] == "annotation" for f in features)
    assert unary_union(exported).symmetric_difference(polygon).area <= tolerance
    assert sum(f["properties"]["percentage_of_total"] for f in features) == pytest.approx(100)


@pytest.mark.parametrize("kind", ["geometry", "feature", "collection"])
def test_supported_geojson_forms(tmp_path, kind):
    geometry = mapping(curved_band())
    feature = {"type": "Feature", "geometry": geometry, "properties": {}}
    raw = {"geometry": geometry, "feature": feature,
           "collection": {"type": "FeatureCollection", "features": [feature]}}[kind]
    path = tmp_path / "polygon.geojson"
    path.write_text(json.dumps(raw))
    polygon, _, _ = load_geojson(path)
    assert polygon.equals(curved_band())


@pytest.mark.parametrize("polygon", [
    MultiPolygon([box(0, 0, 1, 1), box(2, 0, 3, 1)]),
    Polygon([(0, 0), (4, 0), (4, 4), (0, 4)], holes=[[(1, 1), (2, 1), (2, 2), (1, 2)]]),
    Polygon([(0, 0), (2, 2), (0, 2), (2, 0)]),
    Polygon(),
])
def test_reject_unsupported_geometry(polygon):
    with pytest.raises(SubdivisionError):
        subdivide(polygon)


def test_collection_does_not_silently_drop_features(tmp_path):
    feature = {"type": "Feature", "geometry": mapping(curved_band()), "properties": {}}
    path = tmp_path / "multiple.geojson"
    path.write_text(json.dumps({"type": "FeatureCollection", "features": [feature, feature]}))
    with pytest.raises(SubdivisionError, match="exactly one"):
        load_geojson(path)


def test_failed_cuts_raise_instead_of_empty_padding():
    with pytest.raises(SubdivisionError, match="Cut"):
        split_polygon(box(0, 0, 1, 1), LineString([(5, 5), (6, 5)]), 5)


def test_validation_rejects_fewer_segments():
    with pytest.raises(SubdivisionError, match="Expected 5 segments, got 1"):
        validate_partition([curved_band()], curved_band(), 5)


def test_validation_rejects_overlap_even_if_union_covers_input():
    with pytest.raises(SubdivisionError, match="overlapping"):
        validate_partition([box(0, 0, 0.6, 1), box(0.4, 0, 1, 1)], box(0, 0, 1, 1), 2)


def test_validation_rejects_missing_area():
    with pytest.raises(SubdivisionError, match="cover"):
        validate_partition([box(0, 0, 0.4, 1), box(0.6, 0, 1, 1)], box(0, 0, 1, 1), 2)


def test_existing_output_is_unchanged(tmp_path):
    path = tmp_path / "synthetic.geojson"
    write_feature(path)
    out = tmp_path / "output"
    out.mkdir()
    target = out / "synthetic_segments.geojson"
    target.write_text("existing user file")
    with pytest.raises(FileExistsError):
        process_file(path, out)
    assert target.read_text() == "existing user file"


def test_cli_success_and_no_overwrite(tmp_path):
    inputs, outputs = tmp_path / "input", tmp_path / "output"
    inputs.mkdir()
    write_feature(inputs / "synthetic.geojson")
    original = (inputs / "synthetic.geojson").read_bytes()
    assert main([str(inputs), str(outputs)]) == 0
    target = outputs / "synthetic_segments.geojson"
    saved = target.read_bytes()
    assert main([str(inputs), str(outputs)]) == 1
    assert target.read_bytes() == saved
    assert (inputs / "synthetic.geojson").read_bytes() == original


def test_batch_preflight_does_not_export_partial_geometry(tmp_path):
    inputs, outputs = tmp_path / "input", tmp_path / "output"
    inputs.mkdir()
    write_feature(inputs / "a.geojson")
    (inputs / "b.geojson").write_text("invalid json")
    assert main([str(inputs), str(outputs)]) == 1
    assert not outputs.exists()


def test_duplicate_output_names_rejected(tmp_path):
    inputs, outputs = tmp_path / "input", tmp_path / "output"
    inputs.mkdir()
    write_feature(inputs / "same.json")
    write_feature(inputs / "same.geojson")
    assert main([str(inputs), str(outputs)]) == 1
    assert not outputs.exists()


@pytest.mark.parametrize("extra", [[], ["--segments", "1"]])
def test_empty_input_or_invalid_count(tmp_path, extra):
    inputs = tmp_path / "input"
    inputs.mkdir()
    assert main([str(inputs), str(tmp_path / "output")] + extra) == 1


def test_same_input_output_directory_rejected(tmp_path):
    write_feature(tmp_path / "synthetic.geojson")
    assert main([str(tmp_path), str(tmp_path)]) == 1
    assert not (tmp_path / "synthetic_segments.geojson").exists()
