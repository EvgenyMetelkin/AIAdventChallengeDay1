"""Обработчики инструментов weather_scheduler и схема TOOLS_SCHEMA."""

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List

from scheduler import SchedulerManager

logger = logging.getLogger("weather_scheduler.handlers")

EXPORTS_DIR = os.path.join(os.path.dirname(__file__), "exports")

TOOLS_SCHEMA: List[Dict[str, Any]] = [
    {
        "name": "schedule_job",
        "description": (
            "Поставить однократную задачу на получение погоды. "
            "Задача выполнится один раз в указанное время (не ранее чем через 10 секунд от текущего момента). "
            "Возвращает объект задачи с уникальным ID, статусом и временем выполнения."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "weather_tool": {
                    "type": "string",
                    "description": "Имя инструмента погоды: get_weather_by_coordinates или get_weather_spb",
                    "enum": ["get_weather_by_coordinates", "get_weather_spb"],
                },
                "params": {
                    "type": "object",
                    "description": (
                        "Параметры для вызова погодного инструмента. "
                        "Для get_weather_by_coordinates: {\"latitude\": 59.93, \"longitude\": 30.31}. "
                        "Для get_weather_spb: {}."
                    ),
                },
                "run_at": {
                    "type": "string",
                    "description": "Время выполнения в формате ISO (например, 2026-06-27T12:00:00)",
                },
            },
            "required": ["weather_tool", "params", "run_at"],
        },
    },
    {
        "name": "repeat_job",
        "description": (
            "Запустить повторяющуюся задачу на получение погоды. "
            "Задача будет выполняться каждые interval_seconds секунд (не менее 60) "
            "до наступления end_time (не позже чем через 30 дней). "
            "Возвращает объект задачи с полями interval_seconds, end_time и статусом repeating."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "weather_tool": {
                    "type": "string",
                    "description": "Имя инструмента погоды: get_weather_by_coordinates или get_weather_spb",
                    "enum": ["get_weather_by_coordinates", "get_weather_spb"],
                },
                "params": {
                    "type": "object",
                    "description": (
                        "Параметры для вызова погодного инструмента. "
                        "Для get_weather_by_coordinates: {\"latitude\": 59.93, \"longitude\": 30.31}. "
                        "Для get_weather_spb: {}."
                    ),
                },
                "interval_seconds": {
                    "type": "integer",
                    "description": "Интервал между выполнениями в секундах (не менее 60)",
                    "minimum": 60,
                },
                "end_time": {
                    "type": "string",
                    "description": "Максимальная дата окончания в формате ISO (не позже чем через 30 дней)",
                },
            },
            "required": ["weather_tool", "params", "interval_seconds", "end_time"],
        },
    },
    {
        "name": "cancel_job",
        "description": (
            "Отменить задачу (однократную или повторяющуюся) по её ID. "
            "Если задача уже выполнена или не найдена — возвращает ошибку. "
            "Возвращает обновлённый объект задачи со статусом cancelled."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "job_id": {
                    "type": "string",
                    "description": "Уникальный идентификатор задачи",
                },
            },
            "required": ["job_id"],
        },
    },
    {
        "name": "actual_jobs",
        "description": (
            "Получить список всех запланированных задач "
            "(включая повторяющиеся и ожидающие выполнения). "
            "Возвращает JSON-массив объектов задач."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "export_jobs_to_file",
        "description": (
            "Экспортировать все задачи (включая завершённые) и их сохранённые результаты "
            "в текстовый файл в формате JSON. "
            "Файл сохраняется в поддиректории exports/ с именем jobs_export_<timestamp>.json. "
            "Возвращает объект с полями file_path и count."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "filename": {
                    "type": "string",
                    "description": "Опциональное имя файла (без пути). Если не указано, генерируется автоматически.",
                },
            },
            "required": [],
        },
    },
]


def handle_schedule_job(scheduler: SchedulerManager, arguments: Dict[str, Any]) -> Dict[str, Any]:
    weather_tool = arguments.get("weather_tool", "")
    params = arguments.get("params", {})
    run_at = arguments.get("run_at", "")

    if weather_tool not in ("get_weather_by_coordinates", "get_weather_spb"):
        raise ValueError(f"Неизвестный weather_tool: {weather_tool}")

    if not isinstance(params, dict):
        raise ValueError("params должен быть объектом (dict)")

    if not run_at:
        raise ValueError("run_at обязателен")

    return scheduler.schedule_job(weather_tool, params, run_at)


def handle_repeat_job(scheduler: SchedulerManager, arguments: Dict[str, Any]) -> Dict[str, Any]:
    weather_tool = arguments.get("weather_tool", "")
    params = arguments.get("params", {})
    interval_seconds = arguments.get("interval_seconds", 0)
    end_time = arguments.get("end_time", "")

    if weather_tool not in ("get_weather_by_coordinates", "get_weather_spb"):
        raise ValueError(f"Неизвестный weather_tool: {weather_tool}")

    if not isinstance(params, dict):
        raise ValueError("params должен быть объектом (dict)")

    if not isinstance(interval_seconds, int) or interval_seconds < 60:
        raise ValueError("interval_seconds должен быть целым числом >= 60")

    if not end_time:
        raise ValueError("end_time обязателен")

    return scheduler.repeat_job(weather_tool, params, interval_seconds, end_time)


def handle_cancel_job(scheduler: SchedulerManager, arguments: Dict[str, Any]) -> Dict[str, Any]:
    job_id = arguments.get("job_id", "")
    if not job_id:
        raise ValueError("job_id обязателен")
    return scheduler.cancel_job(job_id)


def handle_actual_jobs(scheduler: SchedulerManager, arguments: Dict[str, Any]) -> List[Dict[str, Any]]:
    return scheduler.get_jobs()


def handle_export_jobs_to_file(scheduler: SchedulerManager, arguments: Dict[str, Any]) -> Dict[str, Any]:
    filename = arguments.get("filename")
    if not filename:
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        filename = f"jobs_export_{ts}.json"

    os.makedirs(EXPORTS_DIR, exist_ok=True)
    filepath = os.path.join(EXPORTS_DIR, filename)
    return scheduler.export_all_jobs(filepath)
