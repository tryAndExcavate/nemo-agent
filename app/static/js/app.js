const { createApp, ref, computed, nextTick, onMounted, watch } = Vue;

createApp({
    setup() {
        const backendUrl = ref(APP_CONFIG.backendUrl);
        const connectionError = ref(null);
        const agents = ref(APP_CONSTANTS.AGENTS);
        const { STREAM_TYPES, SUPPORTED_FILE_TYPES } = APP_CONSTANTS;

        const selectedAgent = ref('chat');
        const chatList = ref([]);
        const currentChatId = ref(null);
        const inputMessage = ref('');
        const selectedFile = ref(null);
        const uploadedFileId = ref(null);
        const isUploading = ref(false);
        const isSending = ref(false);
        const currentRecommendMsgId = ref(null);

        const showConfirmDialog = ref(false);
        const confirmTitle = ref('确认操作');
        const confirmMessage = ref('');
        let confirmCallback = null;
        let _pendingDeleteId = null;

        const messagesContainer = ref(null);
        const textareaInput = ref(null);
        let currentStreamContentDiv = null;
        let abortController = null;

        // ===== 初始化：只加载一次会话列表 =====
        onMounted(async () => {
            APP_UTILS.setupMarkdown();
            await loadChatsFromStorage();
            // 有历史会话则选第一个，没有则新建
            if (chatList.value.length > 0) {
                await selectChat(chatList.value[0].id);
            } else {
                createNewChat();
            }
        });

        const { generateId, formatFileSize, renderMarkdown, processReferences, processRecommendations } = APP_UTILS;

        // ===== 会话列表 =====
        const loadChatsFromStorage = async () => {
            chatList.value = await APP_API.loadChats(backendUrl.value);
        };

        // ===== 选中会话 =====
        const selectChat = async (chatId) => {
            currentChatId.value = chatId;
            const chat = chatList.value.find(c => c.id === chatId);
            if (!chat) return;
            if (chat.isNew) return;

            // 恢复 agent 类型
            if (chat.agentType) {
                const map = { chat:'chat', websearch:'chat', file:'file', ppt:'ppt', deep:'deep', skills:'skills' };
                selectedAgent.value = map[chat.agentType] || chat.agentType || 'chat';
            }

            // 每次都从后端拉取消息（保证数据最新）
            const detail = await APP_API.getChatDetail(backendUrl.value, chatId);
            if (!detail) return;

            chat.messages = buildMessages(detail);
            scrollToBottom();
        };

        function buildMessages(detail) {
            const msgs = [];
            if (!detail.messages || !Array.isArray(detail.messages)) return msgs;
            const refsData = processReferences(detail.reference || null);
            detail.messages.forEach(msg => {
                if (msg.question) {
                    msgs.push({
                        id: 'u_' + msg.id, role: 'user', content: msg.question,
                        file: !!msg.fileid, fileName: msg.fileid ? '已上传文件' : null,
                        timestamp: Date.now()
                    });
                }
                if (msg.answer || msg.thinking) {
                    const t = msg.thinking || '';
                    msgs.push({
                        id: 'a_' + msg.id, role: 'assistant',
                        content: msg.answer || '', thinking: t ? [t] : [],
                        timeline: t ? [{ type: 'thinking', content: t }] : [],
                        reference: processReferences(msg.reference),
                        recommend: processRecommendations(msg.recommend),
                        showTimeline: false, showReference: false,
                        hasThinking: !!t,
                        timestamp: Date.now()
                    });
                }
            });
            return msgs;
        }

        // ===== 新建会话 =====
        const createNewChat = () => {
            const exists = chatList.value.find(c => c.isNew);
            if (exists) { currentChatId.value = exists.id; return; }
            const nc = { id: generateId(), title: '新对话', messages: [], isNew: true };
            chatList.value.unshift(nc);
            currentChatId.value = nc.id;
        };

        // ===== 删除会话 =====
        const deleteChat = (chatId) => {
            _pendingDeleteId = chatId;
            confirmTitle.value = '确认删除';
            confirmMessage.value = '删除该会话后将无法恢复，是否继续？';
            showConfirmDialog.value = true;
        };

        const confirmOk = async () => {
            showConfirmDialog.value = false;
            const chatId = _pendingDeleteId;
            if (!chatId) return;
            _pendingDeleteId = null;
            const result = await APP_API.deleteChat(backendUrl.value, chatId);
            if (result.success) {
                const idx = chatList.value.findIndex(c => c.id === chatId);
                if (idx !== -1) {
                    chatList.value.splice(idx, 1);
                    if (currentChatId.value === chatId) {
                        chatList.value.length > 0 ? await selectChat(chatList.value[0].id) : createNewChat();
                    }
                }
            } else {
                alert('删除失败: ' + (result.message || result.error || '未知错误'));
            }
        };
        const confirmCancel = () => { showConfirmDialog.value = false; _pendingDeleteId = null; };

        // ===== 文件上传 =====
        const handleFileSelect = async (event) => {
            const files = event.target.files;
            if (files.length > 0) {
                if (selectedFile.value) { alert('已上传文件，请先删除当前文件'); return; }
                await uploadOneFile(files[0]);
            }
            event.target.value = '';
        };
        const uploadOneFile = async (file) => {
            const validExts = SUPPORTED_FILE_TYPES.extensions;
            const ext = file.name.split('.').pop().toLowerCase();
            if (!SUPPORTED_FILE_TYPES.mime.includes(file.type) && !validExts.includes(ext)) {
                alert('不支持的文件类型，仅支持 PDF/Word/TXT/PNG/JPG'); return;
            }
            selectedFile.value = file; isUploading.value = true;
            try {
                const res = await APP_API.uploadFile(backendUrl.value, file);
                uploadedFileId.value = res.fileId;
            } catch (e) { alert('上传失败: ' + e.message); removeFile(); }
            finally { isUploading.value = false; }
        };
        const removeFile = () => { selectedFile.value = null; uploadedFileId.value = null; };

        // ===== 发送消息 =====
        const sendMessage = async () => {
            if (isSending.value || isUploading.value) return;
            const msg = inputMessage.value.trim();
            if (!msg && !selectedFile.value) return;
            if (!currentChat.value) return;

            clearAllRecommendQuestions();
            const hasFile = !!selectedFile.value;
            const fileIdToSend = uploadedFileId.value;
            isSending.value = true;
            inputMessage.value = '';
            if (textareaInput.value) textareaInput.value.style.height = 'auto';

            const chat = currentChat.value;
            if (chat.isNew) chat.isNew = false;

            // 添加用户消息
            chat.messages.push({
                id: generateId(), role: 'user', content: msg,
                file: hasFile, fileName: selectedFile.value ? selectedFile.value.name : null,
                timestamp: Date.now()
            });
            // 更新标题（首条消息）
            if (chat.messages.filter(m => m.role === 'user').length === 1 && msg) {
                chat.title = msg.substring(0, 20) + (msg.length > 20 ? '...' : '');
            }

            // AI 占位
            let aiMsg = {
                id: generateId(), role: 'assistant',
                content: '', thinking: [], timeline: [],
                reference: [], recommend: [],
                showTimeline: true, showReference: false, hasThinking: false,
                timestamp: Date.now()
            };
            chat.messages.push(aiMsg);
            aiMsg = chat.messages[chat.messages.length - 1];

            await nextTick();
            const el = messagesContainer.value?.querySelectorAll('.message.assistant');
            const last = el?.[el.length - 1];
            if (last) { const t = last.querySelector('.text-content'); if (t) currentStreamContentDiv = t; }
            scrollToBottom();

            const apiUrl = APP_API.getStreamChatUrl(backendUrl.value, selectedAgent.value, hasFile && fileIdToSend);
            const url = new URL(apiUrl, window.location.origin);
            url.searchParams.append('query', msg || '请分析这个文件');
            url.searchParams.append('conversationId', currentChatId.value);
            if (hasFile && fileIdToSend) url.searchParams.append('fileId', fileIdToSend);

            try {
                abortController = new AbortController();
                const res = await fetch(url.toString(), {
                    method: 'GET', headers: { 'Accept': 'text/event-stream', 'Cache-Control': 'no-cache' },
                    signal: abortController.signal
                });
                if (!res.ok) throw new Error('HTTP ' + res.status);

                const reader = res.body.getReader();
                const decoder = new TextDecoder('utf-8');
                let buf = '';
                while (true) {
                    const { done, value } = await reader.read();
                    if (done) break;
                    buf += decoder.decode(value, { stream: true });
                    let i;
                    while ((i = buf.indexOf('\n')) !== -1) {
                        const line = buf.substring(0, i); buf = buf.substring(i + 1);
                        if (!line.startsWith('data: ')) continue;
                        const d = line.slice(6).trim();
                        if (!d || d === STREAM_TYPES.DONE) continue;
                        try { processStreamData(JSON.parse(d), aiMsg); } catch (e) {}
                    }
                }
            } catch (err) {
                if (err.name !== 'AbortError') {
                    aiMsg.content += '\n\n⚠️ ' + err.message;
                    updateStreamContent(aiMsg.content);
                }
            } finally {
                isSending.value = false;
                abortController = null;
                currentStreamContentDiv = null;
            }
        };

        const processStreamData = (data, aiMsg) => {
            switch (data.type) {
                case STREAM_TYPES.TEXT:
                    aiMsg.content += data.content || '';
                    updateStreamContent(aiMsg.content);
                    break;
                case STREAM_TYPES.THINKING:
                    aiMsg.hasThinking = true;
                    aiMsg.thinking.push(data.content || '');
                    const last = aiMsg.timeline[aiMsg.timeline.length - 1];
                    if (last && last.type === 'thinking') last.content += data.content;
                    else aiMsg.timeline.push({ type: 'thinking', content: data.content });
                    scrollToBottom();
                    break;
                case STREAM_TYPES.TOOL_START:
                    aiMsg.timeline.push({ type: 'tool', toolName: data.toolName || '?', toolCallId: data.toolCallId || '', status: 'running' });
                    break;
                case STREAM_TYPES.TOOL_END:
                    const e = aiMsg.timeline.find(t => t.type === 'tool' && t.toolCallId === (data.toolCallId || '') && t.status === 'running');
                    if (e) e.status = 'completed';
                    else aiMsg.timeline.push({ type: 'tool', toolName: data.toolName || '?', toolCallId: data.toolCallId || '', status: 'completed' });
                    break;
                case STREAM_TYPES.REFERENCE:
                    aiMsg.reference = processReferences(data.content);
                    if (aiMsg.reference.length) aiMsg.showReference = true;
                    break;
                case STREAM_TYPES.RECOMMEND:
                    aiMsg.recommend = processRecommendations(data.content);
                    break;
                case STREAM_TYPES.ERROR:
                    aiMsg.timeline.push({ type: 'error', message: data.message || data.content || '未知错误', detail: data.detail || '' });
                    break;
                case STREAM_TYPES.COMPLETE:
                    aiMsg.showTimeline = aiMsg.timeline.some(t => t.type === 'error');
                    currentRecommendMsgId.value = aiMsg.id;
                    currentStreamContentDiv = null;
                    break;
            }
        };

        const updateStreamContent = (content) => {
            if (currentStreamContentDiv) {
                currentStreamContentDiv.innerHTML = renderMarkdown(content);
                if (typeof hljs !== 'undefined') {
                    currentStreamContentDiv.querySelectorAll('pre code').forEach(b => hljs.highlightElement(b));
                }
            }
            scrollToBottom();
        };

        const stopMessage = async () => {
            if (!isSending.value) return;
            await APP_API.stopStream(backendUrl.value, currentChatId.value);
            isSending.value = false;
            currentStreamContentDiv = null;
        };

        const selectAgent = (agentId) => {
            if (selectedFile.value) removeFile();
            selectedAgent.value = agentId;
        };

        const quickPrompt = (text) => {
            inputMessage.value = text;
            nextTick(() => textareaInput.value?.focus());
        };

        const clearAllRecommendQuestions = () => {
            const chat = currentChat.value;
            if (chat) chat.messages.forEach(m => m.recommend = []);
        };

        const sendRecommendQuestion = (q) => { clearAllRecommendQuestions(); inputMessage.value = q; sendMessage(); };

        const toggleTimeline = (msgId) => {
            const m = currentChat.value?.messages.find(x => x.id === msgId);
            if (m) m.showTimeline = !m.showTimeline;
        };
        const toggleReference = (msgId) => {
            const m = currentChat.value?.messages.find(x => x.id === msgId);
            if (m) m.showReference = !m.showReference;
        };

        const currentChat = computed(() => chatList.value.find(c => c.id === currentChatId.value));
        const isLastMessage = (msg) => {
            const chat = currentChat.value;
            return chat && chat.messages.length > 0 && chat.messages[chat.messages.length - 1].id === msg.id;
        };

        const copyMessage = async (msg) => {
            const text = msg.role === 'user' ? msg.content : (msg.content || '');
            if (!text) return;
            try { await navigator.clipboard.writeText(text); msg.copied = true; setTimeout(() => msg.copied = false, 2000); }
            catch (e) { console.error(e); }
        };

        const canSend = computed(() => !isSending.value && !isUploading.value && (inputMessage.value.trim() || selectedFile.value));

        const scrollToBottom = () => nextTick(() => { if (messagesContainer.value) messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight; });

        watch(inputMessage, () => nextTick(() => {
            if (textareaInput.value) { textareaInput.value.style.height = 'auto'; textareaInput.value.style.height = textareaInput.value.scrollHeight + 'px'; }
        }));

        return {
            backendUrl, connectionError, agents, selectedAgent,
            chatList, currentChatId, currentChat, inputMessage,
            selectedFile, isUploading, isSending, currentRecommendMsgId, canSend,
            messagesContainer, textareaInput,
            selectAgent, quickPrompt, sendRecommendQuestion, isLastMessage,
            createNewChat, selectChat, deleteChat, removeFile, handleFileSelect,
            sendMessage, stopMessage, toggleTimeline, toggleReference, copyMessage,
            renderMarkdown, formatFileSize,
            showConfirmDialog, confirmTitle, confirmMessage, confirmOk, confirmCancel
        };
    }
}).mount('#app');
