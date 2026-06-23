---
name: testing-mock-patterns
description: Use ONLY when writing or modifying tests in test_agent.py or test_swarm.py. Covers mock setup, _RunAgentMock context manager, AsyncMock vs MagicMock, invariant test patterns.
---

# Testing Mock Patterns

## Cardinal Rules

1. **NEVER mock `httpx.AsyncClient` directly.** Always mock `orchestrator._run_agent` (or `Agent.send_message` / `Agent.send_message_without_history` for agent tests).
2. **`_run_agent` takes exactly 3 positional args**: `system_prompt, user_message, invariants=None`. Always include `invariants=None` in mock functions, even when unused.
3. **`httpx.Response.json()` is synchronous** — mock with `MagicMock`, not `AsyncMock`.
4. **Invariant checks double LLM calls per stage.** `_check_invariants()` internally calls `_run_agent()` a second time — account for this when mocking.

## Mocking `_run_agent` in Swarm Tests

### Pattern A: Context manager (`_RunAgentMock`) — Preferred

Defined in `test_swarm.py:73-89`:
```python
class _RunAgentMock:
    """Context manager for mocking _run_agent."""
    def __init__(self, orchestrator, response_text):
        self._orchestrator = orchestrator
        self._response = response_text

    def __enter__(self):
        self._original = self._orchestrator._run_agent
        async def fake(sp, um, invariants=None):
            return self._response
        self._orchestrator._run_agent = fake
        return self

    def __exit__(self, *args):
        self._orchestrator._run_agent = self._original
        return False

# Usage:
with _RunAgentMock(orchestrator, "# Plan\n\nTest content"):
    task = await orchestrator.start_planning(task_id)
# _run_agent restored automatically
```

### Pattern B: Try/finally with cleanup function

Defined in `test_swarm.py:59-70`:
```python
def _mock_run_agent(orchestrator, response_text):
    original = orchestrator._run_agent
    async def _fake_run_agent(system_prompt, user_message, invariants=None):
        return response_text
    orchestrator._run_agent = _fake_run_agent
    return lambda: setattr(orchestrator, '_run_agent', original)

# Usage:
restore = _mock_run_agent(orchestrator, response_text)
try:
    task = await orchestrator.start_planning(task_id)
finally:
    restore()
```

### Pattern C: Inline for error tests

```python
async def raising_agent(sp, um, invariants=None):
    raise Exception("Request timed out")

original = orchestrator._run_agent
orchestrator._run_agent = raising_agent
try:
    task = await orchestrator.start_planning(task.task_id)
finally:
    orchestrator._run_agent = original
# assert task.stages["planning"].status == "failed"
```

## Fixtures

### `mock_user` (test_agent.py:12-33)
Real `User` dataclass with `MagicMock` for save methods:
```python
@pytest.fixture
def mock_user():
    user = User(user_id="test_user_001", name="Test User",
                preferences={"STYLE": "formal", "CONSTRAINTS": "", "CONTEXT": ""},
                working_memory=[], agents={"agent001": {"name": "default", ...}},
                current_agent_id="agent001")
    user.save_agents = MagicMock()
    user.save_working_memory = MagicMock()
    user.save_preferences = MagicMock()
    return user
```

### `mock_agent` (test_swarm.py:34-44)
Fully mocked via `MagicMock`:
```python
@pytest.fixture
def mock_agent():
    agent = MagicMock()
    agent.api_key = "test_key"
    agent.base_url = "https://fake.api"
    agent.model = "test-model"
    agent.temperature = 0.7
    agent.max_tokens = 500
    agent.timeout = 30.0
    agent.user = MagicMock()
    return agent
```

### `orchestrator` (test_swarm.py:47-50)
Uses `mock_agent` and `temp_dir`:
```python
@pytest.fixture
def orchestrator(mock_agent, temp_dir):
    return SwarmOrchestrator(agent=mock_agent, base_dir=temp_dir)
```

### `temp_dir` (test_swarm.py:25-30)
Creates a temp dir, cleans up with `shutil.rmtree`:
```python
@pytest.fixture
def temp_dir():
    d = tempfile.mkdtemp()
    yield d
    shutil.rmtree(d, ignore_errors=True)
```

## AsyncMock vs MagicMock

- `MagicMock` — for synchronous methods (callables, attribute access)
- `AsyncMock` — for async generators and `async def` methods (used in agent tests, e.g., mocking `agent.send_message_without_history`)
- Swarm tests mock `orchestrator._run_agent` by replacing it with an `async def` function — neither `MagicMock` nor `AsyncMock` is needed for this

## Invariant Check Double-Call

When testing a stage method that includes invariant checking, the mock must handle **two** `_run_agent` calls:
1. The stage LLM call (e.g., planning agent)
2. The invariant checker LLM call

If using a fixed response mock, both calls return the same text — ensure the response can be parsed as valid invariant check JSON by the checker. Alternatively, mock with a function that returns different values based on the system prompt.

## Test Classes (test_swarm.py)

| Class | Purpose | Tests |
|-------|---------|-------|
| `TestSwarmStage` | Enum values and labels | 3 |
| `TestSystemPrompts` | Prompt string assertions | 4 |
| `TestSwarmTask` | Task dataclass + serialization | ~5 |
| `TestSwarmOrchestrator` | Stage transitions, persistence | ~10 |
| `TestUserInputFlow` | Question-answer flow | ~5 |
| `TestSwarmActions` | Approve/reject/pause/resume/cancel | ~8 |
| `TestOrchestratorErrors` | Error handling (timeout, HTTP) | 3 |
| `TestSummaryExtraction` | `_extract_summary` utility | 4 |
| `TestInvariantParsing` | `parse_invariants_md` + format functions | ~7 |
| `TestOrchestratorInvariants` | Full invariant enforcement flow | 8 |
| `TestInvariantEdgeCases` | Empty content, malformed JSON | ~4 |
| `TestSwarmArtifacts` | Artifact file creation/paths | ~3 |

## Test Classes (test_agent.py)

| Class | Purpose | Tests |
|-------|---------|-------|
| `TestAgentInit` | Agent initialization, agent_id generation | 3 |
| `TestAgentMessage` | `send_message` with mock HTTP | 4 |
| `TestAgentStreaming` | `send_message_stream` | 3 |
| `TestAgentHistory` | History management + reset | 3 |
| `TestUserMethods` | User dataclass methods, `to_dict` | 3 |
| `TestWorkingMemory` | Working memory operations | 3 |

## Error Testing Pattern

Stage methods **do not re-raise exceptions** — they catch them and store in `stage.error`. In tests:

```python
async def raising_agent(sp, um, invariants=None):
    raise Exception("Request timed out")

# Replace _run_agent, call stage method
# Assert: task.stages["planning"].status == "failed"
# Assert: task.stages["planning"].error contains "timed out"
# Assert: no exception raised (method returns normally)
```

Also verify `_assert_stage` raises `ValueError` for wrong-stage transitions:
```python
with pytest.raises(ValueError, match="not found"):
    await orchestrator.start_planning("nonexistent")
```

## Running Tests

```bash
# All tests (85 total)
python -m pytest test_agent.py test_swarm.py -v

# Swarm only (66 tests)
python -m pytest test_swarm.py -v

# Single class
python -m pytest test_swarm.py::TestOrchestratorInvariants -v

# Single test
python -m pytest test_swarm.py::TestOrchestratorInvariants::test_execution_invariant_fail -v
```
