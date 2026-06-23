---
name: invariants
description: Use ONLY when working with invariant enforcement, invariants.md files, parse_invariants_md, _check_invariants, format_invariants_prompt, or adding invariant-aware features to swarm stages.
---

# Invariant Enforcement System

## Overview

Invariants are hard constraints enforced during swarm task execution. Each stage's output is checked against invariants by a separate LLM call. Violations block the pipeline and require user intervention.

## File Format: `users/{uid}/invariants.md`

Two supported formats (parsed by `parse_invariants_md()` at `utils.py:62`):

### Bullet list (preferred)
```markdown
# Invariants

- Код должен быть на Python 3.9+
- Все функции должны иметь type hints
- Имена файлов должны быть в snake_case
```

### Plain text fallback (one rule per line)
```markdown
Код должен быть на Python 3.9+
Все функции должны иметь type hints
```

If no bullet markers found, `parse_invariants_md` falls back to treating each non-empty, non-header line as an invariant.

## Key Functions (utils.py)

### `parse_invariants_md(content: str) -> List[str]` (line 62)
- Parses bullet list (`- `, `* `, `1. `, `1) `) with multi-line continuation support
- Continuation lines (indented) are folded into the preceding bullet
- Fallback: each non-empty non-header line becomes an invariant
- Returns empty list for empty/whitespace-only content

### `format_invariants_prompt(invariants: List[str]) -> str` (line 116)
Injects invariants into agent system prompts. Output format:
```
## ИНВАРИАНТЫ (ЖЁСТКИЕ ОГРАНИЧЕНИЯ)

Ниже перечислены инварианты, которые ты ОБЯЗАН соблюдать...
1. First invariant
2. Second invariant
```
Returns empty string if invariants list is empty.

### `format_invariant_check_prompt(invariants: List[str], artifact_text: str) -> str` (line 143)
Creates the prompt for the invariant checker LLM. Requests JSON output:
```json
{"violations": [{"invariant": "rule text", "reason": "why violated"}]}
```
Or: `{"violations": []}` when no violations.

## Invariant Lifecycle

### 1. Creation (web.py `POST /api/swarm/create`)
```
load invariants from users/{uid}/invariants.md
→ parse_invariants_md(content)
→ create SwarmTask with invariants=list
→ frozen in state.json
```
Invariants are **frozen at creation**. Editing `invariants.md` via UI only affects new tasks.

### 2. Per-stage enforcement (swarm.py)
Each stage method (planning, execution, validation, finishing):

```python
# Step 1: Ensure invariants loaded
invs = self._ensure_invariants(task)

# Step 2: Run primary agent with invariants injected
output = await self._run_agent(SYSTEM_PROMPT, user_msg, invariants=invs)

# Step 3: Save output to disk (always happens)

# Step 4: Run invariant checker (separate LLM call)
check_result = await self._check_invariants(invs, output, stage_name)

# Step 5: Handle violations
if not check_result["passed"]:
    task.stages[stage_name].status = "failed"
    task.stages[stage_name].error = "Нарушены инварианты: ..."
    task.current_stage = SwarmStage.FAILED
    task.stage_checks["_failed_stage"] = stage_name
```

### 3. `_ensure_invariants(task: SwarmTask) -> List[str]` (swarm.py:1241)
- Returns `task.invariants` if non-empty
- If empty: tries to reload from `invariants.md` via `parse_invariants_md()`
- On reload: updates `task.invariants` and saves task
- On failure: returns whatever `task.invariants` currently is

### 4. `_check_invariants(invariants, artifact_text, stage_name) -> dict` (swarm.py:1268)
- Returns immediately `{"passed": True, "violations": []}` if no invariants
- Calls `_run_agent(INVARIANT_CHECKER_SYSTEM_PROMPT, check_prompt, invariants=None)`
- Parses JSON response, extracts `violations` list
- `passed = len(violations) == 0`

**Non-blocking error handling:**
- LLM call fails (timeout, HTTP error): returns `{"passed": True, "violations": [], "checker_error": str(e)}`
- JSON parse failure: returns `{"passed": True, "violations": [], "parse_error": str(e)}`
- In both cases, `passed: True` — the pipeline proceeds despite checker failure

### 5. Recovery from violations
- Task enters `FAILED` state with `_failed_stage` recorded
- User fixes invariants or artifact, then calls `restart_stage(task_id)`
- `restart_stage` clears the failed stage AND all downstream stages
- `retry_stage` clears only invariant checks for the retried stage and downstream

## API Endpoints

| Endpoint | Purpose |
|----------|---------|
| `GET /api/invariants` | Read current user's invariants (raw markdown) |
| `PUT /api/invariants` | Update invariants (atomic write via `_atomic_write_text`) |
| `POST /api/swarm/create` | Creates task with frozen invariants |

## SwarmOrchestrator Stage Map for Invariants

| Stage method | Calls `_ensure_invariants` | Calls `_check_invariants` |
|--------------|---------------------------|--------------------------|
| `start_planning` (via `_finalize_planning`) | Yes | Yes (planning) |
| `start_execution` | Yes | Yes (execution) |
| `start_validation` | Yes | Yes (validation) |
| `start_finishing` | Yes | Yes (finishing) |

Each stage has its own `stage_checks[stage_name]` dict with invariant check results.

## `INVARIANT_CHECKER_SYSTEM_PROMPT` (swarm.py:192)
Russian-language prompt instructing the checker to:
- Be strict but fair
- Report only real violations
- Each violation must be specific (which invariant, what text, why)
- Return empty list if no violations
- Respond strictly in JSON format without markdown wrapping

## Testing Invariants

Test files covering invariants:
- `test_swarm.py::TestInvariantParsing` — `parse_invariants_md`, bullet parsing, fallback
- `test_swarm.py::TestOrchestratorInvariants` — full enforcement flow, FAILED state, restart/retry
- `test_swarm.py::TestInvariantEdgeCases` — empty content, malformed JSON checker responses

Key test patterns:
```python
# Test that invalid output triggers invariant failure
async def fake_planning(sp, um, invariants=None):
    return "Some output that violates invariants"

async def fake_checker(sp, um, invariants=None):
    return '{"violations": [{"invariant": "Rule 1", "reason": "Violated"}]}'

# First call: planning, second call: checker
# With _RunAgentMock returning a single value, both get same text
# Better: use a function mock that returns different values
```

When testing invariant failures, remember that `_check_invariants` calls `_run_agent` — you need to mock the checker's response separately from the stage agent's response.
