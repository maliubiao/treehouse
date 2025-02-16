import json
import sys

import requests


def main():
    # 读取测试HTML文件
    try:
        with open("test.html", "r", encoding="utf-8") as f:
            html_content = f.read()
    except FileNotFoundError:
        print("错误：未找到test.html文件")
        sys.exit(1)
    except Exception as e:
        print(f"读取文件出错: {str(e)}")
        sys.exit(1)

    # 构造请求数据
    payload = {"content": html_content}

    # 发送请求
    try:
        response = requests.post(
            url="http://localhost:3000/html_reader", headers={"Content-Type": "application/json"}, json=payload
        )
        response.raise_for_status()  # 检查HTTP错误
    except requests.exceptions.RequestException as e:
        print(f"API请求失败: {str(e)}")
        sys.exit(1)

    # 解析响应
    try:
        result = response.json()
    except json.JSONDecodeError:
        print("错误：响应不是有效的JSON格式")
        sys.exit(1)

    # 输出textContent
    if "textContent" in result:
        print("提取的文本内容：\n")
        print(result["textContent"])
    else:
        print("响应中缺少textContent字段")
        print("完整响应：", json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
