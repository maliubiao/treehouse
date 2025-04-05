document.addEventListener('DOMContentLoaded', function() {
    const content = document.getElementById('content');
    const searchInput = document.getElementById('search');
    const expandAllBtn = document.getElementById('expandAll');
    const collapseAllBtn = document.getElementById('collapseAll');
    const exportBtn = document.getElementById('exportBtn');

    // 搜索功能
    searchInput.addEventListener('input', function() {
        const term = this.value.toLowerCase();
        const elements = content.querySelectorAll('div');

        elements.forEach(el => {
            const text = el.textContent.toLowerCase();
            if (term && text.includes(term)) {
                el.classList.add('highlight');
                let parent = el.parentElement;
                while (parent && parent !== content) {
                    if (parent.classList.contains('foldable')) {
                        parent.classList.add('expanded');
                        const group = parent.nextElementSibling;
                        if (group) group.classList.remove('collapsed');
                    }
                    parent = parent.parentElement;
                }
            } else {
                el.classList.remove('highlight');
            }
        });
    });

    // 展开/折叠功能
    content.addEventListener('click', function(e) {
        if (e.target.classList.contains('foldable')) {
            e.target.classList.toggle('expanded');
            const group = e.target.nextElementSibling;
            if (group) group.classList.toggle('collapsed');
        }
    });

    // 全部展开
    expandAllBtn.addEventListener('click', function() {
        const foldables = content.querySelectorAll('.foldable');
        foldables.forEach(el => {
            el.classList.add('expanded');
            const group = el.nextElementSibling;
            if (group) group.classList.remove('collapsed');
        });
    });

    // 全部折叠
    collapseAllBtn.addEventListener('click', function() {
        const foldables = content.querySelectorAll('.foldable');
        foldables.forEach(el => {
            el.classList.remove('expanded');
            const group = el.nextElementSibling;
            if (group) group.classList.add('collapsed');
        });
    });

    // 导出功能
    exportBtn.addEventListener('click', function() {
        const html = document.documentElement.outerHTML;
        const blob = new Blob([html], {type: 'text/html'});
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'trace_report.html';
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    });
});