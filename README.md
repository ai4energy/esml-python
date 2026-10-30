# ESML Python 客户端

ESML 引擎的 **MIT** Python 客户端。公开面是**一次性调用**：`solve` / `simulate`
每次启动一个 `esml` 进程，读取 `esml.solve/v1` / `esml.simulate/v1` JSON，
调用之间不保留状态。

常驻数字孪生（DTIL）会话 `Session`（`predict` / `snapshot` / `restore`）属于
**商业版**能力，需要商业版引擎；学术版会在 `esml session` 入口响亮拒绝。

```python
from esml import simulate, solve

steady = solve("plant.esml", system="Plant")
print(steady.values)

traj = simulate("plant.esml", (0.0, 60.0), 60, observe=["tank.T"])
print(traj.series["tank.T"][-1])
```

## 安装

```bash
pip install git+https://github.com/ai4energy/esml-python
```

还需要**引擎二进制**：

- 免费学术版（展平未知量 ≤ 16,384，非商业用途）：
  <https://github.com/ai4energy/esml/releases>
- 放到 `PATH`，或设 `ESML_BIN=/path/to/esml`，或传 `binary="/path/to/esml"`。
  显式给出的路径不可执行时**响亮报错**，绝不静默换一个二进制。

## API

一次性调用（学术版即可用）：

| 调用 | 含义 |
| --- | --- |
| `solve(path, *, system=None, libraries=(), binary=None, timeout=120.0)` | 稳态求解 → `SolveOutput(values, unknowns, system, raw)` |
| `simulate(path, tspan=(0.0, 1.0), steps=100, observe=None, *, …)` | 一次性时间积分 → `SimulateOutput(t, series, steps, system, raw)` |

`observe` 只接受变量路径；空列表在客户端拒绝，未知/重复路径由引擎拒绝。

商业版常驻会话（DTIL）：

| 调用 | 含义 |
| --- | --- |
| `Session(path, *, system=None, libraries=(), binary=None, timeout=None)` | 常驻会话 |
| `solve()` / `simulate(tspan, steps, observe=None)` / `predict(horizon, …)` | 求解、链式积分、非推进预测 |
| `set_param` / `set_params` / `set_state` / `set_states` / `clear_state` | 热参数与状态注入 |
| `snapshot()` / `restore(snapshot)` / `info()` / `close()` | 快照恢复、状态与生命周期 |

错误类型：`EsmlError`（引擎报错，含 `.op` / `.raw`）、`EsmlProtocolError`
（非 `esml.*/v1` 信封）、`EsmlTimeout`、`EsmlClosed`、`EsmlBinaryNotFound`。

## 许可

- **本包**：MIT（见 `LICENSE`）。
- **ESML 引擎**：**商业软件，不是 MIT**（见 `LICENSE-ENGINE.md`）。学术版（≤ 16,384 未知量、不含 DTIL）
  非商业用途免费；商业用途需取得商业许可（mingtao.li@gmail.com）。本包不含引擎
  代码，只通过公开 JSON 协议调用引擎。

## 开发

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[test]"
pytest -q                                      # 协议测试（假引擎）
ESML_BIN=/path/to/esml pytest -q tests/test_integration.py
```

协议测试使用 `tests/fake_esml.py`；真机集成测试只在设置 `ESML_BIN` 时运行。
