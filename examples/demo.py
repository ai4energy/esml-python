"""最小示例：一次性 solve 与 simulate（学术版即可运行）。

    export ESML_BIN=/path/to/esml
    python examples/demo.py
"""

from __future__ import annotations

import pathlib

from esml import simulate, solve

DOC = pathlib.Path(__file__).with_name("decay.esml")


def main() -> None:
    steady = solve(DOC, system="S")
    print(f"稳态: {steady.values}")

    traj = simulate(DOC, (0.0, 1.0), 20, observe=["m.x"], system="S")
    print(f"x(1) = {traj.series['m.x'][-1]:.6f}")


if __name__ == "__main__":
    main()
