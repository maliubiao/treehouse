let ws = new WebSocket(`ws://${window.location.host}/ws`);

// 初始化自动补全
document.addEventListener('DOMContentLoaded', () => {
    const fileInput = document.getElementById('filename');
    new FileAutocomplete(fileInput, {
        baseDir: '/Users/richard/code/terminal-llm',
        delay: 200
    });
});

ws.onmessage = function(event) {
    const msg = JSON.parse(event.data);
    if (msg.type === 'variables') {
        displayVariables(msg.data);
        document.querySelector('#current-location').textContent = 
            `Current location: ${msg.location}`;
    } else if (msg.type === 'breakpoint') {
        updateBreakpointsList();
    } else if (msg.type === 'stack_trace') {
        updateStackTrace(msg.data);
    } else if (msg.type === 'breakpoint_variables') {
        displayVariables(msg.data);
        document.querySelector('#current-location').textContent = 
            `Breakpoint location: ${msg.location}`;
    }
};

function displayVariables(data) {
    if (!Object.keys(data).length) {
        return;
    }
    const variableDataElement = document.getElementById('variable-data');
    variableDataElement.innerHTML = '';

    const table = document.createElement('table');
    const thead = document.createElement('thead');
    const tbody = document.createElement('tbody');

    thead.innerHTML = `
        <tr>
            <th>Variable</th>
            <th>Type</th>
            <th>Value</th>
        </tr>
    `;

    for (const [key, value] of Object.entries(data)) {
        const tr = document.createElement('tr');
        const typeCell = document.createElement('td');
        const valueCell = document.createElement('td');
        
        // 解析序列化后的数据结构
        const valueInfo = typeof value === 'object' ? value : JSON.parse(value);
        const varType = valueInfo.type;
        const isComplex = valueInfo.complex;
        let rawValue = valueInfo.value;

        typeCell.textContent = varType;
        typeCell.className = 'type-cell';

        try {
            // 尝试解析可能存在的嵌套JSON
            rawValue = JSON.parse(rawValue);
        } catch (e) {
            // 保持原始值如果解析失败
        }

        const displayValue = isComplex ? JSON.stringify(rawValue, null, 2) : rawValue;
        const valueStr = typeof displayValue === 'string' ? displayValue : JSON.stringify(displayValue);

        if (isComplex || valueStr.length > 50) {
            const shortValue = valueStr.substring(0, 50) + (valueStr.length > 50 ? '...' : '');
            const previewSpan = document.createElement('span');
            previewSpan.className = 'value-preview';
            previewSpan.textContent = shortValue;
            
            const viewButton = document.createElement('button');
            viewButton.textContent = 'View Full';
            viewButton.addEventListener('click', () => showFullValue(key, valueStr, varType));

            valueCell.append(previewSpan, viewButton);
        } else {
            valueCell.textContent = valueStr;
        }

        tr.innerHTML = `
            <td>${key}</td>
        `;
        tr.appendChild(typeCell);
        tr.appendChild(valueCell);
        tbody.appendChild(tr);
    }

    table.appendChild(thead);
    table.appendChild(tbody);
    variableDataElement.appendChild(table);
}

function escapeHtml(str) {
    return str.replace(/&/g, '&amp;')
              .replace(/</g, '&lt;')
              .replace(/>/g, '&gt;')
              .replace(/"/g, '&quot;')
              .replace(/'/g, '&#039;');
}

function syntaxHighlight(json) {
    json = json.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    return json.replace(/("(\\u[a-zA-Z0-9]{4}|\\[^u]|[^\\"])*"(\s*:)?|\b(true|false|null)\b|-?\d+(?:\.\d*)?(?:[eE][+\-]?\d+)?)/g, 
        function (match) {
            let cls = 'number';
            if (/^"/.test(match)) {
                if (/:$/.test(match)) {
                    cls = 'key';
                } else {
                    cls = 'string';
                }
            } else if (/true|false/.test(match)) {
                cls = 'boolean';
            } else if (/null/.test(match)) {
                cls = 'null';
            }
            return '<span class="' + cls + '">' + match + '</span>';
        });
}

function showFullValue(key, value, type) {
    const modal = document.getElementById('value-modal');
    const formattedValue = type === 'dict' || type === 'list' ? 
        syntaxHighlight(JSON.stringify(JSON.parse(value), null, 2)) : 
        escapeHtml(value);

    modal.innerHTML = `
        <div class="modal-content">
            <span class="close" onclick="closeModal()">&times;</span>
            <h2>${escapeHtml(key)} <span class="type-tag">${type}</span></h2>
            <pre><code class="language-json">${formattedValue}</code></pre>
            <button onclick="closeModal()">Close</button>
        </div>
    `;
    Prism.highlightAllUnder(modal);
    modal.style.display = 'block';
}

function closeModal() {
    document.getElementById('value-modal').style.display = 'none';
}

function updateBreakpointsList() {
    fetch('/breakpoints')
        .then(r => r.json())
        .then(data => {
            const list = document.getElementById('breakpoints-list');
            list.innerHTML = data.breakpoints.map(bp => 
                `<div class="breakpoint-item">
                    ${bp.file}:${bp.line} 
                    ${bp.function ? `(function: ${bp.function})` : ''}
                    ${bp.condition ? `(cond: ${bp.condition})` : ''}
                    <button onclick="deleteBreakpoint(${bp.id})">Delete</button>
                </div>`
            ).join('');
        });
}

function updateStackTrace(stack) {
    const stackTraceElement = document.getElementById('stack-trace');
    if (!stackTraceElement) {
        const container = document.querySelector('.container');
        const stackTraceDiv = document.createElement('div');
        stackTraceDiv.id = 'stack-trace';
        stackTraceDiv.className = 'stack-trace-panel';
        stackTraceDiv.innerHTML = `
            <h2>Stack Trace</h2>
            <pre></pre>
        `;
        container.appendChild(stackTraceDiv);
    }
    const preElement = document.querySelector('#stack-trace pre');
    preElement.textContent = stack.map(frame => 
        `${frame.filename}:${frame.lineno} in ${frame.function}`
    ).join('\n');
}

function addBreakpoint() {
    const filename = document.getElementById('filename').value;
    const line = parseInt(document.getElementById('line').value);
    const condition = document.getElementById('condition').value.trim() || null;
    const variables = document.getElementById('variables').value.split(',').map(v => v.trim()).filter(v => v);
    
    fetch('/breakpoints', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ file: filename, line: line, condition: condition, variables: variables })
    }).then(updateBreakpointsList);
}

function addFunctionBreakpoint() {
    const filename = document.getElementById('filename').value;
    const functionName = document.getElementById('function-name').value.trim();
    if (!functionName) return;

    fetch('/breakpoints', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ file: filename, function: functionName })
    }).then(() => {
        closeFunctionModal();
        updateBreakpointsList();
    });
}

function deleteBreakpoint(bpId) {
    fetch(`/breakpoints/${bpId}`, {
        method: 'DELETE',
    }).then(updateBreakpointsList);
}

function addVariable() {
    const variable = document.getElementById('variable').value;
    fetch('/variables', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ variables: [variable] })
    });
}
function showFunctionBreakpointModal() {
    document.getElementById('function-breakpoint-modal').style.display = 'block';
}

function closeFunctionModal() {
    document.getElementById('function-breakpoint-modal').style.display = 'none';
}

// Initial load
updateBreakpointsList();
