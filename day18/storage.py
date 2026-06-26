import json
import os
import time
from threading import RLock
from typing import Any, Dict, List, Optional

JOBS_FILE = os.path.join(os.path.dirname(__file__), "cache", "jobs.json")
RESULTS_DIR = os.path.join(os.path.dirname(__file__), "cache", "results")

_storage_lock = RLock()


def _ensure_dirs():
    os.makedirs(os.path.dirname(JOBS_FILE), exist_ok=True)
    os.makedirs(RESULTS_DIR, exist_ok=True)


def load_jobs() -> List[Dict[str, Any]]:
    """Загружает список всех задач из основного файла jobs.json."""
    with _storage_lock:
        _ensure_dirs()
        if not os.path.isfile(JOBS_FILE):
            return []
        try:
            with open(JOBS_FILE, "r", encoding="utf-8") as f:
                jobs = json.load(f)
            if not isinstance(jobs, list):
                return []
            return jobs
        except (json.JSONDecodeError, OSError):
            return []


def save_jobs(jobs: List[Dict[str, Any]]):
    """Сохраняет полный список задач в jobs.json."""
    with _storage_lock:
        _ensure_dirs()
        try:
            with open(JOBS_FILE, "w", encoding="utf-8") as f:
                json.dump(jobs, f, ensure_ascii=False, indent=2)
        except OSError as e:
            raise RuntimeError(f"Не удалось сохранить jobs.json: {e}")


def get_job_by_id(job_id: str) -> Optional[Dict[str, Any]]:
    """Возвращает задачу по ID или None."""
    jobs = load_jobs()
    for job in jobs:
        if job.get("id") == job_id:
            return job
    return None


def add_job(job: Dict[str, Any]):
    """Добавляет новую задачу в jobs.json."""
    with _storage_lock:
        _ensure_dirs()
        jobs = load_jobs()
        jobs.append(job)
        save_jobs(jobs)


def update_job(job_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Обновляет поля задачи в jobs.json. Возвращает обновлённый объект или None."""
    with _storage_lock:
        jobs = load_jobs()
        for i, job in enumerate(jobs):
            if job.get("id") == job_id:
                job.update(updates)
                job["updated_at"] = _now_iso()
                save_jobs(jobs)
                return job
    return None


def save_result(job_id: str, data: Any):
    """Сохраняет результат выполнения погодного запроса в отдельный файл."""
    with _storage_lock:
        _ensure_dirs()
        result_path = os.path.join(RESULTS_DIR, f"{job_id}.json")
        try:
            with open(result_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except OSError as e:
            raise RuntimeError(f"Не удалось сохранить результат для {job_id}: {e}")


def load_result(job_id: str) -> Optional[Any]:
    """Загружает результат выполнения из файла."""
    result_path = os.path.join(RESULTS_DIR, f"{job_id}.json")
    if not os.path.isfile(result_path):
        return None
    try:
        with open(result_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def cleanup_old_data(retention_hours: int):
    """Удаляет устаревшие результаты и записи старше retention_hours часов."""
    _ensure_dirs()
    now = time.time()
    retention_seconds = retention_hours * 3600

    with _storage_lock:
        # Удаляем старые файлы результатов
        if os.path.isdir(RESULTS_DIR):
            for filename in os.listdir(RESULTS_DIR):
                if not filename.endswith(".json"):
                    continue
                filepath = os.path.join(RESULTS_DIR, filename)
                try:
                    if now - os.path.getmtime(filepath) > retention_seconds:
                        os.remove(filepath)
                except OSError:
                    pass

        # Удаляем старые записи из jobs.json
        jobs = load_jobs()
        kept = []
        for job in jobs:
            status = job.get("status", "")
            # Повторяющиеся задачи не удаляем, пока не закончены или отменены
            if status == "repeating":
                kept.append(job)
                continue

            if status in ("completed", "cancelled", "failed"):
                # Проверяем completed_at или updated_at
                timestamp = job.get("completed_at") or job.get("updated_at")
                if timestamp:
                    try:
                        from datetime import datetime
                        dt = datetime.fromisoformat(timestamp)
                        if now - dt.timestamp() > retention_seconds:
                            continue  # Пропускаем — задача устарела
                    except (ValueError, OSError):
                        pass

            kept.append(job)

        save_jobs(kept)


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def export_jobs_to_filepath(filepath: str) -> int:
    """Экспортирует все задачи (включая результаты) в JSON-файл. Возвращает количество задач."""
    _ensure_dirs()
    os.makedirs(os.path.dirname(filepath), exist_ok=True)

    jobs = load_jobs()
    export_data = []
    for job in jobs:
        job_copy = dict(job)
        result_file = job.get("result_file")
        if result_file and os.path.isfile(result_file):
            job_copy["result_data"] = load_result(job.get("id", ""))
        export_data.append(job_copy)

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(export_data, f, ensure_ascii=False, indent=2)

    return len(export_data)
