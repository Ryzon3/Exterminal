"""
Exterminal: A smart terminal application that uses an LLM to interpret natural language
commands and execute them in a Linux-like environment.

This main script orchestrates user input, LLM interaction, command execution,
and console output.
"""
import json
import os
import time
from dotenv import load_dotenv
from rich.console import Console
from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.formatted_text import HTML
from typing import List, Dict, Any, Tuple, Optional, cast

from command_executor import CommandExecutor
from llm_handler import LLMHandler
from app_config import load_config

def change_directory(new_dir: str, console: Console) -> str:
    """
    Changes the current working directory of the application.

    Args:
        new_dir: The target directory path.
        console: The Rich Console object for printing output.

    Returns:
        A string message indicating the result of the operation.
    """
    try:
        os.chdir(new_dir)
        result: str = f"Directory changed to {new_dir}"
        console.print(f"[dodger_blue1]Output:[/dodger_blue1]\n[hot_pink2]{result}[/hot_pink2]")
        return result
    except FileNotFoundError:
        result = f"Directory '{new_dir}' not found"
        console.print(f"[bright_red]Error:[/bright_red] {result}")
        return result
    except PermissionError:
        result = f"You do not have permission to access '{new_dir}'"
        console.print(f"[bright_red]Error:[/bright_red] {result}")
        return result
    except Exception as e: # Catch any other OS-level errors during cd
        result = f"Error changing directory to '{new_dir}': {e}"
        console.print(f"[bright_red]Error:[/bright_red] {result}")
        return result


if __name__ == '__main__':
    load_dotenv()
    console: Console = Console(color_system="256")
    
    try:
        app_settings: Dict[str, Any] = load_config()
        command_executor: CommandExecutor = CommandExecutor(console=console)
        llm_handler: LLMHandler = LLMHandler(
            console=console,
            model_name=str(app_settings.get('llm', {}).get('model_name', 'gpt-4o')),
            temperature=float(app_settings.get('llm', {}).get('temperature', 0.0)),
            system_prompt=str(app_settings.get('system_prompt_content', 'You are a helpful assistant.')),
            cache_db_name=str(app_settings.get('cache', {}).get('db_name', '.exterminal_cache.db'))
        )
    except Exception as e_init:
        console.print(f"[bold bright_red]Fatal Initialization Error: {e_init}[/bold bright_red]")
        console.print("[bold bright_red]Exterminal cannot start. Please check configurations and dependencies.[/bold bright_red]")
        exit(1)

    prompt_history_file: str = os.path.join(os.path.expanduser('~'), app_settings.get("prompt_history_file", ".exterminal_history"))
    prompt_session: PromptSession[str] = PromptSession(
        HTML('<style fg="#d75faf">Exterminal > </style>'), # type: ignore
        history=FileHistory(prompt_history_file),
        auto_suggest=AutoSuggestFromHistory(),
    )
    
    messages_history: List[Dict[str, str]] = []
    world_model: Dict[str, Any] = {}
    
    console.clear()
    console.rule("[b hot_pink2]Exterminal[/b hot_pink2]", style="dodger_blue1")
    # ... (welcome messages are implicitly handled by the main loop's first iteration message print)
    console.print("[dodger_blue1 i][b hot_pink2]Exterminal[/b hot_pink2] is a smart terminal that can execute human-readable commands, remember information, answer questions, and more![/dodger_blue1 i]")
    console.print("[dodger_blue1 i]Type any command to execute it or type '[u bright_red]exit[/u bright_red]' to exit. [/dodger_blue1 i]")
    console.print("[dodger_blue1 i]Type '[u bright_red]clear[/u bright_red]' to clear the terminal. [/dodger_blue1 i]")
    console.print("[dodger_blue1 i]Type '[u bright_red]help[/u bright_red]' to get help. [/dodger_blue1 i]")
    console.print("")

    while True:
        try:
            current_user_input: str = prompt_session.prompt()

            world_model['directory'] = os.getcwd()
            try:
                world_model['directory_contents'] = os.listdir()
            except Exception as e_ls:
                world_model['directory_contents'] = [f"Error listing directory: {e_ls}"]

            messages_history.append({'role': 'user', 'content': current_user_input})

            if current_user_input.lower() in ["exit", "e", "quit", "q"]:
                console.print("[dodger_blue1]Exiting [b hot_pink2]Exterminal[/b hot_pink2]...[/dodger_blue1]")
                break

            if current_user_input.lower() in ["clear", "c", "cls"]:
                console.clear()
                console.rule("[b hot_pink2]Exterminal[/b hot_pink2]", style="dodger_blue1")
                messages_history = []
                continue
            if not current_user_input.strip(): continue
            if current_user_input.lower() in ['wm', 'world_model', 'world']:
                console.print("[dodger_blue1]Current World Model:[/dodger_blue1]")
                console.print_json(data=world_model); console.print("")
                continue
            if current_user_input.lower() in ['messages', 'm', 'history']:
                console.print("[dodger_blue1]Current Messages History:[/dodger_blue1]")
                for msg in messages_history:
                     console.print(f"[b]{msg['role']}:[/b]")
                     try: content_data = json.loads(msg['content']); console.print_json(data=content_data)
                     except (json.JSONDecodeError, TypeError): console.print(msg['content'])
                console.print("")
                continue
            if current_user_input.lower() in ["help", "h", "?"]:
                console.print("[dodger_blue1]Available Commands:[/dodger_blue1]")
                console.print("- [hot_pink2]exit, e, quit, q[/hot_pink2]: Exit Exterminal.")
                console.print("- [hot_pink2]clear, c, cls[/hot_pink2]: Clear the terminal screen.")
                console.print("- [hot_pink2]world_model, wm, world[/hot_pink2]: View the current world model.")
                console.print("- [hot_pink2]messages, m, history[/hot_pink2]: View the messages history.")
                console.print("- [hot_pink2]help, h, ?[/hot_pink2]: Display this help message.")
                console.print("- [hot_pink2]--force-llm[/hot_pink2]: (Append to your prompt) Force a new LLM query, bypassing cache.")
                console.print("")
                continue

            force_llm_query: bool = False
            if '--force-llm' in current_user_input:
                current_user_input = current_user_input.replace('--force-llm', '').strip()
                force_llm_query = True

            llm_response_json: Optional[Dict[str, Any]] = llm_handler.get_llm_response(
                messages_history=messages_history[:-1],
                current_user_input=current_user_input,
                world_model=world_model,
                force_new_response=force_llm_query
            )

            # Flexible extraction of command list
            extracted_commands_list: Optional[List[str]] = None
            if llm_response_json: # Ensure llm_response_json is not None
                extracted_commands_list = llm_response_json.get('commands')
                if not isinstance(extracted_commands_list, list):
                    # Fallback to checking 'commands_planned' if 'commands' is not a list or not found
                    extracted_commands_list = llm_response_json.get('commands_planned')

            if not isinstance(extracted_commands_list, list): # Check again after potential fallback
                error_msg = "LLM did not return commands in the expected list format (checked 'commands' and 'commands_planned')."
                console.print(f"[bright_red]Error: {error_msg}[/bright_red]")
                if llm_response_json: # Print the problematic response if it exists
                    console.print(f"LLM Response (raw): {llm_response_json}")
                messages_history.append({'role': 'assistant', 'content': json.dumps({'error': error_msg, 'raw_response': llm_response_json})})
                continue

            # At this point, extracted_commands_list is confirmed to be a list (it could be empty).
            if llm_response_json and 'world_model' in llm_response_json and isinstance(llm_response_json['world_model'], dict):
                world_model.update(llm_response_json['world_model'])

            llm_thoughts: str = llm_response_json.get("thoughts", "No thoughts provided.") if llm_response_json else "No thoughts (LLM response was null)."
            assistant_turn_content_dict: Dict[str, Any] = {
                "thoughts": llm_thoughts,
                "commands_planned": extracted_commands_list # Log the actually used command list
            }
            if llm_response_json and 'world_model' in llm_response_json and isinstance(llm_response_json['world_model'], dict):
                assistant_turn_content_dict["world_model_updates"] = llm_response_json['world_model']
            messages_history.append({'role': 'assistant', 'content': json.dumps(assistant_turn_content_dict)})

            commands_to_process: List[str] = list(extracted_commands_list) # Use the validated list
            current_command_idx: int = 0
            # ... (rest of the command processing loop remains the same) ...
            while current_command_idx < len(commands_to_process):
                llm_command_full_str: str = commands_to_process[current_command_idx]
                command_to_run_actual: str = ""
                command_type_str: str = ""

                if isinstance(llm_command_full_str, str):
                    parts: List[str] = llm_command_full_str.split(":", 1)
                    if len(parts) == 2:
                        command_type_str = parts[0].strip().upper()
                        command_to_run_actual = parts[1].strip()
                    else:
                        console.print(f"[bright_red]Invalid command format from LLM: {llm_command_full_str}[/bright_red]")
                        messages_history.append({'role': 'system', 'content': f"Error: Invalid command format '{llm_command_full_str}'"})
                        current_command_idx += 1
                        continue
                else:
                    console.print(f"[bright_red]Invalid command object type from LLM: {type(llm_command_full_str)}[/bright_red]")
                    messages_history.append({'role': 'system', 'content': f"Error: Invalid command object type '{type(llm_command_full_str)}'"})
                    current_command_idx += 1
                    continue

                if command_type_str == "EXECUTE" or command_type_str == "EXECUTE AND CONFIRM":
                    if command_type_str == "EXECUTE AND CONFIRM":
                        try:
                            confirm_ans: str = console.input(f"[dodger_blue1]Proceed with command: [hot_pink2]{command_to_run_actual}[/hot_pink2]? ([green1]y[/green1]/[bright_red]n[/bright_red])[/dodger_blue1]")
                        except KeyboardInterrupt:
                            console.print("[yellow]\nConfirmation cancelled by user.[/yellow]")
                            confirm_ans = "n"

                        if 'n' in confirm_ans.lower():
                            console.print("[yellow]Command skipped by user.[/yellow]")
                            messages_history.append({'role': 'system', 'content': f"Command SKIPPED by user: {command_to_run_actual}"})
                            current_command_idx += 1
                            continue

                    if command_to_run_actual.startswith("cd "):
                        target_dir: str = command_to_run_actual[3:].strip()
                        cd_result: str = change_directory(target_dir, console)
                        messages_history.append({'role': 'system', 'content': f"COMMAND: {command_to_run_actual}\nOUTPUT: {cd_result}"})
                    else:
                        status, stdout, stderr = command_executor.execute_command(command_to_run_actual)
                        messages_history.append({'role': 'system', 'content': f"COMMAND: {command_to_run_actual}\nSTATUS: {status}\nSTDOUT_CAPTURE: {stdout}\nSTDERR_CAPTURE: {stderr}"})

                        is_error: bool = not (status.startswith("Command executed successfully") or status.startswith("Interactive command") or status.startswith("Command interrupted by user"))
                        if is_error:
                            console.print(f"[bright_red]Error executing: '{command_to_run_actual}'\nStatus: {status}\nStderr from executor: {stderr}[/bright_red]")
                            try:
                                fix_ans_str: str = console.input("[dodger_blue1]Attempt to auto-fix this error? ([green1]y[/green1]/[bright_red]n[/bright_red])[/dodger_blue1]")
                            except KeyboardInterrupt:
                                console.print("[yellow]\nFix attempt cancelled by user.[/yellow]")
                                fix_ans_str = "n"

                            if 'y' in fix_ans_str.lower():
                                fixed_cmd_suggestion, updated_cmds_list = llm_handler.attempt_to_fix_command(
                                    original_command=command_to_run_actual, error_output=stderr if stderr else status,
                                    previous_llm_response_json=llm_response_json, failed_command_index=current_command_idx
                                )
                                if fixed_cmd_suggestion == "ANSWER":
                                    messages_history.append({'role': 'system', 'content': "LLM fix resulted in an explanation."})
                                elif updated_cmds_list:
                                    messages_history.append({'role': 'system', 'content': f"LLM Fix: New command sequence: {updated_cmds_list}"})
                                    commands_to_process = list(updated_cmds_list); current_command_idx = 0; continue
                                elif fixed_cmd_suggestion:
                                    messages_history.append({'role': 'system', 'content': f"LLM Fix: Retrying '{command_to_run_actual}' as '{fixed_cmd_suggestion}'"})
                                    commands_to_process[current_command_idx] = f"{command_type_str}: {fixed_cmd_suggestion}"
                                    continue
                                else:
                                    messages_history.append({'role': 'system', 'content': "LLM fix attempt yielded no actionable command."})
                            else: messages_history.append({'role': 'system', 'content': "User opted not to fix error."})
                elif command_type_str == "ANSWER":
                    console.print(f"[hot_pink2]{command_to_run_actual}[/hot_pink2]")
                    messages_history.append({'role': 'system', 'content': f"LLM Answer: {command_to_run_actual}"})
                elif command_type_str == "NOINFO":
                    console.print("[dodger_blue1]There is not enough information to execute the command. Please resend with more information.[/dodger_blue1]")
                    messages_history.append({'role': 'system', 'content': "LLM indicated NOINFO."})
                else:
                    console.print(f"[bright_red]Unknown command type from LLM: {command_type_str}[/bright_red]")
                    messages_history.append({'role': 'system', 'content': f"LLM output unknown command type: {command_type_str}"})
                current_command_idx += 1

            cache_config: Dict[str, Any] = cast(Dict[str, Any], app_settings.get("cache", {}))
            cleanup_interval_seconds: int = cast(int, app_settings.get("periodic_cleanup_interval_seconds", 15*60))
            if int(time.time()) % cleanup_interval_seconds == 0:
                llm_handler.periodic_cache_cleanup(days_to_keep=int(cache_config.get('expire_days', 30)))

        except KeyboardInterrupt: # Catch Ctrl+C during LLM/Command processing parts of the loop
            console.print("[yellow]\nOperation interrupted by user. Returning to prompt.[/yellow]")
            messages_history.append({'role': 'system', 'content': 'User interrupted operation during command processing.'})
            continue
        except EOFError:
            console.print("[dodger_blue1]\nExiting Exterminal due to EOF...[/dodger_blue1]")
            break
        except Exception as e_main_loop:
            console.print(f"[bold bright_red]An unexpected error occurred in the main loop: {e_main_loop}[/bold bright_red]")
            console.print_exception(show_locals=True, max_frames=2)
            messages_history.append({'role': 'system', 'content': f"FATAL ERROR in main loop: {e_main_loop}. Please check logs."})
            console.print("[yellow]Attempting to recover. Please try a new command or 'exit'.[/yellow]")
            continue

    console.print("[dim]Exterminal session ended.[/dim]")
