# ESML Python 客户端

ESML 引擎的 **MIT** Python 客户端。公开面是**一次性调用**：`solve` / `simulate`
每次启动一个 `esml` 进程，读取 `esml.solve/v1` / `esml.simulate/v1` JSON，
调用之间不保留状态。

0.4.0 起，客户端**彻底开放引擎的命令行**：除了一次性求解，还包括前验证器
（`check` / `check-units`）、计算任务（`tasks`）、结构报告与展平转储
（`inspect` / `dump`），以及一个**不做任何限制**的逃生口 `run_cli`。

学术版（免费、非商业）的**唯一**限制是**总未知量 ≤ 16,384**；其余能力
（常驻 DTIL 会话、加密等）由引擎二进制按 edition 自己决定——客户端**不做
功能白名单**，它只负责把引擎的答案如实端出来。

```python
from esml import simulate, solve

steady = solve("plant.esml", system="Plant")
print(steady.values)
print(steady.units.get("tank.T"), steady.meta["unitCoverage"])

traj = simulate("plant.esml", (0.0, 60.0), 60, observe=["tank.T"])
print(traj.series["tank.T"][-1], traj.units.get("tank.T"))
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

### 全功能命令行

| 调用 | 含义 |
| --- | --- |
| `run_cli(args, *, input=None, timeout=120.0, binary=None)` | 任意子命令的**逃生口** → `CLIResult(stdout, stderr, code, args)` |
| `check(path, *, libraries=(), binary=None, timeout=120.0)` | 前验证 → 报告数组 `list[dict]`（`file` / `well_formed` / `summary` / `findings`） |
| `check_units(path, *, libraries=(), binary=None, timeout=120.0)` | 单位检查 → 同形状的报告数组 |
| `tasks(path, *, system=None, libraries=(), jobs=None, binary=None, timeout=300.0)` | 跑 `<computeTasks>` → `TasksOutput{tasks, raw}` |
| `inspect(path, *, system=None, libraries=(), …)` | 结构报告（文本，原样返回 stdout） |
| `dump(path, *, system=None, libraries=(), …)` | 展平转储（文本，原样返回 stdout） |
| `version(binary=None)` | 引擎版本号（如 `1.9.0`），或 `None` |

`run_cli` **不限制子命令**：`session`、`encrypt` 等商业功能也放行，由二进制
自己判断本 edition 支不支持。**非零退出不是异常**——`run_cli` 原样返回退出码；
只有超时抛 `EsmlTimeout`。哪个退出码算失败，由上表的 typed 包装各自判定。

`check` / `check_units` 在**引擎非零退出**或**报告里有 `error` 级 finding**
时抛 `EsmlError`（`code="check.failed"` / `"check-units.failed"`），报告仍在
`err.raw["reports"]` 里；`warning` 不判红。之所以不只看退出码：引擎的
`check-units --json` 路径总是退 0，即使它找到了错误。

`tasks` 返回 `TasksOutput`，其 `tasks` 是 `TaskResult{name, kind, target, units,
meta, outcome, raw}` 列表。信封必须声明 `apiVersion == "esml.tasks/v1"`，否则
抛 `EsmlProtocolError`；`ok=false` 抛 `EsmlError`（整个信封在 `err.raw`）。

> 命名提醒：包级的 `esml.tasks` 是**函数**（它盖住了同名子模块）。
> 要拿模块请 `from esml.tasks import tasks`。

### 一次性调用

| 调用 | 含义 |
| --- | --- |
| `solve(path, *, system=None, libraries=(), binary=None, timeout=120.0)` | 稳态求解 → `SolveOutput(values, unknowns, system, raw, units, meta)` |
| `simulate(path, tspan=(0.0, 1.0), steps=100, observe=None, *, …)` | 一次性时间积分 → `SimulateOutput(t, series, steps, system, raw, units, meta)` |

`units` 是路径 → SI 量纲表达式的映射（模型未声明单位时缺项）；`meta` 含
`engineVersion`、`docHash`（源文件 SHA-256）、`durationMs`、`converged`、
`iterations`、`residual`、`residualTolerance` 与 `unitCoverage`。字段语义见
[结果契约](https://docs.ai4energy.cn/esml/results)。

引擎版本：`units` / `meta` 需引擎 **>= 1.8.1**；`iterations` / `residual` /
`EsmlError.code` 需引擎 **>= 1.9.0**。旧引擎缺少的字段会表现为空的 `meta` /
`units` 或 `None`，客户端不伪造。`check` / `check-units` 的 `--json` 面与
`tasks` 的 `esml.tasks/v1` 面同样取决于引擎是否提供：**引擎没有这面时，客户端
会响亮报 `EsmlProtocolError`，而不是给一个空结果**。而 `esml.solve/v1` /
`esml.simulate/v1` / `esml.session/v1` 这三张信封只有**商业引擎**给。

`observe` 只接受变量路径；空列表在客户端拒绝，未知/重复路径由引擎拒绝。

### 学术版的未知量锁

```python
from esml import MAX_UNKNOWNS          # 16_384
```

`solve` 的信封带 `unknowns` 时，客户端会核对它：超过 `MAX_UNKNOWNS` 就抛
`EsmlError`（`code` 与 `kind` 都是 `academic_limit`），消息写明
「学术版上限 16384，商业版请用商业二进制/客户端」。

锁的**权威在引擎**：学术版引擎本来就会拒绝这样的模型，客户端这道闸只是把
拒绝说得更清楚。`tasks` 与 `simulate` 的信封**不报总未知量**，所以那里由
学术版引擎在 flatten / solve 时自己拒绝——客户端不替引擎编一个结论。

### 商业版常驻会话（DTIL）

| 调用 | 含义 |
| --- | --- |
| `Session(path, *, system=None, libraries=(), binary=None, timeout=None)` | 常驻会话 |
| `solve()` / `simulate(tspan, steps, observe=None)` / `predict(horizon, …)` | 求解、链式积分、非推进预测 |
| `set_param` / `set_params` / `set_state` / `set_states` / `clear_state` | 热参数与状态注入 |
| `snapshot()` / `restore(snapshot)` / `info()` / `close()` | 快照恢复、状态与生命周期 |

`Session.solve()` 返回 `SolveResult(values, …, units, meta)`；`simulate` /
`predict` 返回 `Trajectory(…, units, meta)`；字段与一次性契约一致。

错误类型：`EsmlError`（引擎报错，含 `.op` / `.raw`，以及 `esml.error/v1`
的 `.code` / `.kind` / `.hint` / `.doc_hash`）、`EsmlProtocolError`
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

> 真机集成测试要的是**商业引擎**：它验的是 `esml.solve/v1` /
> `esml.simulate/v1` / `esml.session/v1` 这套 JSON 信封。开源（MIT）引擎只提供
> 人读的命令行（`check` / `check-units` / `inspect` / `dump` / `tasks`），`solve`
> 即便带 `--json` 也只吐文本错误——于是 `tests/test_integration.py` 在开源引擎上
> 会失败，**这是预期的，不是客户端的 bug**（main 上同样失败）。用开源引擎时，
> 能真机验的是 `check` / `check_units` / `inspect` / `dump` / `version` 这几条。
