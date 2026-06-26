import json
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

import storage
import weather_client

logger = logging.getLogger("weather_scheduler.scheduler")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


def _parse_iso(iso_str: str) -> datetime:
    """Парсит ISO-строку в datetime с поддержкой Z-суффикса.

    Всегда возвращает offset-aware datetime (UTC).
    """
    iso_str = iso_str.strip()
    if iso_str.endswith("Z"):
        iso_str = iso_str[:-1] + "+00:00"
    dt = datetime.fromisoformat(iso_str)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


class SchedulerManager:
    """Управляет планировщиком задач: создание, выполнение, отмена, очистка."""

    def __init__(
        self,
        weather_host: str = "localhost",
        weather_port: int = 9001,
        weather_auth_key: Optional[str] = None,
        retention_hours: int = 24,
        weather_client_timeout: int = 30,
    ):
        self._weather_host = weather_host
        self._weather_port = weather_port
        self._weather_auth_key = weather_auth_key
        self._retention_hours = retention_hours
        self._weather_client_timeout = weather_client_timeout

        self._scheduler = BackgroundScheduler(timezone=timezone.utc)
        self._scheduler.add_job(
            self._cleanup_job,
            trigger=IntervalTrigger(minutes=5),
            id="cleanup",
            name="cleanup_old_data",
            replace_existing=True,
        )
        self._scheduler.start()

        logger.info("Планировщик инициализирован и запущен")

    def restore_jobs(self):
        """Восстанавливает сохранённые задачи из хранилища при старте."""
        jobs = storage.load_jobs()
        logger.info(f"Загружено {len(jobs)} задач из хранилища")

        for job in jobs:
            job_id = job.get("id", "")
            status = job.get("status", "")

            if status == "scheduled":
                scheduled_time_str = job.get("scheduled_time")
                if not scheduled_time_str:
                    continue
                try:
                    scheduled_time = _parse_iso(scheduled_time_str)
                except (ValueError, OSError):
                    logger.warning(f"Некорректное scheduled_time для задачи {job_id}, пропускаем")
                    continue

                if scheduled_time > _now():
                    self._add_apscheduler_single(job_id, scheduled_time)
                    logger.info(f"Восстановлена однократная задача {job_id} на {scheduled_time_str}")
                else:
                    logger.info(f"Задача {job_id} пропущена (время в прошлом), помечаем failed")
                    storage.update_job(job_id, {
                        "status": "failed",
                        "error": "Время выполнения в прошлом на момент восстановления",
                        "completed_at": _now_iso(),
                    })

            elif status == "repeating":
                interval_seconds = job.get("interval_seconds", 60)
                end_time_str = job.get("end_time")
                end_time = None
                if end_time_str:
                    try:
                        end_time = _parse_iso(end_time_str)
                    except (ValueError, OSError):
                        pass

                if end_time and _now() >= end_time:
                    logger.info(f"Повторяющаяся задача {job_id} завершена (end_time достигнут)")
                    storage.update_job(job_id, {
                        "status": "finished",
                        "completed_at": _now_iso(),
                    })
                else:
                    self._add_apscheduler_repeating(job_id, interval_seconds, end_time)
                    logger.info(f"Восстановлена повторяющаяся задача {job_id} (интервал {interval_seconds}с)")

        logger.info("Восстановление задач завершено")

    def _add_apscheduler_single(self, job_id: str, run_at: datetime):
        """Добавляет однократную задачу в APScheduler."""
        try:
            self._scheduler.add_job(
                self._execute_single_job,
                trigger=DateTrigger(run_date=run_at),
                args=[job_id],
                id=job_id,
                name=f"single_{job_id}",
                replace_existing=True,
                misfire_grace_time=30,
            )
        except Exception as e:
            logger.exception(f"Ошибка добавления однократной задачи {job_id} в APScheduler")

    def _add_apscheduler_repeating(self, job_id: str, interval_seconds: int, end_time: Optional[datetime]):
        """Добавляет повторяющуюся задачу в APScheduler."""
        try:
            kwargs = {"seconds": interval_seconds}
            trigger = IntervalTrigger(**kwargs)
            self._scheduler.add_job(
                self._execute_repeating_job,
                trigger=trigger,
                args=[job_id, end_time, interval_seconds],
                id=job_id,
                name=f"repeating_{job_id}",
                replace_existing=True,
                misfire_grace_time=30,
            )
        except Exception as e:
            logger.exception(f"Ошибка добавления повторяющейся задачи {job_id} в APScheduler")

    def schedule_job(
        self,
        weather_tool: str,
        params: Dict[str, Any],
        run_at_str: str,
    ) -> Dict[str, Any]:
        """Создаёт однократную задачу."""
        try:
            run_at = _parse_iso(run_at_str)
        except (ValueError, OSError):
            raise ValueError(f"Некорректный формат run_at: {run_at_str}")

        min_time = _now() + timedelta(seconds=10)
        if run_at < min_time:
            raise ValueError(
                f"run_at должно быть не менее чем через 10 секунд от текущего момента. "
                f"Минимальное: {min_time.isoformat()}"
            )

        job_id = uuid.uuid4().hex
        job = {
            "id": job_id,
            "status": "scheduled",
            "created_at": _now_iso(),
            "scheduled_time": run_at_str,
            "interval_seconds": None,
            "end_time": None,
            "weather_tool": weather_tool,
            "params": params,
            "result_file": None,
            "result": None,
            "error": None,
            "completed_at": None,
            "updated_at": _now_iso(),
        }

        storage.add_job(job)
        self._add_apscheduler_single(job_id, run_at)
        logger.info(f"Создана однократная задача {job_id} на {run_at_str}")
        return job

    def repeat_job(
        self,
        weather_tool: str,
        params: Dict[str, Any],
        interval_seconds: int,
        end_time_str: str,
    ) -> Dict[str, Any]:
        """Создаёт повторяющуюся задачу."""
        if interval_seconds < 60:
            raise ValueError("interval_seconds должен быть не менее 60 (не чаще 1 раза в минуту)")

        try:
            end_time = _parse_iso(end_time_str)
        except (ValueError, OSError):
            raise ValueError(f"Некорректный формат end_time: {end_time_str}")

        max_end = _now() + timedelta(days=30)
        if end_time > max_end:
            raise ValueError(
                f"end_time не должен быть позже чем через 30 дней. Максимальное: {max_end.isoformat()}"
            )

        if _now() >= end_time:
            raise ValueError("end_time должно быть в будущем")

        job_id = uuid.uuid4().hex
        job = {
            "id": job_id,
            "status": "repeating",
            "created_at": _now_iso(),
            "scheduled_time": None,
            "interval_seconds": interval_seconds,
            "end_time": end_time_str,
            "weather_tool": weather_tool,
            "params": params,
            "result_file": None,
            "result": None,
            "error": None,
            "completed_at": None,
            "updated_at": _now_iso(),
        }

        storage.add_job(job)
        self._add_apscheduler_repeating(job_id, interval_seconds, end_time)
        logger.info(f"Создана повторяющаяся задача {job_id} (интервал {interval_seconds}с, до {end_time_str})")
        return job

    def cancel_job(self, job_id: str) -> Dict[str, Any]:
        """Отменяет задачу (однократную или повторяющуюся)."""
        job = storage.get_job_by_id(job_id)
        if not job:
            raise ValueError(f"Задача с ID {job_id} не найдена")

        status = job.get("status", "")
        if status in ("completed", "finished", "cancelled"):
            raise ValueError(f"Задача {job_id} уже завершена (статус: {status})")

        # Удаляем из APScheduler
        try:
            if self._scheduler.get_job(job_id):
                self._scheduler.remove_job(job_id)
        except Exception:
            pass

        updated = storage.update_job(job_id, {
            "status": "cancelled",
            "completed_at": _now_iso(),
        })
        if not updated:
            raise RuntimeError(f"Не удалось обновить задачу {job_id}")

        logger.info(f"Задача {job_id} отменена")
        return updated

    def get_jobs(self, status_filter: Optional[str] = None) -> List[Dict[str, Any]]:
        """Возвращает список задач, опционально фильтруя по статусу."""
        jobs = storage.load_jobs()
        if status_filter:
            jobs = [j for j in jobs if j.get("status") == status_filter]
        return jobs

    def export_all_jobs(self, filepath: str) -> Dict[str, Any]:
        """Экспортирует все задачи в JSON-файл."""
        count = storage.export_jobs_to_filepath(filepath)
        logger.info(f"Экспортировано {count} задач в {filepath}")
        return {"file_path": filepath, "count": count}

    def _execute_single_job(self, job_id: str):
        """Выполняет однократную задачу: вызывает погодный API, сохраняет результат."""
        logger.info(f"Выполнение однократной задачи {job_id}")

        job = storage.get_job_by_id(job_id)
        if not job:
            logger.warning(f"Задача {job_id} не найдена в хранилище")
            return

        if job.get("status") == "cancelled":
            logger.info(f"Задача {job_id} отменена, пропускаем выполнение")
            return

        storage.update_job(job_id, {"status": "running"})
        self._run_weather_call(job_id, job)

    def _execute_repeating_job(self, job_id: str, end_time: Optional[datetime], interval_seconds: int):
        """Выполняет повторяющуюся задачу, проверяет end_time."""
        logger.info(f"Выполнение повторяющейся задачи {job_id}")

        job = storage.get_job_by_id(job_id)
        if not job:
            logger.warning(f"Повторяющаяся задача {job_id} не найдена, удаляем из планировщика")
            try:
                self._scheduler.remove_job(job_id)
            except Exception:
                pass
            return

        status = job.get("status", "")
        if status == "cancelled":
            logger.info(f"Повторяющаяся задача {job_id} отменена, удаляем из планировщика")
            try:
                self._scheduler.remove_job(job_id)
            except Exception:
                pass
            return

        if status == "finished":
            try:
                self._scheduler.remove_job(job_id)
            except Exception:
                pass
            return

        if end_time and _now() >= end_time:
            storage.update_job(job_id, {
                "status": "finished",
                "completed_at": _now_iso(),
            })
            try:
                self._scheduler.remove_job(job_id)
            except Exception:
                pass
            logger.info(f"Повторяющаяся задача {job_id} завершена по end_time")
            return

        storage.update_job(job_id, {"status": "running"})
        self._run_weather_call(job_id, job)

    def _run_weather_call(self, job_id: str, job: Dict[str, Any]):
        """Общая логика вызова погодного API и сохранения результата."""
        weather_tool = job.get("weather_tool", "")
        params = job.get("params", {})

        try:
            result = weather_client.call_weather_tool(
                tool_name=weather_tool,
                params=params,
                host=self._weather_host,
                port=self._weather_port,
                auth_key=self._weather_auth_key,
                timeout=self._weather_client_timeout,
            )

            result_path = os.path.join(storage.RESULTS_DIR, f"{job_id}.json")
            storage.save_result(job_id, result)

            storage.update_job(job_id, {
                "status": "completed",
                "result": result,
                "result_file": result_path,
                "completed_at": _now_iso(),
                "error": None,
            })
            logger.info(f"Задача {job_id} выполнена успешно")

        except Exception as e:
            error_msg = str(e)
            logger.error(f"Задача {job_id} завершилась с ошибкой: {error_msg}")
            storage.update_job(job_id, {
                "status": "failed",
                "error": error_msg,
                "completed_at": _now_iso(),
            })

    def _cleanup_job(self):
        """Фоновая задача очистки старых данных."""
        try:
            storage.cleanup_old_data(self._retention_hours)
        except Exception as e:
            logger.exception(f"Ошибка при очистке старых данных: {e}")

    def shutdown(self):
        """Останавливает планировщик."""
        self._scheduler.shutdown(wait=False)
        logger.info("Планировщик остановлен")
