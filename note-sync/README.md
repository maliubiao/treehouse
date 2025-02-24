# obsidian 多机目录同步

这个小工具提供在不同的电脑间同步gpt生成的obsidian目录的功能，rsync + 索引diff   

## 使用方式

```bash

# 普通模式, 请注意rsync里目录+/ 是两个目录同级同步，不加则子文件夹
# ~/.ssh/config 时配置一个alias, 写public key比较方便

python sync.py --remote user@host:/path/to/obsidian/ --local /path/to/obsidian/

# Dry-run模式 
--dry-run
```

```crontab
#crontab定时同步
*/60 * * * * * python ~/code/terminal-llm/note-sync/sync.py  --remote MacMini:~/code/terminal-llm/obsidian/ --local /Users/richard/code/terminal-llm/obsidian/
```
