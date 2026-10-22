"""Import pinned optional source packages without installing into the baseline env."""
import hashlib
import importlib
from pathlib import Path
import sys


def source_package(source_root, package):
    root = Path(source_root).resolve()
    if not (root / package / "__init__.py").is_file():
        raise ValueError(f"Missing source package: {root / package}")
    if package not in sys.modules:
        sys.path.insert(0, str(root))
        importlib.import_module(package)
    module = sys.modules[package]
    loaded = Path(module.__file__).resolve().parent
    expected = root / package
    if loaded != expected:
        # Several checkpoints share an identical upstream source snapshot. Reuse
        # its module only if every Python file matches, never mix implementations.
        expected_paths = {p.relative_to(expected) for p in expected.rglob("*.py")}
        loaded_paths = {p.relative_to(loaded) for p in loaded.rglob("*.py")}
        if expected_paths != loaded_paths or any(
            hashlib.sha256((expected / p).read_bytes()).digest() != hashlib.sha256((loaded / p).read_bytes()).digest()
            for p in expected_paths
        ):
            raise RuntimeError(f"A different {package} implementation is already imported; use a separate worker")
    return module
