/**
 * 工具函数文件
 */

const generateId = () => {
    return 'chat_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9);
};

const formatFileSize = (bytes) => {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
};

const setupMarkdown = () => {
    if (typeof marked !== 'undefined' && typeof hljs !== 'undefined') {
        marked.setOptions({
            highlight: function(code, lang) {
                if (lang && hljs.getLanguage(lang)) {
                    try { return hljs.highlight(code, { language: lang }).value; } catch (err) {}
                }
                return hljs.highlightAuto(code).value;
            },
            breaks: true,
            gfm: true,
            sanitize: false
        });
    }
};

const renderMarkdown = (content) => {
    if (!content) return '';
    if (typeof marked === 'undefined') return content;

    let processedContent = content
        .replace(/\\n/g, '\n')
        .replace(/\\r\\n/g, '\n')
        .replace(/\\r/g, '\n');

    const html = marked.parse(processedContent);

    if (typeof DOMPurify !== 'undefined') {
        return DOMPurify.sanitize(html);
    }
    return html;
};

const processReferences = (refsData) => {
    if (!refsData) return [];
    let references = refsData;

    if (typeof references === 'string') {
        try { references = JSON.parse(references); } catch (e) { return []; }
    }

    // 嵌套格式 {data: {content: "..."}}
    if (references && references.data && references.data.content) {
        const contentData = references.data.content;
        if (typeof contentData === 'string') {
            try { references = JSON.parse(contentData); } catch (e) { return []; }
        } else {
            references = contentData;
        }
    }

    // 后端返回 {type: 'reference', content: "[...]"}
    if (references && references.type === 'reference' && typeof references.content === 'string') {
        try { references = JSON.parse(references.content); } catch (e) { return []; }
    }

    if (!Array.isArray(references)) return [];

    return references
        .filter(ref => ref != null)
        .map(ref => {
            let linkUrl, displayTitle;

            if (typeof ref === 'string') {
                try {
                    const parsed = JSON.parse(ref);
                    linkUrl = parsed.url || parsed.link;
                    displayTitle = parsed.title || parsed.url || parsed.link || '无标题';
                } catch {
                    linkUrl = ref;
                    displayTitle = ref;
                }
            } else if (typeof ref === 'object' && ref !== null) {
                linkUrl = ref.url || ref.link;
                displayTitle = ref.title || ref.url || ref.link || '无标题';
            }

            if (linkUrl && !linkUrl.startsWith('http://') && !linkUrl.startsWith('https://')) {
                linkUrl = 'https://' + linkUrl;
            }

            return { url: linkUrl, title: displayTitle };
        })
        .filter(ref => ref.url);
};

const processRecommendations = (recommendData) => {
    if (!recommendData) return [];
    let recommendations = recommendData;

    if (typeof recommendations === 'string') {
        try { recommendations = JSON.parse(recommendations); } catch (e) { return []; }
    }

    if (!Array.isArray(recommendations)) return [];
    return recommendations;
};

window.APP_UTILS = {
    generateId,
    formatFileSize,
    setupMarkdown,
    renderMarkdown,
    processReferences,
    processRecommendations
};
