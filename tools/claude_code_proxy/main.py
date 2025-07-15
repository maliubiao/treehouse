from __future__ import annotations

import argparse

import uvicorn
from dotenv import load_dotenv

# Load environment variables from .env file before other imports
# to ensure they are available for the config module.
load_dotenv()

# Note: The relative import works because we will run this module
# using `python -m claude_code_proxy.main` from the project root.
from .config_manager import AppConfig, config_manager
from .server import app


def start_server(cmd_args: argparse.Namespace) -> None:
    """
    Starts the Uvicorn server to run the FastAPI application.

    Args:
        cmd_args: Command-line arguments parsed by argparse.
    """
    if cmd_args.config:
        config_manager.config_path = cmd_args.config

    # Load config and potentially override with command-line arguments
    config = config_manager.load_config(reload=True)
    if cmd_args.host:
        config.server.host = cmd_args.host
    if cmd_args.port:
        config.server.port = cmd_args.port
    if cmd_args.reload:
        config.server.reload = cmd_args.reload

    print("--- Starting Anthropic to OpenAI Proxy Server ---")
    print(f"Configuration loaded from: {config_manager.config_path or 'default settings'}")
    print(f"Server will run on: http://{config.server.host}:{config.server.port}")
    print(f"Reload mode: {'On' if config.server.reload else 'Off'}")

    # Display providers information
    providers = config.openai_providers
    if providers:
        print(f"\nLoaded {len(providers)} OpenAI-compatible providers:")
        for key, provider in providers.items():
            print(f"  - [{key}] {provider.name}: {provider.base_url} (Reasoning: {provider.supports_reasoning})")
    else:
        print("\nNo OpenAI-compatible providers configured.")

    anthropic_cfg = config.anthropic_config
    if anthropic_cfg:
        print("\nAnthropic Routing Configuration:")
        print(f"  - Default Provider: {anthropic_cfg.default_provider}")
        print(f"  - Model-specific providers: {len(anthropic_cfg.model_providers)} mappings")

    print("\n-------------------------------------------------")
    print("Point your Anthropic client to this server, for example:")
    print(f"export ANTHROPIC_BASE_URL=http://{config.server.host}:{config.server.port}/v1")
    print("-------------------------------------------------")

    # Run the server.
    uvicorn.run(
        "claude_code_proxy.server:app",
        host=config.server.host,
        port=config.server.port,
        reload=config.server.reload,
    )


def main() -> None:
    """
    Main function to parse command-line arguments and start the server.
    """
    parser = argparse.ArgumentParser(description="Anthropic to OpenAI Proxy Server")
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="Path to YAML configuration file (e.g., config.yml)",
    )
    parser.add_argument(
        "--host",
        type=str,
        default=None,
        help="Server host to bind to (overrides config)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Server port to listen on (overrides config)",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Enable auto-reload mode for development (overrides config)",
    )

    args = parser.parse_args()
    start_server(args)


if __name__ == "__main__":
    main()
