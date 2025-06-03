"""
Handles all interactions with the Language Model (LLM), including
prompt construction, API calls, response parsing, caching, and error fixing suggestions.
"""
import json
import os
import sqlite3
import time
import openai # Import the base openai module for its error types
from openai import OpenAI # Client
from openai.types.chat import ChatCompletion
from rich.console import Console
from typing import List, Dict, Optional, Tuple, Any 

# --- PromptCacheManager Class ---
class PromptCacheManager:
    """
    Manages a local SQLite cache for LLM prompts and their responses
    to reduce API calls and speed up repeated queries.
    """
    def __init__(self, console: Console, db_name: str = '.exterminal_cache.db'):
        """
        Initializes the PromptCacheManager and creates the cache table if it doesn't exist.

        Args:
            console: The Rich Console object for logging messages.
            db_name: The name of the SQLite database file.
        """
        self.console: Console = console
        self.conn: Optional[sqlite3.Connection] = None
        self.cursor: Optional[sqlite3.Cursor] = None
        try:
            db_path: str = os.path.join(os.path.expanduser('~'), db_name)
            self.conn = sqlite3.connect(db_path)
            self.cursor = self.conn.cursor()
            self.cursor.execute('''CREATE TABLE IF NOT EXISTS prompt_cache
                                 (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                                  prompt TEXT UNIQUE, 
                                  response TEXT, 
                                  last_accessed TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
            self.conn.commit()
        except sqlite3.Error as e:
            self.console.print(f"[bright_red]SQLite Error initializing PromptCacheManager ({db_name}): {e}[/bright_red]")
            if self.conn:
                self.conn.close() 
            self.conn = None 
            self.cursor = None

    def save_prompt(self, prompt: str, response: str) -> None:
        """
        Saves a prompt and its corresponding LLM response to the cache.
        If the prompt already exists, it's updated.

        Args:
            prompt: The user prompt string.
            response: The LLM's response string (typically raw JSON).
        """
        if not self.conn or not self.cursor:
            self.console.print("[dim bright_red]Cache database not available. Skipping save.[/dim]")
            return
        try:
            self.cursor.execute("INSERT OR REPLACE INTO prompt_cache (prompt, response, last_accessed) VALUES (?, ?, ?)",
                               (prompt, response, time.time()))
            self.conn.commit()
        except sqlite3.Error as e:
            self.console.print(f"[bright_red]SQLite Error saving prompt to cache: {e}[/bright_red]")

    def get_cached_response(self, prompt: str) -> Optional[Dict[str, Any]]:
        """
        Retrieves a cached LLM response for a given prompt.
        Updates the last_accessed timestamp if a cached entry is found.

        Args:
            prompt: The user prompt string.

        Returns:
            The parsed JSON response as a dictionary if found in cache, otherwise None.
        """
        if not self.conn or not self.cursor:
            self.console.print("[dim bright_red]Cache database not available. Skipping lookup.[/dim]")
            return None
        try:
            self.cursor.execute("SELECT id, response FROM prompt_cache WHERE UPPER(prompt)=UPPER(?)", (prompt,))
            result: Optional[tuple[int, str]] = self.cursor.fetchone()
            
            if result:
                cache_id, response_str = result
                self.cursor.execute("UPDATE prompt_cache SET last_accessed = ? WHERE id = ?", (time.time(), cache_id))
                self.conn.commit()
                return json.loads(response_str) if response_str else None
        except sqlite3.Error as e:
            self.console.print(f"[bright_red]SQLite Error getting cached response: {e}[/bright_red]")
        except json.JSONDecodeError as e:
            self.console.print(f"[bright_red]JSON Decode Error reading cached response: {e}[/bright_red]")
        return None

    def remove_expired_entries(self, days_to_keep: int = 30) -> None:
        """
        Removes cache entries older than a specified number of days.

        Args:
            days_to_keep: The number of days to retain cache entries.
        """
        if not self.conn or not self.cursor:
            self.console.print("[dim bright_red]Cache database not available. Skipping cleanup.[/dim]")
            return
        try:
            cutoff_time: float = time.time() - days_to_keep * 24 * 60 * 60
            self.cursor.execute("DELETE FROM prompt_cache WHERE last_accessed < ?", (cutoff_time,))
            self.conn.commit()
        except sqlite3.Error as e:
            self.console.print(f"[bright_red]SQLite Error removing expired cache entries: {e}[/bright_red]")

    def close_connection(self) -> None:
        """Closes the database connection if it's open."""
        if self.conn:
            try:
                self.conn.close()
            except sqlite3.Error as e:
                 self.console.print(f"[bright_red]SQLite Error closing connection: {e}[/bright_red]")
            finally:
                self.conn = None
                self.cursor = None

    def __del__(self) -> None:
        """Ensures the database connection is closed when the object is deleted."""
        self.close_connection()

# --- LLMHandler Class ---
class LLMHandler:
    """
    Handles all interactions with the Language Model (LLM), including API calls,
    prompt construction, response parsing, caching, and suggesting fixes for errors.
    """
    def __init__(self, console: Console, model_name: str, temperature: float, system_prompt: str, cache_db_name: str = '.exterminal_cache.db'):
        self.console: Console = console
        self.model_name: str = model_name
        self.temperature: float = temperature
        self.system_prompt: str = system_prompt
        try:
            self.client: OpenAI = OpenAI() 
        except openai.OpenAIError as e: # More general OpenAI client init error
            self.console.print(f"[bright_red]Failed to initialize OpenAI client: {e}. Check API key and environment.[/bright_red]")
            # Potentially re-raise or set client to None and handle in methods
            raise # Re-raise for now, main.py might catch it or exit
        self.cache_manager: PromptCacheManager = PromptCacheManager(console, db_name=cache_db_name)
        
        self.error_fix_system_prompt: str = '''
You are a repair technician for Exterminal. Your job is to fix any errors that occur while running commands in the terminal.
You will only be able to fix errors that are caused by the commands themselves, not user errors.
You can only fix errors that are caused by the current command or future commands, not past commands.
If the error is not fixable then you will instead only output 1 command that is a "ANSWER:" command explaining it.
You will be given 3 things as input:
1. The error that occurred while running the command.
2. The command that caused the error.
3. The exterminal system's thoughts and command chains (from the main LLM interaction).

You will output a json object with the following format:
{
    "thoughts": "Your thoughts on the error and how to fix it",
    "commands": [ 
        "EXECUTE: command1", 
        "EXECUTE AND CONFIRM: command2",
        "ANSWER: Your explanation if not fixable"
    ]
}
'''

    def _make_llm_api_call(self, messages_for_llm: List[Dict[str,str]], context_str: str = "main LLM query") -> Optional[Dict[str, Any]]:
        """ Helper method to make the actual API call and handle common errors. """
        output_text: Optional[str] = None
        try:
            with self.console.status(f"[dim]Querying LLM for {context_str}...", spinner="bouncingBall", spinner_style="hot_pink2"):
                response: ChatCompletion = self.client.chat.completions.create(
                    model=self.model_name,
                    response_format={"type": "json_object"},
                    messages=messages_for_llm, # type: ignore 
                    temperature=self.temperature
                )
            output_text = response.choices[0].message.content
            if output_text:
                return json.loads(output_text)
            else:
                self.console.print(f"[bright_red]LLM returned an empty response for {context_str}.[/bright_red]")
                return None
        except json.JSONDecodeError as e:
            self.console.print(f"[bright_red]Failed to parse LLM JSON response for {context_str}: {e}[/bright_red]")
            self.console.print(f"[dim]Raw response: {output_text if output_text is not None else 'N/A'}[/dim]")
            return None
        except openai.RateLimitError as e:
            self.console.print(f"[bright_red]OpenAI API request exceeded rate limit for {context_str}: {e}[/bright_red]")
            return None
        except openai.AuthenticationError as e:
            self.console.print(f"[bright_red]OpenAI API authentication failed for {context_str}: {e}. Check your API key.[/bright_red]")
            return None
        except openai.APIConnectionError as e:
            self.console.print(f"[bright_red]OpenAI API connection error for {context_str}: {e}. Check your network.[/bright_red]")
            return None
        except openai.Timeout as e:
            self.console.print(f"[bright_red]OpenAI API request timed out for {context_str}: {e}[/bright_red]")
            return None
        except openai.APIError as e: # Catch other OpenAI API errors
            self.console.print(f"[bright_red]OpenAI API Error for {context_str}: {e}[/bright_red]")
            return None
        except Exception as e: # Catch any other unexpected error during API call
            self.console.print(f"[bright_red]Unexpected error querying LLM for {context_str}: {e}[/bright_red]")
            return None


    def get_llm_response(self, 
                         messages_history: List[Dict[str, str]], 
                         current_user_input: str, 
                         world_model: Dict[str, Any], 
                         force_new_response: bool = False) -> Optional[Dict[str, Any]]:
        if not force_new_response:
            cached_output: Optional[Dict[str, Any]] = self.cache_manager.get_cached_response(current_user_input)
            if cached_output:
                self.console.print("[dim]Using cached LLM response.[/dim]")
                return cached_output
        
        temp_history = messages_history[:] 
        # Basic character count trimming, TODO: use token counting
        while sum(len(msg.get('content', '')) for msg in temp_history) > 50000: 
            if len(temp_history) > 0: temp_history.pop(0)
            else: break 

        user_message_content: str = f"WORLD_MODEL:\n{json.dumps(world_model)}\n\nUSER_INPUT:\n{current_user_input}"
        full_messages_for_llm: List[Dict[str, str]] = [
            {'role': 'system', 'content': self.system_prompt}
        ] + temp_history + [{'role': 'user', 'content': user_message_content}]

        parsed_output = self._make_llm_api_call(full_messages_for_llm, "main Exterminal query")
        
        if parsed_output and isinstance(parsed_output.get("commands"), list): # Basic validation of response structure
            # Cache the raw JSON string that led to the parsed_output
            # This assumes _make_llm_api_call would return the raw string if we needed to save it,
            # but currently it returns parsed. For simplicity, we re-serialize.
            # A more robust way would be for _make_llm_api_call to return (raw_text, parsed_dict)
            try:
                raw_output_to_cache = json.dumps(parsed_output)
                self.cache_manager.save_prompt(current_user_input, raw_output_to_cache)
            except TypeError as e:
                self.console.print(f"[bright_red]Error serializing LLM response for caching: {e}[/bright_red]")
            return parsed_output
        elif parsed_output: # It's JSON but not the expected structure
             self.console.print(f"[bright_red]LLM response received but not in expected Exterminal format: {parsed_output}[/bright_red]")
             return None # Or return the parsed_output if main can handle it
        return None


    def attempt_to_fix_command(self, 
                               original_command: str, 
                               error_output: str, 
                               previous_llm_response_json: Dict[str, Any], 
                               failed_command_index: int) -> Tuple[Optional[str], Optional[List[str]]]:
        self.console.print("[yellow]Attempting to auto-fix the error...[/yellow]")
        repair_messages: List[Dict[str, str]] = [
            {'role': 'system', 'content': self.error_fix_system_prompt},
            {'role': 'user', 'content': f"The Exterminal system produced the following thoughts and command sequence:\nThoughts: {previous_llm_response_json.get('thoughts', 'N/A')}\nCommands: {json.dumps(previous_llm_response_json.get('commands', []))}"},
            {'role': 'user', 'content': f"The following error occurred when trying to execute a command:\n{error_output}"},
            {'role': 'user', 'content': f"The command that failed was (index {failed_command_index}):\n{original_command}"},
        ]
        
        fixed_output = self._make_llm_api_call(repair_messages, "error fix query")

        if not fixed_output:
            return None, None # Error already printed by _make_llm_api_call
            
        new_commands_sequence: Optional[List[str]] = fixed_output.get("commands")
        if not new_commands_sequence or not isinstance(new_commands_sequence, list) or not new_commands_sequence:
            self.console.print("[yellow]LLM fix did not provide a valid new command sequence.[/yellow]")
            return None, None

        if "ANSWER:" in new_commands_sequence[0]:
             self.console.print(f"[yellow]LLM Fix Response:[/yellow] {new_commands_sequence[0].replace('ANSWER: ', '').strip()}")
             return "ANSWER", new_commands_sequence 

        suggested_command_str_at_index: Optional[str] = None
        if failed_command_index < len(new_commands_sequence):
            raw_cmd_from_llm: str = new_commands_sequence[failed_command_index]
            cmd_prefix_exec: str = "EXECUTE: "
            cmd_prefix_confirm: str = "EXECUTE AND CONFIRM: "
            if raw_cmd_from_llm.startswith(cmd_prefix_exec):
                suggested_command_str_at_index = raw_cmd_from_llm[len(cmd_prefix_exec):]
            elif raw_cmd_from_llm.startswith(cmd_prefix_confirm):
                suggested_command_str_at_index = raw_cmd_from_llm[len(cmd_prefix_confirm):]
        
        self.console.print("[green1]LLM proposed a fix.[/green1]")
        if fixed_output.get("thoughts"):
             self.console.print(f"[dim]Fixer thoughts: {fixed_output['thoughts']}[/dim]")
        return suggested_command_str_at_index, new_commands_sequence

    def periodic_cache_cleanup(self, days_to_keep: int = 30) -> None:
        self.cache_manager.remove_expired_entries(days_to_keep)

if __name__ == '__main__':
    console = Console()
    system_prompt_content_for_test: str = "You are a helpful assistant outputting JSON."
    # ... (rest of __main__ remains for testing, ensure it uses updated methods) ...
    try:
        with open("system_prompt.txt", "r") as f: 
            system_prompt_content_for_test = f.read()
    except FileNotFoundError:
        console.print("[yellow]system_prompt.txt not found for test, using basic fallback.[/yellow]")

    try:
        llm_handler = LLMHandler(console, model_name="gpt-4o", temperature=0, system_prompt=system_prompt_content_for_test)
        
        console.rule("Test 1: Get LLM Response (mocked messages)")
        # ... (tests as before)
    except openai.OpenAIError as e:
         console.print(f"[bright_red]Skipping LLMHandler tests due to OpenAI client initialization error: {e}[/bright_red]")
    except Exception as e:
        console.print(f"[bright_red]Skipping LLMHandler tests due to an unexpected error: {e}[/bright_red]")

    pass # Keep pass if tests are conditional
