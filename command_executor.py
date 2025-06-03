"""
Handles the execution of shell commands, supporting both standard subprocesses
and PTY-based interactive sessions.
"""
import subprocess
import os
import sys
import threading
import signal
import ptyprocess # For PTY-specific exceptions, if any beyond generic OSError
import select
from rich.console import Console
from typing import Tuple, List, Optional, Any

class CommandExecutor:
    """
    Manages the execution of commands, including routing to PTY or standard
    subprocess, handling I/O, and managing interrupts.
    """
    def __init__(self, console: Console):
        """
        Initializes the CommandExecutor.

        Args:
            console: The Rich Console object for output.
        """
        self.console: Console = console
        self.interactive_commands: List[str] = ["python", "nano", "vim", "vi", "ssh", "htop"]

    def execute_command(self, command_str: str) -> Tuple[str, str, str]:
        """
        Executes a given command string, deciding whether to use PTY or a standard subprocess.
        """
        command_parts: List[str] = command_str.split()
        if not command_parts:
            return "Error: Empty command string.", "", ""

        is_interactive: bool = command_parts[0] in self.interactive_commands

        if is_interactive:
            return self._execute_pty(command_str, command_parts)
        else:
            return self._execute_subprocess(command_str)

    def _execute_pty(self, command_str: str, command_parts: List[str]) -> Tuple[str, str, str]:
        """
        Executes a command using a pseudo-terminal (PTY).
        """
        self.console.print(f"[cyan]Starting interactive PTY command:[/cyan] [hot_pink2]{command_str}[/hot_pink2]")
        pty_process: Optional[ptyprocess.PtyProcess] = None
        output_thread: Optional[threading.Thread] = None
        pty_stdout_capture: List[str] = []

        try:
            # ptyprocess.PtyProcess.spawn can raise ptyprocess.PtyProcessError or other OS errors
            pty_process = ptyprocess.PtyProcess.spawn(command_parts)

            def read_pty_output() -> None:
                if pty_process is None: return
                try:
                    while pty_process.isalive():
                        readable, _, _ = select.select([pty_process.fd], [], [], 0.1)
                        if readable:
                            try:
                                output_bytes: bytes = os.read(pty_process.fd, 1024)
                                if output_bytes:
                                    output_str: str = output_bytes.decode(errors='replace')
                                    self.console.print(output_str, end='')
                                    pty_stdout_capture.append(output_str)
                                else: break
                            except EOFError: break
                            except OSError as e_os_read: # Can happen if FD is closed during/before read
                                self.console.print(f"[dim bright_red]PTY read OSError: {e_os_read}[/dim]")
                                break
                except Exception as e_thread:
                    self.console.print(f"[dim bright_red]PTY output thread error: {e_thread}[/dim]")
                    pass

            output_thread = threading.Thread(target=read_pty_output)
            output_thread.daemon = True
            output_thread.start()

            self.console.print(f"[yellow]Entering interactive session for '{command_str}'. Type Ctrl+D to exit (or command-specific exit).[/yellow]")

            while pty_process and pty_process.isalive():
                try:
                    rlist, _, _ = select.select([sys.stdin], [], [], 0.1)
                    if rlist:
                        user_input: str = sys.stdin.readline()
                        if not user_input:
                            self.console.print("[yellow]Ctrl+D received, attempting to close PTY input.[/yellow]")
                            try:
                                if pty_process.isalive(): pty_process.sendeof()
                            except OSError as e_sendeof: # On some systems, PTY might be already closed
                                self.console.print(f"[dim bright_red]Error sending EOF to PTY (OSError): {e_sendeof}[/dim]")
                            except Exception as e_eof_generic:
                                self.console.print(f"[bright_red]Error sending EOF to PTY: {e_eof_generic}[/bright_red]")
                            break
                        if pty_process.isalive(): pty_process.write(user_input.encode())
                except KeyboardInterrupt:
                    self.console.print("[yellow]Ctrl+C received, sending SIGINT to PTY process.[/yellow]")
                    try:
                        if pty_process.isalive(): pty_process.sendintr()
                    except Exception as e_intr:
                        self.console.print(f"[bright_red]Error sending SIGINT to PTY: {e_intr}[/bright_red]")
                except EOFError:
                    self.console.print("[yellow]EOFError on stdin, exiting interactive session.[/yellow]")
                    break
                except IOError as e_io_input: # Catch specific I/O errors on input
                    self.console.print(f"[bright_red]Input forwarding I/O error: {e_io_input}[/bright_red]")
                    break
                except Exception as e_input_generic:
                    self.console.print(f"[bright_red]Input forwarding error: {e_input_generic}[/bright_red]")
                    break

            self.console.print(f"\n[yellow]Interactive session for '{command_str}' ended.[/yellow]")

            exit_status: Optional[int] = -1 # Default if wait fails or pty_process is None
            if pty_process:
                if pty_process.isalive():
                    try:
                        pty_process.close(force=True)
                    except Exception as e_close_pty: # ptyprocess might raise errors on close
                        self.console.print(f"[dim bright_red]Error during PTY close: {e_close_pty}[/dim]")
                try:
                    exit_status = pty_process.wait()
                except ptyprocess.PtyProcessError as e_wait: # Catch error during wait
                     self.console.print(f"[dim bright_red]Error waiting for PTY process: {e_wait}[/dim]")


            if output_thread and output_thread.is_alive():
                output_thread.join(timeout=0.5) # Shorter timeout for cleanup

            final_pty_output: str = "".join(pty_stdout_capture)
            if exit_status == 0:
                return f"Interactive command '{command_str}' finished.", final_pty_output, ""
            else:
                return f"Interactive command '{command_str}' finished with exit code {exit_status}.", final_pty_output, ""

        except FileNotFoundError as e_fnf: # Command not found
            self.console.print(f"[bright_red]Error: Command '{command_parts[0]}' not found for PTY execution: {e_fnf}[/bright_red]")
            return f"Error: Command not found '{command_parts[0]}'.", "", str(e_fnf)
        except PermissionError as e_perm: # Permission denied for command
            self.console.print(f"[bright_red]Error: Permission denied for PTY command '{command_parts[0]}': {e_perm}[/bright_red]")
            return f"Error: Permission denied for '{command_parts[0]}'.", "", str(e_perm)
        except ptyprocess.PtyProcessError as e_pty_general: # General ptyprocess error
            self.console.print(f"[bright_red]PTY Process Error for '{command_str}': {e_pty_general}[/bright_red]")
            return f"PTY process error for '{command_str}': {str(e_pty_general)}", "", str(e_pty_general)
        except Exception as e_generic_pty: # Catch-all for other unexpected PTY issues
            self.console.print(f"[bright_red]Generic PTY execution error for '{command_str}': {e_generic_pty}[/bright_red]")
            if pty_process and pty_process.isalive():
                try: pty_process.close(force=True)
                except: pass
            if output_thread and output_thread.is_alive(): output_thread.join(timeout=0.5)
            return f"Error running interactive command '{command_str}': {str(e_generic_pty)}", "".join(pty_stdout_capture), str(e_generic_pty)
        finally:
            pass # Terminal restoration would go here

    def _execute_subprocess(self, command_str: str) -> Tuple[str, str, str]:
        """
        Executes a command using a standard subprocess.Popen.
        """
        process: Optional[subprocess.Popen[str]] = None
        full_stdout_list: List[str] = []
        full_stderr_list: List[str] = []

        try:
            self.console.print(f"[dodger_blue1]Running command:[/dodger_blue1] [hot_pink2]{command_str}[/hot_pink2]")

            process = subprocess.Popen(
                command_str, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, bufsize=1, executable="/bin/bash" # Explicitly use bash
            )

            if process.stdout:
                for line in iter(process.stdout.readline, ''):
                    self.console.print(f"[dodger_blue1]Output:[/dodger_blue1] {line.strip()}")
                    full_stdout_list.append(line)
                process.stdout.close()

            if process.stderr:
                for line in iter(process.stderr.readline, ''): # Ensure stderr is also fully read
                    self.console.print(f"[bright_red]Error Output:[/bright_red] {line.strip()}")
                    full_stderr_list.append(line)
                process.stderr.close()

            process.wait()

            stdout_str: str = "".join(full_stdout_list)
            stderr_str: str = "".join(full_stderr_list)

            if process.returncode == 0:
                status_msg: str = "Command executed successfully."
                if not stdout_str and not stderr_str:
                    status_msg = "Command executed successfully with no output."
                return status_msg, stdout_str, stderr_str
            else:
                error_msg_detail: str = stderr_str if stderr_str else f"Command failed with return code {process.returncode} and no error output."
                return f"Command failed with return code {process.returncode}.", stdout_str, error_msg_detail

        except FileNotFoundError as e_fnf_sub: # For shell=True, this is less likely for the command itself, but good practice
             self.console.print(f"[bright_red]Error: Command not found during subprocess execution: {e_fnf_sub}. This might indicate an issue with the shell or command path.[/bright_red]")
             return f"Error: Command not found for '{command_str}'.", "", str(e_fnf_sub)
        except PermissionError as e_perm_sub:
             self.console.print(f"[bright_red]Error: Permission denied for subprocess command '{command_str}': {e_perm_sub}[/bright_red]")
             return f"Error: Permission denied for '{command_str}'.", "", str(e_perm_sub)
        except KeyboardInterrupt: # This will now primarily be caught by main.py's loop try/except
            self.console.print("[yellow]Keyboard interrupt during subprocess execution (caught in executor).[/yellow]")
            stdout_str_kb: str = "".join(full_stdout_list)
            stderr_str_kb: str = "".join(full_stderr_list)
            if process and process.poll() is None:
                self.console.print("[yellow]Attempting to interrupt subprocess...[/yellow]")
                try:
                    process.send_signal(signal.SIGINT)
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.console.print("[yellow]Subprocess SIGINT timeout, sending SIGTERM...[/yellow]")
                    process.send_signal(signal.SIGTERM)
                    try: process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        self.console.print("[yellow]Subprocess SIGTERM timeout, sending SIGKILL...[/yellow]")
                        process.kill()
                    except Exception as e_term: self.console.print(f"[bright_red]Error during SIGTERM: {e_term}[/bright_red]")
                except Exception as e_int: self.console.print(f"[bright_red]Error during SIGINT: {e_int}[/bright_red]")

                if process.stdout and not process.stdout.closed: process.stdout.close()
                if process.stderr and not process.stderr.closed: process.stderr.close()
                return "Command interrupted by user.", stdout_str_kb, stderr_str_kb
            elif process:
                 return "Command finished before interrupt handling.", stdout_str_kb, stderr_str_kb
            else:
                return "Command execution aborted by user (no process).", stdout_str_kb, stderr_str_kb
        except Exception as e_generic_sub:
            self.console.print(f"[bright_red]Unexpected error during subprocess execution ('{command_str}'): {e_generic_sub}[/bright_red]")
            if process and process.stdout and not process.stdout.closed: process.stdout.close()
            if process and process.stderr and not process.stderr.closed: process.stderr.close()
            return f"Error executing '{command_str}': {str(e_generic_sub)}", "".join(full_stdout_list), "".join(full_stderr_list) + str(e_generic_sub)

if __name__ == '__main__':
    # ... (main test block remains same) ...
    test_console = Console()
    executor = CommandExecutor(test_console)

    test_console.rule("Test 1: Non-interactive command (ls -lah)")
    status, stdout, stderr = executor.execute_command("ls -lah")
    test_console.print(f"\n[b]Status:[/b] {status}")
    if stdout: test_console.print(f"[dim]Captured stdout length: {len(stdout)}[/dim]")
    if stderr: test_console.print(f"[dim]Captured stderr length: {len(stderr)}[/dim]")

    test_console.rule("Test 2: Non-interactive command with error (cat non_existent_file.txt)")
    status, stdout, stderr = executor.execute_command("cat non_existent_file.txt") # This should produce stderr
    test_console.print(f"\n[b]Status:[/b] {status}")
    if stdout: test_console.print(f"[dim]Captured stdout length: {len(stdout)}[/dim]")
    if stderr: test_console.print(f"[dim]Captured stderr length: {len(stderr)}[/dim]")

    test_console.rule("Test 3: Command not found (non-interactive)")
    status, stdout, stderr = executor.execute_command("somecommandthatdoesnotexist123")
    test_console.print(f"\n[b]Status:[/b] {status}") # Should indicate error from shell
    if stderr: test_console.print(f"[dim]Captured stderr for non-existent command: {len(stderr)}[/dim]")


    test_console.print("\n[yellow]Skipping interactive test in automated run. Test manually if needed.[/yellow]")
    pass
