"""
Swarm Mode — Orchestrator for multi-agent sequential task execution.

Stages: Planning → Execution → Validation → Done
Each stage uses a specialized agent. Transitions require user confirmation.
State is persisted to filesystem for pause/resume support.
"""

import os
import json
import uuid
import logging
from enum import Enum
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger(__name__)


# ============================================================
# Stage definitions
# ============================================================

class SwarmStage(Enum):
    """Stages of the swarm process."""
    IDLE = "idle"
    PLANNING = "planning"           # LLM is generating the plan
    PLAN_REVIEW = "plan_review"     # Waiting for user to approve/reject plan
    EXECUTING = "executing"         # LLM is implementing
    EXEC_REVIEW = "exec_review"     # Waiting for user review
    VALIDATING = "validating"       # LLM is validating results
    VALIDATION_REVIEW = "validation_review"  # Waiting for user to review validation
    FINISHING = "finishing"         # LLM is compiling final report
    DONE = "done"                   # Task complete
    PAUSED = "paused"               # User paused
    CANCELLED = "cancelled"         # User cancelled


STAGE_ORDER = [
    SwarmStage.IDLE,
    SwarmStage.PLANNING,
    SwarmStage.PLAN_REVIEW,
    SwarmStage.EXECUTING,
    SwarmStage.EXEC_REVIEW,
    SwarmStage.VALIDATING,
    SwarmStage.VALIDATION_REVIEW,
    SwarmStage.FINISHING,
    SwarmStage.DONE,
]

STAGE_LABELS = {
    SwarmStage.IDLE: "Готово",
    SwarmStage.PLANNING: "Планирование",
    SwarmStage.PLAN_REVIEW: "Проверка плана",
    SwarmStage.EXECUTING: "Выполнение",
    SwarmStage.EXEC_REVIEW: "Проверка результата",
    SwarmStage.VALIDATING: "Валидация",
    SwarmStage.VALIDATION_REVIEW: "Оценка валидации",
    SwarmStage.FINISHING: "Финализация",
    SwarmStage.DONE: "Завершено",
    SwarmStage.PAUSED: "Пауза",
    SwarmStage.CANCELLED: "Отменено",
}

STAGE_DESCRIPTIONS = {
    SwarmStage.IDLE: "Задача создана, готова к запуску.",
    SwarmStage.PLANNING: "Анализирую запрос и составляю план...",
    SwarmStage.PLAN_REVIEW: "План готов. Ознакомьтесь и подтвердите для продолжения.",
    SwarmStage.EXECUTING: "Выполняю утверждённый план...",
    SwarmStage.EXEC_REVIEW: "Выполнение завершено. Оцените результат.",
    SwarmStage.VALIDATING: "Проверяю результат на соответствие плану...",
    SwarmStage.VALIDATION_REVIEW: "Валидация завершена. Ознакомьтесь с отчётом.",
    SwarmStage.FINISHING: "Формирую итоговый отчёт...",
    SwarmStage.DONE: "Задача выполнена!",
    SwarmStage.PAUSED: "Процесс приостановлен. Нажмите «Продолжить» когда будете готовы.",
    SwarmStage.CANCELLED: "Задача отменена.",
}


# ============================================================
# Specialized agent system prompts
# ============================================================

PLANNER_SYSTEM_PROMPT = """Ты — Агент-Планировщик в мультиагентной системе. Твоя задача — проанализировать запрос пользователя и составить подробный, исполнимый план реализации.

## Формат ответа

Ответ должен быть структурированным Markdown-документом:

# План: [Краткое название]

## 1. Краткое описание задачи
[Один абзац с описанием того, что нужно сделать]

## 2. Пошаговый план
Нумерованный список конкретных шагов. Каждый шаг должен быть достаточно конкретным, чтобы другой агент мог его выполнить.

## 3. Технологии и инструменты
Перечисли необходимые языки, фреймворки, библиотеки и инструменты.

## 4. Ожидаемые результаты
Список файлов или артефактов, которые будут созданы.

## 5. Критерии успеха
Как проверить, что задача выполнена.

## Правила
- Будь конкретным. Избегай расплывчатых формулировок.
- План должен быть исполним другим агентом без дополнительных уточнений.
- Оцени сложность и укажи допущения.
- Пиши на языке, понятном пользователю."""

EXECUTOR_SYSTEM_PROMPT = """Ты — Агент-Исполнитель в мультиагентной системе. Твоя задача — реализовать задачу ТОЧНО по предоставленному плану.

## Что ты получаешь
- Утверждённый план (ниже)
- Контекст с предыдущих этапов

## Что ты должен сделать
1. Следуй плану шаг за шагом
2. Создай все необходимые файлы и артефакты
3. Задокументируй, что сделано на каждом шаге
4. Если шаг невозможно выполнить, объясни причину и предложи альтернативы

## Формат ответа

# Отчёт о выполнении

## Созданные файлы
[Перечисли каждый файл с его назначением]

## Журнал выполнения шагов
[Для каждого шага плана: что сделано, что получено]

## Возникшие проблемы
[Описание проблем и способы их решения]

## Дальнейшие шаги
[Что должен проверить валидатор]

## Правила
- НЕ пропускай шаги. Отработай каждый пункт плана.
- Создавай полные, рабочие реализации.
- Указывай чёткие пути к файлам и описания содержимого.
- Если делаешь допущения, формулируй их явно."""

VALIDATOR_SYSTEM_PROMPT = """Ты — Агент-Валидатор в мультиагентной системе. Твоя задача — проверить, что результат выполнения соответствует утверждённому плану.

## Что ты получаешь
- Исходный план
- Отчёт о выполнении и результаты

## Что ты должен сделать
1. Сравни каждый шаг плана с тем, что было сделано
2. Оцени полноту выполнения (в процентах)
3. Перечисли найденные проблемы
4. Дай рекомендацию: переходить к завершению или повторить выполнение

## Формат ответа

# Отчёт о валидации

## Оценка соответствия: [0-100]%

## Пошаговая проверка
[Для каждого шага плана: статус (ПРОЙДЕН/НЕ ПРОЙДЕН/ЧАСТИЧНО), доказательства, заметки]

## Найденные проблемы
| № | Серьёзность | Описание | Рекомендация |
|---|-------------|----------|--------------|

## Общая оценка
[Резюмирующий абзац]

## Рекомендация
- [ ] ПРОДОЛЖИТЬ — все критерии выполнены
- [ ] ПОВТОРИТЬ выполнение — найдены существенные пробелы
- [ ] ЧАСТИЧНО готово — мелкие замечания, можно отразить в итоговом отчёте

## Правила
- Будь тщательным, но справедливым.
- Отмечай отсутствующие файлы, неполные реализации и отклонения от плана.
- Дай конкретные рекомендации, если требуется повтор."""

FINISHER_SYSTEM_PROMPT = """Ты — Агент-Финализатор в мультиагентной системе. Твоя задача — собрать все результаты в итоговый отчёт, понятный человеку.

## Что ты получаешь
- Исходный план
- Отчёт о выполнении
- Отчёт о валидации

## Что ты должен сделать
1. Обобщи весь процесс от планирования до валидации
2. Перечисли все результаты с описаниями
3. Отметь открытые вопросы из валидации
4. Вынеси итоговый вердикт

## Формат ответа

# Итоговый отчёт: [Название задачи]

## Краткое резюме
[2-3 предложения о том, что было сделано]

## Обзор процесса
- **План**: [краткое описание]
- **Выполнение**: [краткое описание]
- **Валидация**: [краткое описание] (Оценка: X%)

## Результаты
| Файл | Описание |
|------|----------|

## Открытые вопросы
[Список оставшихся проблем, если есть]

## Итоговый вердикт
[Одно предложение: успех, частичный успех или требуется доработка]

## Правила
- Пиши для человека. Будь ясным и профессиональным.
- Включай все существенные детали без лишнего многословия.
- Отчёт должен быть самостоятельным документом о выполненной задаче."""


# ============================================================
# Data model
# ============================================================

@dataclass
class StageResult:
    """Result of a single stage."""
    stage: SwarmStage
    status: str  # "running", "completed", "failed"
    summary: str = ""  # Short description for UI
    artifacts: List[str] = field(default_factory=list)  # File paths
    full_output: str = ""  # Complete LLM response
    started_at: str = ""
    completed_at: str = ""
    error: Optional[str] = None

    def to_dict(self) -> Dict:
        return {
            "stage": self.stage.value,
            "status": self.status,
            "summary": self.summary,
            "artifacts": self.artifacts,
            "full_output": self.full_output,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "StageResult":
        return cls(
            stage=SwarmStage(data["stage"]),
            status=data.get("status", "pending"),
            summary=data.get("summary", ""),
            artifacts=data.get("artifacts", []),
            full_output=data.get("full_output", ""),
            started_at=data.get("started_at", ""),
            completed_at=data.get("completed_at", ""),
            error=data.get("error"),
        )


@dataclass
class SwarmTask:
    """A single swarm task with all stage results."""
    task_id: str
    user_id: str
    description: str
    current_stage: SwarmStage = SwarmStage.IDLE
    stages: Dict[str, StageResult] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""
    user_approved_plan: bool = False
    user_approved_execution: bool = False
    user_approved_validation: bool = False

    def __post_init__(self):
        if not self.created_at:
            self.created_at = str(datetime.now())
        if not self.updated_at:
            self.updated_at = self.created_at
        if not self.task_id:
            self.task_id = uuid.uuid4().hex[:8]

    def to_dict(self) -> Dict:
        return {
            "task_id": self.task_id,
            "user_id": self.user_id,
            "description": self.description,
            "current_stage": self.current_stage.value,
            "stages": {k: v.to_dict() for k, v in self.stages.items()},
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "user_approved_plan": self.user_approved_plan,
            "user_approved_execution": self.user_approved_execution,
            "user_approved_validation": self.user_approved_validation,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "SwarmTask":
        stages = {}
        for k, v in data.get("stages", {}).items():
            stages[k] = StageResult.from_dict(v)
        return cls(
            task_id=data["task_id"],
            user_id=data["user_id"],
            description=data["description"],
            current_stage=SwarmStage(data["current_stage"]),
            stages=stages,
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
            user_approved_plan=data.get("user_approved_plan", False),
            user_approved_execution=data.get("user_approved_execution", False),
            user_approved_validation=data.get("user_approved_validation", False),
        )

    def get_stage_dir(self, stage: SwarmStage) -> str:
        """Get the filesystem directory for a stage's artifacts."""
        if stage == SwarmStage.IDLE:
            return ""
        stage_name = stage.value
        return stage_name

    @property
    def progress_pct(self) -> int:
        """Calculate overall progress (0-100)."""
        stage_progress = {
            SwarmStage.IDLE: 0,
            SwarmStage.PLANNING: 10,
            SwarmStage.PLAN_REVIEW: 20,
            SwarmStage.EXECUTING: 35,
            SwarmStage.EXEC_REVIEW: 50,
            SwarmStage.VALIDATING: 60,
            SwarmStage.VALIDATION_REVIEW: 75,
            SwarmStage.FINISHING: 90,
            SwarmStage.DONE: 100,
        }
        return stage_progress.get(self.current_stage, 0)


# ============================================================
# Swarm Orchestrator
# ============================================================

class SwarmOrchestrator:
    """Manages the lifecycle of swarm tasks.

    Each task goes through: Planning → Execution → Validation → Done.
    Between each stage, the user must confirm.
    State is persisted to disk for pause/resume support.
    """

    def __init__(self, agent, base_dir: str):
        """
        Args:
            agent: An Agent instance with API access (used for LLM calls).
            base_dir: Root directory for swarm state (e.g., 'users/{id}/swarms').
        """
        self._agent = agent
        self._base_dir = base_dir
        self._tasks: Dict[str, SwarmTask] = {}
        os.makedirs(base_dir, exist_ok=True)
        logger.info(f"SwarmOrchestrator initialized at {base_dir}")

    # ================================================================
    # Task lifecycle
    # ================================================================

    async def create_task(self, description: str, user_id: str) -> SwarmTask:
        """Create a new swarm task."""
        task = SwarmTask(
            task_id=uuid.uuid4().hex[:8],
            user_id=user_id,
            description=description,
        )
        self._tasks[task.task_id] = task
        self._save_task(task)
        logger.info(f"Created swarm task {task.task_id}: {description[:80]}...")
        return task

    async def start_planning(self, task_id: str) -> SwarmTask:
        """Start the Planning stage. Runs the Planner agent."""
        task = self._get_task(task_id)
        self._assert_stage(task, SwarmStage.IDLE)

        task.current_stage = SwarmStage.PLANNING
        task.stages["planning"] = StageResult(
            stage=SwarmStage.PLANNING,
            status="running",
            summary="Анализирую запрос и составляю план...",
            started_at=str(datetime.now()),
        )
        self._save_task(task)

        try:
            plan_output = await self._run_agent(
                PLANNER_SYSTEM_PROMPT,
                f"Create a detailed implementation plan for the following task:\n\n{task.description}",
            )
            # Save plan to file
            plan_dir = self._stage_dir(task, "planning")
            os.makedirs(plan_dir, exist_ok=True)
            plan_file = os.path.join(plan_dir, "plan.md")
            with open(plan_file, "w", encoding="utf-8") as f:
                f.write(plan_output)

            task.stages["planning"].status = "completed"
            task.stages["planning"].full_output = plan_output
            task.stages["planning"].artifacts = [plan_file]
            task.stages["planning"].summary = self._extract_summary(plan_output, 300)
            task.stages["planning"].completed_at = str(datetime.now())
            task.current_stage = SwarmStage.PLAN_REVIEW
            self._save_task(task)

            logger.info(f"Planning complete for task {task_id}")
        except Exception as e:
            task.stages["planning"].status = "failed"
            task.stages["planning"].error = str(e)
            task.current_stage = SwarmStage.IDLE
            self._save_task(task)
            raise

        return task

    async def approve_plan(self, task_id: str) -> SwarmTask:
        """User approves the plan. Move to Execution."""
        task = self._get_task(task_id)
        self._assert_stage(task, SwarmStage.PLAN_REVIEW)
        task.user_approved_plan = True
        self._save_task(task)
        return task

    async def reject_plan(self, task_id: str) -> SwarmTask:
        """User rejects the plan. Go back to IDLE for re-planning."""
        task = self._get_task(task_id)
        self._assert_stage(task, SwarmStage.PLAN_REVIEW)
        task.current_stage = SwarmStage.IDLE
        task.user_approved_plan = False
        # Clear planning stage so it can be re-run
        if "planning" in task.stages:
            task.stages["planning"].status = "pending"
            task.stages["planning"].summary = "План отклонён. Готов к повторному планированию."
        self._save_task(task)
        return task

    async def start_execution(self, task_id: str) -> SwarmTask:
        """Start the Execution stage. Runs the Executor agent."""
        task = self._get_task(task_id)
        self._assert_stage(task, SwarmStage.PLAN_REVIEW)
        if not task.user_approved_plan:
            raise ValueError("Plan must be approved before execution")

        task.current_stage = SwarmStage.EXECUTING
        task.stages["execution"] = StageResult(
            stage=SwarmStage.EXECUTING,
            status="running",
            summary="Выполняю утверждённый план...",
            started_at=str(datetime.now()),
        )
        self._save_task(task)

        try:
            plan_content = task.stages.get("planning", StageResult(SwarmStage.PLANNING, "completed")).full_output
            prompt = f"""Execute the following plan:

## Approved Plan
{plan_content}

## Instructions
Implement the plan step by step. Create all necessary files and artifacts.
Describe what you did for each step. Be thorough and follow the plan exactly.
If you cannot complete a step, explain why."""
            
            exec_output = await self._run_agent(EXECUTOR_SYSTEM_PROMPT, prompt)

            # Save execution report
            exec_dir = self._stage_dir(task, "execution")
            os.makedirs(exec_dir, exist_ok=True)
            exec_file = os.path.join(exec_dir, "execution_report.md")
            with open(exec_file, "w", encoding="utf-8") as f:
                f.write(exec_output)

            task.stages["execution"].status = "completed"
            task.stages["execution"].full_output = exec_output
            task.stages["execution"].artifacts = [exec_file]
            task.stages["execution"].summary = self._extract_summary(exec_output, 300)
            task.stages["execution"].completed_at = str(datetime.now())
            task.current_stage = SwarmStage.EXEC_REVIEW
            self._save_task(task)

            logger.info(f"Execution complete for task {task_id}")
        except Exception as e:
            task.stages["execution"].status = "failed"
            task.stages["execution"].error = str(e)
            task.current_stage = SwarmStage.PLAN_REVIEW
            self._save_task(task)
            raise

        return task

    async def approve_execution(self, task_id: str) -> SwarmTask:
        """User approves execution results. Move to Validation."""
        task = self._get_task(task_id)
        self._assert_stage(task, SwarmStage.EXEC_REVIEW)
        task.user_approved_execution = True
        self._save_task(task)
        return task

    async def reject_execution(self, task_id: str) -> SwarmTask:
        """User rejects execution results. Go back to PLAN_REVIEW for re-execution."""
        task = self._get_task(task_id)
        self._assert_stage(task, SwarmStage.EXEC_REVIEW)
        task.current_stage = SwarmStage.PLAN_REVIEW
        task.user_approved_execution = False
        if "execution" in task.stages:
            task.stages["execution"].status = "pending"
            task.stages["execution"].summary = "Результат отклонён. Готов к повторному выполнению."
        self._save_task(task)
        return task

    async def start_validation(self, task_id: str) -> SwarmTask:
        """Start the Validation stage. Runs the Validator agent."""
        task = self._get_task(task_id)
        self._assert_stage(task, SwarmStage.EXEC_REVIEW)
        if not task.user_approved_execution:
            raise ValueError("Execution must be approved before validation")

        task.current_stage = SwarmStage.VALIDATING
        task.stages["validation"] = StageResult(
            stage=SwarmStage.VALIDATING,
            status="running",
            summary="Проверяю результат на соответствие плану...",
            started_at=str(datetime.now()),
        )
        self._save_task(task)

        try:
            plan_content = task.stages.get("planning", StageResult(SwarmStage.PLANNING, "completed")).full_output
            exec_output = task.stages.get("execution", StageResult(SwarmStage.EXECUTING, "completed")).full_output

            prompt = f"""Validate the execution against the plan.

## Original Plan
{plan_content}

## Execution Report
{exec_output}

## Instructions
Compare each step in the plan against what was delivered in the execution report.
Rate completeness, identify gaps, and recommend whether to proceed."""

            val_output = await self._run_agent(VALIDATOR_SYSTEM_PROMPT, prompt)

            # Save validation report
            val_dir = self._stage_dir(task, "validation")
            os.makedirs(val_dir, exist_ok=True)
            val_file = os.path.join(val_dir, "validation_report.md")
            with open(val_file, "w", encoding="utf-8") as f:
                f.write(val_output)

            task.stages["validation"].status = "completed"
            task.stages["validation"].full_output = val_output
            task.stages["validation"].artifacts = [val_file]
            task.stages["validation"].summary = self._extract_summary(val_output, 300)
            task.stages["validation"].completed_at = str(datetime.now())
            task.current_stage = SwarmStage.VALIDATION_REVIEW
            self._save_task(task)

            logger.info(f"Validation complete for task {task_id}")
        except Exception as e:
            task.stages["validation"].status = "failed"
            task.stages["validation"].error = str(e)
            task.current_stage = SwarmStage.EXEC_REVIEW
            self._save_task(task)
            raise

        return task

    async def approve_validation(self, task_id: str) -> SwarmTask:
        """User approves validation. Move to Finishing."""
        task = self._get_task(task_id)
        self._assert_stage(task, SwarmStage.VALIDATION_REVIEW)
        task.user_approved_validation = True
        self._save_task(task)
        return task

    async def reject_validation(self, task_id: str) -> SwarmTask:
        """User rejects validation. Go back to PLAN_REVIEW for re-execution."""
        task = self._get_task(task_id)
        self._assert_stage(task, SwarmStage.VALIDATION_REVIEW)
        task.current_stage = SwarmStage.PLAN_REVIEW
        task.user_approved_validation = False
        if "validation" in task.stages:
            task.stages["validation"].status = "pending"
            task.stages["validation"].summary = "Валидация отклонена. Готов к повторному выполнению."
        self._save_task(task)
        return task

    async def start_finishing(self, task_id: str) -> SwarmTask:
        """Start the Finishing stage. Runs the Finisher agent."""
        task = self._get_task(task_id)
        self._assert_stage(task, SwarmStage.VALIDATION_REVIEW)
        if not task.user_approved_validation:
            raise ValueError("Validation must be approved before finishing")

        task.current_stage = SwarmStage.FINISHING
        task.stages["finishing"] = StageResult(
            stage=SwarmStage.FINISHING,
            status="running",
            summary="Формирую итоговый отчёт...",
            started_at=str(datetime.now()),
        )
        self._save_task(task)

        try:
            plan_content = task.stages.get("planning", StageResult(SwarmStage.PLANNING, "completed")).full_output
            exec_output = task.stages.get("execution", StageResult(SwarmStage.EXECUTING, "completed")).full_output
            val_output = task.stages.get("validation", StageResult(SwarmStage.VALIDATING, "completed")).full_output

            prompt = f"""Compile the final report for this task.

## Task Description
{task.description}

## Original Plan
{plan_content}

## Execution Report
{exec_output}

## Validation Report
{val_output}

## Instructions
Create a comprehensive final report that summarizes the entire process."""

            final_output = await self._run_agent(FINISHER_SYSTEM_PROMPT, prompt)

            # Save final report
            done_dir = self._stage_dir(task, "done")
            os.makedirs(done_dir, exist_ok=True)
            final_file = os.path.join(done_dir, "final_report.md")
            with open(final_file, "w", encoding="utf-8") as f:
                f.write(final_output)

            task.stages["finishing"].status = "completed"
            task.stages["finishing"].full_output = final_output
            task.stages["finishing"].artifacts = [final_file]
            task.stages["finishing"].summary = self._extract_summary(final_output, 300)
            task.stages["finishing"].completed_at = str(datetime.now())
            task.current_stage = SwarmStage.DONE
            self._save_task(task)

            logger.info(f"Task {task_id} complete!")
        except Exception as e:
            task.stages["finishing"].status = "failed"
            task.stages["finishing"].error = str(e)
            task.current_stage = SwarmStage.VALIDATION_REVIEW
            self._save_task(task)
            raise

        return task

    # ================================================================
    # Pause / Resume / Retry / Cancel
    # ================================================================

    async def pause(self, task_id: str) -> SwarmTask:
        """Pause the current task."""
        task = self._get_task(task_id)
        if task.current_stage in (SwarmStage.DONE, SwarmStage.CANCELLED, SwarmStage.PAUSED):
            raise ValueError(f"Cannot pause task in stage: {task.current_stage.value}")
        task.current_stage = SwarmStage.PAUSED
        task.updated_at = str(datetime.now())
        self._save_task(task)
        logger.info(f"Task {task_id} paused")
        return task

    async def resume(self, task_id: str) -> SwarmTask:
        """Resume a paused task. Returns to the review stage before the pause."""
        task = self._get_task(task_id)
        if task.current_stage != SwarmStage.PAUSED:
            raise ValueError(f"Task is not paused, current stage: {task.current_stage.value}")

        # Determine where to resume
        # If execution was completed, resume at EXEC_REVIEW
        # If planning was completed, resume at PLAN_REVIEW
        # If validation was completed, resume at VALIDATION_REVIEW
        if task.stages.get("validation", StageResult(SwarmStage.VALIDATING, "pending")).status == "completed":
            task.current_stage = SwarmStage.VALIDATION_REVIEW
        elif task.stages.get("execution", StageResult(SwarmStage.EXECUTING, "pending")).status == "completed":
            task.current_stage = SwarmStage.EXEC_REVIEW
        elif task.stages.get("planning", StageResult(SwarmStage.PLANNING, "pending")).status == "completed":
            task.current_stage = SwarmStage.PLAN_REVIEW
        else:
            task.current_stage = SwarmStage.IDLE

        task.updated_at = str(datetime.now())
        self._save_task(task)
        logger.info(f"Task {task_id} resumed at {task.current_stage.value}")
        return task

    async def retry_stage(self, task_id: str) -> SwarmTask:
        """Retry the current stage. Goes back to the appropriate pre-stage."""
        task = self._get_task(task_id)
        review_stages = {
            SwarmStage.PLAN_REVIEW: SwarmStage.IDLE,
            SwarmStage.EXEC_REVIEW: SwarmStage.PLAN_REVIEW,
            SwarmStage.VALIDATION_REVIEW: SwarmStage.EXEC_REVIEW,
        }
        if task.current_stage in review_stages:
            task.current_stage = review_stages[task.current_stage]
            task.updated_at = str(datetime.now())
            self._save_task(task)
            logger.info(f"Task {task_id} retry — moved to {task.current_stage.value}")
        else:
            raise ValueError(f"Cannot retry from stage: {task.current_stage.value}")
        return task

    async def cancel(self, task_id: str) -> SwarmTask:
        """Cancel the task."""
        task = self._get_task(task_id)
        if task.current_stage == SwarmStage.DONE:
            raise ValueError("Cannot cancel a completed task")
        task.current_stage = SwarmStage.CANCELLED
        task.updated_at = str(datetime.now())
        self._save_task(task)
        logger.info(f"Task {task_id} cancelled")
        return task

    async def delete_task(self, task_id: str) -> bool:
        """Delete a task and its files."""
        task = self._get_task(task_id)
        task_dir = self._task_dir(task_id)
        import shutil
        if os.path.exists(task_dir):
            shutil.rmtree(task_dir)
        del self._tasks[task_id]
        logger.info(f"Task {task_id} deleted")
        return True

    # ================================================================
    # Query
    # ================================================================

    def get_task(self, task_id: str) -> Optional[SwarmTask]:
        """Get a task by ID."""
        return self._tasks.get(task_id)

    def list_tasks(self, user_id: Optional[str] = None) -> List[SwarmTask]:
        """List all tasks, optionally filtered by user."""
        tasks = list(self._tasks.values())
        if user_id:
            tasks = [t for t in tasks if t.user_id == user_id]
        return sorted(tasks, key=lambda t: t.created_at, reverse=True)

    def load_all_tasks(self) -> None:
        """Load all tasks from disk."""
        if not os.path.exists(self._base_dir):
            return
        for task_id in os.listdir(self._base_dir):
            task_dir = os.path.join(self._base_dir, task_id)
            if not os.path.isdir(task_dir):
                continue
            state_file = os.path.join(task_dir, "state.json")
            if os.path.exists(state_file):
                try:
                    with open(state_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    task = SwarmTask.from_dict(data)
                    self._tasks[task.task_id] = task
                    logger.info(f"Loaded task {task.task_id} ({task.current_stage.value})")
                except Exception as e:
                    logger.error(f"Error loading task {task_id}: {e}")

    # ================================================================
    # Internal helpers
    # ================================================================

    async def _run_agent(self, system_prompt: str, user_message: str) -> str:
        """Run the LLM agent with a specialized system prompt.

        Uses send_message_without_history to avoid polluting the user's
        conversation history.
        """
        # Save original user so we can restore
        original_user = self._agent.user

        # Create a temporary preferences dict for this agent call
        # We bypass the normal system prompt by putting our prompt directly
        # into the message as a system role
        # Actually, send_message_without_history already uses user preferences
        # for the system prompt. We need a different approach.

        # We'll use the httpx client directly since we need a custom system prompt.
        import httpx

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]

        url = f"{self._agent.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._agent.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self._agent.model,
            "messages": messages,
            "temperature": self._agent.temperature,
            "max_tokens": self._agent.max_tokens,
        }

        try:
            async with httpx.AsyncClient(timeout=self._agent.timeout) as client:
                response = await client.post(url, json=payload, headers=headers)
                response.raise_for_status()
                data = response.json()
                return data["choices"][0]["message"]["content"]
        except httpx.TimeoutException:
            raise Exception(f"Request timed out after {self._agent.timeout} seconds.")
        except httpx.HTTPStatusError as e:
            try:
                error_detail = e.response.json().get("error", {}).get("message", str(e))
            except Exception:
                error_detail = str(e)
            raise Exception(f"HTTP error {e.response.status_code}: {error_detail}")
        except httpx.RequestError as e:
            raise Exception(f"Network error: {str(e)}")

    def _get_task(self, task_id: str) -> SwarmTask:
        """Get a task, raising if not found."""
        task = self._tasks.get(task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")
        return task

    def _assert_stage(self, task: SwarmTask, expected: SwarmStage) -> None:
        """Assert the task is in the expected stage."""
        if task.current_stage != expected:
            raise ValueError(
                f"Expected stage {expected.value}, but task is in {task.current_stage.value}"
            )

    def _task_dir(self, task_id: str) -> str:
        """Get the directory for a task."""
        return os.path.join(self._base_dir, task_id)

    def _stage_dir(self, task: SwarmTask, stage_name: str) -> str:
        """Get the directory for a stage's artifacts."""
        return os.path.join(self._task_dir(task.task_id), stage_name)

    def _save_task(self, task: SwarmTask) -> None:
        """Save task state to disk atomically."""
        task.updated_at = str(datetime.now())
        task_dir = self._task_dir(task.task_id)
        os.makedirs(task_dir, exist_ok=True)
        state_file = os.path.join(task_dir, "state.json")
        tmp_file = state_file + ".tmp"
        try:
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(task.to_dict(), f, ensure_ascii=False, indent=2)
            os.replace(tmp_file, state_file)
        except Exception:
            if os.path.exists(tmp_file):
                os.remove(tmp_file)
            raise

    @staticmethod
    def _extract_summary(text: str, max_chars: int = 300) -> str:
        """Extract a short summary from LLM output."""
        if not text:
            return ""
        # Try to find the first meaningful paragraph
        lines = text.strip().split("\n")
        summary_lines = []
        total = 0
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if total + len(stripped) > max_chars:
                remaining = max_chars - total
                if remaining > 20:
                    summary_lines.append(stripped[:remaining] + "...")
                break
            summary_lines.append(stripped)
            total += len(stripped)
        result = " ".join(summary_lines)
        if len(result) > max_chars:
            result = result[:max_chars] + "..."
        return result
