"""
Tests for Swarm Mode — orchestrator, stage transitions, state management.
"""

import pytest
import os
import json
import tempfile
import shutil
from unittest.mock import MagicMock
from swarm import (
    SwarmOrchestrator, SwarmTask, SwarmStage, StageResult,
    STAGE_LABELS, STAGE_DESCRIPTIONS, STAGE_ORDER,
    PLANNER_SYSTEM_PROMPT, EXECUTOR_SYSTEM_PROMPT,
    VALIDATOR_SYSTEM_PROMPT, FINISHER_SYSTEM_PROMPT,
    INVARIANT_CHECKER_SYSTEM_PROMPT,
)
from utils import parse_invariants_md, format_invariants_prompt, format_invariant_check_prompt


# ================================================================
# Fixtures
# ================================================================

@pytest.fixture
def temp_dir():
    """Create a temporary directory for swarm state."""
    d = tempfile.mkdtemp()
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def mock_agent():
    """Create a mock Agent for the orchestrator."""
    agent = MagicMock()
    agent.api_key = "test_key"
    agent.base_url = "https://fake.api"
    agent.model = "test-model"
    agent.temperature = 0.7
    agent.max_tokens = 500
    agent.timeout = 30.0
    agent.user = MagicMock()
    return agent


@pytest.fixture
def orchestrator(mock_agent, temp_dir):
    """Create a SwarmOrchestrator with a mock agent."""
    return SwarmOrchestrator(agent=mock_agent, base_dir=temp_dir)


@pytest.fixture
def mock_llm_response():
    """Create a mock LLM response string."""
    return "# Plan\n\n## 1. Task Summary\nTest plan content\n\n## 2. Steps\n1. Step one\n2. Step two"


def _mock_run_agent(orchestrator, response_text):
    """Replace _run_agent on the orchestrator with a fake that returns a fixed response.

    Returns a cleanup function. Call it after the test to restore the original.
    """
    original = orchestrator._run_agent

    async def _fake_run_agent(system_prompt, user_message, invariants=None):
        return response_text

    orchestrator._run_agent = _fake_run_agent
    return lambda: setattr(orchestrator, '_run_agent', original)


class _RunAgentMock:
    """Context manager for mocking _run_agent."""
    def __init__(self, orchestrator, response_text):
        self._orchestrator = orchestrator
        self._response = response_text
        self._original = None

    def __enter__(self):
        self._original = self._orchestrator._run_agent
        async def fake(sp, um, invariants=None):
            return self._response
        self._orchestrator._run_agent = fake
        return self

    def __exit__(self, *args):
        self._orchestrator._run_agent = self._original
        return False


# ================================================================
# Test Enums and Constants
# ================================================================

class TestSwarmStage:
    """Tests for SwarmStage enum."""

    def test_stage_values(self):
        assert SwarmStage.IDLE.value == "idle"
        assert SwarmStage.PLANNING.value == "planning"
        assert SwarmStage.PLAN_REVIEW.value == "plan_review"
        assert SwarmStage.EXECUTING.value == "executing"
        assert SwarmStage.EXEC_REVIEW.value == "exec_review"
        assert SwarmStage.VALIDATING.value == "validating"
        assert SwarmStage.VALIDATION_REVIEW.value == "validation_review"
        assert SwarmStage.FINISHING.value == "finishing"
        assert SwarmStage.DONE.value == "done"
        assert SwarmStage.PAUSED.value == "paused"
        assert SwarmStage.CANCELLED.value == "cancelled"

    def test_stage_labels(self):
        assert STAGE_LABELS[SwarmStage.IDLE] == "Готово"
        assert STAGE_LABELS[SwarmStage.DONE] == "Завершено"
        assert STAGE_LABELS[SwarmStage.PAUSED] == "Пауза"

    def test_stage_order(self):
        assert STAGE_ORDER[0] == SwarmStage.IDLE
        assert STAGE_ORDER[-1] == SwarmStage.DONE
        assert SwarmStage.PLANNING in STAGE_ORDER
        assert SwarmStage.PAUSED not in STAGE_ORDER


class TestSystemPrompts:
    """Tests for specialized agent system prompts."""

    def test_planner_prompt_exists(self):
        assert "Планировщик" in PLANNER_SYSTEM_PROMPT
        assert "Пошаговый план" in PLANNER_SYSTEM_PROMPT

    def test_executor_prompt_exists(self):
        assert "Исполнитель" in EXECUTOR_SYSTEM_PROMPT
        assert "Отчёт о выполнении" in EXECUTOR_SYSTEM_PROMPT

    def test_validator_prompt_exists(self):
        assert "Валидатор" in VALIDATOR_SYSTEM_PROMPT
        assert "Оценка соответствия" in VALIDATOR_SYSTEM_PROMPT

    def test_finisher_prompt_exists(self):
        assert "Финализатор" in FINISHER_SYSTEM_PROMPT
        assert "Итоговый отчёт" in FINISHER_SYSTEM_PROMPT


# ================================================================
# Test SwarmTask
# ================================================================

class TestSwarmTask:
    """Tests for SwarmTask dataclass."""

    def test_create_task(self):
        task = SwarmTask(task_id="test001", user_id="user1", description="Test task")
        assert task.task_id == "test001"
        assert task.user_id == "user1"
        assert task.description == "Test task"
        assert task.current_stage == SwarmStage.IDLE
        assert task.progress_pct == 0

    def test_to_dict(self):
        task = SwarmTask(task_id="test001", user_id="user1", description="Test")
        d = task.to_dict()
        assert d["task_id"] == "test001"
        assert d["current_stage"] == "idle"
        assert "stages" in d

    def test_from_dict(self):
        data = {
            "task_id": "test001", "user_id": "user1", "description": "Test",
            "current_stage": "idle", "stages": {},
            "created_at": "2024-01-01", "updated_at": "2024-01-01",
            "user_approved_plan": False, "user_approved_execution": False,
            "user_approved_validation": False,
        }
        task = SwarmTask.from_dict(data)
        assert task.task_id == "test001"
        assert task.current_stage == SwarmStage.IDLE

    def test_from_dict_with_stages(self):
        data = {
            "task_id": "test001", "user_id": "user1", "description": "Test",
            "current_stage": "plan_review",
            "stages": {"planning": {"stage": "planning", "status": "completed",
                "summary": "Plan ready", "artifacts": ["plan.md"],
                "full_output": "# Plan content", "started_at": "", "completed_at": "", "error": None}},
            "created_at": "", "updated_at": "",
            "user_approved_plan": False, "user_approved_execution": False,
            "user_approved_validation": False,
        }
        task = SwarmTask.from_dict(data)
        assert task.current_stage == SwarmStage.PLAN_REVIEW
        assert "planning" in task.stages
        assert task.stages["planning"].status == "completed"

    def test_progress_pct(self):
        task = SwarmTask(task_id="test", user_id="u1", description="d")
        assert task.progress_pct == 0
        task.current_stage = SwarmStage.PLAN_REVIEW
        assert task.progress_pct == 20
        task.current_stage = SwarmStage.DONE
        assert task.progress_pct == 100


# ================================================================
# Test StageResult
# ================================================================

class TestStageResult:
    """Tests for StageResult dataclass."""

    def test_create_stage_result(self):
        result = StageResult(stage=SwarmStage.PLANNING, status="completed",
                             summary="Plan created", artifacts=["plan.md"])
        assert result.stage == SwarmStage.PLANNING
        assert result.status == "completed"

    def test_to_dict(self):
        result = StageResult(stage=SwarmStage.EXECUTING, status="running", summary="Running...")
        d = result.to_dict()
        assert d["stage"] == "executing"
        assert d["status"] == "running"

    def test_from_dict(self):
        data = {"stage": "planning", "status": "completed", "summary": "Done",
                "artifacts": [], "full_output": "", "started_at": "", "completed_at": "", "error": None}
        result = StageResult.from_dict(data)
        assert result.stage == SwarmStage.PLANNING
        assert result.status == "completed"


# ================================================================
# Test SwarmOrchestrator — Task Lifecycle
# ================================================================

class TestOrchestratorLifecycle:
    """Tests for the full swarm task lifecycle."""

    @pytest.mark.asyncio
    async def test_create_task(self, orchestrator):
        task = await orchestrator.create_task("Build a web app", "user1")
        assert task.task_id is not None
        assert task.user_id == "user1"
        assert task.current_stage == SwarmStage.IDLE

    @pytest.mark.asyncio
    async def test_list_tasks(self, orchestrator):
        await orchestrator.create_task("Task 1", "user1")
        await orchestrator.create_task("Task 2", "user1")
        await orchestrator.create_task("Task 3", "user2")
        assert len(orchestrator.list_tasks()) == 3
        assert len(orchestrator.list_tasks(user_id="user1")) == 2

    @pytest.mark.asyncio
    async def test_start_planning(self, orchestrator, mock_llm_response):
        task = await orchestrator.create_task("Build a web app", "user1")
        with _RunAgentMock(orchestrator, mock_llm_response):
            task = await orchestrator.start_planning(task.task_id)
        assert task.current_stage == SwarmStage.PLAN_REVIEW
        assert task.stages["planning"].status == "completed"
        assert task.stages["planning"].full_output

    @pytest.mark.asyncio
    async def test_approve_plan(self, orchestrator, mock_llm_response):
        task = await orchestrator.create_task("Build a web app", "user1")
        with _RunAgentMock(orchestrator, mock_llm_response):
            await orchestrator.start_planning(task.task_id)
        task = await orchestrator.approve_plan(task.task_id)
        assert task.user_approved_plan is True

    @pytest.mark.asyncio
    async def test_reject_plan(self, orchestrator, mock_llm_response):
        task = await orchestrator.create_task("Build a web app", "user1")
        with _RunAgentMock(orchestrator, mock_llm_response):
            await orchestrator.start_planning(task.task_id)
        task = await orchestrator.reject_plan(task.task_id)
        assert task.current_stage == SwarmStage.IDLE
        assert task.user_approved_plan is False

    @pytest.mark.asyncio
    async def test_full_lifecycle(self, orchestrator, mock_llm_response):
        task = await orchestrator.create_task("Build a web app", "user1")
        async def fake_run(sp, um, invariants=None): return mock_llm_response
        orig = orchestrator._run_agent
        orchestrator._run_agent = fake_run
        try:
            task = await orchestrator.start_planning(task.task_id)
        finally:
            orchestrator._run_agent = orig
        assert task.current_stage == SwarmStage.PLAN_REVIEW
        await orchestrator.approve_plan(task.task_id)
        orchestrator._run_agent = fake_run
        try:
            task = await orchestrator.start_execution(task.task_id)
        finally:
            orchestrator._run_agent = orig
        assert task.current_stage == SwarmStage.EXEC_REVIEW
        await orchestrator.approve_execution(task.task_id)
        orchestrator._run_agent = fake_run
        try:
            task = await orchestrator.start_validation(task.task_id)
        finally:
            orchestrator._run_agent = orig
        assert task.current_stage == SwarmStage.VALIDATION_REVIEW
        await orchestrator.approve_validation(task.task_id)
        orchestrator._run_agent = fake_run
        try:
            task = await orchestrator.start_finishing(task.task_id)
        finally:
            orchestrator._run_agent = orig
        assert task.current_stage == SwarmStage.DONE

    @pytest.mark.asyncio
    async def test_cannot_skip_stages(self, orchestrator):
        task = await orchestrator.create_task("Test", "user1")
        with pytest.raises(ValueError, match="plan_review"):
            await orchestrator.start_execution(task.task_id)

    @pytest.mark.asyncio
    async def test_cannot_execute_without_plan_approval(self, orchestrator, mock_llm_response):
        task = await orchestrator.create_task("Test", "user1")
        with _RunAgentMock(orchestrator, mock_llm_response):
            task = await orchestrator.start_planning(task.task_id)
        with pytest.raises(ValueError, match="approved"):
            await orchestrator.start_execution(task.task_id)


# ================================================================
# Test SwarmOrchestrator — Pause / Resume / Retry / Cancel
# ================================================================

class TestOrchestratorControls:
    """Tests for pause, resume, retry, cancel."""

    @pytest.mark.asyncio
    async def test_pause_and_resume(self, orchestrator, mock_llm_response):
        task = await orchestrator.create_task("Test", "user1")
        async def fake_run(sp, um, invariants=None): return mock_llm_response
        orig = orchestrator._run_agent
        orchestrator._run_agent = fake_run
        try:
            task = await orchestrator.start_planning(task.task_id)
        finally:
            orchestrator._run_agent = orig
        assert task.current_stage == SwarmStage.PLAN_REVIEW
        task = await orchestrator.pause(task.task_id)
        assert task.current_stage == SwarmStage.PAUSED
        task = await orchestrator.resume(task.task_id)
        assert task.current_stage == SwarmStage.PLAN_REVIEW

    @pytest.mark.asyncio
    async def test_cannot_pause_done_task(self, orchestrator):
        task = await orchestrator.create_task("Test", "user1")
        task.current_stage = SwarmStage.DONE
        orchestrator._save_task(task)
        with pytest.raises(ValueError, match="Cannot pause"):
            await orchestrator.pause(task.task_id)

    @pytest.mark.asyncio
    async def test_cannot_resume_non_paused(self, orchestrator):
        task = await orchestrator.create_task("Test", "user1")
        with pytest.raises(ValueError, match="not paused"):
            await orchestrator.resume(task.task_id)

    @pytest.mark.asyncio
    async def test_retry_stage(self, orchestrator, mock_llm_response):
        task = await orchestrator.create_task("Test", "user1")
        with _RunAgentMock(orchestrator, mock_llm_response):
            await orchestrator.start_planning(task.task_id)
        assert task.current_stage == SwarmStage.PLAN_REVIEW
        task = await orchestrator.retry_stage(task.task_id)
        assert task.current_stage == SwarmStage.IDLE

    @pytest.mark.asyncio
    async def test_cancel(self, orchestrator, mock_llm_response):
        task = await orchestrator.create_task("Test", "user1")
        with _RunAgentMock(orchestrator, mock_llm_response):
            await orchestrator.start_planning(task.task_id)
        task = await orchestrator.cancel(task.task_id)
        assert task.current_stage == SwarmStage.CANCELLED

    @pytest.mark.asyncio
    async def test_cannot_cancel_done(self, orchestrator):
        task = await orchestrator.create_task("Test", "user1")
        task.current_stage = SwarmStage.DONE
        orchestrator._save_task(task)
        with pytest.raises(ValueError, match="Cannot cancel"):
            await orchestrator.cancel(task.task_id)


# ================================================================
# Test SwarmOrchestrator — Persistence
# ================================================================

class TestOrchestratorPersistence:
    """Tests for save/load task state."""

    @pytest.mark.asyncio
    async def test_save_and_reload(self, orchestrator, mock_llm_response, temp_dir, mock_agent):
        task = await orchestrator.create_task("Persist test", "user1")
        task_id = task.task_id
        with _RunAgentMock(orchestrator, mock_llm_response):
            await orchestrator.start_planning(task_id)
        state_file = os.path.join(temp_dir, task_id, "state.json")
        assert os.path.exists(state_file)
        orch2 = SwarmOrchestrator(agent=mock_agent, base_dir=temp_dir)
        orch2.load_all_tasks()
        loaded_task = orch2.get_task(task_id)
        assert loaded_task is not None
        assert loaded_task.current_stage == SwarmStage.PLAN_REVIEW
        assert loaded_task.stages["planning"].status == "completed"

    @pytest.mark.asyncio
    async def test_delete_task(self, orchestrator, temp_dir):
        task = await orchestrator.create_task("Delete test", "user1")
        task_dir = os.path.join(temp_dir, task.task_id)
        assert os.path.exists(task_dir)
        await orchestrator.delete_task(task.task_id)
        assert not os.path.exists(task_dir)
        assert task.task_id not in orchestrator._tasks


# ================================================================
# Test SwarmOrchestrator — Error Handling
# ================================================================

class TestOrchestratorErrors:
    """Tests for error handling in the orchestrator."""

    @pytest.mark.asyncio
    async def test_llm_timeout_returns_to_idle(self, orchestrator):
        task = await orchestrator.create_task("Test", "user1")
        # Directly assign a function that raises
        async def raising_agent(sp, um, invariants=None):
            raise Exception("Request timed out")
        original = orchestrator._run_agent
        orchestrator._run_agent = raising_agent
        try:
            with pytest.raises(Exception, match="Request timed out"):
                await orchestrator.start_planning(task.task_id)
        finally:
            orchestrator._run_agent = original
        task = orchestrator.get_task(task.task_id)
        assert task.current_stage == SwarmStage.IDLE
        assert task.stages["planning"].status == "failed"

    @pytest.mark.asyncio
    async def test_llm_http_error(self, orchestrator):
        task = await orchestrator.create_task("Test", "user1")
        async def raising_agent(sp, um, invariants=None):
            raise Exception("HTTP error 401: Invalid API key")
        original = orchestrator._run_agent
        orchestrator._run_agent = raising_agent
        try:
            with pytest.raises(Exception, match="HTTP error 401"):
                await orchestrator.start_planning(task.task_id)
        finally:
            orchestrator._run_agent = original

    @pytest.mark.asyncio
    async def test_task_not_found(self, orchestrator):
        with pytest.raises(ValueError, match="not found"):
            await orchestrator.start_planning("nonexistent")


# ================================================================
# Test SwarmOrchestrator — Summary Extraction
# ================================================================

class TestSummaryExtraction:
    """Tests for _extract_summary utility."""

    def test_short_text(self):
        result = SwarmOrchestrator._extract_summary("Short summary here.", 100)
        assert result == "Short summary here."

    def test_long_text_truncated(self):
        text = "A" * 500
        result = SwarmOrchestrator._extract_summary(text, 100)
        assert len(result) <= 103
        assert result.endswith("...")

    def test_empty_text(self):
        assert SwarmOrchestrator._extract_summary("") == ""
        assert SwarmOrchestrator._extract_summary(None) == ""

    def test_markdown_headers_skipped(self):
        result = SwarmOrchestrator._extract_summary("# Header\n\nActual content here.", 200)
        assert "Actual content" in result


# ================================================================
# Test Invariant Parsing (utils.py)
# ================================================================

class TestInvariantParsing:
    """Tests for parse_invariants_md and format functions."""

    def test_parse_simple_bullets(self):
        content = """# Invariants

- Use FastAPI only
- All writes must be atomic
- Python 3.9+
"""
        result = parse_invariants_md(content)
        assert len(result) == 3
        assert result[0] == "Use FastAPI only"
        assert result[1] == "All writes must be atomic"
        assert result[2] == "Python 3.9+"

    def test_parse_numbered_list(self):
        content = """# Invariants

1. First rule
2. Second rule
"""
        result = parse_invariants_md(content)
        assert len(result) == 2
        assert result[0] == "First rule"
        assert result[1] == "Second rule"

    def test_parse_asterisk_bullets(self):
        content = "* Rule A\n* Rule B"
        result = parse_invariants_md(content)
        assert len(result) == 2

    def test_parse_empty(self):
        assert parse_invariants_md("") == []
        assert parse_invariants_md(None) == []
        assert parse_invariants_md("# Header only\n") == []

    def test_parse_multiline_bullets(self):
        content = """- First rule with continuation
  on the next line
- Second rule
"""
        result = parse_invariants_md(content)
        assert len(result) == 2
        assert "continuation on the next line" in result[0]

    def test_format_invariants_prompt(self):
        invariants = ["Rule 1", "Rule 2"]
        prompt = format_invariants_prompt(invariants)
        assert "ИНВАРИАНТЫ" in prompt
        assert "Rule 1" in prompt
        assert "Rule 2" in prompt
        assert "ОБЯЗАН" in prompt

    def test_format_invariants_prompt_empty(self):
        assert format_invariants_prompt([]) == ""

    def test_format_invariant_check_prompt(self):
        invariants = ["Use FastAPI", "Python 3.9+"]
        prompt = format_invariant_check_prompt(invariants, "Some artifact text")
        assert "Use FastAPI" in prompt
        assert "Some artifact text" in prompt
        assert "violations" in prompt
        assert "JSON" in prompt

    def test_invariant_checker_prompt_exists(self):
        assert "Проверяющий инвариантов" in INVARIANT_CHECKER_SYSTEM_PROMPT
        assert "нарушений" in INVARIANT_CHECKER_SYSTEM_PROMPT


# ================================================================
# Test SwarmTask — Invariants
# ================================================================

class TestSwarmTaskInvariants:
    """Tests for invariants in SwarmTask."""

    def test_task_with_invariants(self):
        task = SwarmTask(
            task_id="test", user_id="u1", description="d",
            invariants=["Rule 1", "Rule 2"],
        )
        assert task.invariants == ["Rule 1", "Rule 2"]
        assert task.stage_checks == {}

    def test_to_dict_with_invariants(self):
        task = SwarmTask(
            task_id="test", user_id="u1", description="d",
            invariants=["Rule A"],
        )
        task.stage_checks["planning"] = {"passed": True, "violations": []}
        d = task.to_dict()
        assert d["invariants"] == ["Rule A"]
        assert "planning" in d["stage_checks"]
        assert d["stage_checks"]["planning"]["passed"] is True

    def test_from_dict_with_invariants(self):
        data = {
            "task_id": "test", "user_id": "u1", "description": "d",
            "current_stage": "idle", "stages": {},
            "created_at": "", "updated_at": "",
            "user_approved_plan": False, "user_approved_execution": False,
            "user_approved_validation": False,
            "invariants": ["Rule X", "Rule Y"],
            "stage_checks": {"planning": {"passed": False, "violations": [{"invariant": "Rule X", "reason": "Bad"}]}},
        }
        task = SwarmTask.from_dict(data)
        assert task.invariants == ["Rule X", "Rule Y"]
        assert "planning" in task.stage_checks
        assert task.stage_checks["planning"]["passed"] is False

    def test_progress_pct_with_failed(self):
        task = SwarmTask(task_id="test", user_id="u1", description="d")
        task.current_stage = SwarmStage.FAILED
        assert task.progress_pct == 0

        # With completed planning
        task.stages["planning"] = StageResult(stage=SwarmStage.PLANNING, status="completed")
        assert task.progress_pct == 20

        # With completed execution
        task.stages["execution"] = StageResult(stage=SwarmStage.EXECUTING, status="completed")
        assert task.progress_pct == 50

        # With completed validation
        task.stages["validation"] = StageResult(stage=SwarmStage.VALIDATING, status="completed")
        assert task.progress_pct == 75


# ================================================================
# Test SwarmOrchestrator — Invariant Checks
# ================================================================

class TestOrchestratorInvariants:
    """Tests for invariant checking in the orchestrator."""

    @pytest.mark.asyncio
    async def test_create_task_with_invariants(self, orchestrator):
        task = await orchestrator.create_task(
            "Build something", "user1",
            invariants=["Use FastAPI", "Python 3.9+"],
        )
        assert task.invariants == ["Use FastAPI", "Python 3.9+"]
        assert len(task.invariants) == 2

    @pytest.mark.asyncio
    async def test_check_invariants_passes(self, orchestrator):
        """When the check LLM returns no violations."""
        # Mock _run_agent to return a passing JSON for the check call
        call_count = [0]

        async def fake_run(sp, um, invariants=None):
            call_count[0] += 1
            if call_count[0] == 1:
                return "# Plan\n\nValid plan content."
            else:
                return '{"violations": []}'

        original = orchestrator._run_agent
        orchestrator._run_agent = fake_run
        try:
            task = await orchestrator.create_task(
                "Test", "user1",
                invariants=["Rule 1"],
            )
            # start_planning calls _run_agent twice: plan + check
            task = await orchestrator.start_planning(task.task_id)
        finally:
            orchestrator._run_agent = original

        assert task.current_stage == SwarmStage.PLAN_REVIEW
        assert task.stages["planning"].status == "completed"
        assert "planning" in task.stage_checks
        assert task.stage_checks["planning"]["passed"] is True

    @pytest.mark.asyncio
    async def test_check_invariants_fails(self, orchestrator):
        """When the check LLM reports violations, stage goes to FAILED."""
        call_count = [0]

        async def fake_run(sp, um, invariants=None):
            call_count[0] += 1
            if call_count[0] == 1:
                return "# Plan with Django (violates FastAPI invariant)"
            else:
                return '{"violations": [{"invariant": "Use FastAPI", "reason": "Plan uses Django instead of FastAPI"}]}'

        original = orchestrator._run_agent
        orchestrator._run_agent = fake_run
        try:
            task = await orchestrator.create_task(
                "Test", "user1",
                invariants=["Use FastAPI"],
            )
            task = await orchestrator.start_planning(task.task_id)
        finally:
            orchestrator._run_agent = original

        assert task.current_stage == SwarmStage.FAILED
        assert task.stages["planning"].status == "failed"
        assert "planning" in task.stage_checks
        assert task.stage_checks["planning"]["passed"] is False
        assert len(task.stage_checks["planning"]["violations"]) == 1
        assert task.stage_checks["_failed_stage"] == "planning"
        assert "FastAPI" in task.stages["planning"].error

    @pytest.mark.asyncio
    async def test_restart_stage_from_failed(self, orchestrator, mock_llm_response):
        """restart_stage should clear the failed stage and go back."""
        task = await orchestrator.create_task(
            "Test", "user1",
            invariants=["Rule 1"],
        )

        # Simulate a failed planning
        task.stages["planning"] = StageResult(
            stage=SwarmStage.PLANNING, status="failed",
        )
        task.stage_checks["planning"] = {"passed": False, "violations": [{"invariant": "R1", "reason": "bad"}]}
        task.stage_checks["_failed_stage"] = "planning"
        task.current_stage = SwarmStage.FAILED
        orchestrator._save_task(task)

        task = await orchestrator.restart_stage(task.task_id)
        assert task.current_stage == SwarmStage.IDLE
        assert task.stages["planning"].status == "pending"
        assert task.stages["planning"].full_output == ""
        assert "planning" not in task.stage_checks
        assert "_failed_stage" not in task.stage_checks

    @pytest.mark.asyncio
    async def test_restart_stage_not_failed_raises(self, orchestrator, mock_llm_response):
        task = await orchestrator.create_task("Test", "user1")
        with pytest.raises(ValueError, match="FAILED"):
            await orchestrator.restart_stage(task.task_id)

    @pytest.mark.asyncio
    async def test_retry_from_failed_uses_restart(self, orchestrator, mock_llm_response):
        """retry_stage from FAILED should delegate to restart_stage."""
        task = await orchestrator.create_task(
            "Test", "user1",
            invariants=["Rule 1"],
        )
        task.stages["planning"] = StageResult(stage=SwarmStage.PLANNING, status="failed")
        task.stage_checks["_failed_stage"] = "planning"
        task.current_stage = SwarmStage.FAILED
        orchestrator._save_task(task)

        task = await orchestrator.retry_stage(task.task_id)
        assert task.current_stage == SwarmStage.IDLE

    @pytest.mark.asyncio
    async def test_no_invariants_skips_check(self, orchestrator):
        """When task has no invariants, check returns passed without LLM call."""
        task = await orchestrator.create_task("Test", "user1", invariants=[])

        result = await orchestrator._check_invariants([], "some text", "planning")
        assert result["passed"] is True
        assert result["violations"] == []

    @pytest.mark.asyncio
    async def test_reject_plan_clears_invariant_check(self, orchestrator, mock_llm_response):
        """Rejecting a plan should clear its invariant check."""
        task = await orchestrator.create_task("Test", "user1")
        task.stages["planning"] = StageResult(stage=SwarmStage.PLANNING, status="completed")
        task.stage_checks["planning"] = {"passed": True, "violations": []}
        task.current_stage = SwarmStage.PLAN_REVIEW
        orchestrator._save_task(task)

        task = await orchestrator.reject_plan(task.task_id)
        assert task.current_stage == SwarmStage.IDLE
        assert "planning" not in task.stage_checks

    @pytest.mark.asyncio
    async def test_resume_from_failed(self, orchestrator, mock_llm_response):
        """Resume from FAILED should go back to appropriate review stage."""
        task = await orchestrator.create_task("Test", "user1")
        task.stages["planning"] = StageResult(stage=SwarmStage.PLANNING, status="completed")
        task.current_stage = SwarmStage.FAILED
        orchestrator._save_task(task)

        task = await orchestrator.resume(task.task_id)
        assert task.current_stage == SwarmStage.PLAN_REVIEW

    @pytest.mark.asyncio
    async def test_execution_invariant_fail(self, orchestrator):
        """Execution stage should also go to FAILED on invariant violation."""
        call_count = [0]

        async def fake_run(sp, um, invariants=None):
            call_count[0] += 1
            if call_count[0] == 1:
                return "# Plan\n\nValid plan."
            elif call_count[0] == 2:
                return '{"violations": []}'  # plan check passes
            elif call_count[0] == 3:
                return "# Execution with forbidden framework"
            else:
                return '{"violations": [{"invariant": "Use FastAPI", "reason": "Used Flask"}]}'

        original = orchestrator._run_agent
        orchestrator._run_agent = fake_run
        try:
            task = await orchestrator.create_task(
                "Test", "user1",
                invariants=["Use FastAPI"],
            )
            # Planning
            task = await orchestrator.start_planning(task.task_id)
            assert task.current_stage == SwarmStage.PLAN_REVIEW
            await orchestrator.approve_plan(task.task_id)

            # Execution — should fail invariant check
            task = await orchestrator.start_execution(task.task_id)
        finally:
            orchestrator._run_agent = original

        assert task.current_stage == SwarmStage.FAILED
        assert task.stages["execution"].status == "failed"
        assert task.stage_checks["execution"]["passed"] is False
        assert task.stage_checks["_failed_stage"] == "execution"

    @pytest.mark.asyncio
    async def test_failed_stage_label(self):
        """FAILED stage should have proper labels."""
        assert STAGE_LABELS[SwarmStage.FAILED] == "Ошибка инвариантов"
        assert "инвариантов" in STAGE_DESCRIPTIONS[SwarmStage.FAILED]
