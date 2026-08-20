/**
 * API 调用封装 — Python FastAPI 后端适配版
 * 字段名适配 snake_case → camelCase
 */

const testConnection = async (backendUrl) => {
    try {
        const response = await fetch(`${backendUrl}/file/list`, {
            method: 'GET', headers: { 'Accept': 'application/json' }
        });
        return { success: true };
    } catch (error) {
        return { success: false, error: '无法连接到后端服务，请确保后端在 ' + (backendUrl || '当前地址') + ' 运行' };
    }
};

const loadChats = async (backendUrl) => {
    try {
        const response = await fetch(`${backendUrl}/conversations/active?user_id=1`, {
            method: 'GET', headers: { 'Accept': 'application/json' }
        });
        if (!response.ok) throw new Error('获取会话列表失败');
        const result = await response.json();
        if (result.items) {
            return result.items.map(item => ({
                id: item.session_id,
                title: item.title || '新对话',
                agentType: item.agent_type,
                fileid: null,
                messages: []
            }));
        }
        return [];
    } catch (error) {
        console.error('加载会话列表失败:', error);
        return [];
    }
};

const loadArchivedChats = async (backendUrl) => {
    try {
        const response = await fetch(`${backendUrl}/conversations/archived?user_id=1`, {
            method: 'GET', headers: { 'Accept': 'application/json' }
        });
        if (!response.ok) throw new Error('获取归档会话列表失败');
        const result = await response.json();
        if (result.items) {
            return result.items.map(item => ({
                id: item.session_id,
                title: item.title || '新对话',
                agentType: item.agent_type,
                fileid: null,
                messages: []
            }));
        }
        return [];
    } catch (error) {
        console.error('加载归档会话列表失败:', error);
        return [];
    }
};

const activateChat = async (backendUrl, sessionId) => {
    try {
        const response = await fetch(`${backendUrl}/conversations/${sessionId}/activate?user_id=1`, {
            method: 'POST'
        });
        return response.ok;
    } catch (error) {
        console.error('激活会话失败:', error);
        return false;
    }
};

const getChatDetail = async (backendUrl, chatId) => {
    try {
        const response = await fetch(`${backendUrl}/session/${chatId}`, {
            method: 'GET', headers: { 'Accept': 'application/json' }
        });
        if (!response.ok) throw new Error('获取会话详情失败');
        const result = await response.json();
        if (result.code === 200 && result.data) {
            return result.data;
        }
        return null;
    } catch (error) {
        console.error('获取会话详情失败:', error);
        return null;
    }
};

const deleteChat = async (backendUrl, chatId) => {
    try {
        const response = await fetch(`${backendUrl}/session/${chatId}`, {
            method: 'DELETE', headers: { 'Accept': 'application/json' }
        });
        if (!response.ok) throw new Error('删除会话失败');
        const result = await response.json();
        return { success: result.code === 200, message: result.message };
    } catch (error) {
        console.error('删除会话失败:', error);
        return { success: false, error: error.message };
    }
};

const uploadFile = async (backendUrl, file) => {
    const formData = new FormData();
    formData.append('file', file);

    const response = await fetch(`${backendUrl}/file/upload`, {
        method: 'POST', body: formData
    });

    if (!response.ok) throw new Error('文件上传失败');

    const result = await response.json();
    if (result.code === 200 && result.data) {
        return {
            success: true,
            fileId: result.data.file_id   // Python 后端用 snake_case
        };
    }
    throw new Error(result.message || '文件上传失败');
};

const getStreamChatUrl = (backendUrl, selectedAgent, hasFile) => {
    if (hasFile) return `${backendUrl}/agent/file/stream`;
    if (selectedAgent === 'ppt') return `${backendUrl}/agent/pptx/stream`;
    if (selectedAgent === 'deep') return `${backendUrl}/agent/deep/stream`;
    if (selectedAgent === 'skills') return `${backendUrl}/agent/skills/stream`;
    return `${backendUrl}/agent/chat/stream`;
};

const stopStream = async (backendUrl, conversationId) => {
    try {
        const response = await fetch(`${backendUrl}/agent/stop?conversationId=${conversationId}`, { method: 'GET' });
        return await response.json();
    } catch (error) {
        console.warn('调用停止接口失败:', error);
        return null;
    }
};

window.APP_API = {
    testConnection, loadChats, loadArchivedChats, activateChat, getChatDetail,
    deleteChat, uploadFile, getStreamChatUrl, stopStream
};
