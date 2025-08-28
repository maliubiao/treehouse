#!/usr/bin/env python3
"""
Test if browser window needs to be frontmost for AppleScript detection
测试浏览器窗口是否需要是最前窗口才能被AppleScript检测到
"""

import subprocess
import time


def test_frontmost_requirement():
    """Test if browser window needs to be frontmost for detection"""
    print("🔍 Testing frontmost window requirement for AppleScript detection...")
    print("=" * 70)

    # Test with browser in background
    print("\n1. 🖥️  Testing with browser in BACKGROUND...")
    test_browser_detection("Microsoft Edge", "Background")

    # Bring browser to foreground and test again
    print("\n2. 🖥️  Bringing browser to FOREGROUND and testing again...")

    # AppleScript to bring Edge to foreground
    bring_to_front_script = """
tell application "Microsoft Edge"
    activate
end tell
"""

    try:
        result = subprocess.run(["osascript", "-e", bring_to_front_script], capture_output=True, text=True, timeout=5)

        if result.returncode == 0:
            print("✅ Successfully brought Microsoft Edge to foreground")
            # Wait a moment for window to become active
            time.sleep(2)
        else:
            print(f"❌ Failed to bring browser to foreground: {result.stderr}")

    except Exception as e:
        print(f"❌ Error bringing browser to foreground: {e}")

    # Test detection again
    test_browser_detection("Microsoft Edge", "Foreground")

    print("\n" + "=" * 70)
    print("📊 Frontmost Window Test Completed!")


def test_browser_detection(process_name, test_scenario):
    """Test browser detection with detailed AppleScript"""
    print(f"\n   Testing {test_scenario} scenario for {process_name}...")

    # Enhanced AppleScript with more debugging info
    applescript = f'''
tell application "System Events"
    try
        -- Check if process exists
        set processExists to exists (process "{process_name}")
        
        if processExists then
            -- Get process info
            tell process "{process_name}"
                set processFrontmost to frontmost
                set windowCount to count of windows
                
                -- Check if any windows exist
                if windowCount > 0 then
                    -- Check if window 1 exists and is visible
                    if exists window 1 then
                        set windowVisible to visible of window 1
                        set windowPosition to position of window 1
                        set windowSize to size of window 1
                        
                        return "SUCCESS: frontmost=" & processFrontmost & ", windows=" & windowCount & ", visible=" & windowVisible & ", position=" & (item 1 of windowPosition) & "," & (item 2 of windowPosition) & ", size=" & (item 1 of windowSize) & "," & (item 2 of windowSize)
                    else
                        return "WINDOW_NOT_EXIST: Process has " & windowCount & " windows but window 1 doesn't exist"
                    end if
                else
                    return "NO_WINDOWS: Process exists but has no windows"
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
        print(f"   Output: {result.stdout.strip()}")

        if result.stderr:
            print(f"   Error: {result.stderr.strip()}")

        # Parse and display results
        if result.returncode == 0 and result.stdout.strip():
            output = result.stdout.strip()

            if output.startswith("SUCCESS:"):
                print(f"   ✅ {test_scenario} detection: SUCCESS")
                # Extract and display details
                details = output.replace("SUCCESS: ", "")
                print(f"   📋 Details: {details}")

            elif output.startswith("NO_PROCESS:"):
                print(f"   ❌ {test_scenario} detection: Process not running")

            elif output.startswith("NO_WINDOWS:"):
                print(f"   ⚠️  {test_scenario} detection: Process running but no windows")

            elif output.startswith("WINDOW_NOT_EXIST:"):
                print(f"   ⚠️  {test_scenario} detection: Window doesn't exist")

            elif output.startswith("ERROR:"):
                print(f"   ❌ {test_scenario} detection: Error - {output.replace('ERROR:', '')}")

            else:
                print(f"   ❓ {test_scenario} detection: Unknown response")

        else:
            print(f"   ❌ {test_scenario} detection: AppleScript failed")

    except subprocess.TimeoutExpired:
        print(f"   ⏰ {test_scenario} detection: AppleScript timed out")
    except Exception as e:
        print(f"   ❌ {test_scenario} detection: Exception - {e}")


def main():
    """Run the frontmost window test"""
    print("🔍 Browser Frontmost Window Requirement Test")
    print("=" * 70)

    test_frontmost_requirement()


if __name__ == "__main__":
    main()
