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

logger = getLogger(__name__)


class SSHSession:
    def __init__(self, user, host):
        self.user = user
        self.host = host
        self.pid: int | None = None
        self.fd: int | None = None
        self.buffer = b""
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._reader_thread: threading.Thread | None = None
        self.password: str | None = None
        self.prompt: bytes = b"$ "

    def __enter__(self):
        logger.info(f"[SSH] Connecting to {self.user}@{self.host}")
        self.pid, self.fd = pty.fork()

        if self.pid == 0:
            logger.info("[SSH] Child process: starting ssh...")
            command = f"ssh {self.user}@{self.host}"
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
        # Wait for the password prompt with a short timeout
        output = self.read_until(b"password: ", timeout=3)

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
        logger.info("Login successful, at shell prompt.")

    def run(self, command: str, timeout: float = 10.0) -> str:
        """Runs a command in the SSH session and returns its output."""
        logger.info(f"Running command: {command}")
        self.write(command.encode() + b"\n")
        # The output will contain the command, its output, and the next prompt.
        raw_output = self.read_until(self.prompt, timeout=timeout)

        # 1. Decode to string for easier processing
        decoded_output = raw_output.decode(errors="ignore")

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