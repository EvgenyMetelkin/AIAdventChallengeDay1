import json
import os
import uuid
import shutil
from typing import Dict, List, Optional


class User:
    def __init__(self, user_id: str, name: str = "", users_dir: str = "users"):
        self.user_id = user_id
        self.users_dir = users_dir
        self.user_dir = os.path.join(users_dir, user_id)
        os.makedirs(self.user_dir, exist_ok=True)

        self.settings_path = os.path.join(self.user_dir, "settings.json")
        self.settings = self._load_settings()

        if name:
            self.settings["name"] = name
            self._save_settings()

        self.agents_path = os.path.join(self.user_dir, "agents.json")
        self.agents = self._load_agents()

        self.current_agent_id = self.settings.get("current_agent_id")
        if self.current_agent_id and self.current_agent_id not in self.agents:
            self.current_agent_id = None

    @property
    def name(self) -> str:
        return self.settings.get("name", self.user_id)

    @name.setter
    def name(self, value: str):
        self.settings["name"] = value
        self._save_settings()

    def _load_settings(self) -> dict:
        if os.path.exists(self.settings_path):
            with open(self.settings_path, encoding="utf-8") as f:
                return json.load(f)
        return {"system_prompt": "", "default_model": "deepseek-v4-flash",
                "default_temperature": 0.7, "default_max_tokens": 500}

    def _save_settings(self):
        with open(self.settings_path, "w", encoding="utf-8") as f:
            json.dump(self.settings, f, indent=2, ensure_ascii=False)

    def _load_agents(self) -> dict:
        if os.path.exists(self.agents_path):
            with open(self.agents_path, encoding="utf-8") as f:
                return json.load(f)
        return {}

    def save_agents(self):
        with open(self.agents_path, "w", encoding="utf-8") as f:
            json.dump(self.agents, f, indent=2, ensure_ascii=False)
        self.settings["current_agent_id"] = self.current_agent_id
        self._save_settings()

    def add_agent(self, name: str) -> str:
        agent_id = uuid.uuid4().hex[:8]
        self.agents[agent_id] = {"name": name, "history": []}
        if self.current_agent_id is None:
            self.current_agent_id = agent_id
        self.save_agents()
        return agent_id

    def remove_agent(self, agent_id: str):
        if agent_id in self.agents:
            del self.agents[agent_id]
            if self.current_agent_id == agent_id:
                self.current_agent_id = next(iter(self.agents)) if self.agents else None
            self.save_agents()

    def get_current_history(self) -> list:
        if self.current_agent_id and self.current_agent_id in self.agents:
            return self.agents[self.current_agent_id].get("history", [])
        return []

    def reset_current_history(self):
        if self.current_agent_id and self.current_agent_id in self.agents:
            self.agents[self.current_agent_id]["history"] = []
            self.save_agents()

    def get_system_prompt(self) -> str:
        return self.settings.get("system_prompt", "")

    def set_system_prompt(self, prompt: str):
        self.settings["system_prompt"] = prompt
        self._save_settings()

    def get_default_model(self) -> str:
        return self.settings.get("default_model", "deepseek-v4-flash")

    def get_default_temperature(self) -> float:
        return self.settings.get("default_temperature", 0.7)

    def get_default_max_tokens(self) -> int:
        return self.settings.get("default_max_tokens", 500)

    def set_defaults(self, model: str = None, temperature: float = None,
                     max_tokens: int = None):
        if model is not None:
            self.settings["default_model"] = model
        if temperature is not None:
            self.settings["default_temperature"] = temperature
        if max_tokens is not None:
            self.settings["default_max_tokens"] = max_tokens
        self._save_settings()

    def to_dict(self) -> dict:
        return {
            "user_id": self.user_id,
            "name": self.name,
            "current_agent_id": self.current_agent_id,
            "settings": self.settings,
            "agents": {k: {"name": v["name"],
                           "history_length": len(v.get("history", []))}
                       for k, v in self.agents.items()}
        }

    def delete(self):
        if os.path.exists(self.user_dir):
            shutil.rmtree(self.user_dir)


class UserManager:
    def __init__(self, users_dir: str = "users"):
        self.users_dir = users_dir
        os.makedirs(users_dir, exist_ok=True)

    def get_user_ids(self) -> List[str]:
        if not os.path.exists(self.users_dir):
            return []
        return sorted([d for d in os.listdir(self.users_dir)
                       if os.path.isdir(os.path.join(self.users_dir, d))])

    def get_all_users(self) -> List[Dict]:
        users = []
        for uid in self.get_user_ids():
            user = self.get_user(uid)
            if user:
                users.append({"user_id": uid, "name": user.name})
        return users

    def get_user(self, user_id: str) -> Optional[User]:
        if os.path.isdir(os.path.join(self.users_dir, user_id)):
            return User(user_id, users_dir=self.users_dir)
        return None

    def create_user(self, user_id: str = None, name: str = "") -> User:
        if user_id is None:
            user_id = uuid.uuid4().hex[:8]
        if not name:
            name = user_id
        return User(user_id, name, users_dir=self.users_dir)

    def delete_user(self, user_id: str):
        user = self.get_user(user_id)
        if user:
            user.delete()
