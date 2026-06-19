# User Module

## Overview
User management with persistent preferences (MD) and history (JSON).

## Imports
- `utils` (local) - parse_preferences_md, format_preferences_md

## API

### `User`
`User(user_id: str, name: str, preferences: dict = {}, history: list = [], history_file: str = None, preferences_file: str = None)`

- `load_preferences()` - parse MD file into `preferences` dict
- `load_history()` - load JSON history
- `save_history()` / `save_preferences()` - persist to disk
- `get_system_prompt()` - build prompt from STYLE/CONSTRAINTS/CONTEXT
- `reset_history()` - clear and save
- `to_dict()` - summary dict

### `create_user(user_dir, name, preferences_content=None) -> User`
Creates new user with UUID ID, saves defaults.

### `load_all_users(user_dir) -> Dict[str, User]`
Loads all user subdirs; reads name from `#` line in preferences.md.

### `create_default_user(user_dir) -> User`
Creates "Default User" with sample preferences.

## Usage
```python
user = create_user("./users", "Alice", "## STYLE\nBe brief.")
user.get_system_prompt()  # "# System Instructions\n\n## STYLE\nBe brief."
user.save_history()
```

## Notes
- `__post_init__` auto-loads if files exist.
- Preferences keys: `STYLE`, `CONSTRAINTS`, `CONTEXT`.
- `user_id` is auto-generated 8-char hex.
- Missing keys in preferences default to `""`.
- `create_default_user` used if no users exist.