#!/usr/bin/env python3
import os
import sys
import asyncio
import argparse
from dotenv import load_dotenv
from agent import Agent

def parse_args():
    parser = argparse.ArgumentParser(description="CLI for interacting with LLM via Agent")
    parser.add_argument("query", nargs="?", help="Single query to send (non-interactive mode)")
    parser.add_argument("--interactive", "-i", action="store_true", help="Run in interactive mode")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose logging")
    parser.add_argument("--history-file", help="File to load/save conversation history (JSON)")
    # Override configuration via CLI
    parser.add_argument("--api-key", help="LLM API key (overrides env)")
    parser.add_argument("--base-url", help="Base URL for LLM API")
    parser.add_argument("--model", help="Model name")
    parser.add_argument("--temperature", type=float, help="Temperature")
    parser.add_argument("--max-tokens", type=int, help="Max tokens")
    parser.add_argument("--timeout", type=float, help="Timeout in seconds")
    return parser.parse_args()

def load_config(args):
    load_dotenv()  # Load .env file

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

async def run_interactive(agent: Agent, history_file: str = None):
    if history_file:
        agent.load_history(history_file)
    print("Interactive mode. Type 'exit' or 'quit' to quit, 'reset' to clear conversation history.")
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
            try:
                response = await agent.send_message(user_input)
                print(response)
            except Exception as e:
                print(f"Error: {e}", file=sys.stderr)
    finally:
        if history_file:
            agent.save_history(history_file)
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
    agent = Agent(**config)

    if args.interactive or args.query is None:
        await run_interactive(agent, args.history_file)
    else:
        await run_single(agent, args.query)

if __name__ == "__main__":
    asyncio.run(main())