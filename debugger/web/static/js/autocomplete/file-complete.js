class FileAutocomplete {
    constructor(inputEl, options = {}) {
        this.input = inputEl;
        this.delay = options.delay || 300;
        this.minLength = options.minLength || 1;
        this.baseDir = options.baseDir || '/Users/richard/code/terminal-llm';
        this.container = document.createElement('div');
        this.container.className = 'autocomplete-container';
        this.input.parentNode.insertBefore(this.container, this.input.nextSibling);
        this.autoTriggered = false;
        
        this.input.style.position = 'relative';
        this.container.style.position = 'absolute';
        this.setupEvents();
    }

    setupEvents() {
        let timeout;
        this.input.addEventListener('input', (e) => {
            if (this.autoTriggered) return;
            clearTimeout(timeout);
            if (e.target.value.length >= this.minLength) {
                timeout = setTimeout(() => this.handleInput(e.target.value), this.delay);
            } else {
                this.hide();
            }
        });

        // this.input.addEventListener('focus', () => {
        //     if (this.input.value.length >= this.minLength) {
        //         this.handleInput(this.input.value);
        //     }
        // });

        this.input.addEventListener('keydown', (e) => {
            const items = this.container.querySelectorAll('.autocomplete-item');
            if (!items.length) return;

            const current = this.container.querySelector('.selected');
            switch(e.key) {
                case 'ArrowDown':
                    e.preventDefault();
                    this.selectNext(items, current);
                    break;
                case 'ArrowUp':
                    e.preventDefault();
                    this.selectPrev(items, current);
                    break;
                case 'Enter':
                    e.preventDefault();
                    if (current) {
                        this.selectItem(current);
                    }
                    break;
                case 'Escape':
                    this.hide();
                    break;
            }
        });

        document.addEventListener('click', (e) => {
            if (!this.container.contains(e.target) && e.target !== this.input) {
                this.hide();
            }
        });
    }

    selectNext(items, current) {
        const next = current ? 
            current.nextElementSibling || items[0] : 
            items[0];
        if (current) current.classList.remove('selected');
        next.classList.add('selected');
        this.scrollToItem(next);
    }

    selectPrev(items, current) {
        const prev = current ? 
            current.previousElementSibling || items[items.length-1] : 
            items[items.length-1];
        if (current) current.classList.remove('selected');
        prev.classList.add('selected');
        this.scrollToItem(prev);
    }

    scrollToItem(item) {
        const container = this.container;
        const itemTop = item.offsetTop;
        const itemHeight = item.offsetHeight;
        const containerHeight = container.offsetHeight;
        const scrollTop = container.scrollTop;

        if (itemTop < scrollTop) {
            container.scrollTop = itemTop;
        } else if (itemTop + itemHeight > scrollTop + containerHeight) {
            container.scrollTop = itemTop + itemHeight - containerHeight;
        }
    }

    async handleInput(value) {
        const normalizedValue = value.replace(/\/+/g, '/');
        const path = normalizedValue.startsWith('/') ? 
            normalizedValue : 
            `${this.baseDir}/${normalizedValue}`;
            
        const [dir, partial] = this.parsePathComponents(path);

        try {
            const response = await fetch(`/autocomplete/file?dir=${encodeURIComponent(dir)}&partial=${encodeURIComponent(partial)}`);
            if (!response.ok) throw new Error('请求失败');
            const results = await response.json();
            this.showResults(dir, partial, results);
        } catch (error) {
            console.error('Autocomplete error:', error);
            this.hide();
        }
    }

    parsePathComponents(fullPath) {
        const cleanPath = fullPath.replace(/\/+/g, '/');
        if (cleanPath.endsWith('/')) {
            return [cleanPath.slice(0, -1), ''];
        }
        const lastSlashIndex = cleanPath.lastIndexOf('/');
        return [
            cleanPath.slice(0, lastSlashIndex + 1),
            cleanPath.slice(lastSlashIndex + 1)
        ];
    }

    showResults(baseDir, partial, container) {
        this.container.innerHTML = '';
        let items = container.results
        if (!items?.length) return;

        items.forEach(item => {
            const div = document.createElement('div');
            div.className = `autocomplete-item ${item.is_dir ? 'dir' : 'file'}`;
            div.textContent = item.name + (item.is_dir ? '/' : '');
            div.title = item.full_path;
            
            div.addEventListener('click', () => this.selectItem(div));
            this.container.appendChild(div);
        });

        this.container.style.display = 'block';
    }

    selectItem(element) {
        const currentValue = this.input.value;
        const [baseDir, _] = this.parsePathComponents(currentValue);
        const newValue = baseDir + element.textContent;

        this.input.value = newValue.replace(/\/+/g, '/');
        this.input.focus();
        
        if (element.classList.contains('dir')) {
            this.input.value += '/';
            this.autoTriggered = true;
            const event = new Event('input', { bubbles: true });
            this.input.dispatchEvent(event);
            this.autoTriggered = false;
        }
        this.hide();

    }

    hide() {
        this.container.style.display = 'none';
        this.container.innerHTML = '';
    }
}
