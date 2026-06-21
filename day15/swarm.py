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
import re
from enum import Enum
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime

from utils import format_invariants_prompt, format_invariant_check_prompt

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
    FAILED = "failed"               # Invariant check failed, awaiting retry


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
    SwarmStage.FAILED: "Ошибка инвариантов",
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
    SwarmStage.FAILED: "Проверка инвариантов не пройдена. Исправьте нарушения и перезапустите этап.",
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

INVARIANT_CHECKER_SYSTEM_PROMPT = """Ты — Агент-Проверяющий инвариантов в мультиагентной системе. Твоя задача — проверить, что сгенерированный артефакт не нарушает ни одного из заданных инвариантов.

## Правила
- Будь строгим, но справедливым. Отмечай только реальные нарушения.
- Каждое нарушение должно быть конкретным: какой инвариант, что именно в тексте его нарушает, почему.
- Если нарушений нет, верни пустой список.
- Отвечай строго в формате JSON без маркдаун-обёртки."""

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


QUESTION_GENERATOR_SYSTEM_PROMPT = """Ты — Агент-Генератор вопросов в мультиагентной системе. Твоя задача — проанализировать запрос пользователя и сформулировать уточняющие вопросы, которые помогут составить более точный план.

## Формат ответа

Отвечай строго в формате JSON без маркдаун-обёртки:

```json
{
  "questions": [
    "Вопрос 1?",
    "Вопрос 2?",
    "Вопрос 3?"
  ]
}
```

## Правила
- Задавай 3-5 конкретных, полезных вопросов.
- Вопросы должны уточнять детали, которые повлияют на план.
- Спрашивай о технологиях, ограничениях, приоритетах, форматах.
- Не задавай очевидных вопросов, ответы на которые уже есть в запросе.
- Пиши на том же языке, что и запрос пользователя.
- Каждый вопрос должен быть самодостаточным и понятным."""


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
    invariants: List[str] = field(default_factory=list)
    stage_checks: Dict[str, dict] = field(default_factory=dict)
    # Interactive planning fields (Day 15)
    pending_questions: List[str] = field(default_factory=list)
    answers: List[str] = field(default_factory=list)
    plan_text: str = ""
    question_index: int = 0
    waiting_for_answers: bool = False

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
            "invariants": self.invariants,
            "stage_checks": self.stage_checks,
            "pending_questions": self.pending_questions,
            "answers": self.answers,
            "plan_text": self.plan_text,
            "question_index": self.question_index,
            "waiting_for_answers": self.waiting_for_answers,
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
            invariants=data.get("invariants", []),
            stage_checks=data.get("stage_checks", {}),
            pending_questions=data.get("pending_questions", []),
            answers=data.get("answers", []),
            plan_text=data.get("plan_text", ""),
            question_index=data.get("question_index", 0),
            waiting_for_answers=data.get("waiting_for_answers", False),
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
            SwarmStage.FAILED: None,  # progress stays where it was
        }
        pct = stage_progress.get(self.current_stage)
        if pct is not None:
            return pct
        # For FAILED, compute from completed stages
        if self.stages.get("validation", StageResult(SwarmStage.VALIDATING, "pending")).status == "completed":
            return 75
        elif self.stages.get("execution", StageResult(SwarmStage.EXECUTING, "pending")).status == "completed":
            return 50
        elif self.stages.get("planning", StageResult(SwarmStage.PLANNING, "pending")).status == "completed":
            return 20
        return 0


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

    async def create_task(self, description: str, user_id: str, invariants: Optional[List[str]] = None) -> SwarmTask:
        """Create a new swarm task.

        Args:
            description: Task description
            user_id: User who owns the task
            invariants: Optional list of invariant strings to enforce throughout the task
        """
        task = SwarmTask(
            task_id=uuid.uuid4().hex[:8],
            user_id=user_id,
            description=description,
            invariants=invariants or [],
        )
        self._tasks[task.task_id] = task
        self._save_task(task)
        logger.info(f"Created swarm task {task.task_id}: {description[:80]}...")
        return task

    async def start_planning(self, task_id: str) -> SwarmTask:
        """Start the Planning stage. Generates clarifying questions first."""
        task = self._get_task(task_id)
        self._assert_stage(task, SwarmStage.IDLE)

        task.current_stage = SwarmStage.PLANNING
        task.stages["planning"] = StageResult(
            stage=SwarmStage.PLANNING,
            status="running",
            summary="Генерирую уточняющие вопросы...",
            started_at=str(datetime.now()),
        )
        task.waiting_for_answers = False
        task.pending_questions = []
        task.answers = []
        task.question_index = 0
        task.plan_text = ""
        self._save_task(task)

        try:
            # Generate clarifying questions
            questions = await self._generate_questions(task)
            if not questions:
                # If no questions generated, fall back to direct planning
                task.stages["planning"].summary = "Анализирую запрос и составляю план..."
                self._save_task(task)
                invs = self._ensure_invariants(task)
                plan_output = await self._run_agent(
                    PLANNER_SYSTEM_PROMPT,
                    f"Create a detailed implementation plan for the following task:\n\n{task.description}",
                    invariants=invs,
                )
                return await self._finalize_planning(task, plan_output, invs)

            # Store questions and wait for answers
            task.pending_questions = questions
            task.question_index = 0
            task.waiting_for_answers = True
            task.stages["planning"].status = "running"
            task.stages["planning"].summary = f"Ожидаю ответы на {len(questions)} уточняющих вопросов..."
            self._save_task(task)
            logger.info(f"Generated {len(questions)} questions for task {task_id}")

        except Exception as e:
            task.stages["planning"].status = "failed"
            task.stages["planning"].error = str(e)
            task.stages["planning"].completed_at = str(datetime.now())
            # Stay in PLANNING with error info instead of reverting to IDLE
            self._save_task(task)
            logger.error(f"Question generation failed for task {task_id}: {e}")

        return task

    async def _finalize_planning(self, task: SwarmTask, plan_output: str, invs: List[str]) -> SwarmTask:
        """Save the plan and move to PLAN_REVIEW."""
        plan_dir = self._stage_dir(task, "planning")
        os.makedirs(plan_dir, exist_ok=True)
        plan_file = os.path.join(plan_dir, "plan.md")
        with open(plan_file, "w", encoding="utf-8") as f:
            f.write(plan_output)

        # Run invariant check
        check_result = await self._check_invariants(invs, plan_output, "planning")
        task.stage_checks["planning"] = check_result

        if not check_result["passed"]:
            task.stages["planning"].status = "failed"
            task.stages["planning"].full_output = plan_output
            task.stages["planning"].artifacts = [plan_file]
            task.stages["planning"].summary = self._extract_summary(plan_output, 300)
            task.stages["planning"].completed_at = str(datetime.now())
            task.stages["planning"].error = "Нарушены инварианты: " + "; ".join(
                v.get("reason", v.get("invariant", "")) for v in check_result["violations"]
            )
            task.current_stage = SwarmStage.FAILED
            task.stage_checks["_failed_stage"] = "planning"
            task.waiting_for_answers = False
            self._save_task(task)
            logger.warning(f"Planning failed invariant check for task {task.task_id}: {len(check_result['violations'])} violations")
            return task

        task.stages["planning"].status = "completed"
        task.stages["planning"].full_output = plan_output
        task.stages["planning"].artifacts = [plan_file]
        task.stages["planning"].summary = self._extract_summary(plan_output, 300)
        task.stages["planning"].completed_at = str(datetime.now())
        task.plan_text = plan_output
        task.waiting_for_answers = False
        task.current_stage = SwarmStage.PLAN_REVIEW
        self._save_task(task)
        logger.info(f"Planning complete for task {task.task_id}")
        return task

    async def _generate_questions(self, task: SwarmTask) -> List[str]:
        """Generate clarifying questions for the task description."""
        prompt = f"Проанализируй следующий запрос и сформулируй уточняющие вопросы:\n\n{task.description}"
        raw_response = await self._run_agent(QUESTION_GENERATOR_SYSTEM_PROMPT, prompt)
        try:
            cleaned = raw_response.strip()
            if cleaned.startswith("```"):
                cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
                cleaned = re.sub(r"\s*```$", "", cleaned)
            result = json.loads(cleaned)
            return result.get("questions", [])
        except json.JSONDecodeError:
            # Fallback: try to extract questions line by line
            lines = [l.strip().lstrip("-*1234567890. ") for l in raw_response.strip().split("\n") if l.strip() and "?" in l]
            if lines:
                return lines[:5]
            logger.warning(f"Failed to parse questions JSON for task {task.task_id}")
            return []

    async def _generate_plan(self, task: SwarmTask) -> str:
        """Generate the implementation plan using all answers."""
        qa_text = ""
        for i, (q, a) in enumerate(zip(task.pending_questions, task.answers)):
            qa_text += f"\nВопрос {i+1}: {q}\nОтвет: {a}\n"
        prompt = f"""Исходный запрос:
{task.description}

Уточняющие вопросы и ответы:
{qa_text}

Составь подробный план реализации на основе запроса и полученных ответов."""
        invs = self._ensure_invariants(task)
        return await self._run_agent(PLANNER_SYSTEM_PROMPT, prompt, invariants=invs)

    async def handle_user_input(self, task_id: str, text: str) -> SwarmTask:
        """Handle user text input routed to the swarm task based on current stage.

        Args:
            task_id: The task ID
            text: User's input text

        Returns:
            Updated task
        """
        task = self._get_task(task_id)

        if task.current_stage == SwarmStage.PLANNING and task.waiting_for_answers:
            # Answering clarifying questions
            if task.question_index < len(task.pending_questions):
                task.answers.append(text)
                task.question_index += 1
                task.stages["planning"].summary = (
                    f"Получен ответ {task.question_index}/{len(task.pending_questions)}..."
                )
                self._save_task(task)

                # If all questions answered, generate the plan
                if task.question_index >= len(task.pending_questions):
                    try:
                        plan_output = await self._generate_plan(task)
                        invs = self._ensure_invariants(task)
                        return await self._finalize_planning(task, plan_output, invs)
                    except Exception as e:
                        task.stages["planning"].status = "failed"
                        task.stages["planning"].error = str(e)
                        task.stages["planning"].completed_at = str(datetime.now())
                        task.waiting_for_answers = False
                        # Stay in PLANNING with error — user can retry
                        self._save_task(task)
                        logger.error(f"Plan generation failed for task {task_id}: {e}")
            return task

        elif task.current_stage == SwarmStage.PLAN_REVIEW:
            # Treat as refine_plan implicitly
            return await self.refine_plan(task_id, text)

        # For other stages, ignore or log the input
        logger.info(f"User input for task {task_id} at stage {task.current_stage.value} ignored (not expecting input)")
        return task

    async def refine_plan(self, task_id: str, text: str) -> SwarmTask:
        """Refine the generated plan with additional user feedback.

        Stays in PLAN_REVIEW after regeneration.
        """
        task = self._get_task(task_id)
        self._assert_stage(task, SwarmStage.PLAN_REVIEW)

        # Append the refinement to answers for context
        task.answers.append(f"[Уточнение]: {text}")

        task.stages["planning"].status = "running"
        task.stages["planning"].summary = "Перегенерирую план с учётом уточнений..."
        self._save_task(task)

        try:
            plan_output = await self._generate_plan(task)
            invs = self._ensure_invariants(task)

            # Save updated plan
            plan_dir = self._stage_dir(task, "planning")
            os.makedirs(plan_dir, exist_ok=True)
            plan_file = os.path.join(plan_dir, "plan.md")
            with open(plan_file, "w", encoding="utf-8") as f:
                f.write(plan_output)

            # Run invariant check
            check_result = await self._check_invariants(invs, plan_output, "planning")
            task.stage_checks["planning"] = check_result

            if not check_result["passed"]:
                task.stages["planning"].status = "failed"
                task.stages["planning"].full_output = plan_output
                task.stages["planning"].artifacts = [plan_file]
                task.stages["planning"].summary = self._extract_summary(plan_output, 300)
                task.stages["planning"].completed_at = str(datetime.now())
                task.stages["planning"].error = "Нарушены инварианты: " + "; ".join(
                    v.get("reason", v.get("invariant", "")) for v in check_result["violations"]
                )
                task.current_stage = SwarmStage.FAILED
                task.stage_checks["_failed_stage"] = "planning"
                self._save_task(task)
                logger.warning(f"Plan refinement failed invariant check for task {task_id}")
                return task

            task.stages["planning"].status = "completed"
            task.stages["planning"].full_output = plan_output
            task.stages["planning"].artifacts = [plan_file]
            task.stages["planning"].summary = self._extract_summary(plan_output, 300)
            task.stages["planning"].completed_at = str(datetime.now())
            task.plan_text = plan_output
            task.current_stage = SwarmStage.PLAN_REVIEW  # Stay in review
            self._save_task(task)
            logger.info(f"Plan refined for task {task_id}")

        except Exception as e:
            task.stages["planning"].status = "failed"
            task.stages["planning"].error = str(e)
            task.current_stage = SwarmStage.PLAN_REVIEW
            self._save_task(task)
            logger.error(f"Plan refinement failed for task {task_id}: {e}")

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
        # Clear invariant check for planning too
        task.stage_checks.pop("planning", None)
        task.waiting_for_answers = False
        task.pending_questions = []
        task.answers = []
        task.question_index = 0
        task.plan_text = ""
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
            # Fallback: use plan_text if full_output is empty (e.g. after interactive planning)
            if not plan_content and task.plan_text:
                plan_content = task.plan_text
            prompt = f"""Execute the following plan:

## Approved Plan
{plan_content}

## Instructions
Implement the plan step by step. Create all necessary files and artifacts.
Describe what you did for each step. Be thorough and follow the plan exactly.
If you cannot complete a step, explain why."""
            
            invs = self._ensure_invariants(task)
            exec_output = await self._run_agent(EXECUTOR_SYSTEM_PROMPT, prompt, invariants=invs)

            # Save execution report
            exec_dir = self._stage_dir(task, "execution")
            os.makedirs(exec_dir, exist_ok=True)
            exec_file = os.path.join(exec_dir, "execution_report.md")
            with open(exec_file, "w", encoding="utf-8") as f:
                f.write(exec_output)

            # Run invariant check
            check_result = await self._check_invariants(invs, exec_output, "execution")
            task.stage_checks["execution"] = check_result

            if not check_result["passed"]:
                task.stages["execution"].status = "failed"
                task.stages["execution"].full_output = exec_output
                task.stages["execution"].artifacts = [exec_file]
                task.stages["execution"].summary = self._extract_summary(exec_output, 300)
                task.stages["execution"].completed_at = str(datetime.now())
                task.stages["execution"].error = "Нарушены инварианты: " + "; ".join(
                    v.get("reason", v.get("invariant", "")) for v in check_result["violations"]
                )
                task.current_stage = SwarmStage.FAILED
                task.stage_checks["_failed_stage"] = "execution"
                self._save_task(task)
                logger.warning(f"Execution failed invariant check for task {task_id}: {len(check_result['violations'])} violations")
                return task

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
            task.stages["execution"].completed_at = str(datetime.now())
            # Stay in EXECUTING with failed status — don't revert to PLAN_REVIEW
            # This lets the user see the error and retry via restart_stage
            task.stage_checks["_failed_stage"] = "execution"
            self._save_task(task)
            logger.error(f"Execution failed for task {task_id}: {e}")

        return task

    async def approve_execution(self, task_id: str) -> SwarmTask:
        """User approves the execution. Move to Validation."""
        task = self._get_task(task_id)
        self._assert_stage(task, SwarmStage.EXEC_REVIEW)
        task.user_approved_execution = True
        self._save_task(task)
        return task

    async def reject_execution(self, task_id: str) -> SwarmTask:
        """User rejects the execution. Go back to PLAN_REVIEW."""
        task = self._get_task(task_id)
        self._assert_stage(task, SwarmStage.EXEC_REVIEW)
        task.current_stage = SwarmStage.PLAN_REVIEW
        task.user_approved_execution = False
        if "execution" in task.stages:
            task.stages["execution"].status = "pending"
            task.stages["execution"].summary = "Выполнение отклонено."
        task.stage_checks.pop("execution", None)
        self._save_task(task)
        return task

    async def start_validation(self, task_id: str) -> SwarmTask:
        """Start the Validation stage."""
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
            if not plan_content and task.plan_text:
                plan_content = task.plan_text
            exec_output = task.stages.get("execution", StageResult(SwarmStage.EXECUTING, "completed")).full_output

            prompt = f"""Validate the following implementation against the plan.

## Original Plan
{plan_content}

## Execution Report
{exec_output}

## Instructions
Compare each step. Assess completeness. Recommend next steps."""

            invs = self._ensure_invariants(task)
            val_output = await self._run_agent(VALIDATOR_SYSTEM_PROMPT, prompt, invariants=invs)

            # Save validation report
            val_dir = self._stage_dir(task, "validation")
            os.makedirs(val_dir, exist_ok=True)
            val_file = os.path.join(val_dir, "validation_report.md")
            with open(val_file, "w", encoding="utf-8") as f:
                f.write(val_output)

            # Run invariant check
            check_result = await self._check_invariants(invs, val_output, "validation")
            task.stage_checks["validation"] = check_result

            if not check_result["passed"]:
                task.stages["validation"].status = "failed"
                task.stages["validation"].full_output = val_output
                task.stages["validation"].artifacts = [val_file]
                task.stages["validation"].summary = self._extract_summary(val_output, 300)
                task.stages["validation"].completed_at = str(datetime.now())
                task.stages["validation"].error = "Нарушены инварианты: " + "; ".join(
                    v.get("reason", v.get("invariant", "")) for v in check_result["violations"]
                )
                task.current_stage = SwarmStage.FAILED
                task.stage_checks["_failed_stage"] = "validation"
                self._save_task(task)
                logger.warning(f"Validation failed invariant check for task {task_id}")
                return task

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
            task.stages["validation"].completed_at = str(datetime.now())
            # Stay in VALIDATING with failed status
            task.stage_checks["_failed_stage"] = "validation"
            self._save_task(task)
            logger.error(f"Validation failed for task {task_id}: {e}")

        return task

    async def approve_validation(self, task_id: str) -> SwarmTask:
        """User approves the validation. Move to Finishing."""
        task = self._get_task(task_id)
        self._assert_stage(task, SwarmStage.VALIDATION_REVIEW)
        task.user_approved_validation = True
        self._save_task(task)
        return task

    async def reject_validation(self, task_id: str) -> SwarmTask:
        """User rejects the validation. Go back to EXEC_REVIEW."""
        task = self._get_task(task_id)
        self._assert_stage(task, SwarmStage.VALIDATION_REVIEW)
        task.current_stage = SwarmStage.EXEC_REVIEW
        task.user_approved_validation = False
        if "validation" in task.stages:
            task.stages["validation"].status = "pending"
            task.stages["validation"].summary = "Валидация отклонена."
        task.stage_checks.pop("validation", None)
        self._save_task(task)
        return task

    async def start_finishing(self, task_id: str) -> SwarmTask:
        """Start the Finishing stage."""
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
            if not plan_content and task.plan_text:
                plan_content = task.plan_text
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

            invs = self._ensure_invariants(task)
            final_output = await self._run_agent(FINISHER_SYSTEM_PROMPT, prompt, invariants=invs)

            # Save final report
            done_dir = self._stage_dir(task, "done")
            os.makedirs(done_dir, exist_ok=True)
            final_file = os.path.join(done_dir, "final_report.md")
            with open(final_file, "w", encoding="utf-8") as f:
                f.write(final_output)

            # Run invariant check
            check_result = await self._check_invariants(invs, final_output, "finishing")
            task.stage_checks["finishing"] = check_result

            if not check_result["passed"]:
                task.stages["finishing"].status = "failed"
                task.stages["finishing"].full_output = final_output
                task.stages["finishing"].artifacts = [final_file]
                task.stages["finishing"].summary = self._extract_summary(final_output, 300)
                task.stages["finishing"].completed_at = str(datetime.now())
                task.stages["finishing"].error = "Нарушены инварианты: " + "; ".join(
                    v.get("reason", v.get("invariant", "")) for v in check_result["violations"]
                )
                task.current_stage = SwarmStage.FAILED
                task.stage_checks["_failed_stage"] = "finishing"
                self._save_task(task)
                logger.warning(f"Finishing failed invariant check for task {task_id}: {len(check_result['violations'])} violations")
                return task

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
            task.stages["finishing"].completed_at = str(datetime.now())
            # Stay in FINISHING with failed status
            task.stage_checks["_failed_stage"] = "finishing"
            self._save_task(task)
            logger.error(f"Finishing failed for task {task_id}: {e}")

        return task

    # ================================================================
    # Pause / Resume / Cancel / Retry
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
        """Resume a paused or failed task. Returns to the appropriate stage."""
        task = self._get_task(task_id)
        if task.current_stage not in (SwarmStage.PAUSED, SwarmStage.FAILED,
                                       SwarmStage.EXECUTING, SwarmStage.VALIDATING, SwarmStage.FINISHING):
            raise ValueError(f"Task is not paused or failed, current stage: {task.current_stage.value}")

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
            SwarmStage.PLAN_REVIEW: ("planning", SwarmStage.IDLE),
            SwarmStage.EXEC_REVIEW: ("execution", SwarmStage.PLAN_REVIEW),
            SwarmStage.VALIDATION_REVIEW: ("validation", SwarmStage.EXEC_REVIEW),
        }
        if task.current_stage in review_stages:
            stage_name, target = review_stages[task.current_stage]
            all_stages = ["planning", "execution", "validation", "finishing"]
            clear_from_idx = all_stages.index(stage_name) if stage_name in all_stages else 0
            for i in range(clear_from_idx, len(all_stages)):
                task.stage_checks.pop(all_stages[i], None)

            task.current_stage = target
            task.updated_at = str(datetime.now())
            self._save_task(task)
            logger.info(f"Task {task_id} retry — moved to {task.current_stage.value}")
        elif task.current_stage == SwarmStage.FAILED:
            return await self.restart_stage(task_id)
        else:
            raise ValueError(f"Cannot retry from stage: {task.current_stage.value}")
        return task

    async def cancel(self, task_id: str) -> SwarmTask:
        """Cancel the task."""
        task = self._get_task(task_id)
        if task.current_stage in (SwarmStage.DONE, SwarmStage.CANCELLED):
            raise ValueError(f"Cannot cancel task in stage: {task.current_stage.value}")
        task.current_stage = SwarmStage.CANCELLED
        task.updated_at = str(datetime.now())
        self._save_task(task)
        logger.info(f"Task {task_id} cancelled")
        return task

    async def delete_task(self, task_id: str) -> None:
        """Permanently delete a task and all its data."""
        task = self._get_task(task_id)
        task_dir = self._task_dir(task_id)
        del self._tasks[task_id]
        import shutil
        if os.path.exists(task_dir):
            shutil.rmtree(task_dir)
        logger.info(f"Task {task_id} deleted")

    async def restart_stage(self, task_id: str) -> SwarmTask:
        """Restart the failed stage after fixing invariants.
        
        Works from FAILED state or from active stages that have _failed_stage set
        (e.g. EXECUTING with a failed LLM call).
        """
        task = self._get_task(task_id)
        
        # Allow restart from FAILED or from active stages with _failed_stage
        failed_stages = {SwarmStage.EXECUTING, SwarmStage.VALIDATING, SwarmStage.FINISHING, SwarmStage.FAILED}
        if task.current_stage not in failed_stages:
            raise ValueError(f"Cannot restart from stage: {task.current_stage.value}")
        if task.current_stage != SwarmStage.FAILED and not task.stage_checks.get("_failed_stage"):
            raise ValueError(f"No failure recorded for stage {task.current_stage.value}")

        stage_name = task.stage_checks.get("_failed_stage", "")
        if not stage_name:
            raise ValueError("No failed stage recorded — cannot determine where to restart")

        stage_rewind = {
            "planning": SwarmStage.IDLE,
            "execution": SwarmStage.PLAN_REVIEW,
            "validation": SwarmStage.EXEC_REVIEW,
            "finishing": SwarmStage.VALIDATION_REVIEW,
        }

        target_stage = stage_rewind.get(stage_name)
        if target_stage is None:
            raise ValueError(f"Unknown stage to restart: {stage_name}")

        all_stages = ["planning", "execution", "validation", "finishing"]
        clear_from_idx = all_stages.index(stage_name) if stage_name in all_stages else 0

        for i in range(clear_from_idx, len(all_stages)):
            s = all_stages[i]
            if s in task.stages:
                task.stages[s].status = "pending"
                task.stages[s].summary = f"Этап сброшен из-за перезапуска '{stage_name}'."
                task.stages[s].full_output = ""
                task.stages[s].artifacts = []
                task.stages[s].error = None
            task.stage_checks.pop(s, None)
        task.stage_checks.pop("_failed_stage", None)

        task.current_stage = target_stage
        self._save_task(task)
        logger.info(f"Task {task_id} stage '{stage_name}' restarted, back to {target_stage.value}, "
                     f"cleared {len(all_stages) - clear_from_idx} stages")
        return task

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

    async def _run_agent(self, system_prompt: str, user_message: str, invariants: Optional[List[str]] = None) -> str:
        """Run the LLM agent with a specialized system prompt."""
        full_system_prompt = system_prompt
        if invariants:
            inv_block = format_invariants_prompt(invariants)
            full_system_prompt = system_prompt + "\n\n" + inv_block

        import httpx

        messages = [
            {"role": "system", "content": full_system_prompt},
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

    def _ensure_invariants(self, task: SwarmTask) -> List[str]:
        """Ensure invariants are loaded for a task."""
        if task.invariants:
            return task.invariants

        from utils import parse_invariants_md
        invariants_file = os.path.join(
            os.path.dirname(self._base_dir),
            "invariants.md",
        )
        if os.path.exists(invariants_file):
            try:
                with open(invariants_file, "r", encoding="utf-8") as f:
                    content = f.read()
                loaded = parse_invariants_md(content)
                if loaded:
                    task.invariants = loaded
                    self._save_task(task)
                    logger.info(
                        f"Reloaded {len(loaded)} invariants from file for task {task.task_id}"
                    )
                    return loaded
            except Exception as e:
                logger.warning(f"Failed to reload invariants for task {task.task_id}: {e}")

        return task.invariants

    async def _check_invariants(self, invariants: List[str], artifact_text: str, stage_name: str) -> dict:
        """Check whether an artifact violates any invariants."""
        if not invariants:
            return {"passed": True, "violations": [], "raw_response": "No invariants to check"}

        check_prompt = format_invariant_check_prompt(invariants, artifact_text)
        logger.info(f"Running invariant check for stage '{stage_name}' ({len(invariants)} invariants)")

        try:
            raw_response = await self._run_agent(
                INVARIANT_CHECKER_SYSTEM_PROMPT,
                check_prompt,
                invariants=None,
            )
        except Exception as e:
            logger.warning(f"Invariant check LLM call failed for stage '{stage_name}': {e}")
            return {"passed": True, "violations": [], "raw_response": "",
                    "checker_error": str(e)}

        try:
            cleaned = raw_response.strip()
            if cleaned.startswith("```"):
                cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
                cleaned = re.sub(r"\s*```$", "", cleaned)
            result = json.loads(cleaned)
            violations = result.get("violations", [])
            passed = len(violations) == 0
            logger.info(
                f"Invariant check for stage '{stage_name}': {'PASSED' if passed else 'FAILED'} "
                f"({len(violations)} violations)"
            )
            return {"passed": passed, "violations": violations, "raw_response": raw_response}
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse invariant check response as JSON: {e}")
            return {"passed": True, "violations": [], "raw_response": raw_response,
                    "parse_error": str(e)}

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
