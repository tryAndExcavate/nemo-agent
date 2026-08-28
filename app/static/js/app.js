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
        const showAccordion = ref(false);     // 是否显示手风琴分支视图

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

            // ===== 分支标签拖拽删除（全局监听） =====
            document.addEventListener('mousemove', onDragTab);
            document.addEventListener('mouseup', endDragTab);
            document.addEventListener('touchmove', onDragTab, { passive: false });
            document.addEventListener('touchend', endDragTab);
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
        const selectChat = async (chatId, opts = {}) => {
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

            // 判断是否有分支 → 树视图（手风琴替换分支轮次）
            const tree = buildTree(detail.messages);
            if (tree && hasBranches(tree)) {
                showAccordion.value = true;
                accordionResetFns.length = 0;
                const treeEl = document.getElementById('messageTree');
                if (treeEl) renderMessageTree(tree, treeEl);
            } else {
                showAccordion.value = false;
            }

            scrollToBottom();

            // 检查是否有活跃的 SSE 流，如有则重连（刷新页面后恢复流式回复）
            // skipReconnect: 编辑/重新生成流程传入 true，避免与自身 SSE 流冲突
            if (!opts.skipReconnect) {
                checkAndReconnectStream(chatId, chat);
            }
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

        // ===== 树形结构：flat → tree =====
        function buildTree(messages) {
            if (!messages || !Array.isArray(messages) || !messages.length) return null;
            const byId = new Map();
            messages.forEach(m => byId.set(m.id, { ...m, children: [] }));
            let root = null;
            byId.forEach(node => {
                if (node.parent_id == null) { root = node; return; }
                const parent = byId.get(String(node.parent_id));
                if (parent) { node.parentNode = parent; parent.children.push(node); }
            });
            byId.forEach(n => n.children.sort((a, b) => (a.branch_order || 0) - (b.branch_order || 0)));
            return root;
        }

        function hasBranches(node) {
            if (!node) return false;
            if (node.children && node.children.length > 1) return true;
            return (node.children || []).some(c => hasBranches(c));
        }

        // ===== 树视图渲染：手风琴替换分支轮次 =====
        const DEPTH_COLORS = ['#8b5cf6', '#10b981', '#f59e0b', '#a855f7', '#ef4444'];
        const accordionResetFns = [];

        function escapeHtml(str) {
            if (str == null) return '';
            return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
        }

        // 渲染单个节点的 Q&A 气泡
        function renderNodeBubbles(node, container) {
            if (node.question) {
                const div = document.createElement('div');
                div.className = 'message user';
                div.dataset.nodeId = String(node.id);
                div.innerHTML =
                    '<div class="message-avatar">👤</div>' +
                    '<div class="message-content"><div class="user-message"><div>' + escapeHtml(node.question) + '</div></div></div>';
                container.appendChild(div);
            }
            if (node.answer || node.thinking) {
                const div = document.createElement('div');
                div.className = 'message assistant';
                div.dataset.nodeId = String(node.id);
                let inner = '';
                if (node.thinking) {
                    inner += '<div class="timeline-section"><div class="timeline-header"><div class="timeline-icon-wrapper"><i class="fas fa-brain timeline-main-icon"></i></div><span class="timeline-title">思考过程</span></div><div class="timeline-content"><div class="timeline-item"><div class="timeline-dot thinking"></div><div class="timeline-item-body"><div class="timeline-thinking">' + escapeHtml(node.thinking) + '</div></div></div></div></div>';
                }
                inner += '<div class="text-content markdown-body">' + renderMarkdown(node.answer || '') + '</div>';
                inner += '<div class="message-actions" style="display: flex; opacity: 1;"><button class="action-btn regenerate-btn" title="重新生成"><i class="fas fa-redo"></i> 重新生成</button></div>';
                div.innerHTML = '<div class="message-avatar">🤖</div><div class="message-content"><div class="ai-message">' + inner + '</div></div>';
                const regenBtn = div.querySelector('.regenerate-btn');
                if (regenBtn) regenBtn.addEventListener('click', () => regenerateMessage('a_' + node.id));
                container.appendChild(div);
            }
        }

        // 递归渲染：节点 → Q&A → 线性 / 分支
        function renderMessageTree(tree, container) {
            container.innerHTML = '';
            if (!tree) return;
            accordionResetFns.length = 0;
            currentActiveBookAddFn = null;  // 重置，让初始化时重新设置
            currentActiveBookNodeId = null;
            renderNodeRecursive(tree, container, 0);
            scrollToBottom();
        }

        function renderNodeRecursive(node, container, depth) {
            renderNodeBubbles(node, container);
            const children = node.children || [];
            if (children.length === 1) {
                renderNodeRecursive(children[0], container, depth);
            } else if (children.length > 1) {
                const book = createBranchBook(children, depth, null);
                container.appendChild(book.element);
            }
        }

        // 沿单子链渲染并返回线程末端节点（用于确定"继续追问"的挂载点）
        function renderSubtreeTail(node, container, depth) {
            renderNodeBubbles(node, container);
            const children = node.children || [];
            if (children.length === 1) {
                return renderSubtreeTail(children[0], container, depth);
            }
            return node;
        }

        // 分支页内容：Q&A + 子树 + 输入框（输入框挂在线程末端）
        function renderBranchPage(node, content, depth) {
            renderNodeBubbles(node, content);
            const children = node.children || [];
            let tailNode = node;
            if (children.length === 1) {
                tailNode = renderSubtreeTail(children[0], content, depth + 1);
            } else if (children.length > 1) {
                const nestedWrap = document.createElement('div');
                nestedWrap.className = 'branch-nested-wrap';
                nestedWrap.style.setProperty('--depth-color', DEPTH_COLORS[depth % DEPTH_COLORS.length]);
                const label = document.createElement('div');
                label.className = 'branch-nested-label';
                label.innerHTML = '<span>↳ 该分支下有 ' + children.length + ' 个子分支</span><span>可继续切换 / 追加</span>';
                nestedWrap.appendChild(label);
                const book = createBranchBook(children, depth + 1, null);
                nestedWrap.appendChild(book.element);
                content.appendChild(nestedWrap);
            }
            addBranchInput(tailNode, content);
        }

        // 分支输入框
        function addBranchInput(node, content) {
            const row = document.createElement('div');
            row.className = 'branch-input-row';
            const inputBox = document.createElement('textarea');
            inputBox.className = 'branch-input-box';
            inputBox.placeholder = '在此分支继续追问…';
            const sendBtn = document.createElement('button');
            sendBtn.className = 'branch-input-send';
            sendBtn.textContent = '发送';
            sendBtn.addEventListener('click', () => {
                const text = inputBox.value.trim();
                if (!text || sendBtn.disabled) return;
                inputBox.disabled = true;
                sendBtn.disabled = true;
                continueBranch(node, text, row).finally(() => {
                    inputBox.disabled = false;
                    sendBtn.disabled = false;
                    inputBox.value = '';
                });
            });
            inputBox.addEventListener('keydown', (e) => {
                if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendBtn.click(); }
            });
            row.appendChild(inputBox);
            row.appendChild(sendBtn);
            content.appendChild(row);
        }

        function truncateQ(q) {
            const s = (q || '').replace(/\s+/g, ' ');
            return s.length > 14 ? s.slice(0, 14) + '…' : s;
        }

        // 草稿分支编辑器：输入新问题 → 发送生成新分支 / 取消删除草稿
        function renderDraftContent(node, page, content, onSubmit, onCancel) {
            const titleRow = document.createElement('div');
            titleRow.className = 'branch-title-row';
            titleRow.innerHTML =
                '<span class="branch-order-num">' + (node.branch_order || '') + '</span>' +
                '<strong>新的并排分支</strong><span class="branch-draft-badge">待发送</span>';
            content.appendChild(titleRow);

            const tip = document.createElement('div');
            tip.className = 'draft-tip';
            tip.textContent = '这是与当前节点并排的新对话（同一层级），输入问题后将独立生成回答，不影响其它分支。';
            content.appendChild(tip);

            const textarea = document.createElement('textarea');
            textarea.className = 'draft-input';
            textarea.placeholder = '例如：如果换一种思路会怎样？';
            content.appendChild(textarea);

            const btnRow = document.createElement('div');
            btnRow.className = 'draft-btn-row';
            const sendBtn = document.createElement('button');
            sendBtn.className = 'draft-send-btn';
            sendBtn.textContent = '发送，生成该分支';
            const cancelBtn = document.createElement('button');
            cancelBtn.className = 'draft-cancel-btn';
            cancelBtn.textContent = '取消';
            sendBtn.addEventListener('click', () => {
                const val = textarea.value.trim();
                if (!val) { textarea.focus(); return; }
                if (sendBtn.disabled) return;
                sendBtn.disabled = true;
                cancelBtn.disabled = true;
                onSubmit(node, val, content, page);
            });
            cancelBtn.addEventListener('click', () => onCancel(node, page));
            textarea.addEventListener('keydown', (e) => {
                if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendBtn.click(); }
            });
            btnRow.appendChild(sendBtn);
            btnRow.appendChild(cancelBtn);
            content.appendChild(btnRow);

            requestAnimationFrame(() => textarea.focus());
        }

        // 新增并排分支：后端建节点 → 流式生成回答 → 刷新整棵树
        async function streamNewBranch(node, text, content, page) {
            if (node.parent_id == null) {
                alert('无法在根节点下新增分支');
                return;
            }
            // 1. 后端创建分支节点
            let branchId;
            try {
                const resp = await fetch(`${backendUrl.value}/branches/${currentChatId.value}/create`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ parent_id: String(node.parent_id), question: text })
                });
                const result = await resp.json();
                if (result.code !== 200) throw new Error(result.message || '创建分支失败');
                branchId = String(result.data.branch_id);
            } catch (e) {
                alert('创建分支失败: ' + e.message);
                return;
            }

            // 2. 用真实 ID 替换草稿节点/页面
            node.id = branchId;
            node.question = text;
            node.draft = false;
            page.dataset.nodeId = branchId;

            // 3. 清空草稿编辑器，渲染 Q&A 气泡
            content.innerHTML = '';
            const qBubble = document.createElement('div');
            qBubble.className = 'message user';
            qBubble.innerHTML = '<div class="message-avatar">👤</div><div class="message-content"><div class="user-message"><div>' + escapeHtml(text) + '</div></div></div>';
            content.appendChild(qBubble);
            const aBubble = document.createElement('div');
            aBubble.className = 'message assistant';
            aBubble.innerHTML = '<div class="message-avatar">🤖</div><div class="message-content"><div class="ai-message"><div class="text-content markdown-body"></div></div></div>';
            content.appendChild(aBubble);
            const textEl = aBubble.querySelector('.text-content');
            let answerText = '';

            // 4. 流式生成回答（复用该记录，历史截止到父节点）
            try {
                const apiUrl = APP_API.getStreamChatUrl(backendUrl.value, selectedAgent.value, false);
                const url = new URL(apiUrl, window.location.origin);
                url.searchParams.append('query', text);
                url.searchParams.append('conversationId', currentChatId.value);
                url.searchParams.append('regenerateFromId', branchId);
                url.searchParams.append('untilMessageId', String(node.parent_id));

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
                        try {
                            const evt = JSON.parse(d);
                            if (evt.type === 'text' && evt.content) {
                                answerText += evt.content;
                                textEl.innerHTML = renderMarkdown(answerText);
                            }
                        } catch (e) {}
                    }
                }
            } catch (err) {
                if (err.name !== 'AbortError') {
                    textEl.innerHTML = renderMarkdown('⚠️ ' + err.message);
                }
            } finally {
                abortController = null;
            }
            // 5. 完成后刷新整棵树（草稿结构被真实节点替换）
            await refreshTreeView();
        }

        // 3D 书本：同层分支并排展示
        function createBranchBook(siblings, depth, notifyParentHeight) {
            const isTop = depth === 0;
            const shell = document.createElement('div');
            shell.className = 'branch-shell' + (isTop ? '' : ' nested');
            const stage = document.createElement('div');
            stage.className = 'branch-stage';
            const tabsWrap = document.createElement(isTop ? 'nav' : 'div');
            tabsWrap.className = isTop ? 'rail-tabs' : 'pill-tabs';
            if (isTop) { shell.appendChild(stage); shell.appendChild(tabsWrap); }
            else { shell.appendChild(tabsWrap); shell.appendChild(stage); }

            let current = 0;
            const pageEls = [];
            const tabEls = [];

            function updateHeight() {
                requestAnimationFrame(() => {
                    // 取所有页中最高的那个，避免短页漏出长页
                    let maxH = 0;
                    pageEls.forEach(p => { if (p.offsetHeight > maxH) maxH = p.offsetHeight; });
                    if (maxH > 0) stage.style.height = maxH + 'px';
                    if (notifyParentHeight) notifyParentHeight();
                });
            }

            function layout() {
                pageEls.forEach((page, i) => {
                    page.classList.remove('active', 'before', 'after');
                    if (i === current) page.classList.add('active');
                    else if (i < current) { page.classList.add('before'); page.style.setProperty('--d', current - i); }
                    else { page.classList.add('after'); page.style.setProperty('--d', i - current); }
                });
                tabEls.forEach((tab, i) => tab.classList.toggle('current', i === current));
                updateHeight();
            }

            function resetToActive() {
                const idx = siblings.findIndex(n => n.is_active_branch);
                current = idx === -1 ? siblings.length - 1 : idx;
                layout();
            }
            accordionResetFns.push(resetToActive);

            const ro = new ResizeObserver(updateHeight);

            // 在本层新增并排分支：追加一个草稿页并切换到它
            // overrideParentId: 工具栏调用时传入活跃节点 id，新分支挂在该节点下
            function addDraftBranch(overrideParentId) {
                // 过滤掉事件对象（addTab 直接绑定时 click event 会作为第一个参数传入）
                const validOverride = (typeof overrideParentId === 'string' || typeof overrideParentId === 'number')
                    ? overrideParentId : undefined;
                const parentId = validOverride !== undefined ? validOverride
                    : (siblings.length ? siblings[0].parent_id : null);
                const maxOrder = siblings.reduce((m, s) => Math.max(m, s.branch_order || 0), 0);
                const draftNode = {
                    id: 'draft_' + Date.now() + '_' + Math.floor(Math.random() * 1000),
                    parent_id: parentId,
                    branch_order: maxOrder + 1,
                    is_active_branch: false,
                    draft: true,
                    question: '',
                    answer: '',
                    children: [],
                    parentNode: null
                };
                siblings.push(draftNode);
                buildOne(draftNode);
                tabsWrap.appendChild(addTab);  // 保证“+”始终在最后
                current = pageEls.length - 1;
                layout();
            }

            function cancelDraft(node, page) {
                const sIdx = siblings.indexOf(node);
                if (sIdx > -1) siblings.splice(sIdx, 1);
                const pIdx = pageEls.indexOf(page);
                if (pIdx > -1) {
                    pageEls.splice(pIdx, 1);
                    const [removedTab] = tabEls.splice(pIdx, 1);
                    if (removedTab) removedTab.remove();
                }
                page.remove();
                tabsWrap.appendChild(addTab);
                current = Math.max(0, siblings.length - 1);
                layout();
            }

            function buildOne(node) {
                const page = document.createElement('article');
                page.className = 'branch-page' + (isTop ? '' : ' sub');
                page.dataset.nodeId = String(node.id);
                const content = document.createElement('div');
                content.className = 'branch-page-content';
                page.appendChild(content);
                stage.appendChild(page);
                pageEls.push(page);
                ro.observe(page);

                if (node.draft) {
                    renderDraftContent(node, page, content, streamNewBranch, cancelDraft);
                } else {
                    renderBranchPage(node, content, depth);
                }

                const tab = document.createElement('button');
                tab.className = isTop ? 'rail-tab' : 'pill-tab';
                tab.textContent = node.draft
                    ? '分支 ' + (node.branch_order || '') + '（待填写）'
                    : (isTop ? '分支 ' + (node.branch_order || '') + '：' : '') + truncateQ(node.question);
                tab.addEventListener('click', () => {
                    if (dragState && dragState.moved) return; // 拖拽中不切换
                    const idx = pageEls.indexOf(page);
                    if (idx !== -1 && idx !== current) { current = idx; layout(); }
                    currentActiveBookAddFn = addDraftBranch;
                    currentActiveBookNodeId = node.id;
                });
                tab.addEventListener('mousedown', (e) => { startDragTab(e, tab, node); });
                tab.addEventListener('touchstart', (e) => { startDragTab(e, tab, node); }, { passive: true });
                tabsWrap.appendChild(tab);
                tabEls.push(tab);
            }

            siblings.forEach(buildOne);

            const addTab = document.createElement('button');
            addTab.className = (isTop ? 'rail-tab' : 'pill-tab') + ' add-tab';
            addTab.textContent = isTop ? '＋ 新增分支' : '＋ 新增';
            tabsWrap.appendChild(addTab);
            addTab.addEventListener('click', addDraftBranch);

            // 优先选中活跃分支（新分支会被标记为活跃 → 栈顶优先且文字清晰）
            const activeIdx = siblings.findIndex(n => n.is_active_branch);
            current = activeIdx !== -1 ? activeIdx : siblings.length - 1;
            layout();
            // 仅在用户未点击过任何标签时初始化（避免覆盖用户已选择的层级）
            if (!currentActiveBookAddFn) {
                currentActiveBookAddFn = addDraftBranch;
                currentActiveBookNodeId = siblings[current] ? siblings[current].id : null;
            }

            return { element: shell, updateHeight };
        }

        // 通用：以指定父节点继续对话（流式输出到容器内）
        async function streamWithParent(parentId, text, container, insertBeforeEl) {
            const qBubble = document.createElement('div');
            qBubble.className = 'message user';
            qBubble.innerHTML = '<div class="message-avatar">👤</div><div class="message-content"><div class="user-message"><div>' + escapeHtml(text) + '</div></div></div>';
            const aBubble = document.createElement('div');
            aBubble.className = 'message assistant';
            aBubble.innerHTML = '<div class="message-avatar">🤖</div><div class="message-content"><div class="ai-message"><div class="text-content markdown-body"></div></div></div>';
            const textEl = aBubble.querySelector('.text-content');
            if (insertBeforeEl) { container.insertBefore(qBubble, insertBeforeEl); container.insertBefore(aBubble, insertBeforeEl); }
            else { container.appendChild(qBubble); container.appendChild(aBubble); }
            let answerText = '';

            try {
                const apiUrl = APP_API.getStreamChatUrl(backendUrl.value, selectedAgent.value, false);
                const url = new URL(apiUrl, window.location.origin);
                url.searchParams.append('query', text);
                url.searchParams.append('conversationId', currentChatId.value);
                url.searchParams.append('parentId', String(parentId));
                url.searchParams.append('untilMessageId', String(parentId));

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
                        try {
                            const evt = JSON.parse(d);
                            if (evt.type === 'text' && evt.content) {
                                answerText += evt.content;
                                textEl.innerHTML = renderMarkdown(answerText);
                            }
                        } catch (e) {}
                    }
                }
            } catch (err) {
                if (err.name !== 'AbortError') {
                    textEl.innerHTML = renderMarkdown('⚠️ ' + err.message);
                }
            } finally {
                abortController = null;
            }
            // 完成后刷新整棵树
            await refreshTreeView();
        }

        // 分支内继续追问
        async function continueBranch(node, text, inputRow) {
            await streamWithParent(node.id, text, inputRow.parentElement, inputRow);
        }

        // 获取活跃路径的叶节点 id（树模式下底部输入框继续对话的目标）
        async function getActiveLeafId() {
            const detail = await APP_API.getChatDetail(backendUrl.value, currentChatId.value);
            if (!detail) return null;
            const tree = buildTree(detail.messages);
            if (!tree) return null;
            let node = tree;
            while (true) {
                const children = node.children || [];
                if (!children.length) return node.id;
                // 优先活跃分支；多个活跃取 branch_order 最大（最新）
                const actives = children.filter(c => c.is_active_branch);
                let target = null;
                if (actives.length === 1) target = actives[0];
                else if (actives.length > 1) target = actives[actives.length - 1];
                else if (children.length === 1) target = children[0];
                else target = children[children.length - 1];
                node = target;
            }
        }

        // 将所有层级的手风琴书本切回活跃分支
        function resetToMainBranch() {
            accordionResetFns.forEach(fn => fn());
        }

        // 在当前活跃分支所在层级新增并排分支
        let currentActiveBookAddFn = null;  // { fn, activeNodeId }
        let currentActiveBookNodeId = null;

        function addBranchAtCurrentLevel() {
            if (currentActiveBookAddFn) currentActiveBookAddFn(currentActiveBookNodeId);
        }

        // 刷新树视图 + 主对话
        async function refreshTreeView() {
            const chat = currentChat.value;
            if (!chat) return;
            const detail = await APP_API.getChatDetail(backendUrl.value, currentChatId.value);
            if (!detail) return;
            chat.messages = buildMessages(detail);
            const tree = buildTree(detail.messages);
            if (tree && hasBranches(tree)) {
                showAccordion.value = true;
                const treeEl = document.getElementById('messageTree');
                if (treeEl) renderMessageTree(tree, treeEl);
            } else {
                showAccordion.value = false;
            }
            scrollToBottom();
        }

        // ===== 拖拽删除分支标签 =====
        let dragState = null; // { tab, node, isTop, startX, startY, offsetX, offsetY }

        function startDragTab(e, tab, node) {
            if (isSending.value) return;
            if (tab.classList.contains('add-tab')) return; // "+" 标签不允许删除
            const clientX = e.touches ? e.touches[0].clientX : e.clientX;
            const clientY = e.touches ? e.touches[0].clientY : e.clientY;
            dragState = {
                tab, node,
                isTop: tab.classList.contains('rail-tab'),
                startX: clientX, startY: clientY,
                offsetX: 0, offsetY: 0, moved: false,
            };
        }

        function onDragTab(e) {
            if (!dragState) return;
            const clientX = e.touches ? e.touches[0].clientX : e.clientX;
            const clientY = e.touches ? e.touches[0].clientY : e.clientY;
            const dx = clientX - dragState.startX;
            const dy = clientY - dragState.startY;
            dragState.offsetX = dx;
            dragState.offsetY = dy;
            if (Math.abs(dx) > 5 || Math.abs(dy) > 5) dragState.moved = true;
            const { tab, isTop } = dragState;
            tab.classList.add('swiping');

            if (isTop) {
                const dist = Math.max(0, dx);
                tab.style.transform = 'translateX(' + dist + 'px)';
                tab.classList.toggle('delete-ready', dist > 60);
            } else {
                const dist = Math.max(0, -dy);
                tab.style.transform = 'translateY(' + (-dist) + 'px)';
                tab.classList.toggle('delete-ready', dist > 50);
            }
            if (e.cancelable) e.preventDefault(); // 阻止选中文本
        }

        function endDragTab() {
            if (!dragState) return;
            const { tab, node, isTop, offsetX, offsetY } = dragState;
            tab.classList.remove('swiping');

            const pastThreshold = isTop ? offsetX > 60 : offsetY < -50;

            if (pastThreshold && node.id) {
                // 确认删除：飞走动画 → 刷新
                tab.classList.add('deleted');
                const msgId = String(node.id).replace(/^[ua]_/, '');
                setTimeout(async () => {
                    await deleteBranchById(msgId);
                    await refreshTreeView();
                }, 350);
            } else {
                // 弹回原位
                tab.style.transition = 'transform .4s cubic-bezier(.22,1,.36,1)';
                tab.style.transform = '';
                tab.addEventListener('transitionend', function handler() {
                    tab.style.transition = '';
                    tab.removeEventListener('transitionend', handler);
                });
            }

            tab.classList.remove('delete-ready');
            dragState = null;
        }

        async function deleteBranchById(messageId) {
            try {
                const resp = await fetch(
                    `${backendUrl.value}/branches/${currentChatId.value}/${messageId}`,
                    { method: 'DELETE' }
                );
                const result = await resp.json();
                if (result.code !== 200) {
                    console.error('删除分支失败:', result.message || result.error);
                }
            } catch (e) {
                console.error('删除分支请求失败:', e);
            }
        }

        // 树模式下：把 SSE 流式输出写入指定分支页内
        async function streamIntoTreePage(regenId, query) {
            const page = document.querySelector(`.branch-page[data-node-id="${regenId}"]`);
            if (!page) return false;
            const content = page.querySelector('.branch-page-content');
            if (!content) return false;
            const inputRow = content.querySelector('.branch-input-row');

            // 复用已存在的回复气泡（重新生成时），否则新建
            let aBubble = content.querySelector(':scope > .message.assistant');
            let textEl;
            if (aBubble) {
                textEl = aBubble.querySelector('.text-content');
                if (textEl) textEl.innerHTML = '';
            }
            if (!aBubble || !textEl) {
                aBubble = document.createElement('div');
                aBubble.className = 'message assistant';
                aBubble.innerHTML = '<div class="message-avatar">🤖</div><div class="message-content"><div class="ai-message"><div class="text-content markdown-body"></div></div></div>';
                textEl = aBubble.querySelector('.text-content');
                if (inputRow) content.insertBefore(aBubble, inputRow);
                else content.appendChild(aBubble);
            }
            let answerText = '';
            let thinkingText = '';

            try {
                const apiUrl = APP_API.getStreamChatUrl(backendUrl.value, selectedAgent.value, false);
                const url = new URL(apiUrl, window.location.origin);
                url.searchParams.append('query', query);
                url.searchParams.append('conversationId', currentChatId.value);
                url.searchParams.append('regenerateFromId', regenId);

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
                        try {
                            const evt = JSON.parse(d);
                            if (evt.type === 'text' && evt.content) {
                                answerText += evt.content;
                                textEl.innerHTML = renderMarkdown(answerText);
                            } else if (evt.type === 'thinking' && evt.content) {
                                thinkingText += evt.content;
                            }
                        } catch (e) {}
                    }
                }
            } catch (err) {
                if (err.name !== 'AbortError') {
                    textEl.innerHTML = renderMarkdown('⚠️ ' + err.message);
                }
            } finally {
                abortController = null;
            }
            // 完成后刷新整棵树
            await refreshTreeView();
            return true;
        }

        // 树模式下重新生成：就地流式更新该节点的回复气泡
        async function streamRegenerateInTree(messageId, question) {
            const bubble = document.querySelector(`.message.assistant[data-node-id="${messageId}"]`);
            let textEl = null;
            if (bubble) textEl = bubble.querySelector('.text-content');
            if (textEl) textEl.innerHTML = '';

            if (!textEl) {
                // 找不到气泡，退化为追加到页面
                return streamIntoTreePage(messageId, question);
            }

            let answerText = '';
            try {
                const apiUrl = APP_API.getStreamChatUrl(backendUrl.value, selectedAgent.value, false);
                const url = new URL(apiUrl, window.location.origin);
                url.searchParams.append('query', question);
                url.searchParams.append('conversationId', currentChatId.value);
                url.searchParams.append('regenerateFromId', messageId);

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
                        try {
                            const evt = JSON.parse(d);
                            if (evt.type === 'text' && evt.content) {
                                answerText += evt.content;
                                textEl.innerHTML = renderMarkdown(answerText);
                            }
                        } catch (e) {}
                    }
                }
            } catch (err) {
                if (err.name !== 'AbortError') {
                    textEl.innerHTML = renderMarkdown('⚠️ ' + err.message);
                }
            } finally {
                abortController = null;
            }
            await refreshTreeView();
            return true;
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

            // 树模式（有分支）：继续活跃分支，流式输出到树视图
            if (showAccordion.value) {
                try {
                    const activeLeafId = await getActiveLeafId();
                    if (activeLeafId) {
                        const treeEl = document.getElementById('messageTree');
                        if (treeEl) {
                            scrollToBottom();
                            await streamWithParent(activeLeafId, msg || '请分析这个文件', treeEl, null);
                        }
                    }
                } catch (e) {
                    console.error('树模式发送失败:', e);
                    alert('发送失败: ' + e.message);
                } finally {
                    isSending.value = false;
                    abortController = null;
                }
                return;
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
                    await selectChat(currentChatId.value, { skipReconnect: true });
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

                    // 分支模式下，使用新分支的 ID 作为 regenerateFromId
                    const regenId = shouldCreateBranch ? result.data.branch_id : msgId;

                    // 刷新消息列表
                    chat.messages = [];
                    await selectChat(currentChatId.value, { skipReconnect: true });

                    // 树模式（有分支）：流式输出到手风琴新分支页内，栈顶优先显示
                    if (showAccordion.value) {
                        isSending.value = true;
                        scrollToBottom();
                        await streamIntoTreePage(regenId, newQuestion);
                        isSending.value = false;
                        return;
                    }

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
                    url.searchParams.append('regenerateFromId', regenId);

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
                            updateStreamContent(reactiveAiMsg.content);
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
                await selectChat(currentChatId.value, { skipReconnect: true });
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

            // 树模式：就地更新该节点的回复气泡
            if (showAccordion.value) {
                await streamRegenerateInTree(messageId, question);
                isSending.value = false;
                return;
            }

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
            editingMessageId, editText, createBranch, showAccordion,
            startEditMessage, cancelEditMessage, submitEdit,
            regenerateMessage, switchToBranch, loadSiblingBranches,
            prevBranch, nextBranch, addBranchAtCurrentLevel
        };
    }
}).mount('#app');
