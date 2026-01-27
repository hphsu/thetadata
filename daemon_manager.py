"""
ThetaTerminal daemon lifecycle management
Handles daemon discovery, auto-start, and port detection
"""
import logging
import subprocess
import time
import socket
from pathlib import Path
import os
import sys

logger = logging.getLogger(__name__)


class DaemonManager:
    """Manage ThetaTerminal v3 daemon lifecycle"""

    def __init__(self, config):
        self.config = config
        self.host = config.theta_host
        self.port = config.theta_port
        self.timeout = 5  # timeout for connection attempts

    def is_daemon_running(self) -> bool:
        """Check if daemon is running by attempting to connect"""
        # Try configured port first
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(self.timeout)
            result = sock.connect_ex((self.host, self.port))
            sock.close()
            if result == 0:
                return True
        except Exception as e:
            logger.debug(f"Connection check on port {self.port} failed: {e}")

        # Try alternative ports if configured port doesn't work
        alternative_ports = [25503, 25520, 25510]
        for alt_port in alternative_ports:
            if alt_port == self.port:
                continue  # Skip if already tried
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(self.timeout)
                result = sock.connect_ex((self.host, alt_port))
                sock.close()
                if result == 0:
                    logger.info(f"Found daemon running on port {alt_port}")
                    # Update config to use this port
                    self.port = alt_port
                    self.config.theta_port = alt_port
                    self.config.theta_base_url = f"http://{self.host}:{alt_port}"
                    return True
            except Exception as e:
                logger.debug(f"Connection check on port {alt_port} failed: {e}")

        return False

    def find_jar_file(self) -> Path:
        """Find ThetaTerminalv3.jar in common locations"""
        search_paths = [
            Path.cwd() / "ThetaTerminalv3.jar",
            Path.home() / "ThetaTerminalv3.jar",
            Path.home() / "Downloads" / "ThetaTerminalv3.jar",
            Path.home() / "Desktop" / "ThetaTerminalv3.jar",
            Path("/Applications/ThetaTerminalv3.jar"),
            Path("/opt/thetadata/ThetaTerminalv3.jar"),
            Path("/Users/frank/src/thetadata/ThetaTerminalv3.jar"),  # Current project
        ]

        for path in search_paths:
            if path.exists():
                logger.info(f"Found ThetaTerminal JAR: {path}")
                return path

        # Try to find it using 'find' command
        try:
            result = subprocess.run(
                ["find", str(Path.home()), "-name", "ThetaTerminalv3.jar", "-type", "f"],
                capture_output=True,
                timeout=10
            )
            if result.stdout:
                jar_path = Path(result.stdout.decode().strip().split('\n')[0])
                if jar_path.exists():
                    logger.info(f"Found ThetaTerminal JAR via find: {jar_path}")
                    return jar_path
        except Exception as e:
            logger.debug(f"Failed to search for JAR: {e}")

        return None

    def start_daemon(self, jar_path: Path = None) -> bool:
        """Start ThetaTerminal daemon"""
        if self.is_daemon_running():
            logger.info(f"✓ Daemon already running at {self.host}:{self.port}")
            return True

        logger.info("Daemon not running, attempting to start...")

        # Find JAR if not provided
        if jar_path is None:
            jar_path = self.find_jar_file()

        if jar_path is None:
            logger.error(
                "✗ Could not find ThetaTerminalv3.jar\n"
                "  Please provide the path or place it in one of these locations:\n"
                "    - Current directory\n"
                "    - Home directory (~)\n"
                "    - ~/Downloads\n"
                "    - ~/Desktop\n"
                "    - Project directory"
            )
            return False

        if not jar_path.exists():
            logger.error(f"✗ JAR file not found: {jar_path}")
            return False

        logger.info(f"Starting ThetaTerminal from: {jar_path}")

        try:
            # Start daemon in background
            if sys.platform == "win32":
                # Windows
                subprocess.Popen(
                    ["java", "-jar", str(jar_path)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
            else:
                # macOS and Linux
                subprocess.Popen(
                    ["java", "-jar", str(jar_path)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True  # Detach from parent process
                )

            # Wait for daemon to start
            logger.info("Waiting for daemon to initialize...")
            for attempt in range(30):  # Wait up to 30 seconds
                time.sleep(1)
                if self.is_daemon_running():
                    logger.info(f"✓ Daemon started successfully at {self.host}:{self.port}")
                    return True
                if attempt % 5 == 0:
                    logger.info(f"  Still waiting... ({attempt}s)")

            logger.error("✗ Daemon failed to start within timeout")
            return False

        except Exception as e:
            logger.error(f"✗ Failed to start daemon: {e}")
            return False

    def ensure_running(self, jar_path: Path = None) -> bool:
        """Ensure daemon is running, start it if not"""
        if self.is_daemon_running():
            logger.info(f"✓ Daemon is running at {self.host}:{self.port}")
            return True

        logger.warning(f"Daemon not running at {self.host}:{self.port}")
        return self.start_daemon(jar_path)

    def stop_daemon(self) -> bool:
        """Stop ThetaTerminal daemon"""
        logger.info("Stopping ThetaTerminal daemon...")
        try:
            if sys.platform == "win32":
                subprocess.run(["taskkill", "/F", "/IM", "java.exe"])
            else:
                # Kill java process running ThetaTerminal
                subprocess.run(
                    ["pkill", "-9", "-f", "ThetaTerminalv3.jar"],
                    timeout=5
                )
            logger.info("Daemon stopped")
            return True
        except Exception as e:
            logger.warning(f"Failed to stop daemon: {e}")
            return False


def ensure_daemon(config, jar_path: Path = None) -> bool:
    """Convenience function to ensure daemon is running"""
    manager = DaemonManager(config)
    return manager.ensure_running(jar_path)
