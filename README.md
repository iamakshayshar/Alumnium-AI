# Alumnium + Selenium pytest framework with CI

This repository contains a minimal pytest framework that integrates:
- Selenium WebDriver (via webdriver-manager)
- Alumnium.ai (`alumnium`) for AI-driven test steps (`al.do`, `al.check`, `al.get`)
- ReportPortal integration (via `pytest-reportportal`) with screenshots on failure
- GitHub Actions CI workflow to run tests on `ubuntu-latest` with Chrome

**Important**
- Do NOT commit your API keys. Set LLM/provider keys (e.g. `OPENAI_API_KEY`) and ReportPortal secrets via repository secrets or environment variables in CI.
- This repo is an example scaffold. Adjust timeouts, locators, and Alumnium instructions to suit your application.

## Quickstart (local)
1. Create a venv and install:
```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```
2. Set LLM/provider keys and ReportPortal secrets as env vars.
3. Run tests:
```bash
pytest -q
```
