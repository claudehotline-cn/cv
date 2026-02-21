# Auth E2E Tests

These tests are intended to run inside the `agent-test` container so they can use
the Docker Compose service network (`agent-api`, `agent-auth`, `rag-service`).

Run command:

```bash
docker exec agent-test pytest -q -c /workspace/agent-test/pytest.ini -m auth_integration /workspace/agent-test/tests/integration/auth/test_auth_e2e.py
```
