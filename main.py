import json
import os
import subprocess
from openai import OpenAI
from dotenv import load_dotenv
import rich
import rich.text
from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.formatted_text import HTML
import sqlite3
import time

class PromptCacheManager:
    def __init__(self, db_name='.exterminal_cache.db'):
        self.conn = sqlite3.connect(os.path.join(os.path.expanduser('~'), db_name))
        self.c = self.conn.cursor()
        
        # Create table for storing cached prompts
        self.c.execute('''CREATE TABLE IF NOT EXISTS prompt_cache
                         (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                          prompt TEXT UNIQUE, 
                          response TEXT, 
                          last_accessed TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        
        self.conn.commit()

    def save_prompt(self, prompt, response):
        """Save a new prompt-response pair"""
        self.c.execute("INSERT OR REPLACE INTO prompt_cache (prompt, response, last_accessed) VALUES (?, ?, ?)",
                      (prompt, response, time.time()))
        self.conn.commit()

    def get_cached_response(self, prompt):
        """Retrieve a cached response"""
        self.c.execute("SELECT * FROM prompt_cache WHERE UPPER(prompt)=UPPER(?)", (prompt,))
        result = self.c.fetchone()
        
        if result:
            # Update last accessed timestamp
            self.c.execute("UPDATE prompt_cache SET last_accessed = ? WHERE id = ?", (time.time(), result[0]))
            self.conn.commit()
            
            return json.loads(result[2]) if result[2] else None
        
        return None

    def remove_expired_entries(self):
        """Remove entries older than 30 days"""
        cutoff_time = time.time() - 30 * 24 * 60 * 60
        self.c.execute("DELETE FROM prompt_cache WHERE last_accessed < ?", (cutoff_time,))
        self.conn.commit()

    def close_connection(self):
        """Close the database connection"""
        self.conn.close()

    def __del__(self):
        """Automatically close the connection when the object is destroyed"""
        self.close_connection()


system_prompt = '''
You are the Exterminal system. Your job is to recognize user input and figure out how to exectute the commands in a Linux based terminal.
You will parse the user input and calculate your thoughts on it. You will through that then be able to execute several commands in a linux shell to execute the user's command.
Note the home directory is provided through the "world_model" object, and you can change the directory using the "cd" command.
Do not use '~' to represent the home directory, instead use the full path or relative path, the world model will have info for the path name.
Don't store temporary information in the world model, only store important information that will be used later.
If you don't find what you need you can execute a command to check the information yourself.
Ex: if you need info on what is in a file, you can use cat to output the file, then tell the user to 
ask again through an "ANSWER" command.
Note you can also use the "ANSWER" command to speak to the user, for more information, for more context,
or just to chat. (and more)
Thus the commands will be of the following format:
"EXECUTE: the command to be run in a shell"
"EXECUTE AND CONFIRM: the command to be run in a shell and ask user to confirm this command, pause if this command looks like it will have a big impact"
"ANSWER: A command to answer a user QUESTION"
"NOINFO: A command if the user doesn't provide enough information to execute the command"
Only add commands for the current user query, assume previous commands have been executed.
If the user query is 
You will output a json object with the following format:
{
    "thoughts": "Your thoughts on the user input and how to process and execute it",
    "world_model" (only update with important things to store, don't update current directory): {
        "key": value, can be a string, object, array, etc. The world is the limit.
    },
    "commands": [
        Example1-> "EXECUTE: command1",
        Example2-> "NOINFO:",
        Example3-> "EXECUTE AND CONFIRM: command2",
    ]
}
'''

def change_directory(new_dir):
    try:
        os.chdir(new_dir)
        return f"Directory changed to {new_dir}"
    except FileNotFoundError:
        return f"Directory '{new_dir}' not found"
    except PermissionError:
        return f"You do not have permission to access '{new_dir}'"


if __name__ == '__main__':
    load_dotenv()
    client = OpenAI()
    console = rich.console.Console(color_system="256")
    cache_manager = PromptCacheManager()
    
    session = PromptSession(
        HTML('<style fg="#d75faf">Exterminal > </style>'),
        history=FileHistory(os.path.join(os.path.expanduser('~'), ".exterminal_history")),
        auto_suggest=AutoSuggestFromHistory(),
    )
    
    messages = [
        {'role': 'system', 'content': system_prompt},
    ]
    world_model = {}
    
    console.clear()
    console.rule("[b hot_pink2]Exterminal[/b hot_pink2]", style="dodger_blue1")
    console.print("[dodger_blue1 i][b hot_pink2]Exterminal[/b hot_pink2] is a smart terminal that can execute human-readable commands, remember information, answer questions, and more![/dodger_blue1 i]")
    console.print("[dodger_blue1 i]Type any command to execute it or type '[u bright_red]exit[/u bright_red]' to exit. [/dodger_blue1 i]")
    console.print("[dodger_blue1 i]Type '[u bright_red]clear[/u bright_red]' to clear the terminal. [/dodger_blue1 i]")
    console.print("[dodger_blue1 i]Type '[u bright_red]help[/u bright_red]' to get help. [/dodger_blue1 i]")
    console.print("")
    while True:
        inp = session.prompt()
        world_model['directory'] = os.getcwd()
        world_model['directory contents'] = os.listdir()
        # Trim messages if overall content is too long
        while sum([len(x['content']) for x in messages]) > 10000:
            messages = messages[0:] + messages[1:]
        
        if inp == "exit" or inp == "e":
            console.print("[dodger_blue1]Exiting [b hot_pink2]Exterminal[/b hot_pink2]...[/dodger_blue1]")
            break
        
        if inp == "clear" or inp == "c":
            console.clear()
            console.rule("[b hot_pink2]Exterminal[/b hot_pink2]", style="dodger_blue1")
            messages = [
                {'role': 'system', 'content': system_prompt},
            ]
            continue
        
        if inp == "":
            continue
        
        if inp == 'wm' or inp == 'world_model':
            console.print("[dodger_blue1]World Model:[/dodger_blue1]")
            console.print(world_model, style="hot_pink2")
            console.print("")
            continue
        
        if inp == 'messages':
            console.print("[dodger_blue1]Messages:[/dodger_blue1]")
            console.print(messages[1:], style="hot_pink2")
            console.print("")
            continue
        
        if inp == "help" or inp == "h":
            console.print("[dodger_blue1 i][b hot_pink2]Exterminal[/b hot_pink2] is a smart terminal that can execute human-readable commands, remember information, answer questions, and more![/dodger_blue1 i]")
            console.print("[dodger_blue1]You can type any command and [b hot_pink2]Exterminal[/b hot_pink2] will try to execute it for you.[/dodger_blue1]")
            console.print("[dodger_blue1]You can also type '[u bright_red]exit[/u bright_red]' to exit [b hot_pink2]Exterminal[/b hot_pink2] or '[u bright_red]clear[/u bright_red]' to clear the terminal.[/dodger_blue1]")
            console.print("")
            continue
        
        msg = "WORLD_MODEL:\n" + str(world_model) + "\n\n\n" + "USER_INPUT" + inp
        messages.append({'role': 'user', 'content': inp})
        
        output = cache_manager.get_cached_response(inp)
        
        if not output:
            with console.status("Querying LLM...", spinner="bouncingBall", spinner_style="hot_pink2"):
                response = client.chat.completions.create(
                    model='gpt-4o-2024-08-06',
                    response_format={ "type": "json_object" },
                    messages=messages,
                    temperature=0
                )
                # Parse output
                output = response.choices[0].message.content
                cache_manager.save_prompt(inp, output)
                output = json.loads(output)
        
        # Update world model
        if 'world_model' in output:
            world_model.update(output['world_model'])
        
        error = None
        # Get all "EXECUTE" commands and run them
        for command in output['commands']:
            if "EXECUTE" in command and 'cd' in command:
                command = command.replace("EXECUTE: ", "")
                command = command.replace("EXECUTE AND CONFIRM: ", "")
                if 'cd' in command[:2]:
                    command = command.replace("cd ", "")
                    console.print(f"[dodger_blue1]Changing directory to:[/dodger_blue1] [hot_pink2]{command}[/hot_pink2]")
                    result = change_directory(command)
                    console.print(f"[dodger_blue1]Output:[/dodger_blue1]\n[hot_pink2]{result}[/hot_pink2]")
                    messages.append({'role': 'assistant', 'content': f"COMMAND: {command}\nOUTPUT: {result}"})
            elif "EXECUTE:" in command:
                command = command.replace("EXECUTE: ", "")
                console.print(f"[dodger_blue1]Running command:[/dodger_blue1] [hot_pink2]{command}[/hot_pink2]")

                # Run command here using subprocess and capture output
                with console.status("Output: \n", spinner="bouncingBall", spinner_style="hot_pink2"):
                    result = subprocess.run(command, shell=True, capture_output=True)
                # Check if there was an error
                if result.returncode != 0:
                    # If there is an error pause execution and ask if user would like to auto fix or not
                    error = result.stderr.decode("utf-8")
                    break
                result = result.stdout.decode("utf-8")
                if result == "":
                    result = "Command executed successfully."
                console.print(f"[dodger_blue1]Output:[/dodger_blue1]\n[hot_pink2]{result}[/hot_pink2]")
                messages.append({'role': 'assistant', 'content': f"COMMAND: {command}\nOUTPUT: {result}"})
            elif "ANSWER:" in command:
                command = command.replace("ANSWER: ", "")
                console.print(f"[hot_pink2]{command}[/hot_pink2]")
                messages.append({'role': 'assistant', 'content': f"ANSWER: {command}"})
            elif "NOINFO" in command:
                # Tell the user that there is not enough information to execute the command and Please resend the command with more information or a different command
                console.print("[dodger_blue1]There is not enough information to execute the command. Please resend the command with more information or a different command.[/dodger_blue1]")
                console.print("")
                messages.append({'role': 'assistant', 'content': "NOINFO"})
            elif "EXECUTE AND CONFIRM" in command:
                command = command.replace("EXECUTE AND CONFIRM: ", "")
                # Ask user to confirm the command
                ans = console.input(f"[dodger_blue1]Would you like to run the command: [hot_pink2]{command}[/hot_pink2]? ([green1]y[/green1]/[bright_red]n[/bright_red])[/dodger_blue1]")
                if 'n' in ans.lower():
                    # skip the command
                    messages.append({'role': 'assistant', 'content': f"SKIPPED: {command}"})
                    continue
                # run the command
                console.print(f"[dodger_blue1]Running command:[/dodger_blue1] [hot_pink2]{command}[/hot_pink2]")
                # Run command here using subprocess and capture output
                with console.status("Output: \n", spinner="bouncingBall", spinner_style="hot_pink2"):
                    result = subprocess.run(command, shell=True, capture_output=True)
                # Check if there was an error
                if result.returncode != 0:
                    # If there is an error pause execution and ask if user would like to auto fix or not
                    error = result.stderr.decode("utf-8")
                    break
                result = result.stdout.decode("utf-8")
                if result == "":
                    result = "Command executed successfully."
                console.print(f"[dodger_blue1]Output:[/dodger_blue1]\n[hot_pink2]{result}[/hot_pink2]")
                messages.append({'role': 'assistant', 'content': f"COMMAND: {command}\nOUTPUT: {result}"})
        if error:
            # Pause and ask user if they would like to auto fix the error
            console.print(f"[bright_red]Error:[/bright_red] {error}")
            ans = console.input("[dodger_blue1]An error occured while running the command.\nWould you like to auto fix it?([green1]y[/green1]/[bright_red]n[/bright_red])[/dodger_blue1]")
            if 'y' in ans.lower():
                # Auto fix the error
                console.print("[dodger_blue1]Auto fixing the error...[/dodger_blue1]")
        
        if int(time.time()) == 0:
            cache_manager.remove_expired_entries()

        # Print output for testing
        # console.print(output)   
