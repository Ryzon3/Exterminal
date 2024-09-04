## IDEA FOR APP ##
## SMART TERMINAL THAT EXECUTES HUMAN-READABLE COMMANDS ##
## EXAMPLE: "open google" -> opens google.com in browser ##
## EXAMPLE: "open terminal" -> opens terminal ##
## EXAMPLE: "open file" -> opens file explorer ##
## EXAMPLE: "Find file called 'example'" -> finds file called 'example' ##
## EXAMPLE: "Execute python script then parse output and find time" -> executes python script, parses output, and finds time ##

# Overall plan:
# 1. Run main.py from terminal
# 2. Listen for user input
# 3. Process in background and then display only relevant information to user
# 4. User can then interact with the terminal to get more information if needed
# 5. Store world-model in memory to keep track of user's context
# 6. LLM can call for specific terminal commands to update world-model or context for a command

# Neccesary parts:
# 1. We need an LLM to process user input and generate a command
# 2. We need a world-model to keep track of user's context
# 3. We need a way to execute terminal commands
# 4. We need a way to display information
# 5. We need a way for the user to interact and stop the program during execution (use async to run command in separate thread)


# Now let's start coding, we first will design a basic version without any of the above features

import json
import os
import subprocess
from openai import OpenAI
from dotenv import load_dotenv
# Import terminal color/formatting library
import rich

system_prompt = '''
You are the Exterminal system. Your job is to recognize user input and figure out how to exectute the commands in a Linux based terminal.
You will parse the user input and calculate your thoughts on it. You will through that then be able to execute several commands in a linux shell to execute the user's command.
You can also at any time check a world model for any information you might need.
If you don't find what you need you can execute a command to check the information yourself.
Thus the commands will be of the following format:
"EXECUTE: the command to be run in a shell"
"CHECK AND PAUSE: Do not pass any additional commands, just pause and rethink"
"EXECUTE AND PAUSE: the command to be run in a shell and then pause and rethink"
"ANSWER: A command to answer a user question"
"NOINFO: A command if the user doesn't provide enough information to execute the command"
Only add commands for the current user query, assume previous commands have been executed.
If the user query is 
You will output a json object with the following format:
{
    "thoughts": "Your thoughts on the user input and how to process and execute it",
    "world_model" (only update with important things to store): {
        "key": "value"
    },
    "commands": [
        Example1-> "EXECUTE: command1",
        Example2-> "NOINFO",
        Example3-> "CHECK AND PAUSE",
        Example3-> "EXECUTE AND PAUSE: command2",
    ]
}
'''

if __name__ == '__main__':
    load_dotenv()
    client = OpenAI()
    console = rich.console.Console(color_system="256")
    messages = [
        {'role': 'system', 'content': system_prompt},
    ]
    world_model = {}
    
    console.clear()
    console.print("[dodger_blue1]Welcome to [/dodger_blue1][b hot_pink2]Exterminal[/b hot_pink2][dodger_blue1]![/dodger_blue1]")
    console.print("[dodger_blue1 i]Type any command to execute it or type '[u bright_red]exit[/u bright_red]' to exit. [/dodger_blue1 i]")
    console.print("[dodger_blue1 i]Type '[u bright_red]clear[/u bright_red]' to clear the terminal. [/dodger_blue1 i]")
    console.print("[dodger_blue1 i]Type '[u bright_red]help[/u bright_red]' to get help. [/dodger_blue1 i]")
    console.print("")
    while True:
        inp = console.input("[dodger_blue1]Exterminal[/dodger_blue1] > ")
        world_model['directory'] = os.getcwd()
        world_model['files'] = os.listdir()
        # Trim messages if overall content is too long
        if sum([len(x['content']) for x in messages]) > 10000:
            messages = messages[0] + messages[-3:]
        
        if inp == "exit":
            console.print("[dodger_blue1]Exiting Exterminal...[/dodger_blue1]")
            break
        
        if inp == "clear":
            console.clear()
            messages = [
                {'role': 'system', 'content': system_prompt},
            ]
            continue
        
        if inp == "":
            continue
        
        if inp == "help":
            console.print("[dodger_blue1]Exterminal is a smart terminal that can execute human-readable commands.[/dodger_blue1]")
            console.print("[dodger_blue1]You can type any command and Exterminal will try to execute it for you.[/dodger_blue1]")
            console.print("[dodger_blue1]You can also type '[u bright_red]exit[/u bright_red]' to exit Exterminal or '[u bright_red]clear[/u bright_red]' to clear the terminal.[/dodger_blue1]")
            console.print("")
            continue
        
        msg = "WORLD_MODEL:\n" + str(world_model) + "\n\n\n" + "USER_INPUT" + inp
        messages.append({'role': 'user', 'content': inp})
        
        response = client.chat.completions.create(
            model='gpt-4o',
            response_format={ "type": "json_object" },
            messages=messages,
            temperature=0
        )
                
        # Parse output
        output = response.choices[0].message.content
        output = json.loads(output)
        
        error = None
        # Get all "EXECUTE" commands and run them
        for command in output['commands']:
            if "EXECUTE:" in command:
                command = command.replace("EXECUTE: ", "")
                console.print(f"[dodger_blue1]Running command:[/dodger_blue1] [hot_pink2]{command}[/hot_pink2]")

                # Run command here using subprocess and capture output
                result = subprocess.run(command, shell=True, capture_output=True)
                # Check if there was an error
                if result.returncode != 0:
                    # If there is an error pause execution and ask if user would like to auto fix or not
                    error = result.stderr.decode("utf-8")
                    break
                result = result.stdout.decode("utf-8")
                console.print(f"[dodger_blue1]Output:[/dodger_blue1] [hot_pink2]{result}[/hot_pink2]")
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
        if error:
            # Pause and ask user if they would like to auto fix the error
            console.print(f"[bright_red]Error:[/bright_red] {error}")
            ans = console.input("[dodger_blue1]An error occured while running the command.\nWould you like to auto fix it?([green1]y[/green1]/[bright_red]n[/bright_red])[/dodger_blue1]")
            if 'y' in ans.lower():
                # Auto fix the error
                console.print("[dodger_blue1]Auto fixing the error...[/dodger_blue1]")
        # Print output for testing
        # console.print(output)   
        
        
'''
Testing Exterminal commands and expected output:
1. "open google"
2. "open terminal"
3. "create a new file called 'test.py' and write 'print('Hello, World!')'"
'''