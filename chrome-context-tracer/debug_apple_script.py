#!/usr/bin/env python3
"""
Debug script to test AppleScript browser window detection
专门测试AppleScript浏览器窗口检测的调试脚本
"""

import platform
import subprocess


def test_apple_script_detection():
    """Test AppleScript browser detection with detailed debugging"""
    print("🍎 Testing AppleScript browser window detection...")
    print("=" * 60)

    # Test different browser names
    browsers = [
        ("Google Chrome", "Chrome"),
        ("Microsoft Edge", "Edge"),
        ("Safari", "Safari"),
        ("Firefox", "Firefox"),
        ("Brave Browser", "Brave"),
        ("Opera", "Opera"),
    ]

    for process_name, display_name in browsers:
        print(f"\n🔍 Testing {display_name} detection...")

        # AppleScript to check if browser exists and get window info
        applescript = f'''
tell application "System Events"
    try
        -- Check if process exists
        set processExists to exists (process "{process_name}")
        if processExists then
            tell process "{process_name}"
                -- Check if window exists
                if exists window 1 then
                    set windowPosition to position of window 1
                    set windowSize to size of window 1
                    return "SUCCESS:" & (item 1 of windowPosition) & "," & (item 2 of windowPosition) & "," & (item 1 of windowSize) & "," & (item 2 of windowSize)
                else
                    return "NO_WINDOW: Process exists but no window found"
                end if
            end tell
        else
            return "NO_PROCESS: Process does not exist"
        end if
    on error errorMessage
        return "ERROR:" & errorMessage
    end try
end tell
'''

        try:
            result = subprocess.run(["osascript", "-e", applescript], capture_output=True, text=True, timeout=10)

            print(f"   Process: {process_name}")
            print(f"   Return code: {result.returncode}")
            print(f"   Stdout: {result.stdout.strip()}")
            if result.stderr:
                print(f"   Stderr: {result.stderr.strip()}")

            # Parse the result
            if result.returncode == 0 and result.stdout.strip():
                output = result.stdout.strip()
                if output.startswith("SUCCESS:"):
                    coords = output.replace("SUCCESS:", "").split(",")
                    if len(coords) == 4:
                        x, y, width, height = map(int, coords)
                        print(f"   ✅ {display_name}窗口位置: ({x}, {y}), 大小: {width}x{height}")
                    else:
                        print(f"   ⚠️  Unexpected format: {output}")
                elif output.startswith("NO_WINDOW:"):
                    print(f"   ⚠️  {display_name}: Process exists but no window")
                elif output.startswith("NO_PROCESS:"):
                    print(f"   ❌ {display_name}: Process not found")
                elif output.startswith("ERROR:"):
                    print(f"   ❌ {display_name}: Error - {output.replace('ERROR:', '')}")
                else:
                    print(f"   ❓ {display_name}: Unknown response: {output}")
            else:
                print(f"   ❌ {display_name}: AppleScript failed")

        except subprocess.TimeoutExpired:
            print(f"   ⏰ {display_name}: AppleScript timed out")
        except Exception as e:
            print(f"   ❌ {display_name}: Exception - {e}")


def test_system_events_access():
    """Test if we have access to System Events"""
    print("\n🔧 Testing System Events accessibility...")

    applescript = """
tell application "System Events"
    get name
end tell
"""

    try:
        result = subprocess.run(["osascript", "-e", applescript], capture_output=True, text=True, timeout=5)

        if result.returncode == 0:
            print("✅ System Events access: Granted")
            print(f"   System Events name: {result.stdout.strip()}")
        else:
            print("❌ System Events access: Denied")
            print(f"   Error: {result.stderr.strip()}")

    except Exception as e:
        print(f"❌ System Events test failed: {e}")


def test_list_running_processes():
    """List all running processes to see what browsers are available"""
    print("\n📋 Listing running browser processes...")

    # Get list of running processes
    try:
        # Using ps to find browser processes
        browser_keywords = ["chrome", "edge", "safari", "firefox", "brave", "opera"]

        for keyword in browser_keywords:
            result = subprocess.run(["ps", "aux"], capture_output=True, text=True)

            if result.returncode == 0:
                lines = result.stdout.split("\n")
                browser_processes = [line for line in lines if keyword in line.lower() and not "grep" in line]

                if browser_processes:
                    print(f"\n🔍 Processes with '{keyword}':")
                    for i, proc in enumerate(browser_processes[:3]):  # Show first 3
                        print(f"   {i + 1}. {proc.strip()}")
                    if len(browser_processes) > 3:
                        print(f"   ... and {len(browser_processes) - 3} more")
                else:
                    print(f"   No processes with '{keyword}' found")

    except Exception as e:
        print(f"❌ Process listing failed: {e}")


def test_alternative_apple_script_approaches():
    """Test alternative AppleScript approaches for window detection"""
    print("\n🔄 Testing alternative AppleScript approaches...")

    # Approach 1: Direct application tell (may work better for some browsers)
    approaches = [
        {
            "name": "Direct Application Tell",
            "script": """
tell application "Microsoft Edge"
    if it is running then
        set frontWindow to front window
        set windowPosition to position of frontWindow
        set windowSize to size of frontWindow
        return "SUCCESS:" & (item 1 of windowPosition) & "," & (item 2 of windowPosition) & "," & (item 1 of windowSize) & "," & (item 2 of windowSize)
    else
        return "NOT_RUNNING"
    end if
end tell
""",
        },
        {
            "name": "System Events with Error Handling",
            "script": """
try
    tell application "System Events"
        tell process "Microsoft Edge"
            if exists window 1 then
                set windowPosition to position of window 1
                set windowSize to size of window 1
                return "SUCCESS:" & (item 1 of windowPosition) & "," & (item 2 of windowPosition) & "," & (item 1 of windowSize) & "," & (item 2 of windowSize)
            else
                return "NO_WINDOW"
            end if
        end tell
    end tell
on error errorMessage
    return "ERROR:" & errorMessage
end try
""",
        },
    ]

    for approach in approaches:
        print(f"\n🧪 Testing approach: {approach['name']}")

        try:
            result = subprocess.run(["osascript", "-e", approach["script"]], capture_output=True, text=True, timeout=5)

            print(f"   Return code: {result.returncode}")
            print(f"   Output: {result.stdout.strip()}")
            if result.stderr:
                print(f"   Error: {result.stderr.strip()}")

        except Exception as e:
            print(f"   ❌ Failed: {e}")


def main():
    """Run all debug tests"""
    print("🔍 AppleScript Browser Window Detection Debug")
    print("=" * 60)

    # Check if we're on macOS
    if platform.system() != "Darwin":
        print("❌ This script is only for macOS")
        return

    # Run all tests
    test_system_events_access()
    test_list_running_processes()
    test_apple_script_detection()
    test_alternative_apple_script_approaches()

    print("\n" + "=" * 60)
    print("📊 Debug completed!")
    print("=" * 60)


if __name__ == "__main__":
    main()
