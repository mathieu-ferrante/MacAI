"""État mémoire/disque du Mac (repris de SwapGuard) via les outils système, sans dépendance.

Chaque fonction `parse_*` est pure (texte -> données) pour être testable hors macOS.
`collect()` exécute les commandes et assemble un instantané.
"""
from __future__ import annotations

import re
import subprocess
import time
from collections import defaultdict
from dataclasses import dataclass, field

PRESSURE_LABELS = {1: "normale", 2: "tendue", 4: "critique"}


def run(cmd: list[str]) -> str:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=15, check=True).stdout


# --- Parseurs -----------------------------------------------------------------

def _to_bytes(value: str, unit: str) -> int:
    mult = {"K": 1024, "M": 1024**2, "G": 1024**3}[unit.upper()]
    return int(float(value) * mult)


def parse_swapusage(text: str) -> dict:
    """`sysctl vm.swapusage` -> {'total','used','free'} en octets."""
    out = {}
    for key in ("total", "used", "free"):
        m = re.search(rf"{key}\s*=\s*([\d.]+)([KMG])", text)
        out[key] = _to_bytes(*m.groups()) if m else 0
    return out


def parse_vm_stat(text: str) -> dict:
    """`vm_stat` -> {'page_size': int, '<clé normalisée>': int, ...}."""
    m = re.search(r"page size of (\d+) bytes", text)
    stats = {"page_size": int(m.group(1)) if m else 16384}
    for line in text.splitlines()[1:]:
        if ":" not in line:
            continue
        name, _, value = line.rpartition(":")
        value = value.strip().rstrip(".")
        if value.isdigit():
            key = re.sub(r"[^a-z]+", "_", name.strip().strip('"').lower()).strip("_")
            stats[key] = int(value)
    return stats


def parse_memory_free_pct(text: str) -> int | None:
    """`memory_pressure -Q` -> pourcentage de mémoire libre (vision système)."""
    m = re.search(r"free percentage:\s*(\d+)%", text)
    return int(m.group(1)) if m else None


def parse_disk_bytes_written(text: str) -> int:
    """`ioreg -c IOBlockStorageDriver -r -k Statistics` -> octets écrits depuis le démarrage."""
    return sum(int(n) for n in re.findall(r'"Bytes \(Write\)"\s*=\s*(\d+)', text))


def app_name_from_path(path: str) -> str:
    """Regroupe les processus par application : le premier `X.app` du chemin gagne.

    `/Applications/Google Chrome.app/.../Google Chrome Helper (Renderer).app/...` -> `Google Chrome`.
    """
    m = re.search(r"/([^/]+)\.app(/|$)", path)
    if m:
        return m.group(1)
    return path.rsplit("/", 1)[-1] or path


def parse_ps(text: str) -> list[tuple[int, int, str]]:
    """`ps -axo pid=,rss=,comm=` -> [(pid, rss_octets, chemin)]."""
    procs = []
    for line in text.splitlines():
        parts = line.strip().split(None, 2)
        if len(parts) == 3 and parts[0].isdigit() and parts[1].isdigit():
            procs.append((int(parts[0]), int(parts[1]) * 1024, parts[2]))
    return procs


def group_by_app(procs: list[tuple[int, int, str]]) -> list[dict]:
    totals: dict[str, dict] = defaultdict(lambda: {"rss": 0, "count": 0, "pids": [], "is_app": False})
    for pid, rss, path in procs:
        entry = totals[app_name_from_path(path)]
        entry["is_app"] = entry["is_app"] or ".app/" in path
        entry["rss"] += rss
        entry["count"] += 1
        entry["pids"].append(pid)
    apps = [{"name": name, **data} for name, data in totals.items()]
    return sorted(apps, key=lambda a: a["rss"], reverse=True)


# --- Instantané ---------------------------------------------------------------

@dataclass
class Snapshot:
    ts: float
    ram_total: int
    app_mem: int
    wired: int
    compressed: int
    cached: int
    swap_used: int
    swap_total: int
    swapouts: int            # compteur cumulé (octets écrits en swap) depuis le démarrage
    disk_written: int        # compteur cumulé (octets) depuis le démarrage
    pressure_level: int      # 1 normale, 2 tendue, 4 critique
    free_pct: int | None
    apps: list[dict] = field(default_factory=list)

    @property
    def used(self) -> int:
        return self.app_mem + self.wired + self.compressed

    @property
    def pressure_label(self) -> str:
        return PRESSURE_LABELS.get(self.pressure_level, str(self.pressure_level))


def build_snapshot(vm_text, swap_text, memsize_text, pressure_text, mp_text, ioreg_text, ps_text,
                   ts: float | None = None) -> Snapshot:
    vm = parse_vm_stat(vm_text)
    page = vm["page_size"]
    pages = lambda k: vm.get(k, 0) * page  # noqa: E731
    swap = parse_swapusage(swap_text)
    # Mêmes définitions que le Moniteur d'activité.
    return Snapshot(
        ts=ts if ts is not None else time.time(),
        ram_total=int(memsize_text.strip() or 0),
        app_mem=max(pages("anonymous_pages") - pages("pages_purgeable"), 0),
        wired=pages("pages_wired_down"),
        compressed=pages("pages_occupied_by_compressor"),
        cached=pages("file_backed_pages") + pages("pages_purgeable"),
        swap_used=swap["used"],
        swap_total=swap["total"],
        swapouts=pages("swapouts"),
        disk_written=parse_disk_bytes_written(ioreg_text),
        pressure_level=int(pressure_text.strip() or 1),
        free_pct=parse_memory_free_pct(mp_text),
        apps=group_by_app(parse_ps(ps_text)),
    )


def collect(runner=run) -> Snapshot:
    def safe(cmd):
        try:
            return runner(cmd)
        except (subprocess.SubprocessError, OSError):
            return ""

    return build_snapshot(
        vm_text=safe(["vm_stat"]),
        swap_text=safe(["sysctl", "-n", "vm.swapusage"]),
        memsize_text=safe(["sysctl", "-n", "hw.memsize"]),
        pressure_text=safe(["sysctl", "-n", "kern.memorystatus_vm_pressure_level"]),
        mp_text=safe(["memory_pressure", "-Q"]),
        ioreg_text=safe(["ioreg", "-c", "IOBlockStorageDriver", "-r", "-w", "0", "-k", "Statistics"]),
        ps_text=safe(["ps", "-axo", "pid=,rss=,comm="]),
    )


def fmt_bytes(n: float) -> str:
    for unit in ("o", "Ko", "Mo", "Go", "To"):
        if abs(n) < 1024 or unit == "To":
            return f"{n:.0f} {unit}" if unit in ("o", "Ko") else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} To"
