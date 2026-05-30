"""Render the architecture diagram to docs/architecture.png (committed for the README).

A matplotlib renderer is used so the image regenerates with zero extra tooling; an
editable draw.io source lives alongside it at docs/architecture.drawio.

    python docs/make_architecture.py
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.patches as mpatches  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch  # noqa: E402

OUT = Path(__file__).resolve().parent / "architecture.png"

INPUT = "#dbe7ff"
CORE = "#d6f5e3"
DECIDE = "#fff3cd"
OUTPUT = "#f5d6e6"
EDGE = "#34495e"


def box(ax, x, y, w, h, text, color, fontsize=10, bold=False):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.02,rounding_size=0.06",
                                linewidth=1.4, edgecolor=EDGE, facecolor=color))
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center",
            fontsize=fontsize, fontweight="bold" if bold else "normal", color="#1a1a1a")


def arrow(ax, x1, y1, x2, y2, style="-|>", color=EDGE, lw=1.5, ls="-"):
    ax.add_patch(FancyArrowPatch((x1, y1), (x2, y2), arrowstyle=style, mutation_scale=14,
                                 linewidth=lw, color=color, linestyle=ls,
                                 connectionstyle="arc3,rad=0"))


def main() -> None:
    fig, ax = plt.subplots(figsize=(13.5, 8.5))
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 66)
    ax.axis("off")

    ax.text(50, 64, "Settlement Feasibility & Fee Engine — Architecture",
            ha="center", fontsize=15, fontweight="bold", color="#1a1a1a")

    # Inputs
    box(ax, 2, 52, 18, 8, "client.json\n(SDA, drafts, ledger)", INPUT, 9)
    box(ax, 2, 42, 18, 8, "offer.json\n(settlement, balances)", INPUT, 9)
    box(ax, 2, 32, 18, 8, "creditor_rules.json\n(floors, flags, fees)", INPUT, 9)

    box(ax, 26, 42, 16, 8, "models.py\nloaders +\ndate helpers", "#eef1f4", 9)

    # Engine entry
    box(ax, 48, 43, 18, 8, "engine.py\nevaluate_offer()", DECIDE, 11, bold=True)

    # Solver core
    box(ax, 46, 30, 22, 8, "solver.py\nk-loop · shape select\n· best by fee-earliness", CORE, 9, bold=True)

    # Core helpers row
    box(ax, 2, 17, 17, 8, "shapes.py\nfloors/token/tiers\neven · balloon · staircase", CORE, 8.5)
    box(ax, 21, 17, 16, 8, "fee.py\nsuffix-min\nfront-loading", CORE, 8.5)
    box(ax, 39, 17, 16, 8, "simulator.py\ndate-by-date\nledger sim", CORE, 8.5)
    box(ax, 57, 17, 16, 8, "cadence.py\nEOM / clamp\ncadence dates", CORE, 8.5)
    box(ax, 75, 17, 15, 8, "rounding.py\nround-half-up", CORE, 8.5)

    # Decision diamond (as box) + outputs
    box(ax, 75, 43, 22, 9, "feasible?", DECIDE, 11, bold=True)
    box(ax, 75, 30, 22, 8, "Part 1: schedule\n+ pay_shape_used", OUTPUT, 9, bold=True)
    box(ax, 75, 4, 22, 9, "Part 2: minima.py\nbinary-search lump &\nincrement + guardrails", OUTPUT, 9, bold=True)
    box(ax, 46, 4, 22, 8, "Result.to_dict()\nJSON", OUTPUT, 9, bold=True)

    # Arrows: inputs -> models -> engine
    for yy in (56, 46, 36):
        arrow(ax, 20, yy, 26, 46)
    arrow(ax, 42, 46, 48, 47)
    arrow(ax, 57, 43, 57, 38)            # engine -> solver
    arrow(ax, 66, 47, 75, 47.5)          # engine -> feasible?

    # solver uses helpers
    for cx in (10.5, 29, 47, 65, 82.5):
        arrow(ax, 56, 30, cx, 25, color="#7f8c8d", lw=1.1, ls=(0, (4, 3)))

    # feasible? -> outputs
    arrow(ax, 86, 43, 86, 38)            # yes -> schedule
    ax.text(87.5, 40.5, "yes", fontsize=8, color="#2e7d32")
    arrow(ax, 86, 43, 86, 13)            # no -> minima
    ax.text(87.5, 27, "no", fontsize=8, color="#c0392b")
    arrow(ax, 75, 33, 68, 9)             # schedule -> result
    arrow(ax, 75, 8, 68, 8)              # minima -> result

    # Legend
    handles = [
        mpatches.Patch(color=INPUT, label="Inputs"),
        mpatches.Patch(color=CORE, label="Core algorithm"),
        mpatches.Patch(color=DECIDE, label="Control flow"),
        mpatches.Patch(color=OUTPUT, label="Outputs"),
    ]
    ax.legend(handles=handles, loc="lower left", fontsize=8.5, frameon=True, ncol=4,
              bbox_to_anchor=(0.0, -0.02))

    fig.tight_layout()
    fig.savefig(OUT, dpi=150, bbox_inches="tight", facecolor="white")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
