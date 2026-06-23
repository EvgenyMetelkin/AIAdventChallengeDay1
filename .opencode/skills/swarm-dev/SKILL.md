---
name: swarm-dev
description: Use ONLY when working with SwarmOrchestrator, SwarmTask, SwarmStage, stage transitions, swarm tests, _run_agent mocking, or adding/modifying swarm orchestrator code in swarm.py or test_swarm.py.
---

# Swarm Orchestrator Development

## Stage Lifecycle

12 stages: `IDLE → PLANNING → PLAN_REVIEW → EXECUTING → EXEC_REVIEW → VALIDATING → VALIDATION_REVIEW → FINISHING → DONE` + `PAUSED`, `CANCELLED`, `FAILED`.

`STAGE_ORDER` (defined at `swarm.py:44`) excludes PAUSED/CANCELLED/FAILED.

`STAGE_LABELS` and `STAGE_DESCRIPTIONS` dicts map each stage to Russian labels/descriptions.

### Transition methods (on `SwarmOrchestrator`)

| Method | From stage | To stage | Notes |
|--------|-----------|----------|-------|
| `start_planning(task_id)` | IDLE | PLANNING | Generates clarifying questions first; falls back to direct planning if no questions |
| `approve_plan(task_id)` | PLAN_REVIEW | EXECUTING | |
| `reject_plan(task_id)` | PLAN_REVIEW | IDLE | Clears planning stage_checks |
| `start_execution(task_id)` | EXECUTING → EXEC_REVIEW | | LLM runs executor prompt |
| `approve_execution(task_id)` | EXEC_REVIEW | VALIDATING | |
| `reject_execution(task_id)` | EXEC_REVIEW | PLAN_REVIEW | |
| `start_validation(task_id)` | VALIDATING → VALIDATION_REVIEW | | LLM runs validator prompt |
| `approve_validation(task_id)` | VALIDATION_REVIEW | FINISHING | |
| `reject_validation(task_id)` | VALIDATION_REVIEW | EXEC_REVIEW | |
| `start_finishing(task_id)` | FINISHING → DONE / FAILED | | LLM runs finisher prompt |
| `pause(task_id)` | any active → PAUSED | | Cannot pause DONE/CANCELLED/PAUSED |
| `resume(task_id)` | PAUSED/FAILED → appropriate REVIEW | | Computes target from completed stages |
| `cancel(task_id)` | any → CANCELLED | | Cannot cancel DONE/CANCELLED |
| `retry_stage(task_id)` | REVIEW stages → pre-stage | | Clears invariant checks for retried + downstream stages |
| `restart_stage(task_id)` | FAILED or active with `_failed_stage` → pre-stage | | Clears ALL downstream stages AND their invariant checks |
| `delete_task(task_id)` | any | deleted | Removes from disk via `shutil.rmtree` |
| `handle_user_input(task_id, text)` | planning (waiting_for_answers) | | Feeds answers sequentially via `question_index` |
| `refine_plan(task_id, text)` | PLAN_REVIEW | PLANNING | Regenerates plan with user refinements |

## Data Model

### SwarmTask (`swarm.py:294`)
- `task_id: str` — uuid4 hex 8 chars
- `user_id: str`
- `description: str`
- `current_stage: SwarmStage` — defaults to IDLE
- `stages: Dict[str, StageResult]` — keys: "planning", "execution", "validation", "finishing"
- `invariants: List[str]` — frozen copy of invariants.md at creation time
- `stage_checks: Dict[str, Any]` — per-stage invariant check results; `_failed_stage` records which stage failed
- `progress_pct: int` — computed from `current_stage` (IDLE=0, PLANNING=10, PLAN_REVIEW=20, EXECUTING=35, EXEC_REVIEW=50, VALIDATING=60, VALIDATION_REVIEW=75, FINISHING=90, DONE=100)
- `pending_questions: List[str]`, `answers: List[str]`, `question_index: int`, `waiting_for_answers: bool`

### StageResult (`swarm.py:270`)
- `stage: SwarmStage`
- `status: str` — "running", "completed", "failed", "pending"
- `summary: str`
- `artifacts: List[str]` — file paths
- `full_output: str` — complete LLM response
- `error: Optional[str]`
- `started_at: str`, `completed_at: str`

### Serialization
- `SwarmTask.to_dict()` / `SwarmTask.from_dict(data)` — used by `_save_task` / `load_all_tasks`
- `_save_task()` uses atomic write (`.tmp + os.replace()`) at `swarm.py:1327`

## Specialized System Prompts

6 prompts defined at `swarm.py:91-263`:

```
PLANNER_SYSTEM_PROMPT — creates structured implementation plans
EXECUTOR_SYSTEM_PROMPT — follows plan step-by-step, creates files
VALIDATOR_SYSTEM_PROMPT — checks execution against plan, gives 0-100% score
INVARIANT_CHECKER_SYSTEM_PROMPT — strict JSON response ({"violations": [...]})
FINISHER_SYSTEM_PROMPT — compiles final human-readable report
QUESTION_GENERATOR_SYSTEM_PROMPT — generates 3-5 clarifying questions as JSON
```

All prompts are imported in `test_swarm.py` for assertion tests (`TestSystemPrompts`).

## `_run_agent` — the key internal method

Located at `swarm.py:1198`. Signature:
```python
async def _run_agent(self, system_prompt: str, user_message: str, invariants: Optional[List[str]] = None) -> str
```

- Injects invariants into system prompt via `format_invariants_prompt(invariants)` if provided
- Makes direct `httpx` POST to `{base_url}/chat/completions` (does NOT use `Agent` class methods)
- Uses `self._agent` (the injected agent) for model, temperature, max_tokens, timeout, api_key, base_url
- Raises `Exception` on timeout, HTTP errors, network errors
- **This is the method mocked in all tests** — never mock `httpx.AsyncClient` directly

## Invariant Integration in Stages

Every stage method (except approval/rejection) follows this pattern:
```python
invs = self._ensure_invariants(task)
output = await self._run_agent(SYSTEM_PROMPT, user_msg, invariants=invs)
# ... save output ...
check_result = await self._check_invariants(invs, output, stage_name)
if not check_result["passed"]:
    task.current_stage = SwarmStage.FAILED
    task.stage_checks["_failed_stage"] = stage_name
```

- `_ensure_invariants(task)` reloads from `invariants.md` if `task.invariants` is empty (at `swarm.py:1241`)
- `_check_invariants(invs, artifact_text, stage_name)` makes a separate LLM call with `INVARIANT_CHECKER_SYSTEM_PROMPT` (at `swarm.py:1268`)
- Checker failures (timeout, JSON parse error) are **non-blocking**: returns `passed: True` with `checker_error` or `parse_error`
- Exception handlers in stage methods **do not re-raise** — they set `status: "failed"` and `error` field on the stage, then return the task

## Question-Answer Flow

1. `start_planning` calls `_generate_questions(task)` — LLM generates 3-5 clarifying questions
2. If questions returned: `task.waiting_for_answers = True`, `task.pending_questions = questions`
3. Frontend calls `handle_user_input(task_id, text)` — feeds answers one-by-one via `question_index`
4. When all answered (`question_index >= len(pending_questions)`): calls `_generate_plan(task)` to build final plan
5. If no questions generated (empty or parse failure): falls back to direct planning via `PLANNER_SYSTEM_PROMPT`

## `restart_stage` vs `retry_stage`

- **`restart_stage`**: clears the failed stage AND all downstream stages (status→"pending", artifacts cleared). Uses `stage_rewind` dict. Works from FAILED or from active stages with `_failed_stage` set.
- **`retry_stage`**: only clears `stage_checks` for the retried stage and downstream. Moves back to the pre-review target (e.g., PLAN_REVIEW→IDLE, EXEC_REVIEW→PLAN_REVIEW).

## Persistence

- Tasks saved atomically via `_save_task()` in `state.json`
- `load_all_tasks()` reads all `state.json` files from `base_dir` subdirectories
- Artifacts stored as markdown files in stage subdirectories: `planning/plan.md`, `execution/execution_report.md`, `validation/validation_report.md`, `done/final_report.md`
