# 发布到 PyPI（准备清单）

当前状态：**未注册**。PyPI 上 `esml` 名字目前为空（2026-10-30 检查），但需要
owner 的 PyPI 账号才能创建项目和配置 trusted publisher。

## 一次性配置（owner 操作）

1. 注册/登录 <https://pypi.org>。
2. 创建项目 `esml`（或首次上传时自动创建）。
3. 项目 → Settings → Publishing → 添加 **Trusted Publisher**：
   - Owner: `ai4energy`
   - Repository: `esml-python`
   - Workflow: `publish.yml`
   - Environment: `pypi`
4. 不需要长期 API token；GitHub Actions 用 OIDC 换取短期凭据。

## 每次发版

1. 更新 `pyproject.toml` 的 `version` 与 `src/esml/__init__.py` 的 `__version__`。
2. 提交、打 tag、推送：
   ```bash
   git tag -a vX.Y.Z -m "esml-python vX.Y.Z"
   git push origin vX.Y.Z
   ```
3. 在 GitHub 创建 Release（published）→ 触发 `publish.yml`。
4. 或在 Actions 里手动 `workflow_dispatch`。
5. 验证（干净环境）：
   ```bash
   python -m venv /tmp/esml-check && . /tmp/esml-check/bin/activate
   pip install esml==X.Y.Z
   python -c "import esml; print(esml.__version__)"
   ```

## 在注册前

- `pip install git+https://github.com/ai4energy/esml-python@vX.Y.Z` 已经可用。
- 本仓 `CI` 在 Python 3.9–3.13 上跑协议测试；集成测试需 `ESML_BIN`。
