# Test Suite

This directory contains the test suite for ComfyUI MCP Server.

## Running Tests

### Install Test Dependencies

```bash
pip install -r requirements.txt
```

### Run All Tests

```bash
pytest tests/ -v
```

### Run Specific Test Files

```bash
# Basic smoke tests
pytest tests/test_basic.py -v

# Asset registry tests
pytest tests/test_asset_registry.py -v

# Job tools tests
pytest tests/test_job_tools.py -v

# Model categorization tests
pytest tests/test_model_categorization.py -v

# Edge case tests
pytest tests/test_edge_cases.py -v
```

### Run with Coverage

```bash
pip install pytest-cov
pytest tests/ --cov=. --cov-report=html
```

## Test Structure

- `test_basic.py` - Basic smoke tests for critical paths
- `test_asset_registry.py` - Unit tests for AssetRegistry
- `test_job_tools.py` - Tests for job management tools
- `test_model_categorization.py` - Tests for categorized model detection
- `test_edge_cases.py` - Edge case and boundary condition tests

## Test Categories

### Unit Tests
- Test individual components in isolation
- Use mocks for external dependencies
- Fast execution

### Integration Tests
- Test component interactions
- May require ComfyUI running (marked with `@pytest.mark.integration`)
- Slower execution

## Manual Test Checklist

Before v1 release, manually verify:

- [ ] Generate image with default model
- [ ] Generate image with custom model
- [ ] Generate audio/song
- [ ] View image inline (thumb mode)
- [ ] Poll long-running job
- [ ] Cancel queued job
- [ ] List assets with limit
- [ ] List assets filtered by workflow
- [ ] Get metadata for image asset
- [ ] Get metadata for audio asset
- [ ] Queue multiple jobs concurrently
- [ ] Restart server (assets expire naturally)
- [ ] ComfyUI down (graceful errors)
- [ ] Invalid prompt_id (clear error)
- [ ] Special characters in prompt
- [ ] Very long prompt (>1000 chars)

## Continuous Integration

Tests should be run in CI/CD pipeline:

```yaml
# .github/workflows/test.yml
name: Tests
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
        with:
          python-version: '3.10'
      - run: pip install -r requirements.txt
      - run: pytest tests/ -v --ignore=tests/test_integration.py
```
