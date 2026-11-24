"""
Unit Tests for Rapido-Inspired 2D SVG Bus Markers (tests/unit/test_bus_svg_markers.py)
Validates that the top-down 2D bus vector silhouette adheres to the hackathon specifications.
"""
import re
from pathlib import Path


def extract_create_bus_svg_js():
    """Extracts createBusSvg function definition from app.js for structural validation."""
    app_js = (Path(__file__).resolve().parents[2] / "frontend" / "static" / "js" / "app.js").read_text(encoding="utf-8")
    match = re.search(r"function createBusSvg\(freshnessState, bearing\)\s*\{(.*?)\n\}", app_js, re.DOTALL)
    assert match is not None, "createBusSvg function not found in app.js"
    return match.group(1)


def test_bus_svg_vector_dimensions_and_viewbox():
    """Validates SVG viewBox 0 0 64 120 and width/height aspect ratio."""
    fn_body = extract_create_bus_svg_js()
    assert 'viewBox="0 0 64 120"' in fn_body
    assert 'width="32"' in fn_body
    assert 'height="60"' in fn_body


def test_bus_svg_structural_components():
    """Validates wheels, headlights, taillights, windshield gradient, and AC unit louvers."""
    fn_body = extract_create_bus_svg_js()
    # 4 Side Wheels
    assert "4 Side Wheels" in fn_body
    assert fn_body.count('<rect x="2"') >= 1 or fn_body.count('Side Wheels') >= 1
    
    # Directional Headlights
    assert "#FEF08A" in fn_body
    
    # Destination Display Strip (Amber/Yellow)
    assert "#FACC15" in fn_body
    
    # Windshield Gradient
    assert "windshield-grad" in fn_body
    assert "#E0F2FE" in fn_body
    assert "#93C5FD" in fn_body
    
    # Roof AC Unit with horizontal louvers
    assert "Roof Top AC" in fn_body or "AC Climate Unit" in fn_body
    assert fn_body.count("<line x1=") >= 3
    
    # Rear Taillights (Red)
    assert "#EF4444" in fn_body


def test_bus_svg_freshness_states_and_bearing():
    """Validates freshness color mapping (FRESH green, AGING amber, STALE red) and CSS rotation."""
    fn_body = extract_create_bus_svg_js()
    assert "#10B981" in fn_body  # FRESH
    assert "#F59E0B" in fn_body  # AGING
    assert "#EF4444" in fn_body  # STALE
    # The globe billboard is rotated to the bearing; the SVG records it for debugging.
    assert 'data-rotation="${rotation}"' in fn_body
