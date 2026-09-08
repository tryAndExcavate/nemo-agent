/**
 * 常量定义文件（ESM 版，原 window.APP_CONSTANTS）
 */

export const AGENTS = [
    { id: 'chat', name: '对话助手', icon: '💬' },
    { id: 'file', name: '文件问答', icon: '📁' },
    { id: 'ppt', name: 'PPT生成', icon: '📊' },
    { id: 'deep', name: '深度研究', icon: '🔬' },
    { id: 'skills', name: '技能助手', icon: '🛠' }
];

export const SUPPORTED_FILE_TYPES = {
    mime: [
        'application/pdf',
        'application/msword',
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'text/plain',
        'image/png',
        'image/jpeg',
        'image/jpg'
    ],
    extensions: ['pdf', 'doc', 'docx', 'txt', 'png', 'jpg', 'jpeg']
};

export const STREAM_TYPES = {
    TEXT: 'text',
    THINKING: 'thinking',
    TOOL_START: 'tool_start',
    TOOL_END: 'tool_end',
    REFERENCE: 'reference',
    RECOMMEND: 'recommend',
    ERROR: 'error',
    USAGE: 'usage',           // 新增：Token 消耗统计事件
    COMPLETE: 'complete',
    DONE: '[DONE]'
};

export const APP_CONSTANTS = {
    AGENTS,
    SUPPORTED_FILE_TYPES,
    STREAM_TYPES
};
