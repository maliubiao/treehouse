#!/usr/bin/env python3
"""
Test Objective-C/Cocoa API for browser window detection
使用Objective-C/Cocoa API替代AppleScript进行浏览器窗口检测
"""

import platform
import subprocess
import time


def test_objc_window_detection():
    """Test Objective-C/Cocoa API for window detection"""
    print("🍎 Testing Objective-C/Cocoa API for browser window detection...")
    print("=" * 70)

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
        print(f"\n🔍 Testing {display_name} detection with Objective-C...")

        # Objective-C code to get window information using Cocoa APIs
        objc_code = f'''
#import <Cocoa/Cocoa.h>
#import <ApplicationServices/ApplicationServices.h>

int main() {{
    @autoreleasepool {{
        // Get all running applications
        NSArray *runningApps = [[NSWorkspace sharedWorkspace] runningApplications];
        
        // Look for the target browser
        for (NSRunningApplication *app in runningApps) {{
            NSString *appName = [app localizedName];
            if ([appName isEqualToString:@"{process_name}"]) {{
                // Found the browser application
                pid_t pid = [app processIdentifier];
                
                // Get the application's windows using Accessibility API
                AXUIElementRef appElement = AXUIElementCreateApplication(pid);
                
                if (appElement) {{
                    CFArrayRef windows;
                    AXError result = AXUIElementCopyAttributeValue(appElement, kAXWindowsAttribute, (CFTypeRef *)&windows);
                    
                    if (result == kAXErrorSuccess && windows && CFArrayGetCount(windows) > 0) {{
                        // Get the first window
                        AXUIElementRef window = (AXUIElementRef)CFArrayGetValueAtIndex(windows, 0);
                        
                        // Get window position
                        CFTypeRef positionRef;
                        CGPoint position = {{0, 0}};
                        if (AXUIElementCopyAttributeValue(window, kAXPositionAttribute, &positionRef) == kAXErrorSuccess) {{
                            AXValueGetValue(positionRef, kAXValueCGPointType, &position);
                            CFRelease(positionRef);
                        }}
                        
                        // Get window size
                        CFTypeRef sizeRef;
                        CGSize size = {{0, 0}};
                        if (AXUIElementCopyAttributeValue(window, kAXSizeAttribute, &sizeRef) == kAXErrorSuccess) {{
                            AXValueGetValue(sizeRef, kAXValueCGSizeType, &size);
                            CFRelease(sizeRef);
                        }}
                        
                        // Check if window is main/frontmost
                        CFTypeRef mainRef;
                        Boolean isMain = false;
                        if (AXUIElementCopyAttributeValue(window, kAXMainAttribute, &mainRef) == kAXErrorSuccess) {{
                            isMain = CFBooleanGetValue(mainRef);
                            CFRelease(mainRef);
                        }}
                        
                        printf("SUCCESS:%d,%d,%d,%d,%d\\n", 
                               (int)position.x, (int)position.y, 
                               (int)size.width, (int)size.height,
                               isMain);
                        
                        CFRelease(windows);
                        CFRelease(appElement);
                        return 0;
                    }}
                    
                    if (windows) CFRelease(windows);
                    CFRelease(appElement);
                }}
                
                printf("NO_WINDOWS:Process found but no accessible windows\\n");
                return 1;
            }}
        }}
        
        printf("NO_PROCESS:Application not found\\n");
        return 2;
    }}
    return 3;
}}
'''

        # Compile and run the Objective-C code
        try:
            # Write the Objective-C code to a temporary file
            import tempfile

            with tempfile.NamedTemporaryFile(suffix=".m", delete=False) as temp_file:
                temp_file.write(objc_code.encode("utf-8"))
                temp_path = temp_file.name

            # Compile the Objective-C code
            compile_result = subprocess.run(
                [
                    "clang",
                    "-framework",
                    "Cocoa",
                    "-framework",
                    "ApplicationServices",
                    "-o",
                    "/tmp/window_detector",
                    temp_path,
                ],
                capture_output=True,
                text=True,
            )

            if compile_result.returncode != 0:
                print(f"   ❌ Compilation failed: {compile_result.stderr}")
                continue

            # Run the compiled executable
            result = subprocess.run(["/tmp/window_detector"], capture_output=True, text=True, timeout=10)

            print(f"   Process: {process_name}")
            print(f"   Return code: {result.returncode}")
            print(f"   Output: {result.stdout.strip()}")

            if result.stderr:
                print(f"   Error: {result.stderr.strip()}")

            # Parse the result
            if result.returncode == 0 and result.stdout.strip():
                output = result.stdout.strip()
                if output.startswith("SUCCESS:"):
                    parts = output.replace("SUCCESS:", "").split(",")
                    if len(parts) == 5:
                        x, y, width, height, is_main = map(int, parts)
                        main_str = "主窗口" if is_main else "非主窗口"
                        print(f"   ✅ {display_name}窗口位置: ({x}, {y}), 大小: {width}x{height}, {main_str}")
                    else:
                        print(f"   ⚠️  Unexpected format: {output}")
                elif output.startswith("NO_WINDOWS:"):
                    print(f"   ⚠️  {display_name}: 进程存在但无可用窗口")
                elif output.startswith("NO_PROCESS:"):
                    print(f"   ❌ {display_name}: 进程未找到")
                else:
                    print(f"   ❓ {display_name}: 未知响应: {output}")
            else:
                print(f"   ❌ {display_name}: Objective-C检测失败")

        except subprocess.TimeoutExpired:
            print(f"   ⏰ {display_name}: Objective-C检测超时")
        except Exception as e:
            print(f"   ❌ {display_name}: 异常 - {e}")
        finally:
            # Clean up temporary files
            import os

            try:
                os.unlink(temp_path)
                os.unlink("/tmp/window_detector")
            except:
                pass


def test_accessibility_permissions():
    """Test if we have accessibility permissions"""
    print("\n🔧 Testing Accessibility API permissions...")

    # Check if accessibility permissions are granted
    objc_code = """
#import <Cocoa/Cocoa.h>
#import <ApplicationServices/ApplicationServices.h>

int main() {
    @autoreleasepool {
        // Check if we can access accessibility APIs
        NSDictionary *options = @{(__bridge id)kAXTrustedCheckOptionPrompt: @YES};
        BOOL accessibilityEnabled = AXIsProcessTrustedWithOptions((__bridge CFDictionaryRef)options);
        
        if (accessibilityEnabled) {
            printf("ACCESS_GRANTED: Accessibility permissions granted\\n");
            return 0;
        } else {
            printf("ACCESS_DENIED: Accessibility permissions not granted\\n");
            return 1;
        }
    }
}
"""

    try:
        # Write and compile the test
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".m", delete=False) as temp_file:
            temp_file.write(objc_code.encode("utf-8"))
            temp_path = temp_file.name

        compile_result = subprocess.run(
            ["clang", "-framework", "Cocoa", "-o", "/tmp/access_test", temp_path], capture_output=True, text=True
        )

        if compile_result.returncode != 0:
            print("❌ 编译权限检查代码失败")
            return

        # Run the test
        result = subprocess.run(["/tmp/access_test"], capture_output=True, text=True, timeout=5)

        print(f"返回码: {result.returncode}")
        print(f"输出: {result.stdout.strip()}")

        if result.stderr:
            print(f"错误: {result.stderr.strip()}")

    except Exception as e:
        print(f"❌ 权限检查失败: {e}")
    finally:
        # Clean up
        import os

        try:
            os.unlink(temp_path)
            os.unlink("/tmp/access_test")
        except:
            pass


def test_alternative_objc_approaches():
    """Test alternative Objective-C approaches for window detection"""
    print("\n🔄 Testing alternative Objective-C approaches...")

    # Approach 1: Using NSRunningApplication to get frontmost window
    approaches = [
        {
            "name": "NSRunningApplication Frontmost",
            "code": """
#import <Cocoa/Cocoa.h>

int main() {
    @autoreleasepool {
        // Get frontmost application
        NSRunningApplication *frontApp = [[NSWorkspace sharedWorkspace] frontmostApplication];
        if (frontApp) {
            NSString *appName = [frontApp localizedName];
            printf("FRONTMOST:%s\\n", [appName UTF8String]);
            return 0;
        } else {
            printf("NO_FRONTMOST\\n");
            return 1;
        }
    }
}
""",
        },
        {
            "name": "CGWindowList for All Windows",
            "code": """
#import <Cocoa/Cocoa.h>
#import <CoreGraphics/CoreGraphics.h>

int main() {
    @autoreleasepool {
        // Get all windows
        CFArrayRef windowList = CGWindowListCopyWindowInfo(kCGWindowListOptionOnScreenOnly, kCGNullWindowID);
        
        if (windowList) {
            CFIndex count = CFArrayGetCount(windowList);
            printf("WINDOW_COUNT:%ld\\n", count);
            
            // Look for browser windows
            for (CFIndex i = 0; i < count; i++) {
                CFDictionaryRef windowInfo = (CFDictionaryRef)CFArrayGetValueAtIndex(windowList, i);
                
                // Get window owner name
                CFStringRef ownerName = CFDictionaryGetValue(windowInfo, kCGWindowOwnerName);
                if (ownerName) {
                    const char *name = CFStringGetCStringPtr(ownerName, kCFStringEncodingUTF8);
                    if (name && (strstr(name, "Chrome") || strstr(name, "Edge") || strstr(name, "Safari") || 
                                 strstr(name, "Firefox") || strstr(name, "Brave") || strstr(name, "Opera"))) {
                        printf("BROWSER_FOUND:%s\\n", name);
                    }
                }
            }
            
            CFRelease(windowList);
            return 0;
        } else {
            printf("NO_WINDOWS\\n");
            return 1;
        }
    }
}
""",
        },
    ]

    for approach in approaches:
        print(f"\n🧪 Testing approach: {approach['name']}")

        try:
            # Write and compile
            import tempfile

            with tempfile.NamedTemporaryFile(suffix=".m", delete=False) as temp_file:
                temp_file.write(approach["code"].encode("utf-8"))
                temp_path = temp_file.name

            frameworks = ["-framework", "Cocoa"]
            if "CoreGraphics" in approach["code"]:
                frameworks.extend(["-framework", "CoreGraphics"])

            compile_result = subprocess.run(
                ["clang", *frameworks, "-o", "/tmp/alt_test", temp_path], capture_output=True, text=True
            )

            if compile_result.returncode != 0:
                print(f"   ❌ 编译失败: {compile_result.stderr}")
                continue

            # Run the test
            result = subprocess.run(["/tmp/alt_test"], capture_output=True, text=True, timeout=5)

            print(f"   返回码: {result.returncode}")
            print(f"   输出: {result.stdout.strip()}")

            if result.stderr:
                print(f"   错误: {result.stderr.strip()}")

        except Exception as e:
            print(f"   ❌ 失败: {e}")
        finally:
            # Clean up
            import os

            try:
                os.unlink(temp_path)
                os.unlink("/tmp/alt_test")
            except:
                pass


def main():
    """Run all Objective-C/Cocoa API tests"""
    print("🔍 Objective-C/Cocoa API Browser Window Detection Test")
    print("=" * 70)

    # Check if we're on macOS
    if platform.system() != "Darwin":
        print("❌ 此脚本仅适用于 macOS")
        return

    # Run all tests
    test_accessibility_permissions()
    test_objc_window_detection()
    test_alternative_objc_approaches()

    print("\n" + "=" * 70)
    print("📊 Objective-C/Cocoa API 测试完成!")
    print("=" * 70)


if __name__ == "__main__":
    main()
