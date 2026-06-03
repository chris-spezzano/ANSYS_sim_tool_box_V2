"""Smoke test: mesh quality checker (offline - no MAPDL connection needed)."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))


def test_jacobian_estimate():
    import numpy as np
    from ams.geometry.mesh_quality import _estimate_jacobian

    # Perfect square quad
    coords_good = np.array([[0,0,0],[1,0,0],[1,1,0],[0,1,0]], dtype=float)
    j = _estimate_jacobian(coords_good)
    assert j > 0, f"Good quad should have positive Jacobian, got {j}"

    # Inverted quad: clockwise node ordering gives negative Jacobian.
    # CCW (good): BL(0,0) -> BR(1,0) -> TR(1,1) -> TL(0,1)
    # CW (bad):   BL(0,0) -> TL(0,1) -> TR(1,1) -> BR(1,0)
    coords_inv = np.array([[0,0,0],[0,1,0],[1,1,0],[1,0,0]], dtype=float)
    j_inv = _estimate_jacobian(coords_inv)
    assert j_inv < 0, f"Inverted (CW) quad should have negative Jacobian, got {j_inv}"

    print(f"  PASS: Jacobian estimate - good={j:.3f}, inverted={j_inv:.3f}")


def test_quality_report():
    from ams.geometry.mesh_quality import QualityReport
    report = QualityReport(
        passed=True, n_nodes=100, n_elements=80,
        checks={
            "aspect_ratio": {"status": "PASS", "value": 3.2, "msg": "max=3.20 mean=1.5"},
            "jacobian":     {"status": "PASS", "value": 0.85, "msg": "min=0.85"},
        }
    )
    assert report.passed
    assert report.n_nodes == 100
    report.print_summary()
    print("  PASS: QualityReport.print_summary()")


def test_element_selector():
    from ams.geometry.element_selector import choose_element, ELEMENT_LIBRARY

    # Should recommend SHELL181 for thin shell large deformation
    elem = choose_element(spatial_dim=3, is_thin_shell=True, large_deformation=True)
    assert elem.name == "SHELL181", f"Expected SHELL181, got {elem.name}"

    # Should recommend SOLID186 for 3D high accuracy
    elem = choose_element(spatial_dim=3, high_accuracy=True)
    assert elem.name == "SOLID186", f"Expected SOLID186, got {elem.name}"

    # Should recommend BEAM188 for beam
    elem = choose_element(spatial_dim=3, is_beam=True)
    assert elem.name == "BEAM188", f"Expected BEAM188, got {elem.name}"

    print(f"  PASS: choose_element() - {len(ELEMENT_LIBRARY)} elements in library")


def test_quality_thresholds():
    from ams.geometry.mesh_quality import QualityThresholds
    qt = QualityThresholds(aspect_ratio_max=10.0)
    assert qt.aspect_ratio_max == 10.0
    assert qt.jacobian_min == 0.0
    print("  PASS: QualityThresholds()")


if __name__ == "__main__":
    print("=" * 50)
    print("Mesh Quality Smoke Tests")
    print("=" * 50)
    tests = [test_jacobian_estimate, test_quality_report, test_element_selector, test_quality_thresholds]
    passed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except Exception as e:
            print(f"  FAIL: {t.__name__}: {e}")
    print(f"\n{passed}/{len(tests)} passed")
    sys.exit(0 if passed == len(tests) else 1)
