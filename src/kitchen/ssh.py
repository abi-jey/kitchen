import os
import pty
import shlex
import select
import sys
import termios
import threading
import time
import tty
from logging import getLogger
import getpass

import typer

logger = getLogger(__name__)


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

        if self.elevate_privileges:
            typer.secho("Elevating to root privileges with 'sudo -s'...", fg=typer.colors.YELLOW)
            self.write(b"sudo -s\n")
            # Sudo prompt can vary, e.g., "[sudo] password for user:"
            # We'll just look for "password for"
            output = self.read_until(b"password for", timeout=5)
            if b"password for" in output.lower():
                if not self.password:
                    # This should not happen if login required a password
                    self.password = getpass.getpass("Sudo password: ")
                self.write(self.password.encode() + b"\n")

            # Set new prompt and wait for it
            self.prompt = b"# "
            self.read_until(self.prompt, timeout=10)  # Wait for the root prompt to appear

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

        self.write(command.encode() + b"\n")
        # The output will contain the command, its output, and the next prompt.
        raw_output_bytes = self.read_until(self.prompt, timeout=timeout)
        self.last_output = raw_output_bytes.decode(errors="ignore")

        if self.verbose:
            typer.secho("    [REMOTE OUTPUT]", fg=typer.colors.CYAN)
            # Print the raw output, but skip the first line (command echo) and last line (prompt)
            output_lines = self.last_output.splitlines()
            if len(output_lines) > 2:
                for line in output_lines[1:-1]:
                    typer.echo(f"    {line}")
            typer.secho("    [END REMOTE OUTPUT]", fg=typer.colors.CYAN)

        # 1. Decode to string for easier processing
        decoded_output = self.last_output

        # 2. Split into lines
        lines = decoded_output.splitlines()

        # 3. The first line is the command echo, last line is the prompt.
        #    We also filter out any empty lines.
        if len(lines) > 1:
            command_output_lines = lines[1:-1]
            # Rejoin and strip any leading/trailing whitespace from the final result
            return "\n".join(command_output_lines).strip()
        return ""

    def write(self, data: bytes):
        """Write bytes to the SSH session."""
        if self.fd is None:
            raise ConnectionError("SSH session not started")
        logger.debug(f"[WRITER] Sending {len(data)} bytes")
        os.write(self.fd, data)

    def read_until(self, pattern: bytes, timeout: float = 10.0) -> bytes:
        """Read from the session until a pattern is matched or a timeout occurs."""
        if self.fd is None:
            raise ConnectionError("SSH session not started")

        output = b""
        start_time = time.time()
        while True:
            with self._lock:
                if pattern in self.buffer:
                    output, self.buffer = self.buffer.split(pattern, 1)
                    output += pattern  # Include the pattern in the output
                    logger.debug(f"[READER] Matched pattern '{pattern.decode(errors='ignore')}'")
                    return output

            elapsed = time.time() - start_time
            if elapsed > timeout:
                logger.warning(f"[READER] Timeout waiting for pattern '{pattern.decode(errors='ignore')}'")
                with self._lock:
                    output = self.buffer
                    self.buffer = b""
                return output

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