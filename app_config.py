"""
Manages application configuration, loading settings from a YAML file
and providing default values.
"""
import yaml
import os
from rich.console import Console
from typing import Dict, Any, cast

_console = Console() 

DEFAULT_FALLBACK_SYSTEM_PROMPT: str = "You are a helpful AI assistant. Please provide responses in JSON format."

DEFAULT_CONFIG: Dict[str, Any] = {
    "llm": {
        "model_name": "gpt-4o",
        "temperature": 0.0,
        "system_prompt_file": "system_prompt.txt",
    },
    "cache": {
        "db_name": ".exterminal_cache.db",
        "expire_days": 30,
    },
    "system_prompt_content": DEFAULT_FALLBACK_SYSTEM_PROMPT,
}

def load_config(config_path: str = "config.yaml") -> Dict[str, Any]:
    """
    Loads application configuration from a YAML file, merging it with default settings.

    If the specified configuration file does not exist, a new one is created with
    default values. The `system_prompt_content` is loaded from the file path
    specified in `llm.system_prompt_file`. If the prompt file cannot be read,
    a fallback system prompt is used.

    Args:
        config_path: The path to the YAML configuration file.

    Returns:
        A dictionary containing the application settings.
    """
    config: Dict[str, Any] = {
        "llm": DEFAULT_CONFIG["llm"].copy(),
        "cache": DEFAULT_CONFIG["cache"].copy(),
        "system_prompt_content": DEFAULT_CONFIG["system_prompt_content"]
    }

    if os.path.exists(config_path):
        try:
            with open(config_path, 'r') as f:
                user_config: Dict[str, Any] = yaml.safe_load(f)
            if user_config:
                if "llm" in user_config and isinstance(user_config["llm"], dict):
                    config["llm"].update(user_config["llm"])
                elif "llm" in user_config:
                    config["llm"] = user_config["llm"]
                
                if "cache" in user_config and isinstance(user_config["cache"], dict):
                    config["cache"].update(user_config["cache"])
                elif "cache" in user_config:
                     config["cache"] = user_config["cache"]
                
                for key, value in user_config.items():
                    if key not in ["llm", "cache"] and key not in config: 
                        config[key] = value
                _console.print(f"[green]Loaded configuration from {config_path}[/green]")
        except (yaml.YAMLError, TypeError) as e: # Catch YAML parsing errors or if content is not dict-like
            _console.print(f"[bright_red]Error parsing {config_path}: {e}. Using default settings for file values.[/bright_red]")
        except FileNotFoundError: # Should not happen due to os.path.exists, but good for robustness
            _console.print(f"[bright_red]Config file {config_path} not found unexpectedly. Using defaults.[/bright_red]")
        except PermissionError as e:
            _console.print(f"[bright_red]Permission denied reading {config_path}: {e}. Using defaults.[/bright_red]")
        except IOError as e: # Catch other I/O errors
            _console.print(f"[bright_red]I/O error reading {config_path}: {e}. Using defaults.[/bright_red]")
        except Exception as e: # Catch any other unexpected error during loading
            _console.print(f"[bright_red]Unexpected error loading {config_path}: {e}. Using defaults.[/bright_red]")
    else:
        _console.print(f"[yellow]{config_path} not found. Creating with default settings.[/yellow]")
        try:
            config_to_dump: Dict[str, Any] = {
                "llm": config["llm"].copy(), 
                "cache": config["cache"].copy(),
            }
            with open(config_path, 'w') as f:
                yaml.dump(config_to_dump, f, default_flow_style=False, sort_keys=False)
            _console.print(f"[yellow]Default configuration saved to {config_path}. Please review and customize if needed.[/yellow]")
        except (IOError, PermissionError, yaml.YAMLError) as e: # Catch errors during default config writing
            _console.print(f"[bright_red]Error creating default {config_path}: {e}[/bright_red]")
        except Exception as e:
             _console.print(f"[bright_red]Unexpected error creating default {config_path}: {e}[/bright_red]")


    llm_config: Dict[str, Any] = cast(Dict[str, Any], config.get("llm", DEFAULT_CONFIG["llm"]))
    prompt_file_path: str = llm_config.get("system_prompt_file", DEFAULT_CONFIG["llm"]["system_prompt_file"])
    
    try:
        with open(prompt_file_path, 'r') as f:
            config["system_prompt_content"] = f.read()
    except FileNotFoundError:
        _console.print(f"[bright_red]System prompt file '{prompt_file_path}' not found. Using fallback prompt.[/bright_red]")
        config["system_prompt_content"] = DEFAULT_FALLBACK_SYSTEM_PROMPT
    except PermissionError as e:
        _console.print(f"[bright_red]Permission denied reading system prompt file '{prompt_file_path}': {e}. Using fallback.[/bright_red]")
        config["system_prompt_content"] = DEFAULT_FALLBACK_SYSTEM_PROMPT
    except IOError as e:
        _console.print(f"[bright_red]I/O error reading system prompt file '{prompt_file_path}': {e}. Using fallback.[/bright_red]")
        config["system_prompt_content"] = DEFAULT_FALLBACK_SYSTEM_PROMPT
    except Exception as e:
        _console.print(f"[bright_red]Unexpected error reading system prompt file '{prompt_file_path}': {e}. Using fallback.[/bright_red]")
        config["system_prompt_content"] = DEFAULT_FALLBACK_SYSTEM_PROMPT
    
    return config

if __name__ == '__main__':
    _console.rule("Testing Configuration Loading")
    settings = load_config()
    _console.print("\n[b]Current Effective Configuration (system prompt truncated):[/b]")
    test_display_settings = {
        k: (v[:100] + "..." if k == "system_prompt_content" and isinstance(v, str) and len(v) > 100 else v) 
        for k, v in settings.items()
    }
    _console.print(test_display_settings)

    dummy_config_path = "dummy_config_for_test.yaml"
    if os.path.exists(dummy_config_path): os.remove(dummy_config_path)
    
    _console.print(f"\n[b]Testing with non-existent '{dummy_config_path}'.[/b]")
    load_config(dummy_config_path) 
    if os.path.exists(dummy_config_path):
        with open(dummy_config_path, 'r') as f:
            _console.print(f"[dim]Contents of created '{dummy_config_path}':[/dim]\n{f.read()}")
        os.remove(dummy_config_path)

    custom_prompt_file_content: str = "Custom prompt for testing."
    custom_prompt_filename: str = "custom_test_prompt_appconfig.txt"
    with open(custom_prompt_filename, "w") as f: f.write(custom_prompt_file_content)
    
    dummy_user_config_content: str = f"""
llm:
  system_prompt_file: {custom_prompt_filename}
  model_name: "gpt-3.5-turbo-test"
cache:
  expire_days: 10
"""
    with open(dummy_config_path, "w") as f: f.write(dummy_user_config_content)
        
    _console.print(f"\n[b]Testing loading from '{dummy_config_path}' with custom settings:[/b]")
    custom_settings: Dict[str, Any] = load_config(dummy_config_path)
    
    assert custom_settings["system_prompt_content"] == custom_prompt_file_content
    assert custom_settings.get("llm", {}).get("model_name") == "gpt-3.5-turbo-test"
    assert custom_settings.get("cache", {}).get("expire_days") == 10
    _console.print("[green]Custom settings loaded and asserted correctly.[/green]")

    if os.path.exists(dummy_config_path): os.remove(dummy_config_path)
    if os.path.exists(custom_prompt_filename): os.remove(custom_prompt_filename)
    _console.print(f"\n[dim]Cleaned up dummy test files.[/dim]")
    _console.rule()
    pass
