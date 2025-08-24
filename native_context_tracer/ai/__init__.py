from .entrypoint import find_entrypoint_and_break, set_entrypoint_breakpoints
from .treehouse_lldb import AskGptCommand, GPTIntegrationService, ModelSwitchCommand

__ALL__ = ["AskGptCommand", "AskGptCompleter", "set_entrypoint_breakpoints"]

gpt_service: GPTIntegrationService = None
model_switch_cmd: ModelSwitchCommand = None


def __lldb_init_module(debugger, session):
    """Initialize the module and register commands."""
    print("AI module loaded, you can use 'askgpt' 'usegpt' command.")
    global gpt_service, model_switch_cmd
    gpt_service = GPTIntegrationService(session)
    debugger.HandleCommand(f"command script add -c ai.AskGptCommand askgpt")
    debugger.HandleCommand(f"command script add -c ai.ModelSwitchCommand usegpt")
    debugger.HandleCommand(f"command script add -f ai.find_entrypoint_and_break bentry")
