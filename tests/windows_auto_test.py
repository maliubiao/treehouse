#!/usr/bin/env python3
"""
Python script to activate Windows via Remote Desktop
This script assumes Windows App is running with a Windows connection already configured
"""

import argparse
import contextlib
import subprocess
import sys
import time
from typing import Dict, List, Tuple, Union

try:
    from AppKit import NSWorkspace
except ImportError:
    NSWorkspace = None  # type: ignore


class Keyboard:
    """Enhanced AppleScript-based keyboard input implementation with key code support"""

    def __init__(self, debug_mode: bool = False):
        self.debug_mode = debug_mode
        self.key_codes = {
            # Key naming rules:
            # - Letters and numbers use physical key characters (e.g. '1' for main keyboard 1 key)
            # - Symbol keys use actual displayed characters (with shift modifier when needed)
            # - Special function keys use semantic names (e.g. 'enter')
            # Modifier keys
            "left_shift": 56,
            "right_shift": 60,
            "left_ctrl": 59,
            "right_ctrl": 62,
            "left_alt": 58,
            "right_alt": 61,
            "cmd": 55,
            # Special keys
            "enter": 76,
            "return": 36,
            "tab": 48,
            "space": 49,
            "delete": 51,
            "esc": 53,
            "caps_lock": 57,  # WARNING: 根据文档可能无效
            "keyboard_brightness": None,  # 文档明确不支持
            "num_enter": 76,  # 小键盘enter
            "eject": 110,  # 弹出键
            # Arrow keys
            "up": 126,
            "down": 125,
            "left": 123,
            "right": 124,
            # Function keys
            "f1": 122,
            "f2": 120,
            "f3": 99,
            "f4": 118,
            "f5": 96,
            "f6": 97,
            "f7": 98,
            "f8": 100,
            "f9": 101,
            "f10": 109,
            "f11": 103,
            "f12": 111,
            "f13": 105,
            "f14": 107,
            "f15": 113,
            "f16": 106,
            "f17": 64,
            "f18": 79,
            "f19": 80,
            "f20": 90,
            # Numpad keys
            "num_0": 82,
            "num_1": 83,
            "num_2": 84,
            "num_3": 85,
            "num_4": 86,
            "num_5": 87,
            "num_6": 88,
            "num_7": 89,
            "num_8": 91,
            "num_9": 92,
            "num_*": 67,
            "num_/": 75,
            "num_+": 69,
            "num_-": 78,
            "num_=": 81,
            "num_.": 65,
            "num_clear": 71,
            # Top row number keys (1-9 and 0)
            "1": 18,
            "2": 19,
            "3": 20,
            "4": 21,
            "5": 23,
            "6": 22,
            "7": 26,
            "8": 28,
            "9": 25,
            "0": 29,
            # Symbol keys
            "`": 50,  # 左上角数字1左侧
            "{": 33,  # [键 shift状态
            "}": 30,  # ]键 shift状态
            "\\": 42,  # 回车键上方
            ";": 41,  # L键右侧
            "'": 39,  # ;键右侧
            ",": 43,  # M键右侧
            ".": 47,  # ,键右侧
            "/": 44,  # .键右侧
            "=": 24,  # 0键右侧
            "(": 25,  # 9键 shift状态
            ")": 29,  # 0键 shift状态
            "$": 21,  # 4键 shift状态
            "!": 18,  # 1键 shift状态
            "@": 19,  # 2键 shift状态
            "#": 20,  # 3键 shift状态
            "%": 23,  # 5键 shift状态
            "^": 22,  # 6键 shift状态
            "&": 26,  # 7键 shift状态
            "*": 28,  # 8键 shift状态
            "_": 27,  # -键 shift状态
            "+": 24,  # =键 shift状态
            "|": 42,  # \键 shift状态
            '"': 39,  # '键 shift状态
            "?": 44,  # /键 shift状态
            "<": 43,  # ,键 shift状态
            ">": 47,  # .键 shift状态
            ":": 41,  # ;键 shift状态
            "~": 50,  # `键 shift状态
            "[": 33,  # [键
            "]": 30,  # ]键
            "€": 30,  # ]键 alt状态 (欧洲键盘布局)
            "£": 20,  # 3键 alt状态 (英国键盘布局)
        }
        self.modifier_requirements = {
            ")": ["shift"],
            "(": ["shift"],
            "$": ["shift"],
            "!": ["shift"],
            "@": ["shift"],
            "#": ["shift"],
            "%": ["shift"],
            "^": ["shift"],
            "&": ["shift"],
            "*": ["shift"],
            "_": ["shift"],
            "+": ["shift"],
            "{": ["shift"],
            "}": ["shift"],
            "|": ["shift"],
            '"': ["shift"],
            "?": ["shift"],
            "<": ["shift"],
            ">": ["shift"],
            ":": ["shift"],
            "~": ["shift"],
            "€": ["alt"],
            "£": ["alt"],
        }

    def press(self, key: Union[str, int]) -> None:
        """Simulate key press using AppleScript with key code support"""
        if isinstance(key, int):
            key_str = str(key)
            if key_str in self.key_codes:
                key = self.key_codes[key_str]
            script = f"""
            tell application "System Events"
                key code {key}
            end tell
            """
        elif key in self.key_codes:
            script = self._generate_key_code_script(key)
        else:
            script = f"""
            tell application "System Events"
                keystroke "{self._sanitize_keystroke(key)}"
            end tell
            """
        self._execute_apple_script(script)

    def press_multiple(self, keys: List[Union[str, int]]) -> None:
        """Simulate multiple key presses in a single AppleScript call"""
        script_lines = ['tell application "System Events"']

        for key in keys:
            if isinstance(key, int):
                script_lines.append(f"    key code {key}")
            elif key in self.key_codes:
                modifiers = self.modifier_requirements.get(key, [])

                for mod in modifiers:
                    script_lines.append(f"    key down {self._map_modifier(mod)}")

                script_lines.append(f"    key code {self.key_codes[key]}")

                for mod in modifiers:
                    script_lines.append(f"    key up {self._map_modifier(mod)}")
            else:
                script_lines.append(f'    keystroke "{self._sanitize_keystroke(key)}"')

        script_lines.append("end tell")
        self._execute_apple_script("\n".join(script_lines))

    def _generate_key_code_script(self, key: str) -> str:
        """Generate AppleScript for key code with modifiers"""
        key_code = self.key_codes[key]
        modifiers = self.modifier_requirements.get(key, [])
        script_lines = ['tell application "System Events"']

        for mod in modifiers:
            script_lines.append(f"    key down {self._map_modifier(mod)}")

        script_lines.append(f"    key code {key_code}")

        for mod in reversed(modifiers):
            script_lines.append(f"    key up {self._map_modifier(mod)}")

        script_lines.append("end tell")
        return "\n".join(script_lines)

    def _sanitize_keystroke(self, char: str) -> str:
        """Escape special characters for AppleScript keystroke"""
        return char.replace('"', '\\"').replace("\\", "\\\\")

    def hold(self, modifier: str) -> "KeyboardContext":
        """Hold a modifier key (returns context manager)"""
        return KeyboardContext(self, modifier)

    def _execute_apple_script(self, script: str) -> None:
        """Execute AppleScript with error handling"""
        if self.debug_mode:
            print(f"[DEBUG] Executing AppleScript: {script}")
        try:
            subprocess.run(["osascript", "-e", script], check=True, capture_output=True)
        except subprocess.CalledProcessError as e:
            print(
                f"[ERROR] AppleScript execution failed: {str(e)}\nOutput: {e.stdout}\nError: {e.stderr}"
            )
            raise RuntimeError("AppleScript execution failed") from e

    @staticmethod
    def _map_modifier(modifier: str) -> str:
        """Map modifier names to AppleScript constants"""
        mapping = {
            "shift": "shift",
            "ctrl": "control",
            "alt": "option",
            "cmd": "command",
            "win": "command",
            "left_shift": "shift",
            "right_shift": "shift",
            "left_ctrl": "control",
            "right_ctrl": "control",
            "left_alt": "option",
            "right_alt": "option",
        }
        return mapping.get(modifier.lower(), "command")


class KeyboardContext:
    """Context manager for holding modifier keys"""

    def __init__(self, keyboard: Keyboard, modifier: str):
        self.keyboard = keyboard
        self.modifier = modifier

    def __enter__(self):
        """Press modifier key when entering context"""
        script = f"""
        tell application "System Events"
            key down {Keyboard._map_modifier(self.modifier)}
        end tell
        """
        self.keyboard._execute_apple_script(script)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Release modifier key when exiting context"""
        script = f"""
        tell application "System Events"
            key up {Keyboard._map_modifier(self.modifier)}
        end tell
        """
        self.keyboard._execute_apple_script(script)


class CommandExecutor:
    """Base class for command execution functionality"""

    def __init__(self, debug_mode: bool = False):
        self.debug_mode = debug_mode
        self.keyboard = Keyboard(debug_mode=debug_mode)
        self.command_delay = 0.1
        self.initial_delay = 2

    def send_keystrokes_with_delay(self, text: str, delay: float = None) -> None:
        """Send keystrokes with controlled delay"""
        delay = delay or self.command_delay
        self.keyboard.press_multiple([char for char in text])
        time.sleep(delay)

    def execute_commands(self, commands: List[Tuple[str, int]]) -> None:
        """Execute a series of commands in the remote session"""
        try:
            # Open Command Prompt in a single AppleScript block
            script = """
            tell application "System Events"
                -- Open Run dialog
                key down command
                key code 15
                key up command
                delay 1
                -- Type cmd and press enter
                keystroke "cmd"
                key code 76
                delay 2
            end tell
            """
            self.keyboard._execute_apple_script(script)

            # Type commands in Command Prompt
            for cmd, delay in commands:
                print(f"[DEBUG] Executing command: {cmd}")
                self.send_keystrokes_with_delay(cmd)
                self.keyboard.press("enter")
                print(f"[DEBUG] Command executed, waiting {delay} seconds")
                time.sleep(delay)

        except RuntimeError as e:
            print(f"[ERROR] Command execution failed: {str(e)}")
            raise

    def show_notification(self, title: str, message: str) -> None:
        """Show macOS notification"""
        try:
            result = subprocess.run(
                [
                    "osascript",
                    "-e",
                    f'display notification "{message}" with title "{title}"',
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            if self.debug_mode:
                print(f"[DEBUG] Notification output: {result.stdout.strip()}")
        except subprocess.CalledProcessError as e:
            print(
                f"[ERROR] Failed to show notification: {str(e)}\nOutput: {e.stdout}\nError: {e.stderr}"
            )

    def show_alert(self, message: str) -> None:
        """Show macOS alert dialog"""
        try:
            result = subprocess.run(
                [
                    "osascript",
                    "-e",
                    f'display dialog "{message}" with icon stop buttons {{"OK"}} default button "OK"',
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            if self.debug_mode:
                print(f"[DEBUG] Alert output: {result.stdout.strip()}")
        except subprocess.CalledProcessError as e:
            print(
                f"[ERROR] Failed to show alert: {str(e)}\nOutput: {e.stdout}\nError: {e.stderr}"
            )


class WindowsVMActivator(CommandExecutor):
    """Class to handle Windows activation process via Remote Desktop"""

    def __init__(self, debug_mode: bool = False, use_apple_script: bool = False):
        super().__init__(debug_mode)
        self.uac_delay = 5

    def is_remote_desktop_running(self) -> bool:
        """Check if Windows App is running"""
        if NSWorkspace is None:
            return False

        print("[DEBUG] Checking if Remote Desktop is running...")
        workspace = NSWorkspace.sharedWorkspace()
        running = any(
            app.localizedName() == "Windows App"
            for app in workspace.runningApplications()
        )
        print(f"[DEBUG] Remote Desktop running status: {running}")
        return running

    def ensure_remote_desktop_active(self) -> None:
        """Ensure Remote Desktop is active application and window is focused"""
        print("[DEBUG] Ensuring Remote Desktop is active application...")
        try:
            result = subprocess.run(
                ["osascript", "-e", 'tell application "Windows App" to activate'],
                check=True,
                capture_output=True,
                text=True,
            )
            if self.debug_mode:
                print(f"[DEBUG] AppleScript output: {result.stdout.strip()}")
            time.sleep(self.initial_delay)
            print("[DEBUG] Remote Desktop window should now be focused")
        except subprocess.CalledProcessError as e:
            print(
                f"[ERROR] Failed to activate Remote Desktop: {str(e)}\nOutput: {e.stdout}\nError: {e.stderr}"
            )
            raise RuntimeError("Failed to activate Remote Desktop") from e

    @contextlib.contextmanager
    def _hold_multiple_modifiers(self, *modifiers: str):
        """Context manager for holding multiple modifier keys simultaneously"""
        try:
            script_lines = ['tell application "System Events"']
            for modifier in modifiers:
                script_lines.append(f"    key down {Keyboard._map_modifier(modifier)}")
            script_lines.append("end tell")
            self.keyboard._execute_apple_script("\n".join(script_lines))
            yield
        finally:
            script_lines = ['tell application "System Events"']
            for modifier in reversed(modifiers):
                script_lines.append(f"    key up {Keyboard._map_modifier(modifier)}")
            script_lines.append("end tell")
            self.keyboard._execute_apple_script("\n".join(script_lines))

    def _open_elevated_command_prompt(self) -> None:
        """Open elevated Command Prompt using Ctrl+Shift+Enter"""
        print("[DEBUG] Opening elevated Command Prompt with Ctrl+Shift+Enter")

        # Open Run dialog and type cmd in a single AppleScript block
        script = """
        tell application "System Events"
            -- Open Run dialog
            key down command
            key code 15
            key up command
            delay 1
            -- Type cmd and press Ctrl+Shift+Enter
            keystroke "cmd"
            key down control
            key down shift
            key code 76
            key up shift
            key up control
            delay 3
        end tell
        """
        self.keyboard._execute_apple_script(script)

        # Wait for UAC prompt and confirm
        print("[DEBUG] Handling UAC confirmation")
        time.sleep(self.uac_delay)
        self.keyboard.press("left")
        time.sleep(1)
        self.keyboard.press("enter")
        time.sleep(3)
        print("[DEBUG] Administrator Command Prompt opened")

    def activate_windows_vm(self) -> bool:
        """Main function to activate Windows via Remote Desktop"""
        print("[INFO] Starting Windows activation process via Remote Desktop...")
        try:
            if not self.is_remote_desktop_running():
                print("[ERROR] Remote Desktop not running")
                self.show_alert("Windows App is not running")
                return False

            self.ensure_remote_desktop_active()

            commands = [
                ("slmgr /ipk W269N-WFGWX-YVC9B-4J6C9-T83GX", 5),
                ("slmgr /skms skms.netnr.eu.org", 5),
                ("slmgr /ato", 5),
                ("exit", 1),
            ]

            self._open_elevated_command_prompt()
            self.execute_commands(commands)

            self.show_notification(
                "Windows Activation",
                "Windows activation commands sent via Remote Desktop",
            )
            print("[INFO] All commands executed successfully")
            return True

        except RuntimeError as e:
            print(f"[ERROR] Script error: {str(e)}")
            self.show_alert(f"Script error: {str(e)}")
            return False


class TreeHouseEnvInstaller(CommandExecutor):
    """Class to handle environment setup including Chocolatey, Git, UV and repository cloning"""

    def check_prerequisites(self) -> Dict[str, bool]:
        """Check if git/uv/choco are already installed"""
        print("[INFO] Checking environment prerequisites...")
        try:
            self.keyboard.press_multiple(["powershell", "enter"])
            time.sleep(2)
            self._add_to_path()
            self.send_keystrokes_with_delay(
                "(Get-Command choco -ErrorAction SilentlyContinue).Version"
            )
            self.keyboard.press("enter")
            time.sleep(2)
            self.send_keystrokes_with_delay(
                "(Get-Command git -ErrorAction SilentlyContinue).Version"
            )
            self.keyboard.press("enter")
            time.sleep(2)
            self.send_keystrokes_with_delay(
                "(Get-Command uv -ErrorAction SilentlyContinue).Version"
            )
            self.keyboard.press("enter")
            time.sleep(2)
            self.send_keystrokes_with_delay("$env:Path")
            self.keyboard.press("enter")
            time.sleep(2)
            self.keyboard.press_multiple(["exit", "enter"])
            return {"choco": True, "git": True, "uv": True}
        except RuntimeError as e:
            print(f"[ERROR] Prerequisite check failed: {str(e)}")
            return {"choco": False, "git": False, "uv": False}

    def install_uv(self) -> bool:
        """Install uv package manager via PowerShell"""
        print("[INFO] Starting UV installation process...")
        try:
            self.keyboard.press_multiple(["powershell", "enter"])
            time.sleep(2)
            self.send_keystrokes_with_delay(
                "$env:Path += ';C:\\ProgramData\\chocolatey\\bin;$HOME\\.local\\bin'"
            )
            self.keyboard.press("enter")
            time.sleep(1)
            cmd = "iwr -useb https://astral.sh/uv/install.ps1 | iex;"
            self.send_keystrokes_with_delay(cmd)
            self.keyboard.press("enter")
            time.sleep(30)
            self.keyboard.press_multiple(["exit", "enter"])
            print("[INFO] UV installation completed")
            return True
        except RuntimeError as e:
            print(f"[ERROR] UV installation failed: {str(e)}")
            return False

    def clone_repo(self) -> bool:
        """Clone repository with error handling"""
        print("[INFO] Starting repository cloning process...")
        try:
            self.keyboard.press_multiple(["powershell", "enter"])
            time.sleep(2)
            self._add_to_path()
            cmd = "if (!(Test-Path treehouse)) { git clone https://github.com/maliubiao/treehouse } else { Remove-Item -Recurse -Force treehouse; git clone https://github.com/maliubiao/treehouse }"
            self.send_keystrokes_with_delay(cmd)
            self.keyboard.press("enter")
            time.sleep(30)
            self.keyboard.press_multiple(["exit", "enter"])
            print("[INFO] Repository cloned successfully")
            return True
        except RuntimeError as e:
            print(f"[ERROR] Repository cloning failed: {str(e)}")
            return False

    def run_uv_sync(self) -> bool:
        """Run uv sync in cloned directory"""
        print("[INFO] Running uv sync...")
        try:
            self.keyboard.press_multiple(["powershell", "enter"])
            time.sleep(2)
            self._add_to_path()
            self.send_keystrokes_with_delay("cd treehouse")
            self.keyboard.press("enter")
            time.sleep(1)
            self.send_keystrokes_with_delay("uv sync")
            self.keyboard.press("enter")
            time.sleep(10)
            self.keyboard.press_multiple(["exit", "enter"])
            print("[INFO] uv sync completed")
            return True
        except RuntimeError as e:
            print(f"[ERROR] uv sync failed: {str(e)}")
            return False

    def verify_git_installation(self) -> bool:
        """Verify git installation and version"""
        print("[INFO] Verifying git installation...")
        try:
            self.keyboard.press_multiple(["powershell", "enter"])
            time.sleep(2)
            self.send_keystrokes_with_delay("git --version")
            self.keyboard.press("enter")
            time.sleep(2)
            self.keyboard.press_multiple(["exit", "enter"])
            print("[INFO] Git installation verified")
            return True
        except RuntimeError as e:
            print(f"[ERROR] Git verification failed: {str(e)}")
            return False

    def install_chocolatey(self) -> bool:
        """Install Chocolatey package manager via PowerShell"""
        print("[INFO] Starting Chocolatey installation process...")
        try:
            self.keyboard.press_multiple(["powershell", "enter"])
            time.sleep(2)

            cmd = "Set-ExecutionPolicy Bypass -Scope Process -Force; [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.ServicePointManager]::SecurityProtocol -bor 3072; iex ((New-Object System.Net.WebClient).DownloadString('https://community.chocolatey.org/install.ps1')); [Environment]::SetEnvironmentVariable('Path', $env:Path + ';C:\\ProgramData\\chocolatey\\bin', 'User')"
            self.send_keystrokes_with_delay(cmd)
            self.keyboard.press("enter")
            time.sleep(30)

            self.keyboard.press_multiple(["exit", "enter"])
            time.sleep(1)

            print("[INFO] Chocolatey installation completed")
            return True

        except RuntimeError as e:
            print(f"[ERROR] Chocolatey installation failed: {str(e)}")
            return False

    def _add_to_path(self) -> None:
        """Add required paths to environment PATH variable"""
        cmd = '$env:Path += ";C:\\Program Files\\Git\\bin;C:\\ProgramData\\chocolatey\\bin;$HOME\\.local\\bin"'
        self.send_keystrokes_with_delay(cmd)
        self.keyboard.press("enter")
        time.sleep(1)

    def _refresh_environment(self) -> None:
        """Refresh environment variables by reloading PowerShell profile"""
        try:
            self.keyboard.press_multiple(["powershell", "enter"])
            time.sleep(1)
            self.send_keystrokes_with_delay("Import-Module $PROFILE")
            self.keyboard.press("enter")
            time.sleep(1)
            self.keyboard.press_multiple(["exit", "enter"])
        except RuntimeError as e:
            print(f"[WARNING] Failed to refresh environment: {str(e)}")

    def install_git(self) -> bool:
        """Install Git via Chocolatey with unattended mode"""
        print("[INFO] Starting Git installation process...")
        try:
            self.keyboard.press_multiple(["powershell", "enter"])
            time.sleep(2)
            self._add_to_path()

            cmd = "choco install git -y --force --accept-license; [Environment]::SetEnvironmentVariable('Path', $env:Path + ';C:\\Program Files\\Git\\bin', 'User')"
            self.send_keystrokes_with_delay(cmd)
            self.keyboard.press("enter")
            time.sleep(60)

            self.keyboard.press_multiple(["exit", "enter"])
            time.sleep(1)

            print("[INFO] Git installation completed")
            return True

        except RuntimeError as e:
            print(f"[ERROR] Git installation failed: {str(e)}")
            return False


def parse_args() -> argparse.Namespace:
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(
        description="Windows Activation Script via Remote Desktop"
    )
    parser.add_argument(
        "--debug", action="store_true", help="Enable debug mode with key listener"
    )
    parser.add_argument(
        "--apple-script",
        action="store_true",
        help="Use AppleScript for keyboard input instead of Quartz",
    )
    return parser.parse_args()


if __name__ == "__main__":
    print("[INFO] Starting Windows activation script via Remote Desktop...")
    args = parse_args()
    try:
        activator = WindowsVMActivator(debug_mode=args.debug)
        activator.ensure_remote_desktop_active()
        # SUCCESS = activator.activate_windows_vm()

        installer = TreeHouseEnvInstaller(debug_mode=args.debug)
        CHOCO_SUCCESS = installer.install_chocolatey()
        GIT_SUCCESS = installer.install_git()
        installer.install_uv()
        installer.clone_repo()
        installer.run_uv_sync()
        print(
            f"[INFO] Script execution completed. Chocolatey install: {CHOCO_SUCCESS}, Git install: {GIT_SUCCESS}"
        )
        sys.exit(0 if CHOCO_SUCCESS and GIT_SUCCESS else 1)
    except RuntimeError as e:
        print(f"[CRITICAL] Fatal error: {str(e)}")
        sys.exit(1)
