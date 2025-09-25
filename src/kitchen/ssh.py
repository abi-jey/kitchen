import getpass
import logging
from typing import Dict, Optional, Tuple

import paramiko
import typer
from rich.panel import Panel
from rich.text import Text
from rich import print

logger = logging.getLogger(__name__)


class SSHSession:
    """
    A robust SSH session manager using Paramiko.

    This class replaces the previous PTY-based implementation with a modern,
    library-driven approach. It handles connections, command execution (including
    sudo), and provides clean access to stdout, stderr, and exit codes.
    """

    def __init__(
        self,
        user: str,
        host: str,
        ssh_key_path: str | None = None,
        verbose: bool = False,
        password: str | None = None,
    ):
        self.user = user
        self.host = host
        self.ssh_key_path = ssh_key_path
        self.verbose = verbose
        self._password = password  # Store password for sudo
        self.client = paramiko.SSHClient()
        self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self.exit_code: int | None = None
        self.last_output: str = ""

    def __enter__(self) -> "SSHSession":
        if self.verbose:
            typer.secho(f"🔒 Connecting to {self.user}@{self.host}...", fg=typer.colors.YELLOW)
        else:
            logger.info(f"Connecting to {self.user}@{self.host}")

        try:
            # First try key-based/agent auth without prompting
            try:
                self.client.connect(
                    hostname=self.host,
                    username=self.user,
                    key_filename=self.ssh_key_path,
                    timeout=15,
                    auth_timeout=15,
                    look_for_keys=True,
                    allow_agent=True,
                )
            except paramiko.AuthenticationException:
                # Prompt for password only on authentication failure
                prompt = f"🔑 Password for {self.user}@{self.host}: "
                self._password = self._password or getpass.getpass(prompt)
                self.client.connect(
                    hostname=self.host,
                    username=self.user,
                    password=self._password,
                    key_filename=self.ssh_key_path,
                    timeout=15,
                    auth_timeout=15,
                    look_for_keys=False,
                    allow_agent=False,
                )
            if self.verbose:
                typer.secho("✅ Connection successful.", fg=typer.colors.GREEN)
            else:
                logger.info("Connection successful.")

        except paramiko.AuthenticationException:
            typer.secho("❌ Authentication failed. Please check your credentials.", fg=typer.colors.RED)
            raise typer.Exit(1)
        except (paramiko.SSHException, TimeoutError) as e:
            typer.secho(f"❌ SSH connection failed: {e}", fg=typer.colors.RED)
            raise typer.Exit(1)
        return self

    def run(
        self,
        command: str,
        use_sudo: bool = True,
        timeout: float = 300.0,
        env: Optional[Dict[str, str]] = None,
    ) -> Tuple[str, str, int]:
        """Run a command on the remote host.

        - Honors sudo when requested (password supplied via stdin if available).
        - Supports ephemeral environment variables using a shell wrapper.
        - Auto-injects KUBECONFIG for kubectl/kubeadm commands when not explicitly provided.

        Returns (stdout, stderr, exit_code).
        """
        if self.verbose:
            sudo_str = " with sudo" if use_sudo else ""
            typer.secho(f"  - Executing{sudo_str}: {command}", fg=typer.colors.YELLOW)
        else:
            logger.info(f"Running command: {command} (sudo: {use_sudo})")

        # Build environment/export prefix. Also auto-inject KUBECONFIG for kubectl/kubeadm
        env = dict(env or {})
        auto_kube = (
            command.strip().startswith("kubectl ")
            or command.strip().startswith("kubeadm ")
        )
        if auto_kube and "KUBECONFIG" not in env:
            env["KUBECONFIG"] = "/etc/kubernetes/admin.conf"

        export_prefix = ""
        if env:
            # Minimal safe quoting for values
            def _q(v: str) -> str:
                return "'" + v.replace("'", "'\\''") + "'"

            exports = [f"export {k}={_q(v)}" for k, v in env.items()]
            export_prefix = "; ".join(exports) + "; "

        # Always wrap in a shell to ensure env/export and compound commands work
        escaped_command = (export_prefix + command).replace("'", "'\\''")
        base_shell = f"sh -lc '{escaped_command}'"
        full_command = base_shell if not use_sudo else f"sudo -S -p '' {base_shell}"

        # exec_command gives three clean channels. No more screen scraping.
        stdin, stdout, stderr = self.client.exec_command(full_command, timeout=int(timeout))

        # If sudo needs a password, we provide it here.
        if use_sudo:
            if self._password:
                stdin.write(self._password + "\n")
                stdin.flush()
            else:
                # This case should ideally not be reached if authentication required a password
                logger.warning("Sudo requested but no password available to provide.")

        # This is how you get the exit code. It's a built-in feature.
        self.exit_code = stdout.channel.recv_exit_status()

        stdout_str = stdout.read().decode("utf-8", errors="ignore").strip()
        stderr_str = stderr.read().decode("utf-8", errors="ignore").strip()

        self.last_output = stdout_str

        if self.verbose:
            # Determine panel color based on exit code
            panel_color = "green" if self.exit_code == 0 else "red"
            title = f"[bold {panel_color}]Result (Exit Code: {self.exit_code})[/bold {panel_color}]"

            output_text = Text()
            if stdout_str:
                output_text.append(stdout_str)
            if stderr_str:
                if stdout_str:
                    output_text.append("\n\n")
                output_text.append(stderr_str, style="red")

            final_panel = Panel(
                output_text,
                title=title,
                border_style=panel_color,
                title_align="left",
            )
            print(final_panel)

        return stdout_str, stderr_str, self.exit_code

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if self.verbose:
            typer.secho("🔒 Closing connection.", fg=typer.colors.YELLOW)
        else:
            logger.info("Closing SSH session.")
        self.client.close()


if __name__ == "__main__":
    import logging
    from rich.logging import RichHandler

    logging.basicConfig(level=logging.INFO, handlers=[RichHandler()])

    try:
        # Example usage:
        with SSHSession("abja", "192.168.1.80", verbose=True) as ssh:
            stdout, stderr, code = ssh.run("hostname")
            if code == 0:
                print(f"Hostname: {stdout}")

            stdout, stderr, code = ssh.run("whoami")
            if code == 0:
                print(f"User: {stdout}")

            # Example of a command that might fail
            stdout, stderr, code = ssh.run("cat /non/existent/file", use_sudo=False)
            if code != 0:
                print(f"Command failed as expected. STDERR: {stderr}")

    except typer.Exit:
        print("Exiting due to connection or authentication failure.")
    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}")