# gpt 配置
if [[ -z "$GPT_PATH" ]]; then                                                 
    if [ -n "$BASH_VERSION" ]; then                                             
    # 针对 bash，使用 BASH_SOURCE                                             
    _SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)                 
    elif [ -n "$ZSH_VERSION" ]; then                                            
    # 针对 zsh，使用 %x 扩展                                                  
    _SCRIPT_DIR=$(cd "$(dirname "${(%):-%x}")" && pwd)                        
    else                                                                        
    echo "Error: Unsupported shell. Please use bash or zsh."                  
    return 1 2>/dev/null || exit 1                                            
    fi                                                                          
    export GPT_PATH="$_SCRIPT_DIR"                                              
    unset _SCRIPT_DIR                                                           
fi       
export GPT_DOC="$GPT_PATH/obsidian"
export PATH="$GPT_PATH/bin:$PATH"
export GPT_PROMPTS_DIR="$GPT_PATH/prompts"
export GPT_LOGS_DIR="$GPT_PATH/logs"
export GPT_MAX_TOKEN=16384
#export GPT_API_SERVER=http://127.0.0.1:9050/

#DEBUG=1
#对话的uuid
export GPT_UUID_CONVERSATION=`uuidgen`

# 新增重置会话UUID的函数
function newconversation() {
    export GPT_UUID_CONVERSATION=$(uuidgen)
    echo "新会话编号: " $GPT_UUID_CONVERSATION
}

# 新增列举所有会话功能
function allconversation() {
    _conversation_list "${1:-0}"
}

# 重构后的通用会话列表函数
function _conversation_list() {
    local limit=$1
    local title
    [[ $limit -gt 0 ]] && title="最近的${limit}条对话记录" || title="所有对话记录"

    # 使用 Python 处理核心逻辑
    local selection=$(CONVERSATION_LIMIT=$limit python3 -c '
import os, sys, json
from datetime import datetime

conversation_dir = os.path.join(os.environ["GPT_PATH"], "conversation")
files = []

# 递归扫描目录
for root, _, filenames in os.walk(conversation_dir):
    for fname in filenames:
        if fname in ["index.json", ".DS_Store"] or not fname.endswith(".json"):
            continue
        path = os.path.join(root, fname)

        try:
            # 解析路径结构 conversation/YYYY-MM-DD/HH-MM-SS-UUID.json
            date_str = os.path.basename(os.path.dirname(path))
            time_uuid = os.path.splitext(fname)[0]
            uuid = "-".join(time_uuid.split("-")[3:])
            time_str = ":".join(time_uuid.split("-")[0:3])

            # 获取文件修改时间
            mtime = os.path.getmtime(path)

            # 读取第一条消息内容
            preview = "N/A"
            with open(path, "r") as f:
                data = json.load(f)
                if isinstance(data, list) and len(data) > 0:
                    first_msg = data[0].get("content", "")
                    preview = first_msg[:32].replace("\n", " ").strip()

            files.append((mtime, date_str, time_str, uuid, preview, path))
        except Exception as e:
            continue

# 按修改时间倒序排序
files.sort(reverse=True, key=lambda x: x[0])

# 应用数量限制
limit = int(os.getenv("CONVERSATION_LIMIT", "0"))
if limit > 0:
    files = files[:limit]

# 生成带制表符分隔的选择列表
for idx, (_, date, time, uuid, preview, _) in enumerate(files):
    print(f"{idx+1}\t{date} {time}\t{uuid}\t{preview}")
')

    # 处理空结果
    if [[ -z "$selection" ]]; then
        echo "没有找到历史对话"
        return 1
    fi

    # 显示格式化菜单
    echo "$title："
    echo "$selection" | awk -F '\t' '
    BEGIN { format = "\033[1m%2d)\033[0m \033[33m%-19s\033[0m \033[36m%-36s\033[0m %s\n" }
    {
        preview = length($4)>32 ? substr($4,1,32) "..." : $4
        printf format, $1, $2, $3, preview
    }
    '

    # 计算有效条目数
    local item_count=$(echo "$selection" | wc -l)

    # 用户输入处理
    echo -n "请选择对话 (1-${item_count}，直接回车取消): "
    read -r choice

    # 选择验证和处理
    if [[ "$choice" =~ ^[0-9]+$ ]] && (( choice >= 1 && choice <= item_count));
then
        local selected_uuid=$(echo "$selection" | awk -F '\t' -v choice="$choice" 'NR==choice {print $3}')
        export GPT_UUID_CONVERSATION="$selected_uuid"
        echo "已切换到对话: $selected_uuid"
    else
        echo "操作已取消"
    fi
}

# 修改原有 recentconversation 函数
function recentconversation() {
    _conversation_list 10
}

# 初始化目录
mkdir -p "$GPT_PATH"/{bin,prompts,logs} 2>/dev/null

function listgpt() {
    local config_file="${1:-$GPT_PATH/model.json}"

    # 检查配置文件是否存在
    [[ -f "$config_file" ]] || {
        echo >&2 "错误：未找到配置文件: $config_file"
        return 1
    }

    # 使用python3解析并列出所有非空key的模型
    python3 -c "import json, sys; config=json.load(open('$config_file')); [print(f'{k}: {v[\"model_name\"]}') for k, v in config.items() if v.get('key')]" 2>/dev/null
}


function usegpt() {
    local model_name="$1"
    local config_file="${2:-$GPT_PATH/model.json}"
    local no_verbose="$3"

    # 检查参数
    [[ -z "$model_name" ]] && {
        echo >&2 "错误：模型名称不能为空"
        return 1
    }

    # 检查配置文件是否存在
    [[ -f "$config_file" ]] || {
        echo >&2 "错误：未找到配置文件: $config_file"
        return 1
    }

    # 使用python3一次性解析并提取所有配置项
    local key base_url model max_tokens
    read key base_url model max_tokens <<< $(python3 -c "import json, sys; config=json.load(open('$config_file')).get('$model_name', {}); print(config.get('key', ''), config.get('base_url', ''), config.get('model_name', ''), config.get('max_tokens', ''))" 2>/dev/null)

    # 检查是否成功获取配置
    if [[ -z "$key" || -z "$base_url" || -z "$model" ]]; then
        echo >&2 "错误：未找到模型 '$model_name' 或配置不完整"
        return 1
    fi

    # 设置环境变量
    export GPT_KEY="$key"
    export GPT_BASE_URL="$base_url"
    export GPT_MODEL="$model"
    [[ -n "$max_tokens" ]] && export GPT_MAX_TOKEN="$max_tokens"

    # 如果VERBOSE参数不存在，则输出成功日志
    if [[ -z "$no_verbose" ]]; then
        echo "成功设置GPT环境变量："
        echo "  GPT_KEY: ${key:0:4}****"
        echo "  GPT_BASE_URL: $base_url"
        echo "  GPT_MODEL: $model"
        [[ -n "$max_tokens" ]] && echo "  GPT_MAX_TOKEN: $max_tokens"
    fi
}

# 检查GPT_PATH和GPT_KEY是否配置
if [[ -z "$GPT_KEY" || -z "$GPT_BASE_URL"  || -z "$GPT_MODEL" ]]; then
    [[ $DEBUG -eq 1 ]] && echo "Debug: 检测到GPT环境变量未配置，尝试使用默认provider" >&2
    
    if [[ -f "$GPT_PATH/model.json" ]]; then
        [[ $DEBUG -eq 1 ]] && echo "Debug: 找到model.json文件: $GPT_PATH/model.json" >&2
        
        # 使用默认的provider
        default_provider=$(python3 -c "import json; config=json.load(open('$GPT_PATH/model.json')); print('default' if 'default' in config else next(iter(config.keys())))" 2>/dev/null)
        
        if [[ -z "$default_provider" ]]; then
            echo >&2 "错误：未设置默认的provider，请在model.json中配置'default'字段"
            [[ $DEBUG -eq 1 ]] && echo "Debug: model.json中未找到default字段，且无法获取第一个provider" >&2
            return 1
        fi
        
        [[ $DEBUG -eq 1 ]] && echo "Debug: 找到默认provider: $default_provider" >&2
        
        if [[ -n "$default_provider" ]]; then
            [[ $DEBUG -eq 1 ]] && echo "Debug: 正在使用默认provider: $default_provider" >&2
            usegpt "$default_provider" "$GPT_PATH/model.json" 1
            if [[ $? -ne 0 ]]; then
                echo >&2 "错误：使用默认provider $default_provider 失败"
                [[ $DEBUG -eq 1 ]] && echo "Debug: usegpt命令执行失败" >&2
                return 1
            fi
        fi
    else
        echo >&2 "错误：未找到model.json文件: $GPT_PATH/model.json"
        [[ $DEBUG -eq 1 ]] && echo "Debug: 在$GPT_PATH路径下未找到model.json文件" >&2
        return 1
    fi
fi


session_id=$(uuidgen)                                                         
export GPT_SESSION_ID=$session_id 

# 主函数
function explaingpt() {
    local file="$1"
    local prompt_file="${2:-$GPT_PROMPTS_DIR/source-query.txt}"

    # 参数检查
    [[ -f "$file" ]] || {
        echo >&2 "Error: Source file not found: $file"
        return 1
    }
    [[ -f "$prompt_file" ]] || {
        echo >&2 "Error: Prompt file not found: $prompt_file"
        return 1
    }

    echo $GPT_PATH/.venv/bin/python $prompt_file $file
    # 执行核心脚本
    $GPT_PATH/.venv/bin/python $GPT_PATH/llm_query.py --file "$file" --prompt-file "$prompt_file"
}

function commitgpt() {
    newconversation
    askgpt @git-commit-message @git-stage= @git-diff-summary.txt; rm git-diff-summary.txt
    
    # 检查结果文件是否存在且内容有效
    if [[ -f "$GPT_PATH/.lastgptanswer" ]]; then
        # 读取文件内容并去除空白字符
        content=$(cat "$GPT_PATH/.lastgptanswer" | tr -d '[:space:]')
        
        # 检查内容是否为空
        if [[ -z "$content" ]]; then
            echo "错误：GPT返回的提交信息为空"
            rm "$GPT_PATH/.lastgptanswer"
            return 1
        fi
        
        # 打开编辑器让用户确认提交信息
        ${EDITOR:-vim} "$GPT_PATH/.lastgptanswer"
        
        # 再次检查编辑后的内容是否为空
        edited_content=$(cat "$GPT_PATH/.lastgptanswer" | tr -d '[:space:]')
        if [[ -z "$edited_content" ]]; then
            echo "错误：编辑后的提交信息为空"
            rm "$GPT_PATH/.lastgptanswer"
            return 1
        fi
        
        # 执行提交
        git commit -F "$GPT_PATH/.lastgptanswer" && rm "$GPT_PATH/.lastgptanswer"
    else
        echo "错误：未找到提交信息文件 $GPT_PATH/.lastgptanswer"
        return 1
    fi
}

# 检查环境变量的公共函数
_check_gpt_env() {
    if [[ -z "$GPT_KEY" || -z "$GPT_MODEL" || -z "$GPT_BASE_URL" ]]; then
        echo "错误：请先配置GPT_KEY、GPT_MODEL和GPT_BASE_URL环境变量"
        return 1
    fi
}

function chat() {
    # 检查环境变量
    _check_gpt_env || return 1
        
    # 根据参数决定是否创建新会话
    if [[ "$1" == "new" ]]; then
        export GPT_UUID_CONVERSATION=$(uuidgen)
    fi
    
    # 启动聊天机器人
    $GPT_PATH/.venv/bin/python $GPT_PATH/llm_query.py --chatbot 
}

# 为保持兼容性，保留原有函数名
function chatbot() { chat "new"; }
function chatagain() { chat; }

function naskgpt() {
    # 保存当前会话
    local original_session=$GPT_SESSION_ID
    
    # 创建新会话
    newconversation
    
    # 执行提问
    askgpt $@
    
    # 恢复原会话
    export GPT_SESSION_ID=$original_session
    echo "已恢复原会话: $original_session"
}


function askgpt() {
    local question="$@"

    # 参数检查
    [[ -z "$question" ]] && {
        echo >&2 "Error: Question cannot be empty"
        return 1
    }

    # 执行核心脚本
    $GPT_PATH/.venv/bin/python $GPT_PATH/llm_query.py --ask "$question"
}

if [[ -n "$ZSH_VERSION" ]]; then
    _at_complete() {
        # 定义调试开关
        local DEBUG=${GPT_DEBUG:-0}

        # 输出调试信息
        [[ $DEBUG -eq 1 ]] && echo "Debug: 当前PREFIX = $PREFIX" >&2
        [[ $DEBUG -eq 1 ]] && echo "Debug: 当前GPT_PATH = $GPT_PATH" >&2

        # 检查当前输入是否以@开头
        if [[ "$PREFIX" == @* ]]; then
            # 保存原始前缀
            local orig_prefix=$PREFIX
            [[ $DEBUG -eq 1 ]] && echo "Debug: 检测到@前缀，原始前缀 = $orig_prefix" >&2

            # 提取@后的部分作为新前缀
            PREFIX=${orig_prefix#@}
            [[ $DEBUG -eq 1 ]] && echo "Debug: 新PREFIX = $PREFIX" >&2

            # 设置IPREFIX为@，使得补全结果自动添加@
            IPREFIX="@"
            [[ $DEBUG -eq 1 ]] && echo "Debug: 设置IPREFIX = $IPREFIX" >&2

            # 获取prompts目录下的文件列表
            local prompt_files=()
            if [[ -d "$GPT_PATH/prompts" ]]; then
                prompt_files=($(ls "$GPT_PATH/prompts"))
                # 只输出一次提示词文件信息
                [[ $DEBUG -eq 1 ]] && echo "Debug: 找到提示词文件: ${prompt_files[@]}" >&2
            else
                [[ $DEBUG -eq 1 ]] && echo "Debug: 未找到提示词目录 $GPT_PATH/prompts" >&2
            fi
            # 如果GPT_API_SERVER存在，则添加API补全
            local api_completions=()
            if [[ -n "$GPT_API_SERVER" && "$PREFIX" == symbol* ]]; then
                local api_url="${GPT_API_SERVER}complete_simple?prefix=${PREFIX}"
                [[ $DEBUG -eq 1 ]] && echo "Debug: 尝试从API获取补全: $api_url" >&2
                api_completions=($(curl -s --noproxy "*" "$api_url" 2>/dev/null))
                # 在每个补全结果前添加@符号
                # api_completions=("${api_completions[@]/#/@}")
                [[ $DEBUG -eq 1 ]] && echo "Debug: 从API获取到补全: ${api_completions[@]}" >&2
            fi

            # 生成补全建议：首先添加clipboard和tree，然后prompts目录文件，接着API补全，最后普通文件补全
            [[ $DEBUG -eq 1 ]] && echo "Debug: 开始生成补全建议" >&2
            _alternative \
                'special:特殊选项:(clipboard tree treefull read listen symbol:)' \
                'prompts:提示词文件:(${prompt_files[@]})' \
                'api:API补全:(${api_completions[@]})' \
                'files:文件名:_files'

            # 恢复原始前缀（避免影响其他补全）
            PREFIX=$orig_prefix
            IPREFIX=""
            [[ $DEBUG -eq 1 ]] && echo "Debug: 恢复原始前缀 PREFIX = $PREFIX, IPREFIX = $IPREFIX" >&2
        else
            # 其他情况使用默认文件补全
            [[ $DEBUG -eq 1 ]] && echo "Debug: 未检测到@前缀，使用默认文件补全" >&2
            _files "$@"
        fi
    }

    compdef _at_complete askgpt
    compdef _at_complete naskgpt

    function _usegpt_complete() {
        local config_file="${1:-$GPT_PATH/model.json}"
        
        # 检查配置文件是否存在
        [[ -f "$config_file" ]] || {
            echo >&2 "错误：未找到配置文件: $config_file"
            return 1
        }

        # 获取所有可用的provider名称
        local providers=($(python3 -c "import json, sys; config=json.load(open('$config_file')); [print(k) for k in config.keys() if config[k].get('key')]" 2>/dev/null))

        # 生成补全建议
        _describe 'command' providers
    }

    compdef _usegpt_complete usegpt

fi

if [[ -n "$BASH_VERSION" ]]; then
    _askgpt_bash_complete() {
        local cur prev prompt_files special_items api_completions
        cur="${COMP_WORDS[COMP_CWORD]}"

        if [[ "$cur" == @* ]]; then
            local prefix="@"
            local search_prefix="${cur#@}"

            special_items=(clipboard tree treefull read listen symbol:)
            prompt_files=()
            if [[ -d "$GPT_PATH/prompts" ]]; then
                prompt_files=($(ls "$GPT_PATH/prompts" 2>/dev/null))
            fi

            api_completions=()
            if [[ -n "$GPT_API_SERVER" && "$search_prefix" == symbol* ]]; then
                local api_url="${GPT_API_SERVER}complete_simple?prefix=${search_prefix}"
                api_completions=($(curl -s "$api_url" 2>/dev/null))
            fi

            COMPREPLY=()
            [[ -n "$search_prefix" ]] || COMPREPLY+=("${special_items[@]/#/$prefix}")
            [[ ${#prompt_files[@]} -gt 0 ]] && COMPREPLY+=("${prompt_files[@]/#/$prefix}")
            [[ ${#api_completions[@]} -gt 0 ]] && COMPREPLY+=("${api_completions[@]/#/$prefix}")
            COMPREPLY+=($(compgen -f -- "$search_prefix" | sed 's/^/@/'))
            COMPREPLY=($(compgen -W "${COMPREPLY[*]}" -- "$cur"))
        else
            COMPREPLY=($(compgen -f -- "$cur"))
        fi
    }
    complete -F _askgpt_bash_complete askgpt
    complete -F _askgpt_bash_complete naskgpt

    _usegpt_bash_complete() {
        local cur prev config_file
        cur="${COMP_WORDS[COMP_CWORD]}"
        config_file="${GPT_PATH}/model.json"

        # 检查配置文件是否存在
        if [[ ! -f "$config_file" ]]; then
            echo >&2 "错误：未找到配置文件: $config_file"
            return 1
        fi

        # 获取所有可用的provider名称
        local providers=($(python3 -c "import json, sys; config=json.load(open('$config_file')); [print(k) for k in config.keys() if config[k].get('key')]" 2>/dev/null))

        # 生成补全建议
        COMPREPLY=($(compgen -W "${providers[*]}" -- "$cur"))
    }

    complete -F _usegpt_bash_complete usegpt


fi

