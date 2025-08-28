#!/usr/bin/env python3
"""
Debug script to investigate window detection issues
"""

import os
import subprocess
import tempfile


def debug_objective_c_window_detection():
    """Debug Objective-C window detection"""
    print("🔍 Debugging Objective-C window detection...")

    objc_code = """
#import <Cocoa/Cocoa.h>
#import <ApplicationServices/ApplicationServices.h>

int main() {
    @autoreleasepool {
        // 获取所有运行的应用
        NSArray *runningApps = [[NSWorkspace sharedWorkspace] runningApplications];
        
        // 查找Microsoft Edge并打印所有运行的应用
        printf("Running applications:\\n");
        for (NSRunningApplication *app in runningApps) {
            NSString *appName = [app localizedName];
            printf("  - %s\\n", [appName UTF8String]);
            if ([appName isEqualToString:@"Microsoft Edge"]) {
                // 找到浏览器应用
                pid_t pid = [app processIdentifier];
                printf("Found Microsoft Edge, PID: %d\\n", pid);
                
                // 使用Accessibility API获取应用窗口
                AXUIElementRef appElement = AXUIElementCreateApplication(pid);
                
                if (appElement) {
                    CFArrayRef windows;
                    AXError result = AXUIElementCopyAttributeValue(appElement, kAXWindowsAttribute, (CFTypeRef *)&windows);
                    
                    if (result == kAXErrorSuccess && windows) {
                        CFIndex windowCount = CFArrayGetCount(windows);
                        printf("Number of windows: %ld\\n", windowCount);
                        
                        for (CFIndex i = 0; i < windowCount; i++) {
                            AXUIElementRef window = (AXUIElementRef)CFArrayGetValueAtIndex(windows, i);
                            
                            // 获取窗口标题
                            CFTypeRef titleRef;
                            if (AXUIElementCopyAttributeValue(window, kAXTitleAttribute, &titleRef) == kAXErrorSuccess) {
                                NSString *title = (__bridge NSString *)titleRef;
                                printf("Window %ld title: %s\\n", i, [title UTF8String]);
                                CFRelease(titleRef);
                            }
                            
                            // 获取窗口位置
                            CFTypeRef positionRef;
                            CGPoint position = {0, 0};
                            if (AXUIElementCopyAttributeValue(window, kAXPositionAttribute, &positionRef) == kAXErrorSuccess) {
                                AXValueGetValue(positionRef, kAXValueCGPointType, &position);
                                CFRelease(positionRef);
                            }
                            
                            // 获取窗口大小
                            CFTypeRef sizeRef;
                            CGSize size = {0, 0};
                            if (AXUIElementCopyAttributeValue(window, kAXSizeAttribute, &sizeRef) == kAXErrorSuccess) {
                                AXValueGetValue(sizeRef, kAXValueCGSizeType, &size);
                                CFRelease(sizeRef);
                            }
                            
                            printf("Window %ld: pos=(%d, %d), size=%dx%d\\n", 
                                   i, (int)position.x, (int)position.y, 
                                   (int)size.width, (int)size.height);
                            
                            // 检查窗口是否为主窗口
                            CFTypeRef mainWindowRef;
                            Boolean isMainWindow = false;
                            if (AXUIElementCopyAttributeValue(window, CFSTR("AXMain"), &mainWindowRef) == kAXErrorSuccess) {
                                isMainWindow = CFBooleanGetValue(mainWindowRef);
                                CFRelease(mainWindowRef);
                                printf("  Is main window: %s\\n", isMainWindow ? "YES" : "NO");
                            }
                            
                            // 检查窗口是否可见
                            CFTypeRef visibleRef;
                            Boolean isVisible = false;
                            if (AXUIElementCopyAttributeValue(window, CFSTR("AXVisible"), &visibleRef) == kAXErrorSuccess) {
                                isVisible = CFBooleanGetValue(visibleRef);
                                CFRelease(visibleRef);
                                printf("  Is visible: %s\\n", isVisible ? "YES" : "NO");
                            }
                            
                            printf("\\n");
                        }
                        
                        CFRelease(windows);
                    } else {
                        printf("Failed to get windows: error code %d\\n", result);
                    }
                    
                    CFRelease(appElement);
                } else {
                    printf("Failed to create app element\\n");
                }
                
                return 0;
            }
        }
        
        printf("Microsoft Edge not found\\n");
        return 1;
    }
    return 0;
}
"""

    # 编译并运行Objective-C代码
    try:
        # 写入临时文件
        with tempfile.NamedTemporaryFile(suffix=".m", delete=False) as temp_file:
            temp_file.write(objc_code.encode("utf-8"))
            temp_path = temp_file.name

        # 编译
        compile_result = subprocess.run(
            [
                "clang",
                "-framework",
                "Cocoa",
                "-framework",
                "ApplicationServices",
                "-o",
                "/tmp/window_debugger",
                temp_path,
            ],
            capture_output=True,
            text=True,
        )

        if compile_result.returncode != 0:
            print(f"❌ Compilation failed: {compile_result.stderr}")
            return False

        # 运行
        result = subprocess.run(["/tmp/window_debugger"], capture_output=True, text=True)

        print(f"Return code: {result.returncode}")
        print(f"Output:\n{result.stdout}")
        if result.stderr:
            print(f"Errors:\n{result.stderr}")

        # 清理临时文件
        os.unlink(temp_path)

        return result.returncode == 0

    except Exception as e:
        print(f"❌ Debug failed: {e}")
        return False


if __name__ == "__main__":
    print("🔍 Microsoft Edge Window Detection Debug")
    print("=" * 60)

    success = debug_objective_c_window_detection()

    print("=" * 60)
    if success:
        print("✅ Debug completed successfully")
    else:
        print("❌ Debug failed")
