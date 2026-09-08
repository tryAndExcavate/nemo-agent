/**
 * 工具函数文件（ESM 版，原 window.APP_UTILS）
 * marked/hljs/DOMPurify 改为 npm 导入；函数体保持逐字不变
 */
import { marked } from 'marked'
import hljs from 'highlight.js'
import DOMPurify from 'dompurify'

export const generateId = () => {
    return 'chat_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9);
};

export const formatFileSize = (bytes) => {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
};

export const setupMarkdown = () => {
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
};

export const renderMarkdown = (content) => {
    if (!content) return '';
    let processedContent = content
        .replace(/\\n/g, '\n')
        .replace(/\\r\\n/g, '\n')
        .replace(/\\r/g, '\n');

    let html = marked.parse(processedContent);
    html = DOMPurify.sanitize(html);

    // 给 <pre> 代码块包裹容器 + 复制按钮
    html = html.replace(/<pre>([\s\S]*?)<\/pre>/g, (match, inner) => {
        return `<div class="code-block-wrap"><pre>${inner}</pre><button class="copy-code-btn" onclick="window.__copyCode(this)">复制</button></div>`;
    });

    return html;
};

export const processReferences = (refsData) => {
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

export const processRecommendations = (recommendData) => {
    if (!recommendData) return [];
    let recommendations = recommendData;

    if (typeof recommendations === 'string') {
        try { recommendations = JSON.parse(recommendations); } catch (e) { return []; }
    }

    if (!Array.isArray(recommendations)) return [];
    return recommendations;
};

export const APP_UTILS = {
    generateId,
    formatFileSize,
    setupMarkdown,
    renderMarkdown,
    processReferences,
    processRecommendations
};

// 代码块复制按钮点击处理（renderMarkdown 生成的 HTML 内联 onclick 依赖全局）
export function __copyCode(btn) {
    const pre = btn.parentElement.querySelector('pre');
    if (!pre) return;
    const code = pre.textContent;
    navigator.clipboard.writeText(code).then(() => {
        btn.textContent = '已复制';
        btn.classList.add('copied');
        setTimeout(() => { btn.textContent = '复制'; btn.classList.remove('copied'); }, 1500);
    });
}
