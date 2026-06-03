"""Smoke test: resource manager — zombie detection, port check, memory estimate."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))


def test_check_ports():
    from ams.resources.manager import check_ports
    status = check_ports()
    assert isinstance(status, dict), "check_ports should return a dict"
    assert all(isinstance(v, bool) for v in status.values()), "Values should be bool"
    print(f"  PASS: check_ports() -> {len(status)} ports checked")


def test_zombie_dry_run():
    from ams.resources.manager import kill_ansys_zombies
    found = kill_ansys_zombies(dry_run=True, verbose=False)
    assert isinstance(found, list), "Should return a list"
    print(f"  PASS: zombie dry_run -> {len(found)} ANSYS processes found")


def test_resource_manager():
    from ams.resources.manager import ResourceManager
    rm = ResourceManager()
    info = rm.system_info(scan_ports=True)
    assert info.physical_cpus >= 1
    assert info.total_ram_mb  >= 512
    rec = rm.recommend(n_elements=10_000)
    assert rec.nproc    >= 1
    assert rec.ram_mb   >= 256
    assert rec.mapdl_port in range(50050, 50070)
    print(f"  PASS: ResourceManager -> nproc={rec.nproc}, ram={rec.ram_mb}MB, port={rec.mapdl_port}")


def test_estimate_memory():
    from ams.resources.manager import estimate_memory
    mem = estimate_memory(50_000)
    assert mem["conservative_mb"] >= 256
    assert mem["conservative_mb"] >= mem["total_mb"]
    print(f"  PASS: estimate_memory(50k) -> conservative={mem['conservative_mb']} MB")


if __name__ == "__main__":
    print("=" * 50)
    print("Resource Manager Smoke Tests")
    print("=" * 50)
    tests = [test_check_ports, test_zombie_dry_run, test_resource_manager, test_estimate_memory]
    passed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except Exception as e:
            print(f"  FAIL: {t.__name__}: {e}")
    print(f"\n{passed}/{len(tests)} passed")
    sys.exit(0 if passed == len(tests) else 1)
