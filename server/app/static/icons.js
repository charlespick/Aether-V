(function () {
    const ICON_BASE_PATH = '/static/icons';
    const DEFAULT_STYLE = 'round';

    function buildIconUrl(style, name) {
        if (!style || !name) {
            throw new Error('Both style and name are required to build an icon URL.');
        }
        return `${ICON_BASE_PATH}/${style}/${name}.svg`;
    }

    function buildStyleAttribute(url, size) {
        const declarations = [`--icon: url('${url}')`];
        if (typeof size === 'number' && Number.isFinite(size)) {
            declarations.push(`width: ${size}px`, `height: ${size}px`);
        }
        return declarations.length ? ` style="${declarations.join('; ')};"` : '';
    }

    function escapeAttribute(value) {
        return String(value).replace(/"/g, '&quot;');
    }

    function renderIcon(style, name, options = {}) {
        const { size, className = '', label, hidden = !label } = options;
        const classes = ['icon'];
        if (className) {
            classes.push(className);
        }

        const url = buildIconUrl(style, name);
        const styleAttr = buildStyleAttribute(url, size);

        const attributes = [];
        if (label) {
            attributes.push(`role="img"`, `aria-label="${escapeAttribute(label)}"`);
        }
        if (hidden && !label) {
            attributes.push('aria-hidden="true"');
        }

        const attrString = attributes.length ? ' ' + attributes.join(' ') : '';

        return `<span class="${classes.join(' ')}"${styleAttr}${attrString}></span>`;
    }

    function applyIcon(element, style, name, options = {}) {
        if (!element) {
            return;
        }
        element.innerHTML = renderIcon(style, name, options);
    }

    window.iconUtils = {
        DEFAULT_STYLE,
        buildIconUrl,
        renderIcon,
        applyIcon,
        renderDefaultIcon(name, options = {}) {
            return renderIcon(DEFAULT_STYLE, name, options);
        },
        applyDefaultIcon(element, name, options = {}) {
            applyIcon(element, DEFAULT_STYLE, name, options);
        },
    };
})();
