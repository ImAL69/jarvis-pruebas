from __future__ import annotations

from pathlib import Path


class PolicyError(ValueError):
    pass


def _is_within(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def _reject_symlink_escape(resolved: Path, root: Path) -> None:
    current = root
    for part in resolved.relative_to(root).parts:
        current = current / part
        if current.exists() and current.is_symlink():
            target = current.resolve()
            if not _is_within(target, root):
                raise PolicyError(f"Symlink fuera de la raíz permitida: {current}")


def resolve_allowed_path(allowed_roots: list[Path], requested_path: str) -> tuple[Path, Path]:
    path_candidate = Path(requested_path)

    if path_candidate.is_absolute():
        resolved = path_candidate.resolve()
        for root in allowed_roots:
            if _is_within(resolved, root):
                _reject_symlink_escape(resolved, root)
                return resolved, root
        raise PolicyError("Ruta absoluta fuera de las raíces permitidas")

    for root in allowed_roots:
        resolved = (root / path_candidate).resolve()
        if _is_within(resolved, root):
            _reject_symlink_escape(resolved, root)
            return resolved, root

    raise PolicyError("Ruta fuera de las raíces permitidas (path traversal detectado)")
