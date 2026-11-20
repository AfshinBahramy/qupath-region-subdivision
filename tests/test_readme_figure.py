"""Verify that the README visualizes the actual splitter and its exported metadata."""
import json
from pathlib import Path

import numpy as np
from PIL import Image
import pytest
from shapely.geometry import LineString, Point, Polygon, shape
from shapely.ops import unary_union

from examples.make_readme_figure import generate
import examples.make_readme_figure as figure_module
from segment_polygon import (create_perpendicular_lines, find_cut_edges,
                             load_geojson, main, subdivide)

INPUT = Path(__file__).resolve().parents[1] / 'examples/readme/synthetic_band.geojson'


def test_readme_figure_matches_production_geometry_and_cli(tmp_path, monkeypatch):
    # Inspect actual rendered text while retaining normal figure cleanup.
    close = figure_module.plt.close
    segment_labels = []
    def check_labels(figure):
        if hasattr(figure, 'axes'):
            segment_labels.extend(text.get_text() for text in figure.axes[2].texts)
            assert not any('%' in text.get_text() for axis in figure.axes for text in axis.texts)
        close(figure)
    monkeypatch.setattr(figure_module.plt, 'close', check_labels)
    output = tmp_path / 'figure'
    result = generate(INPUT, output)
    assert segment_labels == ['1', '2', '3', '4', '5']
    polygon, _, _ = load_geojson(INPUT)
    segments, centerline = subdivide(polygon)
    edges, _ = find_cut_edges(list(polygon.exterior.coords))
    assert LineString(result['centerline']).equals_exact(centerline, 0)
    for drawn, actual in zip(result['ends'], edges):
        np.testing.assert_array_equal(drawn, np.asarray([actual[2], actual[3]]))
    expected_cuts = unary_union([line.intersection(polygon) for line in
                                create_perpendicular_lines(centerline, polygon, 5)])
    assert unary_union(result['cuts']).equals(expected_cuts)
    expected_points = [centerline.interpolate(k * centerline.length / 5).coords[0]
                       for k in range(1, 5)]
    np.testing.assert_array_equal(result['cut_points'], expected_points)
    assert len(result['segments']) == len(result['features']) == 5
    for number, (ring, feature, segment, label) in enumerate(zip(
            result['segments'], result['features'], segments, result['label_points']), 1):
        assert Polygon(ring).equals_exact(segment, 0)
        assert shape(feature['geometry']).equals_exact(segment, 0)
        assert feature['properties']['segment_number'] == number
        assert feature['properties']['area'] == segment.area
        assert feature['properties']['percentage_of_total'] == 100 * segment.area / polygon.area
        assert segment.covers(Point(label))
    # The renderer's properties are exactly the CLI output, including order and percentages.
    assert main([str(INPUT.parent), str(tmp_path / 'cli')]) == 0
    assert json.loads((output / 'synthetic_band_segments.geojson').read_text()) == json.loads(
        (tmp_path / 'cli/synthetic_band_segments.geojson').read_text())
    with Image.open(output / 'subdivision_example.png') as image:
        image.verify()


def test_figure_regeneration_and_no_overwrite(tmp_path):
    first, second = tmp_path / 'first', tmp_path / 'second'
    source_before = INPUT.read_bytes()
    generate(INPUT, first)
    generate(INPUT, second)
    for name in ['subdivision_example.png', 'synthetic_band_segments.geojson']:
        assert (first / name).read_bytes() == (second / name).read_bytes()
    saved = {p.name: p.read_bytes() for p in first.iterdir()}
    with pytest.raises(FileExistsError, match='fresh output directory'):
        generate(INPUT, first)
    assert saved == {p.name: p.read_bytes() for p in first.iterdir()}
    assert INPUT.read_bytes() == source_before
