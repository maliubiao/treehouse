import argparse
import difflib
import re
import subprocess
from datetime import datetime
from pathlib import Path

# 配置信息
parser = argparse.ArgumentParser(description="RSYNC同步脚本")
parser.add_argument("--remote", required=True, help="远程地址，例如 user@host:/path")
parser.add_argument("--local", required=True, help="本地路径")
parser.add_argument("--interval", type=int, default=0, help="同步间隔秒数（0表示单次执行）")
parser.add_argument("--dry-run", action="store_true", help="模拟运行并显示差异")
args = parser.parse_args()

TEMP_DIR = Path("/tmp/sync_temp")
INDEX_SUFFIX = "-索引.md"
TIME_PATTERN = r"\[\[(\d{4}-\d{1,2}-\d{1,2})/(\d{1,2}-\d{1,2}-\d{1,2})\.md"


def run_rsync(source, target, exclude=None, dry_run=False):
    """执行rsync命令"""
    cmd = ["rsync", "-ravzP" + ("n" if dry_run else "")]
    if exclude:
        cmd.extend(["--exclude", exclude])
    cmd.extend([source, target])
    print(cmd)
    try:
        # 处理中文路径，设置编码为utf-8
        result = subprocess.run(cmd, check=True, text=True, encoding="utf-8", errors="ignore")
        if args.dry_run:
            print(f"[DRY-RUN] RSYNC操作预览:\n{result.stdout}")
    except subprocess.CalledProcessError as e:
        print(f"RSYNC失败: {e}")


def parse_entry_datetime(entry):
    """解析条目中的完整日期时间"""
    match = re.search(TIME_PATTERN, entry)
    if not match:
        return datetime.max  # 无效日期排到最后

    try:
        date_str = match.group(1)
        time_str = match.group(2).replace("-", ":")
        return datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return datetime.max


def generate_diff(original, new_content, filename):
    """生成差异对比"""
    diff = difflib.unified_diff(
        original.splitlines(keepends=True),
        new_content.splitlines(keepends=True),
        fromfile=f"原始 {filename}",
        tofile=f"合并后 {filename}",
        n=3,
    )
    return "".join(diff)


def process_index_file(local_file, dry_run=False):
    """处理索引文件并返回是否修改"""
    temp_file = TEMP_DIR / local_file.name
    # 读取内容
    local_content = ""
    if local_file.exists():
        with open(local_file, "r", encoding="utf-8") as f:
            local_content = f.read()

    remote_content = ""
    if temp_file.exists():
        with open(temp_file, "r", encoding="utf-8") as f:
            remote_content = f.read()

    # 合并内容
    all_entries = []
    if local_content:
        all_entries.extend(local_content.splitlines())
    if remote_content:
        all_entries.extend(remote_content.splitlines())

    # 去重和排序
    seen = set()
    processed = []
    for entry in sorted(all_entries, key=parse_entry_datetime):
        clean_entry = entry.strip()
        if not clean_entry:
            continue

        if clean_entry not in seen:
            seen.add(clean_entry)
            processed.append(entry + "\n")  # 保持换行符一致

    new_content = "".join(processed)

    # 显示差异
    diff = generate_diff(local_content, new_content, local_file.name)
    if diff:
        print(f"\n索引文件 {local_file.name} 合并差异：")
        print(diff)

    # 实际写入
    if new_content != local_content:
        with open(local_file, "w", encoding="utf-8") as f:
            f.write(new_content)
        return True
    return False


def full_sync():
    """完整同步流程"""
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    changed = False

    # 第一步：同步普通文件
    if not args.dry_run:
        print("同步普通文件...")
        run_rsync(args.remote, args.local, exclude=f"*{INDEX_SUFFIX}", dry_run=args.dry_run)
        run_rsync(args.local, args.remote, exclude=f"*{INDEX_SUFFIX}", dry_run=args.dry_run)
    else:
        print("\n普通文件同步预览：")
        run_rsync(args.remote, args.local, exclude=f"*{INDEX_SUFFIX}", dry_run=True)
        run_rsync(args.local, args.remote, exclude=f"*{INDEX_SUFFIX}", dry_run=True)

    # 第二步：处理索引文件
    print("\n处理索引文件...")
    remote_index = f"{args.remote.rstrip('/')}/*{INDEX_SUFFIX}"
    run_rsync(remote_index, str(TEMP_DIR), dry_run=args.dry_run)
    # 处理每个索引文件
    local_index_files = list(Path(args.local).glob(f"*{INDEX_SUFFIX}"))
    for index_file in local_index_files:
        changed |= process_index_file(index_file)

    # 第三步：回传索引文件
    if changed and not args.dry_run:
        print("\n回传合并后的索引文件...")
        run_rsync(f"{TEMP_DIR}/", args.remote, dry_run=args.dry_run)


if __name__ == "__main__":
    if args.interval > 0 and not args.dry_run:
        import time

        while True:
            print(f"\n开始同步 @ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            full_sync()
            print(f"同步完成，等待 {args.interval} 秒...")
            time.sleep(args.interval)
    else:
        full_sync()
        if args.dry_run:
            print("\nDry-run模式完成，未执行实际修改")
