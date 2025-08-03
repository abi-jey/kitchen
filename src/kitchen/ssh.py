import os
import pty
import re
import shlex
import select
import sys
import termios
import threading
import time
import tty
from logging import getLogger, FileHandler, Formatter, DEBUG
import getpass

import typer
from rich.live import Live
from rich.panel import Panel
from rich.text import Text
from rich import print

logger = getLogger(__name__)

# Setup runtime logger for SSH I/O
try:
    runtime_log_path = "runtime.log"
    runtime_logger = getLogger("kitchen.runtime")
    runtime_logger.setLevel(DEBUG)
    if not runtime_logger.handlers:
        handler = FileHandler(runtime_log_path, mode="w")
        handler.setLevel(DEBUG)
        formatter = Formatter("[%(asctime)s] %(message)s")
        handler.setFormatter(formatter)
        runtime_logger.addHandler(handler)
except Exception as e:
    logger.error(f"Failed to set up runtime file logger: {e}")


class SSHSession:
    def __init__(
        self,
        user: str,
        host: str,
        ssh_key_path: str | None = None,
        verbose: bool = False,
        elevate_privileges: bool = False,
    ):
        self.user = user
        self.host = host
        self.ssh_key_path = ssh_key_path
        self.verbose = verbose
        self.elevate_privileges = elevate_privileges
        self.pid: int | None = None
        self.fd: int | None = None
        self.buffer = b""
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._reader_thread: threading.Thread | None = None
        self.password: str | None = None
        self.prompt: bytes = b"$ "
        self.last_output: str = ""

    def __enter__(self):
        if self.verbose:
            typer.secho(f"[SSH] Connecting to {self.user}@{self.host}", fg=typer.colors.YELLOW)
        else:
            logger.info(f"[SSH] Connecting to {self.user}@{self.host}")

        self.pid, self.fd = pty.fork()

        if self.pid == 0:
            logger.info("[SSH] Child process: starting ssh...")
            command = f"ssh {self.user}@{self.host}"
            if self.ssh_key_path:
                command += f" -i {self.ssh_key_path}"
            args = shlex.split(command)
            try:
                os.execvp(args[0], args)
            except Exception as e:
                logger.error(f"[SSH] Failed to exec ssh: {e}")
                os._exit(1)
        else:
            logger.info(f"[SSH] Parent process: forked PID={self.pid}, FD={self.fd}")
            self._reader_thread = threading.Thread(target=self._read_loop, daemon=True)
            self._reader_thread.start()
            logger.info("[SSH] Background reader thread started")
            self.connect()
            return self

    def _read_loop(self):
        logger.debug("[READER] Loop started")
        while not self._stop_event.is_set():
            try:
                if self.fd is None:
                    time.sleep(0.1)
                    continue
                r, _, _ = select.select([self.fd], [], [], 0.1)
                if self.fd in r:
                    data = os.read(self.fd, 1024)
                    if not data:
                        logger.debug("[READER] EOF reached")
                        break
                    with self._lock:
                        self.buffer += data
                    runtime_logger.debug(f"READ: {data!r}")
                    logger.debug(f"[READER] Received {len(data)} bytes")
            except OSError as e:
                logger.error(f"[READER] OSError: {e}")
                break

        logger.debug("[READER] Loop exiting")

    def connect(self, timeout: float = 10.0):
        """
        Handles the initial connection and login process, including password prompt.
        """
        # Wait for the password prompt using the method's timeout argument
        output = self.read_until(b"password: ", timeout=timeout)

        # If password prompt is seen, get password and send it
        if b"password" in output.lower():
            sys.stdout.buffer.write(output)
            sys.stdout.flush()
            if not self.password:
                self.password = getpass.getpass("")
            self.write(self.password.encode() + b"\n")

        # Wait for the shell prompt to ensure login is complete
        final_prompt = self.read_until(self.prompt, timeout=timeout)
        # The prompt might be in the buffer, so we just make sure we clear it
        with self._lock:
            if self.prompt in self.buffer:
                _, self.buffer = self.buffer.split(self.prompt, 1)
        if self.verbose:
            typer.secho("SSH login successful, at shell prompt.", fg=typer.colors.GREEN)
        else:
            logger.info("Login successful, at shell prompt.")

        # Always elevate privileges after login
        self._elevate_to_root()

    def _elevate_to_root(self):
        """
        Elevates the current session to root using 'sudo -s', handling both
        password-prompting and passwordless sudo.
        """
        if self.verbose:
            typer.secho("Elevating to root privileges with 'sudo -s'...", fg=typer.colors.YELLOW)

        self.write(b"sudo -s\n")

        # Wait for either a password prompt or the root prompt
        password_prompt = b"password for"
        root_prompt_temp = b"# "
        found_pattern, output = self._read_until_one_of([password_prompt, root_prompt_temp], timeout=5)

        if found_pattern == password_prompt:
            if self.verbose:
                typer.secho("    - Sudo password required.", fg=typer.colors.YELLOW)
            if not self.password:
                self.password = getpass.getpass("Sudo password: ")
            self.write(self.password.encode() + b"\n")
            # After sending password, we must wait for the root prompt
            self.read_until(root_prompt_temp, timeout=10)
        elif found_pattern == root_prompt_temp:
            if self.verbose:
                typer.secho("    - Passwordless sudo detected.", fg=typer.colors.GREEN)
        else:
            # Neither prompt was found
            typer.secho("❌ Failed to elevate to root. Could not detect password or root prompt.", fg=typer.colors.RED)
            typer.secho(f"    Received: {output.decode(errors='ignore')}", fg=typer.colors.RED)
            raise typer.Exit(1)

        # Set the definitive root prompt
        self.prompt = root_prompt_temp

        # Set KUBECONFIG for the root session
        kubeconfig_cmd = "export KUBECONFIG=/etc/kubernetes/admin.conf\n"
        if self.verbose:
            typer.secho("  - Setting KUBECONFIG for root session...", fg=typer.colors.YELLOW)
        self.write(kubeconfig_cmd.encode())
        self.read_until(self.prompt, timeout=10)  # Wait for the prompt again to confirm command execution

        # Clear the buffer after elevation and setup to ensure a clean state
        with self._lock:
            self.buffer = b""

        if self.verbose:
            typer.secho("Successfully elevated to root and set KUBECONFIG.", fg=typer.colors.GREEN)
        else:
            logger.info("Successfully elevated to root and set KUBECONFIG.")

    def run(self, command: str, timeout: float = 60.0) -> str:
        """Runs a command in the SSH session and returns its output."""
        if self.verbose:
            typer.secho(f"    Executing command: {command}", fg=typer.colors.YELLOW)
        else:
            logger.info(f"Running command: {command}")

        with self._lock:
            self.buffer = b""

        self.write(command.encode() + b"\n")

        full_output_bytes = b""
        live = None
        if self.verbose:
            live = Live(
                Panel(
                    Text("Waiting for output..."),
                    title="[cyan]Remote[/cyan]",
                    border_style="cyan",
                ),
                transient=True,
                refresh_per_second=10,
                vertical_overflow="visible",
            )
            live.start()

        start_time = time.time()
        while True:
            if time.time() - start_time > timeout:
                logger.warning(f"Timeout waiting for command: {command}")
                if live:
                    live.update(
                        Panel(
                            Text(full_output_bytes.decode(errors="ignore"), style="red"),
                            title="[red]Remote (Timeout)[/red]",
                            border_style="red",
                        )
                    )
                break

            chunk = b""
            with self._lock:
                if self.buffer:
                    chunk = self.buffer
                    self.buffer = b""

            if chunk:
                full_output_bytes += chunk
                if live:
                    # Decode for display, but keep original bytes
                    text_to_display = full_output_bytes.decode(errors="ignore")

                    # Manually remove terminal title escape sequences (OSC) that rich might not handle well
                    osc_escape_pattern = re.compile(r"\x1b\].*?\x07")
                    cleaned_text_for_display = osc_escape_pattern.sub("", text_to_display)

                    live.update(
                        Panel(
                            Text.from_ansi(cleaned_text_for_display),
                            title="[cyan]Remote[/cyan]",
                            border_style="cyan",
                        )
                    )

            # Check for prompt in the full output
            if self.prompt in full_output_bytes:
                break

            time.sleep(0.05)

        if live:
            live.stop()

            # Clean the prompt from the final output for display
            final_output_for_display = full_output_bytes
            prompt_pos = final_output_for_display.rfind(self.prompt)
            if prompt_pos != -1:
                # Get everything before the last occurrence of the prompt
                final_output_for_display = final_output_for_display[:prompt_pos]

            # Decode the output
            decoded_output = final_output_for_display.decode(errors="ignore")

            # Manually remove terminal title escape sequences (OSC)
            osc_escape_pattern = re.compile(r"\x1b\].*?\x07")
            cleaned_output = osc_escape_pattern.sub("", decoded_output)

            # Log the content that will be displayed in the final panel
            runtime_logger.debug(f"FINAL_PANEL_CONTENT: {cleaned_output.strip()!r}")

            # Final display after live is stopped, using from_ansi to interpret escape codes
            final_panel = Panel(
                Text.from_ansi(cleaned_output.strip()),
                title="[cyan]Remote[/cyan]",
                border_style="cyan",
                title_align="left",
            )
            print(final_panel)

        output_to_parse = full_output_bytes
        with self._lock:
            prompt_pos = full_output_bytes.find(self.prompt)
            if prompt_pos != -1:
                output_to_parse = full_output_bytes[:prompt_pos]
                self.buffer = full_output_bytes[prompt_pos + len(self.prompt) :] + self.buffer

        self.last_output = output_to_parse.decode(errors="ignore")
        lines = self.last_output.splitlines()

        if lines and command in lines[0]:
            return "\n".join(lines[1:]).strip()

        return self.last_output.strip()

    def write(self, data: bytes):
        """Write bytes to the SSH session."""
        if self.fd is None:
            raise ConnectionError("SSH session not started")
        logger.debug(f"[WRITER] Sending {len(data)} bytes")
        runtime_logger.debug(f"WRITE: {data!r}")
        os.write(self.fd, data)

    def read_until(self, pattern: bytes, timeout: float = 10.0) -> bytes:
        """Read from the session until a pattern is matched or a timeout occurs."""
        _, output = self._read_until_one_of([pattern], timeout)
        return output

    def _read_until_one_of(self, patterns: list[bytes], timeout: float = 10.0) -> tuple[bytes | None, bytes]:
        """
        Read from the session until one of the patterns is matched or a timeout occurs.
        Returns the pattern that was found and the output up to that point.
        """
        if self.fd is None:
            raise ConnectionError("SSH session not started")

        output = b""
        start_time = time.time()
        while True:
            with self._lock:
                for pattern in patterns:
                    if pattern in self.buffer:
                        matched_output, self.buffer = self.buffer.split(pattern, 1)
                        matched_output += pattern  # Include the pattern in the output
                        logger.debug(f"[READER] Matched pattern '{pattern.decode(errors='ignore')}'")
                        return pattern, matched_output

            elapsed = time.time() - start_time
            if elapsed > timeout:
                logger.warning(f"[READER] Timeout waiting for one of patterns: {patterns!r}")
                with self._lock:
                    output = self.buffer
                    self.buffer = b""
                return None, output

            time.sleep(0.1)

    def __exit__(self, exc_type, exc_val, exc_tb):
        logger.info("[SSH] Exiting SSH session")
        self._stop_event.set()

        try:
            logger.debug("[SSH] Sending 'exit'")
            if self.fd is not None:
                os.write(self.fd, b"exit\n")
        except Exception as e:
            logger.warning(f"[SSH] Failed to send exit: {e}")

        if self._reader_thread and self._reader_thread.is_alive():
            self._reader_thread.join(timeout=2)
            logger.debug("[SSH] Reader thread joined")

        if self.pid:
            try:
                os.kill(self.pid, 15)  # SIGTERM
                logger.info("[SSH] SSH process terminated")
            except ProcessLookupError:
                logger.warning("[SSH] Process already terminated")


if __name__ == "__main__":
    import logging
    from rich.logging import RichHandler

    logging.basicConfig(level=logging.INFO, handlers=[RichHandler()])

    try:
        with SSHSession("abja", "192.168.1.80") as ssh:
            hostname = ssh.run("hostname")
            print(f"Hostname: {hostname}")

            whoami = ssh.run("whoami")
            print(f"User: {whoami}")

    except Exception as e:
        logger.error(f"An error occurred: {e}")