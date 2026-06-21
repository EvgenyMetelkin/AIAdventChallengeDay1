#!/usr/bin/env python3
"""
CLI для взаимодействия с LLM через Agent с поддержкой пользователей.

Использование:
    python cli.py "Привет, как дела?"
    python cli.py --interactive
    python cli.py --interactive --user "My User" --preferences preferences.md
"""

import os
import sys
import asyncio
import argparse
from dotenv import load_dotenv
from agent import Agent
from user import User, create_user, create_default_user

USERS_DIR = os.getenv("USERS_DIR", "users")


def parse_args():
    parser = argparse.ArgumentParser(description="CLI for interacting with LLM via Agent")
    parser.add_argument("query", nargs="?", help="Single query to send (non-interactive mode)")
    parser.add_argument("--interactive", "-i", action="store_true", help="Run in interactive mode")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose logging")
    
    # User options
    parser.add_argument("--user", "-u", help="User name (creates if not exists)")
    parser.add_argument("--user-id", help="Use existing user by ID")
    parser.add_argument("--preferences", help="Path to preferences MD file for new user")
    
    # Override configuration via CLI
    parser.add_argument("--api-key", help="LLM API key (overrides env)")
    parser.add_argument("--base-url", help="Base URL for LLM API")
    parser.add_argument("--model", help="Model name")
    parser.add_argument("--temperature", type=float, help="Temperature")
    parser.add_argument("--max-tokens", type=int, help="Max tokens")
    parser.add_argument("--timeout", type=float, help="Timeout in seconds")
    return parser.parse_args()


def load_config(args):
    load_dotenv()

    api_key = args.api_key or os.getenv("LLM_API_KEY")
    if not api_key:
        print("Error: LLM_API_KEY not set. Provide via environment variable or --api-key", file=sys.stderr)
        sys.exit(1)

    base_url = args.base_url or os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")
    model = args.model or os.getenv("LLM_MODEL", "gpt-3.5-turbo")
    temperature = args.temperature if args.temperature is not None else float(os.getenv("LLM_TEMPERATURE", "0.7"))
    max_tokens = args.max_tokens if args.max_tokens is not None else int(os.getenv("LLM_MAX_TOKENS", "500"))
    timeout = args.timeout if args.timeout is not None else float(os.getenv("LLM_TIMEOUT", "30.0"))
    verbose = args.verbose

    return {
        "api_key": api_key,
        "base_url": base_url,
        "model": model,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "timeout": timeout,
        "verbose": verbose
    }


def load_or_create_user(args) -> User:
    """Загружает или создаёт пользователя на основе аргументов CLI."""
    from user import load_all_users
    
    # Если указан user-id, пытаемся загрузить
    if args.user_id:
        users = load_all_users(USERS_DIR)
        if args.user_id in users:
            print(f"Using existing user: {users[args.user_id].name} ({args.user_id})")
            return users[args.user_id]
        else:
            print(f"Error: User with ID '{args.user_id}' not found", file=sys.stderr)
            sys.exit(1)
    
    # Если указано имя пользователя
    if args.user:
        users = load_all_users(USERS_DIR)
        # Ищем по имени
        for user in users.values():
            if user.name.lower() == args.user.lower():
                print(f"Using existing user: {user.name} ({user.user_id})")
                return user
        
        # Создаём нового
        preferences_content = None
        if args.preferences:
            try:
                with open(args.preferences, 'r', encoding='utf-8') as f:
                    preferences_content = f.read()
            except Exception as e:
                print(f"Error reading preferences file: {e}", file=sys.stderr)
                sys.exit(1)
        
        new_user = create_user(USERS_DIR, args.user, preferences_content)
        print(f"Created new user: {new_user.name} ({new_user.user_id})")
        return new_user
    
    # Без указания пользователя: используем первого существующего или создаём дефолтного
    users = load_all_users(USERS_DIR)
    if users:
        first_user = next(iter(users.values()))
        print(f"Using existing user: {first_user.name} ({first_user.user_id})")
        return first_user
    
    default_user = create_default_user(USERS_DIR)
    print(f"Created default user: {default_user.name} ({default_user.user_id})")
    return default_user


async def run_interactive(agent: Agent):
    print("Interactive mode. Type 'exit' or 'quit' to quit, 'reset' to clear conversation history.")
    print(f"User: {agent.user.name} | Agent: {agent.user.agents[agent.user.current_agent_id]['name']}")
    try:
        while True:
            try:
                user_input = input("> ")
            except EOFError:
                break
            if user_input.lower() in ("exit", "quit"):
                break
            if user_input.lower() == "reset":
                agent.reset_conversation()
                print("Conversation reset.")
                continue
            if not user_input.strip():
                continue
            try:
                response = await agent.send_message(user_input)
                print(response)
            except Exception as e:
                print(f"Error: {e}", file=sys.stderr)
    finally:
        agent.user.save_agents()
        print("Goodbye!")


async def run_single(agent: Agent, query: str):
    try:
        response = await agent.send_message(query)
        print(response)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


async def main():
    args = parse_args()
    config = load_config(args)
    
    # Загружаем или создаём пользователя
    user = load_or_create_user(args)
    
    # Создаём агента с пользователем
    agent = Agent(
        api_key=config["api_key"],
        base_url=config["base_url"],
        model=config["model"],
        temperature=config["temperature"],
        max_tokens=config["max_tokens"],
        timeout=config["timeout"],
        verbose=config["verbose"],
        user=user
    )

    if args.interactive or args.query is None:
        await run_interactive(agent)
    else:
        await run_single(agent, args.query)


if __name__ == "__main__":
    asyncio.run(main())
