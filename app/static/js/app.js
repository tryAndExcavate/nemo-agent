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

        // ===== 多会话管理状态 =====
        const currentStatus = ref('active');
        const editingChatId = ref(null);
        const showDeleteModal = ref(false);
        const deleteConfirmText = ref('');
        let pendingDeleteChatId = null;
        const menuOpenId = ref(null);  // 下拉菜单打开的会话ID

        // ===== 分支管理状态 =====
        const editingMessageId = ref(null);  // 正在编辑的消息ID
        const editText = ref('');             // 编辑文本
        const createBranch = ref(true);       // 是否创建分支（默认是）
        const branchCache = new Map();        // 缓存兄弟分支信息

        const messagesContainer = ref(null);
        const textareaInput = ref(null);
        let currentStreamContentDiv = null;
        let abortController = null;
        let lastStreamEventId = sessionStorage.getItem('lastStreamEventId') || '0';  // Redis Stream 位置，跨刷新保留

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

            // ===== 侧边栏拖拽调整宽度 =====
            const handle = document.getElementById('sidebarResizeHandle');
            const sidebar = document.querySelector('.sidebar');
            if (handle && sidebar) {
                let dragging = false;
                handle.addEventListener('mousedown', (e) => {
                    e.preventDefault();
                    dragging = true;
                    handle.classList.add('active');
                    document.body.style.cursor = 'col-resize';
                    document.body.style.userSelect = 'none';
                });
                document.addEventListener('mousemove', (e) => {
                    if (!dragging) return;
                    let newWidth = e.clientX;
                    if (newWidth < 180) newWidth = 180;
                    if (newWidth > 500) newWidth = 500;
                    sidebar.style.width = newWidth + 'px';
                });
                document.addEventListener('mouseup', () => {
                    if (dragging) {
                        dragging = false;
                        handle.classList.remove('active');
                        document.body.style.cursor = '';
                        document.body.style.userSelect = '';
                    }
                });
            }
        });

        const { generateId, formatFileSize, renderMarkdown, processReferences, processRecommendations } = APP_UTILS;

        // ===== 会话列表 =====
        const loadChatsFromStorage = async () => {
            chatList.value = await APP_API.loadChats(backendUrl.value);
        };

        const loadArchivedChatsFromStorage = async () => {
            chatList.value = await APP_API.loadArchivedChats(backendUrl.value);
        };

        // ===== 选中会话 =====
        const selectChat = async (chatId) => {
            currentChatId.value = chatId;
            const chat = chatList.value.find(c => c.id === chatId);
            if (!chat) return;
            if (chat.isNew) return;

            // 异步激活会话（不阻塞）
            APP_API.activateChat(backendUrl.value, chatId).catch(err =>
                console.error('激活会话失败:', err)
            );

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

            // 检查是否有活跃的 SSE 流，如有则重连（刷新页面后恢复流式回复）
            checkAndReconnectStream(chatId, chat);
        };

        let isReconnecting = false;  // 防止 reconnect → selectChat → reconnect 无限循环

        const checkAndReconnectStream = async (chatId, chat) => {
            if (isReconnecting) return;  // 正在重连中，跳过

            // 检查 Redis Stream 中是否有该会话的活跃流
            let active = false;
            try {
                const resp = await fetch(`${backendUrl.value}/agent/active/${chatId}`);
                const data = await resp.json();
                active = data.active;
            } catch {}

            if (!active) {
                // 没有活跃流，清除旧的位置记录
                lastStreamEventId = '0';
                sessionStorage.removeItem('lastStreamEventId');
                return;
            }

            // 有活跃流，使用上次保存的位置重连
            const resumeFromId = lastStreamEventId || '0';
            isReconnecting = true;

            // 创建 AI 占位消息
            const aiMsg = {
                id: generateId(), role: 'assistant', question: '',
                content: '', thinking: [], timeline: [],
                reference: [], recommend: [],
                showTimeline: true, showReference: false, hasThinking: false,
                usage: null, timestamp: Date.now()
            };
            chat.messages.push(aiMsg);
            const reactiveAiMsg = chat.messages[chat.messages.length - 1];

            isSending.value = true;
            await nextTick();
            const el = messagesContainer.value?.querySelectorAll('.message.assistant');
            const lastEl = el?.[el.length - 1];
            if (lastEl) { const t = lastEl.querySelector('.text-content'); if (t) currentStreamContentDiv = t; }
            scrollToBottom();

            try {
                abortController = new AbortController();
                const res = await fetch(`${backendUrl.value}/agent/reconnect/${chatId}?lastEventId=${resumeFromId}`, {
                    signal: abortController.signal,
                });
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
                        try { processStreamData(JSON.parse(d), reactiveAiMsg); } catch (e) {}
                    }
                }
            } catch (err) {
                if (err.name !== 'AbortError') {
                    console.error('重连流失败:', err);
                }
            } finally {
                isSending.value = false;
                abortController = null;
                currentStreamContentDiv = null;
                lastStreamEventId = '0';
                sessionStorage.removeItem('lastStreamEventId');
                isReconnecting = false;
                // 不重建消息列表，直接从数据库更新内容（保留流式渲染效果）
                try {
                    const detail = await APP_API.getChatDetail(backendUrl.value, chatId);
                    if (detail && detail.messages) {
                        const dbMsgs = buildMessages(detail);
                        // 用数据库的 assistant 消息更新已渲染的流式消息
                        for (const dbMsg of dbMsgs) {
                            if (dbMsg.role === 'assistant') {
                                const existing = chat.messages.find(m => m.role === 'assistant' && m.question === dbMsg.question);
                                if (existing) {
                                    Object.assign(existing, dbMsg);  // 更新内容，保留 DOM 渲染
                                }
                            }
                        }
                    }
                } catch {}
            }
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
                        question: msg.question,  // 保留原始问题，供重新生成时使用
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

        // ===== 异步生成标题 =====
        const generateAndUpdateTitle = async (sessionId, message) => {
            try {
                // 调用后端生成标题并更新
                const response = await fetch(`${backendUrl.value}/conversations/${sessionId}/generate-title?user_id=1`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ message: message })
                });
                if (response.ok) {
                    const result = await response.json();
                    if (result.title) {
                        // 更新本地会话标题
                        const chat = chatList.value.find(c => c.id === sessionId);
                        if (chat) {
                            chat.title = result.title;
                        }
                    }
                }
            } catch (e) {
                console.warn('生成标题失败，使用默认标题:', e);
            }
        };

        // ===== 发送消息 =====
        const sendMessage = async () => {
            if (isSending.value || isUploading.value) return;
            const msg = inputMessage.value.trim();
            if (!msg && !selectedFile.value) return;
            if (!currentChat.value) return;

            lastStreamEventId = '0';  // 重置 Redis Stream 位置
            clearAllRecommendQuestions();
            const hasFile = !!selectedFile.value;
            const fileIdToSend = uploadedFileId.value;
            isSending.value = true;
            inputMessage.value = '';
            if (textareaInput.value) textareaInput.value.style.height = 'auto';

            const chat = currentChat.value;
            if (chat.isNew) {
                chat.isNew = false;
                // 持久化到后端（不传递 initial_message，标题后续异步更新）
                try {
                    const response = await fetch(`${backendUrl.value}/conversations?user_id=1`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            session_id: chat.id,
                            title: chat.title || '新对话'
                        })
                    });
                    if (!response.ok) console.error('Failed to persist conversation');

                    // 异步生成标题（不阻塞主流程）
                    if (msg && msg.trim().length > 0) {
                        generateAndUpdateTitle(chat.id, msg).catch(err =>
                            console.error('生成标题失败:', err)
                        );
                    }
                } catch (e) { console.error('Persist conversation error:', e); }
            }

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
                question: msg,  // 保留原始问题，供重新生成时使用
                content: '', thinking: [], timeline: [],
                reference: [], recommend: [],
                showTimeline: true, showReference: false, hasThinking: false,
                usage: null,  // 新增：预先声明 usage 属性
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
            // 记录 Redis Stream 事件 ID，用于断线重连
            if (data._stream_event_id) {
                lastStreamEventId = data._stream_event_id;
                sessionStorage.setItem('lastStreamEventId', lastStreamEventId);
            }
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
                case STREAM_TYPES.USAGE:
                    aiMsg.usage = data.data || data.content || null;
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

        // ===== 多会话管理方法 =====
        const filteredChatList = computed(() => chatList.value);

        const switchTab = async (status) => {
            console.log('switchTab 被调用，status:', status);
            currentStatus.value = status;
            if (status === 'active') {
                console.log('加载活跃会话...');
                await loadChatsFromStorage();
            } else {
                console.log('加载归档会话...');
                await loadArchivedChatsFromStorage();
            }
            console.log('加载完成，chatList:', chatList.value.length);
        };

        const startRename = (chatId, event) => {
            event.stopPropagation();
            editingChatId.value = chatId;
            menuOpenId.value = null;  // 关闭下拉菜单
            nextTick(() => {
                const input = document.querySelector('.rename-input');
                if (input) { input.focus(); input.select(); }
            });
        };

        const startRenameFromMenu = (chatId) => {
            editingChatId.value = chatId;
            menuOpenId.value = null;  // 关闭下拉菜单
            nextTick(() => {
                const input = document.querySelector('.rename-input');
                if (input) { input.focus(); input.select(); }
            });
        };

        const toggleMenu = (chatId) => {
            if (menuOpenId.value === chatId) {
                menuOpenId.value = null;
            } else {
                menuOpenId.value = chatId;
            }
        };

        const commitRename = async (chatId, event) => {
            const newTitle = event.target.value.trim();
            editingChatId.value = null;
            if (!newTitle) return;

            const chat = chatList.value.find(c => c.id === chatId);
            if (chat && chat.title !== newTitle) {
                try {
                    await fetch(`${backendUrl.value}/conversations/${chatId}/rename?user_id=1`, {
                        method: 'PATCH',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ title: newTitle })
                    });
                    chat.title = newTitle;
                } catch (e) { console.error('Rename failed:', e); }
            }
        };

        const cancelRename = () => { editingChatId.value = null; };

        // ===== 分支管理方法 =====
        const startEditMessage = (messageId, originalText) => {
            editingMessageId.value = messageId;
            editText.value = originalText;
            createBranch.value = true;  // 默认分支
        };

        const cancelEditMessage = () => {
            editingMessageId.value = null;
            editText.value = '';
        };

        const submitEdit = async () => {
            const msgIdStr = editingMessageId.value;
            const newQuestion = editText.value.trim();
            const shouldCreateBranch = createBranch.value;

            if (!newQuestion) {
                alert('请输入新的问题');
                return;
            }

            let finalMsgIdStr = msgIdStr;

            // 如果是客户端临时 ID（chat_xxx），先从后端刷新消息列表拿到数据库 ID
            if (msgIdStr.startsWith('chat_')) {
                const chat = currentChat.value;
                if (chat) {
                    chat.messages = [];
                    await selectChat(currentChatId.value);
                    const fresh = chat.messages.find(m => m.role === 'user' && m.content === editText.value);
                    if (fresh) {
                        finalMsgIdStr = fresh.id;
                    } else {
                        alert('无法定位该消息，请重试');
                        return;
                    }
                }
            }

            const msgId = finalMsgIdStr.replace(/^[ua]_/, '');
            if (!msgId) {
                alert('无效的消息ID');
                return;
            }

            try {
                const response = await fetch(`${backendUrl.value}/branches/${currentChatId.value}/edit`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        message_id: msgId,
                        new_question: newQuestion,
                        create_branch: shouldCreateBranch
                    })
                });

                const result = await response.json();
                if (result.code === 200) {
                    editingMessageId.value = null;
                    editText.value = '';

                    const chat = currentChat.value;
                    if (!chat) return;

                    // 刷新消息列表：不分支模式下后端已删除旧 answer，只剩 user 消息
                    chat.messages = [];
                    await selectChat(currentChatId.value);

                    // 移除残留的旧 AI 回复（如有）
                    const userIdx = chat.messages.findIndex(m => m.id === 'u_' + msgId);
                    if (userIdx !== -1) {
                        const afterIdx = userIdx + 1;
                        if (afterIdx < chat.messages.length && chat.messages[afterIdx].role === 'assistant') {
                            chat.messages.splice(afterIdx, 1);
                        }
                    }

                    // 插入空的 AI 占位消息
                    const aiMsg = {
                        id: generateId(), role: 'assistant',
                        question: newQuestion,
                        content: '', thinking: [], timeline: [],
                        reference: [], recommend: [],
                        showTimeline: true, showReference: false, hasThinking: false,
                        usage: null, timestamp: Date.now()
                    };
                    // 找到 user 消息位置，在其后插入 AI 占位
                    const insertIdx = chat.messages.findIndex(m => m.id === 'u_' + msgId);
                    if (insertIdx !== -1) {
                        chat.messages.splice(insertIdx + 1, 0, aiMsg);
                    } else {
                        chat.messages.push(aiMsg);
                    }
                    // 重新获取 Vue 代理对象引用，确保流式更新能触发 DOM 渲染
                    const reactiveAiMsg = insertIdx !== -1
                        ? chat.messages[insertIdx + 1]
                        : chat.messages[chat.messages.length - 1];

                    isSending.value = true;
                    await nextTick();
                    const el = messagesContainer.value?.querySelectorAll('.message.assistant');
                    const last = el?.[el.length - 1];
                    if (last) { const t = last.querySelector('.text-content'); if (t) currentStreamContentDiv = t; }
                    scrollToBottom();

                    // 打开 SSE 流，使用 regenerateFromId 复用已有 ai_session 记录
                    const apiUrl = APP_API.getStreamChatUrl(backendUrl.value, selectedAgent.value, false);
                    const url = new URL(apiUrl, window.location.origin);
                    url.searchParams.append('query', newQuestion);
                    url.searchParams.append('conversationId', currentChatId.value);
                    url.searchParams.append('regenerateFromId', msgId);

                    try {
                        abortController = new AbortController();
                        const res = await fetch(url.toString(), {
                            method: 'GET',
                            headers: { 'Accept': 'text/event-stream', 'Cache-Control': 'no-cache' },
                            signal: abortController.signal,
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
                                try { processStreamData(JSON.parse(d), reactiveAiMsg); } catch (e) {}
                            }
                        }
                    } catch (err) {
                        if (err.name !== 'AbortError') {
                            reactiveAiMsg.content += '\n\n⚠️ ' + err.message;
                            updateStreamContent(aiMsg.content);
                        }
                    } finally {
                        isSending.value = false;
                        abortController = null;
                        currentStreamContentDiv = null;
                    }
                } else {
                    alert('编辑失败: ' + result.message);
                }
            } catch (e) {
                console.error('编辑失败:', e);
                alert('编辑失败: ' + e.message);
            }
        };

        const regenerateMessage = async (messageIdStr) => {
            if (isSending.value) return;

            const chat = currentChat.value;
            if (!chat) return;

            let finalMsgIdStr = messageIdStr;

            // 如果是客户端临时 ID（chat_xxx），先从后端刷新拿到数据库 ID
            if (messageIdStr.startsWith('chat_')) {
                chat.messages = [];
                await selectChat(currentChatId.value);
                // 刷新后取最后一条 assistant 消息
                const fresh = chat.messages.filter(m => m.role === 'assistant').pop();
                if (fresh) {
                    finalMsgIdStr = fresh.id;
                } else {
                    alert('无法定位该消息，请重试');
                    return;
                }
            }

            // 通过 id 找到被点击的 assistant 消息，取其存储的 question
            const aiMsg = chat.messages.find(m => m.id === finalMsgIdStr);
            if (!aiMsg || aiMsg.role !== 'assistant') return;
            const question = aiMsg.question;  // buildMessages 中存入的原始问题
            const aiMsgIndex = chat.messages.indexOf(aiMsg);

            // 移除旧的 AI 回复
            if (aiMsgIndex !== -1) {
                chat.messages.splice(aiMsgIndex, 1);
            }

            // 插入新的 AI 占位消息
            const newAiMsg = {
                id: generateId(), role: 'assistant',
                question: question,  // 保留问题给后续重新生成使用
                content: '', thinking: [], timeline: [],
                reference: [], recommend: [],
                showTimeline: true, showReference: false, hasThinking: false,
                usage: null, timestamp: Date.now()
            };
            chat.messages.push(newAiMsg);
            // 重新获取 Vue 代理对象引用，确保流式更新能触发 DOM 渲染
            const reactiveNewAiMsg = chat.messages[chat.messages.length - 1];

            isSending.value = true;

            await nextTick();
            const el = messagesContainer.value?.querySelectorAll('.message.assistant');
            const last = el?.[el.length - 1];
            if (last) { const t = last.querySelector('.text-content'); if (t) currentStreamContentDiv = t; }
            scrollToBottom();

            const messageId = messageIdStr.replace(/^[ua]_/, '');
            const apiUrl = APP_API.getStreamChatUrl(backendUrl.value, selectedAgent.value, false);
            const url = new URL(apiUrl, window.location.origin);
            url.searchParams.append('query', question);
            url.searchParams.append('conversationId', currentChatId.value);
            url.searchParams.append('regenerateFromId', messageId);

            try {
                abortController = new AbortController();
                const res = await fetch(url.toString(), {
                    method: 'GET',
                    headers: { 'Accept': 'text/event-stream', 'Cache-Control': 'no-cache' },
                    signal: abortController.signal,
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
                        try { processStreamData(JSON.parse(d), reactiveNewAiMsg); } catch (e) {}
                    }
                }
            } catch (err) {
                if (err.name !== 'AbortError') {
                    reactiveNewAiMsg.content += '\n\n⚠️ ' + err.message;
                    updateStreamContent(reactiveNewAiMsg.content);
                }
            } finally {
                isSending.value = false;
                abortController = null;
                currentStreamContentDiv = null;
            }
        };

        const switchToBranch = async (branchId) => {
            // branchId 保持字符串，避免雪花ID精度丢失
            const targetBranchId = String(branchId);
            if (!targetBranchId) {
                alert('无效的分支ID');
                return;
            }

            try {
                const response = await fetch(`${backendUrl.value}/branches/${currentChatId.value}/switch`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ target_branch_id: targetBranchId })
                });

                const result = await response.json();
                if (result.code === 200) {
                    // 重新加载消息列表（确保消息不重复）
                    const chat = currentChat.value;
                    if (chat) {
                        chat.messages = [];  // 先清空消息列表
                        await selectChat(currentChatId.value);  // 重新加载
                    }
                } else {
                    alert('分支切换失败: ' + result.message);
                }
            } catch (e) {
                console.error('分支切换失败:', e);
                alert('分支切换失败: ' + e.message);
            }
        };

        const loadSiblingBranches = async (messageIdStr) => {
            // 从消息ID中提取纯数字字符串（去掉'u_'或'a_'前缀，保持字符串避免雪花ID精度丢失）
            const messageId = messageIdStr.replace(/^[ua]_/, '');
            if (!messageId) {
                return [];
            }

            try {
                const response = await fetch(`${backendUrl.value}/branches/${currentChatId.value}/siblings/${messageId}`);
                const result = await response.json();

                if (result.code === 200) {
                    const siblings = result.data.siblings || [];
                    branchCache.set(messageIdStr, siblings);
                    return siblings;
                }
                return [];
            } catch (e) {
                console.error('加载兄弟分支失败:', e);
                return [];
            }
        };

        const prevBranch = async (messageId) => {
            const siblings = branchCache.get(messageId) || await loadSiblingBranches(messageId);
            const currentIndex = siblings.findIndex(s => s.branch_id === messageId);
            if (currentIndex > 0) {
                await switchToBranch(siblings[currentIndex - 1].branch_id);
            }
        };

        const nextBranch = async (messageId) => {
            const siblings = branchCache.get(messageId) || await loadSiblingBranches(messageId);
            const currentIndex = siblings.findIndex(s => s.branch_id === messageId);
            if (currentIndex < siblings.length - 1) {
                await switchToBranch(siblings[currentIndex + 1].branch_id);
            }
        };

        const archiveChat = async (chatId) => {
            try {
                await fetch(`${backendUrl.value}/conversations/${chatId}/archive?user_id=1`, {
                    method: 'PATCH'
                });
                // 刷新当前列表
                if (currentStatus.value === 'active') {
                    await loadChatsFromStorage();
                } else {
                    await loadArchivedChatsFromStorage();
                }
                if (currentChatId.value === chatId) currentChatId.value = null;
            } catch (e) { console.error('Archive failed:', e); }
        };

        const restoreChat = async (chatId) => {
            try {
                await fetch(`${backendUrl.value}/conversations/${chatId}/restore?user_id=1`, {
                    method: 'PATCH'
                });
                // 刷新当前列表
                if (currentStatus.value === 'active') {
                    await loadChatsFromStorage();
                } else {
                    await loadArchivedChatsFromStorage();
                }
                if (currentChatId.value === chatId) currentChatId.value = null;
            } catch (e) { console.error('Restore failed:', e); }
        };

        const openDeleteModal = (chatId) => {
            pendingDeleteChatId = chatId;
            showDeleteModal.value = true;
            deleteConfirmText.value = '';
        };

        const closeDeleteModal = () => {
            showDeleteModal.value = false;
            pendingDeleteChatId = null;
            deleteConfirmText.value = '';
        };

        const confirmDelete = async () => {
            if (!pendingDeleteChatId) return;
            try {
                await fetch(`${backendUrl.value}/conversations/${pendingDeleteChatId}?user_id=1`, {
                    method: 'DELETE'
                });
                // 刷新归档列表
                await loadArchivedChatsFromStorage();
                if (currentChatId.value === pendingDeleteChatId) currentChatId.value = null;
            } catch (e) { console.error('Delete failed:', e); }
            closeDeleteModal();
        };

        return {
            backendUrl, connectionError, agents, selectedAgent,
            chatList, currentChatId, currentChat, inputMessage,
            selectedFile, isUploading, isSending, currentRecommendMsgId, canSend,
            messagesContainer, textareaInput,
            selectAgent, quickPrompt, sendRecommendQuestion, isLastMessage,
            createNewChat, selectChat, deleteChat, removeFile, handleFileSelect,
            sendMessage, stopMessage, toggleTimeline, toggleReference, copyMessage,
            renderMarkdown, formatFileSize,
            showConfirmDialog, confirmTitle, confirmMessage, confirmOk, confirmCancel,
            currentStatus, filteredChatList, switchTab,
            editingChatId, startRename, startRenameFromMenu, toggleMenu, menuOpenId, commitRename, cancelRename,
            archiveChat, restoreChat, showDeleteModal, deleteConfirmText,
            openDeleteModal, closeDeleteModal, confirmDelete,
            // 分支管理
            editingMessageId, editText, createBranch,
            startEditMessage, cancelEditMessage, submitEdit,
            regenerateMessage, switchToBranch, loadSiblingBranches,
            prevBranch, nextBranch
        };
    }
}).mount('#app');
