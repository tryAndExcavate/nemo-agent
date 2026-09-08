<script setup>
// ===== Nemo App.vue —— 从旧单页 (app.js setup + index.html #app) 机械迁移的骨架版 =====
import { ref, computed, nextTick, onMounted, watch } from 'vue'
import hljs from 'highlight.js'
import { APP_CONFIG } from './lib/config.js'
import { APP_CONSTANTS } from './lib/constants.js'
import { APP_API } from './lib/api.js'
import { APP_UTILS } from './lib/utils.js'

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

    // ===== 任务模式状态 =====
    const modeType = ref('chat');  // 'chat' | 'task'
    const showAgentDrawer = ref(false);
    const currentChatAgent = computed(() => agents.value.find(a => a.id === selectedAgent.value) || agents.value[0]);
    const inputPlaceholder = computed(() => {
        if (modeType.value === 'task') return '描述任务目标，或选择下方模板…';
        return '输入消息…（支持 Markdown，Shift+Enter 换行）';
    });

    // 任务数据
    const task = ref({ status: 'idle', goal: '', steps: [], finalOutput: '', context: { used: 0, max: 8000 }, contextUsage: null, totalTokens: 0, elapsedSec: 0 });
    const taskGoalDraft = ref('');
    const editingTaskGoal = ref(false);
    // 任务对话消息
    const taskMessages = ref([]);  // [{role:'user'|'ai', content:'', steps:[], usage:null, _showSteps:false}]
    const taskInput = ref('');
    const useMemoryAgent = ref(false);  // 记忆模式：启用后用 memory-retriever 子智能体
    const taskInputSending = ref(false);
    const tmBody = ref(null);
    const tmChatArea = ref(null);
    const taskInputRef = ref(null);
    const taskTemplates = ref([
        '梳理项目接口文档并生成变更清单',
        '分析代码库中的潜在安全漏洞',
        '为项目编写单元测试',
        '重构指定模块的代码结构'
    ]);
    const workspaces = ref([
        { id: 'ws1', name: '当前项目', path: '.' },
    ]);
    const selectedWorkspaceId = ref('ws1');
    const selectedWorkspace = computed(() => workspaces.value.find(w => w.id === selectedWorkspaceId.value));
    const showWorkspaceMenu = ref(false);
    const showFileTree = ref(false);

    // 目录浏览器状态
    const showDirBrowser = ref(false);
    const dirBrowserPath = ref('.');
    const dirBrowserItems = ref([]);
    const dirBrowserLoading = ref(false);
    const dirBrowserError = ref('');
    const workspaceFileTree = ref([]);

    // 任务列表状态
    const taskList = ref([]);
    const taskListLoading = ref(false);

    const taskStatusLabel = computed(() => {
        const map = { idle: '待执行', executing: '执行中', paused: '已暂停', done: '已完成', error: '出错' };
        return map[task.value.status] || task.value.status;
    });
    const taskContextPercent = computed(() => Math.round((task.value.context.used / task.value.context.max) * 100));
    const taskContextLevelClass = computed(() => {
        const p = taskContextPercent.value;
        if (p > 80) return 'high';
        if (p > 50) return 'mid';
        return 'low';
    });

    function formatK(n) { return n >= 1000 ? (n / 1000).toFixed(1) + 'k' : String(n); }
    function ctxBarWidth(key) {
        const u = task.value.contextUsage;
        if (!u || !u.total) return '0%';
        return Math.round((u[key] || 0) / u.total * 100) + '%';
    }
    function ctxPct(key) {
        const u = task.value.contextUsage;
        if (!u || !u.total) return '0';
        return Math.round((u[key] || 0) / u.total * 100);
    }
    const ctxTooltipStyle = ref({});
    const ctxTooltipVisible = ref(false);
    // 点击仪表：先从服务端同步当前任务最新的上下文窗口用量，再切换明细弹窗
    async function toggleCtxTooltip(e) {
        // 点击弹窗内部不关闭（便于阅读/复制）
        if (e.target.closest && e.target.closest('.tm-context-detail')) return;
        if (ctxTooltipVisible.value) { ctxTooltipVisible.value = false; return; }
        const rect = e.currentTarget.getBoundingClientRect();
        ctxTooltipStyle.value = {
            position: 'fixed',
            top: (rect.bottom + 6) + 'px',
            left: rect.left + 'px',
            zIndex: 200,
        };
        // 展示前先同步数值：保证每次刷新/切换任务后，仪表里的上下文用量是最新的
        const usage = await syncCtxUsageFromServer();
        if (usage) ctxTooltipVisible.value = true;
    }
    function hideCtxTooltip() {
        ctxTooltipVisible.value = false;
    }
    // 把服务端 meta 的 ctx_* 窗口明细换算成前端 contextUsage / 仪表数值
    function applyCtxMeta(meta) {
        const m = meta || {};
        const parts = {
            system_prompt: m.ctx_system_tokens || 0,
            history: m.ctx_history_tokens || 0,
            tool_definitions: m.ctx_tool_def_tokens || 0,
            tool_results: m.ctx_tool_result_tokens || 0,
            current_input: m.ctx_input_tokens || 0,
        };
        const ctxTotal = parts.system_prompt + parts.history +
            parts.tool_definitions + parts.tool_results + parts.current_input;
        const usageTotal = (m.total_input_tokens || 0) + (m.total_output_tokens || 0);
        const used = ctxTotal || usageTotal;
        const has = ctxTotal > 0 || usageTotal > 0;
        // 后端暂无明细时不覆盖实时值（运行中的任务以 llm_input 推来的 context_usage 为准）
        if (!has) return task.value.contextUsage || null;
        task.value.context = { used, max: (task.value.context && task.value.context.max) || 8000 };
        task.value.contextUsage = { ...parts, total: ctxTotal || usageTotal };
        return task.value.contextUsage;
    }
    // 从后端 /agent/task/load 重新拉取当前任务的上下文窗口用量，同步到仪表
    async function syncCtxUsageFromServer() {
        const convId = task.value.conversationId;
        if (!convId || task.value.status === 'idle') return task.value.contextUsage;
        try {
            const resp = await fetch('/agent/task/load?conversationId=' + encodeURIComponent(convId));
            const data = await resp.json();
            return applyCtxMeta(data.meta || {});
        } catch (e) {
            return task.value.contextUsage;
        }
    }
    function formatToolIO(io) { return io ? (typeof io === 'string' ? io : JSON.stringify(io, null, 2)) : ''; }
    function switchToChatMode() { modeType.value = 'chat'; showAgentDrawer.value = false; }
    function switchToTaskMode() { modeType.value = 'task'; currentStatus.value = 'tasks'; loadTaskList(); }
    function chooseSubAgent(id) { selectedAgent.value = id; showAgentDrawer.value = false; modeType.value = 'chat'; }
    function getAgentDesc(id) {
        const map = { chat: '智能问答', file: '文件分析', ppt: 'PPT生成', deep: '深度研究', skills: '技能助手' };
        return map[id] || '';
    }
    let _taskAbortController = null;
    let _currentStep = null;
    let _currentAiMsg = null;

    async function loadWorkspaces() {
        try {
            const resp = await fetch('/api/workspaces');
            const data = await resp.json();
            const list = (data.workspaces || []).map(w => ({
                id: w.path || w.id,
                name: w.name || '当前项目',
                path: w.path || '.',
            }));
            if (list.length === 0) list.push({ id: '.', name: '当前项目', path: '.' });
            workspaces.value = list;
            const activePath = data.active || (list[0] && list[0].path);
            const active = list.find(w => w.path === activePath) || list[0];
            selectedWorkspaceId.value = active ? active.id : (list.length ? list[0].id : '');
        } catch (e) {
            workspaces.value = [{ id: 'ws1', name: '当前项目', path: '.' }];
            selectedWorkspaceId.value = 'ws1';
        }
    }
    function selectWorkspace(id) {
        const ws = workspaces.value.find(w => w.id === id);
        selectedWorkspaceId.value = id;
        showWorkspaceMenu.value = false;
        showDirBrowser.value = false;
        if (ws) persistWorkspaceSelect(ws.path);
    }
    // 连接/切换到某路径工作区：本地选中 + 写回后端，刷新后仍在
    function activateWorkspace(path) {
        if (!path) return;
        const existing = workspaces.value.find(w => w.path === path);
        if (existing) {
            selectedWorkspaceId.value = existing.id;
        } else {
            const id = path;
            workspaces.value.push({ id, name: path.split(/[\\/]/).filter(Boolean).pop() || path, path });
            selectedWorkspaceId.value = id;
        }
        showWorkspaceMenu.value = false;
        showDirBrowser.value = false;
        persistWorkspaceSelect(path);
    }
    function persistWorkspaceSelect(path) {
        if (!path) return;
        fetch('/api/workspaces', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ path }),
        }).catch(() => {});
    }

    async function openDirBrowser() {
        showWorkspaceMenu.value = false;
        showDirBrowser.value = true;
        dirBrowserLoading.value = true;
        dirBrowserError.value = '';
        // 初始路径：用户主目录
        const home = navigator.userAgent.includes('Windows')
            ? (await _fetchDirs('C:\\\\Users')).path || 'C:\\'
            : (await _fetchDirs('/home')).path || '/';
        dirBrowserPath.value = home;
        await _loadDirItems(home);
    }

    async function _fetchDirs(path) {
        try {
            const resp = await fetch('/api/directories?path=' + encodeURIComponent(path));
            return await resp.json();
        } catch (e) {
            return { path, items: [], error: e.message };
        }
    }

    async function _loadDirItems(path) {
        dirBrowserLoading.value = true;
        dirBrowserError.value = '';
        const data = await _fetchDirs(path);
        dirBrowserPath.value = data.path || path;
        dirBrowserItems.value = data.items || [];
        dirBrowserError.value = data.error || '';
        dirBrowserLoading.value = false;
    }

    async function dirBrowserNavigate(path) { await _loadDirItems(path); }

    async function dirBrowserGoUp() {
        const cur = dirBrowserPath.value;
        const sep = cur.includes('\\') ? '\\' : '/';
        const parts = cur.split(sep).filter(Boolean);
        if (parts.length <= 1) return;
        parts.pop();
        const parent = parts.join(sep) || sep;
        await _loadDirItems(parent);
    }

    let _pendingEditWsId = null;

    function editWorkspace(ws) {
        showWorkspaceMenu.value = false;
        showDirBrowser.value = true;
        dirBrowserPath.value = ws.path;
        _pendingEditWsId = ws.id;
        _loadDirItems(ws.path);
    }

    function dirBrowserConfirm() {
        const path = dirBrowserPath.value;
        if (_pendingEditWsId) {
            const ws = workspaces.value.find(w => w.id === _pendingEditWsId);
            const oldPath = ws ? ws.path : null;
            const wasSelected = selectedWorkspaceId.value === _pendingEditWsId;
            if (ws) {
                const name = path.split(/[\\/]/).filter(Boolean).pop() || path;
                ws.id = path; ws.name = name; ws.path = path;
            }
            _pendingEditWsId = null;
            if (wasSelected) selectedWorkspaceId.value = path;
            showDirBrowser.value = false;
            if (oldPath && oldPath !== path) {
                fetch('/api/workspaces?path=' + encodeURIComponent(oldPath), { method: 'DELETE' }).catch(() => {});
            }
            persistWorkspaceSelect(path);
        } else {
            showDirBrowser.value = false;
            activateWorkspace(path);
    }
    }
    function removeWorkspace(id) {
        const ws = workspaces.value.find(w => w.id === id);
        workspaces.value = workspaces.value.filter(w => w.id !== id);
        if (selectedWorkspaceId.value === id) {
            selectedWorkspaceId.value = workspaces.value.length > 0 ? workspaces.value[0].id : '';
        }
        if (ws && ws.path) {
            fetch('/api/workspaces?path=' + encodeURIComponent(ws.path), { method: 'DELETE' }).catch(() => {});
        }
    }
    async function startTask() {
        const goal = taskGoalDraft.value.trim();
        const ws = workspaces.value.find(w => w.id === selectedWorkspaceId.value);
        if (!goal || !ws) return;

        // 生成会话 ID
        const convId = 'task-' + Date.now() + '-' + Math.random().toString(36).slice(2, 8);

        // 初始化 task 状态
        task.value = {
            status: 'executing', goal, steps: [], finalOutput: '', contextUsage: null,
            context: { used: 0, max: 8000 }, conversationId: convId,
            workspacePath: ws.path, totalTokens: 0, elapsedSec: 0
        };
        _currentStep = null;
        taskGoalDraft.value = '';
        // 初始化对话消息
        taskMessages.value = [{ role: 'user', content: goal, steps: [], usage: null, _showSteps: false }];
        localStorage.setItem('lastTaskConvId', convId);

        try {
            // 1. POST 启动任务
            await fetch('/agent/task/start', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ goal, conversation_id: convId, workspace_path: ws.path })
            });

            // 2. 连接 SSE 读取流
            _taskAbortController = new AbortController();
            const sseUrl = `/agent/task/stream?conversationId=${convId}`;
            const resp = await fetch(sseUrl, { signal: _taskAbortController.signal });
            const reader = resp.body.getReader();
            const decoder = new TextDecoder();
            let buffer = '';
            let shouldStop = false;

            while (!shouldStop) {
                const { done, value } = await reader.read();
                if (done) break;
                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split('\n');
                buffer = lines.pop();
                for (const line of lines) {
                    if (!line.startsWith('data: ')) continue;
                    const raw = line.slice(6).trim();
                    if (!raw || raw === '[DONE]') continue;
                    try {
                        const evt = JSON.parse(raw);
                        _handleTaskEvent(evt);
                        if (evt.type === 'done') { shouldStop = true; break; }
                    } catch(e) {}
                }
            }
            // 收到 done 后立即关闭连接，不等后端超时
            reader.cancel();
        } catch (e) {
            if (e.name !== 'AbortError') {
                task.value.status = 'error';
                task.value.finalOutput = '任务启动失败: ' + e.message;
            }
        }
    }

    function _handleTaskEvent(evt) {
        const t = task.value;
        if (!t || t.status === 'idle') return;

        switch (evt.type) {
            case 'text': {
                const text = evt.content || '';
                if (_currentStep) {
                    _currentStep.output = (_currentStep.output || '') + text;
                    if (!_currentStep._titleSet && _currentStep.output.trim().length > 5) {
                        const preview = _currentStep.output.trim().replace(/\n/g, ' ').substring(0, 20);
                        _currentStep.title = preview + (preview.length >= 20 ? '...' : '');
                        _currentStep._titleSet = true;
                    }
                } else {
                    _createStep('分析中...');
                    _currentStep.output = text;
                }
                // 追踪 AI 对话消息
                if (!_currentAiMsg) {
                    _currentAiMsg = { role: 'ai', content: '', steps: [], usage: null, _showSteps: false, timelineSteps: [], _expanded: true };
                    taskMessages.value.push(_currentAiMsg);
                    _syncAiTimeline();
                }
                _currentAiMsg.content += text;
                scrollTaskToBottom();
                break;
            }
            case 'tool_start': {
                if (!_currentStep) {
                    const toolLabel = { list_files: '列出文件', read_file: '读取文件', write_file: '写入文件', edit_file: '编辑文件', grep: '搜索内容', bash: '执行命令', glob_files: '匹配文件', load_skill: '加载技能', loadContent: '加载文件内容' };
                    _createStep(toolLabel[evt.tool] || '调用 ' + (evt.tool || ''));
                }
                const toolItem = {
                    type: 'tool', toolName: evt.tool || '',
                    input: evt.data?.input || '', output: '', status: 'running'
                };
                if (!_currentStep.timeline) _currentStep.timeline = [];
                _currentStep.timeline.push(toolItem);
                _currentStep._activeTool = toolItem;
                // 追踪到 AI 消息（含 input 数据）
                if (_currentAiMsg) {
                    _currentAiMsg.steps.push({ name: evt.tool || '', input: evt.data?.input || null, output: null, status: 'running' });
                }
                break;
            }
            case 'tool_result': {
                if (_currentStep && _currentStep._activeTool) {
                    _currentStep._activeTool.output = evt.data?.content || '';
                    _currentStep._activeTool.status = evt.data?.is_error ? 'error' : 'completed';
                    _currentStep._activeTool = null;
                }
                // 更新 AI 消息的步骤状态 + 输出
                if (_currentAiMsg && _currentAiMsg.steps.length > 0) {
                    const lastStep = _currentAiMsg.steps[_currentAiMsg.steps.length - 1];
                    if (lastStep.status === 'running') {
                        lastStep.status = evt.data?.is_error ? 'error' : 'success';
                        lastStep.output = evt.data?.content || '';
                    }
                }
                break;
            }
            case 'llm_input': {
                if (!_currentStep) _createStep('LLM 调用 #' + (evt.data?.turn || ''));
                if (_currentStep && evt.data) {
                    if (!_currentStep.llmMonitor) _currentStep.llmMonitor = { input: null, output: null };
                    _currentStep.llmMonitor.input = evt.data;
                }
                // 捕获上下文用量
                if (evt.data?.context_usage) {
                    t.contextUsage = evt.data.context_usage;
                    t.context.used = evt.data.context_usage.total || 0;
                }
                break;
            }
            case 'llm_output': {
                if (_currentStep && evt.data) {
                    if (!_currentStep.llmMonitor) _currentStep.llmMonitor = { input: null, output: null };
                    _currentStep.llmMonitor.output = evt.data;
                }
                break;
            }
            case 'message_complete': {
                if (_currentStep) {
                    _currentStep.status = 'success';
                    if (evt.usage) {
                        _currentStep.usage = evt.usage;
                    }
                }
                _currentStep = null;
                // 保存 usage 到 AI 消息
                if (_currentAiMsg && evt.usage) {
                    _currentAiMsg.usage = evt.usage;
                }
                break;
            }
            case 'error': {
                if (_currentStep) {
                    _currentStep.status = 'error';
                    if (!_currentStep.timeline) _currentStep.timeline = [];
                    _currentStep.timeline.push({ type: 'error', message: evt.content || '未知错误' });
                } else {
                    _createStep('错误');
                    _currentStep.status = 'error';
                    _currentStep.output = evt.content || '';
                }
                t.status = 'error';
                t.finalOutput = evt.content || '任务执行出错';
                break;
            }
            case 'info': {
                if (!_currentStep) _createStep(evt.content || '处理中');
                break;
            }
            case 'done': {
                t.status = 'done';
                if (_currentStep) {
                    _currentStep.status = 'success';
                }
                // 读取任务级统计
                if (evt.total_input_tokens || evt.total_output_tokens) {
                    t.totalTokens = (evt.total_input_tokens || 0) + (evt.total_output_tokens || 0);
                }
                if (evt.elapsed_sec) {
                    t.elapsedSec = evt.elapsed_sec;
                }
                const lastStepWithOutput = [...t.steps].reverse().find(s => s.output && s.output.trim());
                t.finalOutput = lastStepWithOutput ? lastStepWithOutput.output : (t.finalOutput || '任务已完成');
                _currentStep = null;
                _currentAiMsg = null;
                taskInputSending.value = false;
                _taskAbortController = null;
                scrollTaskToBottom();
                break;
            }
        }
    }

    function _createStep(title) {
        const step = {
            id: 'step-' + Date.now() + '-' + Math.random().toString(36).slice(2, 6),
            title, status: 'running', collapsed: false, showTimeline: false,
            timeline: [], output: '', usage: null, _titleSet: false, llmMonitor: null
        };
        task.value.steps.push(step);
        _currentStep = step;
        _syncAiTimeline();
    }

    // 让当前 AI 消息“领养”本轮创建的详细步骤（工具/LLM 明细），供 tm-timeline 气泡渲染
    function _syncAiTimeline() {
        if (!_currentAiMsg) return;
        if (!_currentAiMsg.timelineSteps) _currentAiMsg.timelineSteps = [];
        for (const s of task.value.steps) {
            if (!_currentAiMsg.timelineSteps.includes(s)) _currentAiMsg.timelineSteps.push(s);
        }
    }

    // 气泡里只展示有实质内容的步骤（工具调用 / LLM 明细）；纯叙述文本以 msg.content 呈现
    function richStepsOf(msg) {
        return (msg.timelineSteps || []).filter(s => s && ((s.timeline && s.timeline.length) || s.llmMonitor));
    }

    function pauseTask() { task.value.status = 'paused'; }
    function resumeTask() { task.value.status = 'executing'; }

    function stopTask() {
        if (_taskAbortController) { _taskAbortController.abort(); _taskAbortController = null; }
        // 通知后端停止
        const convId = task.value.conversationId;
        if (convId) {
            fetch('/agent/task/stop', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ conversation_id: convId })
            }).catch(() => {});
        }
        task.value.status = 'done';
        task.value.finalOutput = '任务已终止';
    }

    function resetTask() {
        if (_taskAbortController) { _taskAbortController.abort(); _taskAbortController = null; }
        _currentStep = null;
        _currentAiMsg = null;
        task.value = { status: 'idle', goal: '', steps: [], finalOutput: '', context: { used: 0, max: 8000 }, contextUsage: null, totalTokens: 0, elapsedSec: 0 };
        taskGoalDraft.value = '';
        taskMessages.value = [];
        taskInput.value = '';
        taskInputSending.value = false;
        localStorage.removeItem('lastTaskConvId');
    }

    // 上下文压缩：调后端生成摘要，更新前端仪表数值
    async function compressContext() {
        const convId = task.value.conversationId;
        if (!convId) return;
        const before = task.value.contextUsage?.total || 0;
        try {
            const resp = await fetch('/agent/task/compress', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ conversation_id: convId })
            });
            const data = await resp.json();
            if (data.error) {
                console.error('上下文压缩失败:', data.error);
                return;
            }
            // 更新前端上下文仪表数值
            if (data.ctx_usage) {
                task.value.contextUsage = data.ctx_usage;
                task.value.context.used = data.after_tokens || 0;
            }
            // 插入一条系统消息通知用户压缩完成
            if (data.summary_preview) {
                taskMessages.value.push({
                    role: 'ai',
                    content: `[上下文已压缩] ${data.before_tokens} → ${data.after_tokens} tokens\n摘要预览: ${data.summary_preview}`,
                    steps: [], usage: null, _showSteps: false, timelineSteps: [], _expanded: false,
                });
                scrollTaskToBottom();
            }
        } catch (e) {
            console.error('上下文压缩失败:', e);
        }
    }

    async function toggleMemoryAgent() {
        const convId = task.value.conversationId;
        if (!convId) return;
        const newVal = !useMemoryAgent.value;
        try {
            await fetch('/agent/task/memory-agent-toggle', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ conversation_id: convId, enabled: newVal })
            });
            useMemoryAgent.value = newVal;
        } catch (e) {
            console.error('切换记忆模式失败:', e);
        }
    }

    function scrollTaskToBottom() {
        nextTick(() => {
            const el = tmBody.value || tmChatArea.value;
            if (el) el.scrollTop = el.scrollHeight;
        });
    }

    async function sendTaskMessage() {
        const text = taskInput.value.trim();
        if (!text || taskInputSending.value) return;
        const convId = task.value.conversationId;
        if (!convId) return;

        // 添加用户消息
        taskMessages.value.push({ role: 'user', content: text, steps: [], usage: null, _showSteps: false });
        taskInput.value = '';
        taskInputSending.value = true;
        scrollTaskToBottom();

        // 重置本轮步骤追踪
        _currentStep = null;
        _currentAiMsg = null;

        // 先用当前的 AbortController 停止旧 SSE 连接
        if (_taskAbortController) {
            _taskAbortController.abort();
            _taskAbortController = null;
        }

        try {
            // 1. 等后端停止旧任务（后端会等旧任务真正结束再返回）
            await fetch('/agent/task/stop', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ conversation_id: convId })
            }).catch(() => {});

            task.value.status = 'executing';
            task.value.steps = [];

            // 2. 等后端启动新任务（后端会先清理旧 Redis Stream）
            await fetch('/agent/task/start', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ goal: text, conversation_id: convId, workspace_path: task.value.workspacePath || '.' })
            });

            // 3. 连接 SSE 读取新任务流（此时旧流已清理干净）
            _taskAbortController = new AbortController();
            const sseUrl = `/agent/task/stream?conversationId=${convId}`;
            const resp = await fetch(sseUrl, { signal: _taskAbortController.signal });
            const reader = resp.body.getReader();
            const decoder = new TextDecoder();
            let buffer = '';
            let shouldStop = false;

            while (!shouldStop) {
                const { done, value } = await reader.read();
                if (done) break;
                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split('\n');
                buffer = lines.pop();
                for (const line of lines) {
                    if (!line.startsWith('data: ')) continue;
                    const raw = line.slice(6).trim();
                    if (!raw || raw === '[DONE]') continue;
                    try {
                        const evt = JSON.parse(raw);
                        _handleTaskEvent(evt);
                        if (evt.type === 'done') { shouldStop = true; break; }
                    } catch(e) {}
                }
            }
            reader.cancel();
        } catch (e) {
            if (e.name !== 'AbortError') {
                taskInputSending.value = false;
            }
        }
    }

    async function loadTaskList() {
        taskListLoading.value = true;
        try {
            const resp = await fetch('/agent/task/list');
            const data = await resp.json();
            taskList.value = data.tasks || [];
        } catch (e) { taskList.value = []; }
        taskListLoading.value = false;
    }

    function loadTaskRecord(convId) {
        currentChatId.value = null;
        modeType.value = 'task';
        task.value = { status: 'done', goal: '加载中...', steps: [], finalOutput: '', context: { used: 0, max: 8000 }, conversationId: convId, workspacePath: '' };
        taskMessages.value = [];
        fetch('/agent/task/load?conversationId=' + encodeURIComponent(convId))
            .then(r => r.json())
            .then(data => {
                const meta = data.meta || {};
                const msgs = data.messages || [];
                // 从元数据恢复状态：把服务端保存的 ctx_* 上下文窗口明细同步到仪表数值
                // （与实时 llm_input 携带的 context_usage 口径一致；老任务无 ctx_* 时回退累计 usage）
                task.value = {
                    status: meta.status || 'done',
                    goal: meta.goal || '',
                    steps: [],
                    finalOutput: '',
                    context: { used: 0, max: 8000 },
                    contextUsage: null,
                    conversationId: convId,
                    workspacePath: meta.workspace_path || '',
                    totalTokens: (meta.total_input_tokens || 0) + (meta.total_output_tokens || 0),
                    elapsedSec: meta.duration_sec || 0,
                };
                applyCtxMeta(meta);
                // 同步记忆模式开关
                useMemoryAgent.value = !!meta.use_memory_agent;
                // 同步徽标：当前任务的目录取自后端 meta.workspace_path
                const wsPath = meta.workspace_path || '';
                if (wsPath) {
                    const exWs = workspaces.value.find(w => w.path === wsPath);
                    if (exWs) {
                        selectedWorkspaceId.value = exWs.id;
                    } else {
                        const nid = wsPath;
                        workspaces.value.push({ id: nid, name: wsPath.split(/[\\/]/).filter(Boolean).pop() || wsPath, path: wsPath });
                        selectedWorkspaceId.value = nid;
                        persistWorkspaceSelect(wsPath);
                    }
                }
                // 从消息恢复 goal（如果元数据没有）
                if (!task.value.goal) {
                    const userMsg = msgs.find(m => m.type === 'user');
                    if (userMsg) task.value.goal = userMsg.content || '未命名任务';
                }
                // 构建对话消息
                const loadedMsgs = [];
                for (const m of msgs) {
                    if (m.type === 'user') {
                        loadedMsgs.push({ role: 'user', content: m.content || '', steps: [], usage: null, _showSteps: false });
                    } else if (m.type === 'assistant') {
                        let text = '';
                        if (Array.isArray(m.content)) {
                            text = m.content.filter(b => b.type === 'text').map(b => b.text).join('');
                        }
                        if (text) loadedMsgs.push({ role: 'ai', content: text, steps: [], usage: null, _showSteps: false });
                    }
                }
                taskMessages.value = loadedMsgs;
                // finalOutput
                const assistantMsgs = msgs.filter(m => m.type === 'assistant');
                const texts = assistantMsgs.map(m => {
                    if (Array.isArray(m.content)) {
                        return m.content.filter(b => b.type === 'text').map(b => b.text).join('');
                    }
                    return '';
                }).filter(Boolean);
                task.value.finalOutput = texts.length > 0 ? texts.join('\n\n') : '共 ' + msgs.length + ' 条消息';
            });
    }

    async function deleteTaskRecord(convId) {
        try {
            await fetch('/agent/task/delete', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ conversation_id: convId })
            });
            // 刷新列表
            await loadTaskList();
            // 如果当前显示的是被删除的任务，重置面板
            if (task.value.conversationId === convId) resetTask();
        } catch (e) { console.error('删除任务失败:', e); }
    }

    function toggleStepTimeline(stepId) {
        const step = task.value.steps.find(s => s.id === stepId);
        if (step) step.showTimeline = !step.showTimeline;
    }
    function closeAllPopups() { showAgentDrawer.value = false; showWorkspaceMenu.value = false; }

    // ===== 初始化：只加载一次会话列表 =====
    onMounted(async () => {
        APP_UTILS.setupMarkdown();
        await loadWorkspaces();
        await loadChatsFromStorage();
        // 有历史会话则选第一个，没有则新建
        if (chatList.value.length > 0) {
            await selectChat(chatList.value[0].id);
        } else {
            createNewChat();
        }

        // 恢复上次的任务状态
        const lastTaskConvId = localStorage.getItem('lastTaskConvId');
        if (lastTaskConvId) {
            loadTaskRecord(lastTaskConvId);
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
        document.addEventListener('click', (e) => {
            if (ctxTooltipVisible.value && !(e.target.closest && e.target.closest('.tm-context-meter'))) {
                ctxTooltipVisible.value = false;
            }
        });
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
        // 点侧栏会话 → 切回对话页面（若当前停留在任务全屏视图则退出）
        switchToChatMode();
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
        currentStatus.value = status;
        if (status === 'active') {
            await loadChatsFromStorage();
        } else if (status === 'archived') {
            await loadArchivedChatsFromStorage();
        } else if (status === 'tasks') {
            await loadTaskList();
        }
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
</script>

<template>
    <div id="app">
        <!-- 科技感光晕效果 -->
        <div class="glow-effect glow-effect-1"></div>
        <div class="glow-effect glow-effect-2"></div>
        <div class="glow-effect glow-effect-3"></div>

        <div class="container">
            <!-- 左侧会话列表 -->
            <div class="sidebar">
                <div class="sidebar-header">
                    <div class="app-title">
                        <span class="logo-icon">🌱</span>
                        <span class="title-text">Nemo</span>
                    </div>
                    <button class="new-chat-btn" @click="createNewChat">
                        <i class="fas fa-plus"></i>
                        <span>新对话</span>
                    </button>
                    <!-- 归档/活跃切换标签 -->
                    <div class="tab-switch">
                        <span :class="['tab', { active: currentStatus === 'active' }]"
                              @click="switchTab('active')">对话</span>
                        <span :class="['tab', { active: currentStatus === 'archived' }]"
                              @click="switchTab('archived')">归档</span>
                        <span :class="['tab', { active: currentStatus === 'tasks' }]"
                              @click="switchTab('tasks')">任务</span>
                    </div>
                </div>
                <div class="chat-list" v-if="currentStatus !== 'tasks'">
                    <div v-for="chat in filteredChatList" :key="chat.id"
                         :class="['chat-item', { active: currentChatId === chat.id }]"
                         @click="selectChat(chat.id)">
                        <!-- 标题显示/编辑 -->
                        <span v-if="editingChatId !== chat.id"
                              class="chat-title"
                              @dblclick="startRename(chat.id, $event)">
                            {{ chat.title }}
                        </span>
                        <input v-else
                               type="text"
                               class="rename-input"
                               :value="chat.title"
                               @blur="commitRename(chat.id, $event)"
                               @keydown.enter="commitRename(chat.id, $event)"
                               @keydown.escape="cancelRename"
                               ref="renameInput">
                        <!-- 操作按钮 -->
                        <span class="chat-actions">
                            <button v-if="currentStatus === 'active'"
                                    class="action-btn menu-btn"
                                    title="更多操作"
                                    @click.stop="toggleMenu(chat.id)">
                                <i class="fas fa-ellipsis-v"></i>
                            </button>
                            <button v-if="currentStatus === 'archived'"
                                    class="action-btn restore-btn"
                                    title="恢复"
                                    @click.stop="restoreChat(chat.id)">
                                <i class="fas fa-undo"></i>
                            </button>
                            <button v-if="currentStatus === 'archived'"
                                    class="action-btn delete-btn"
                                    title="删除"
                                    @click.stop="openDeleteModal(chat.id)">
                                <i class="fas fa-trash-alt"></i>
                            </button>
                        </span>
                        <!-- 下拉菜单（活跃会话） -->
                        <div v-if="currentStatus === 'active' && menuOpenId === chat.id"
                             class="dropdown-menu"
                             @click.stop>
                            <button class="dropdown-item" @click.stop="startRenameFromMenu(chat.id)">
                                <i class="fas fa-edit"></i> 修改标题
                            </button>
                            <button class="dropdown-item archive-item" @click.stop="archiveChat(chat.id)">
                                <i class="fas fa-archive"></i> 归档
                            </button>
                        </div>
                    </div>
                </div>

                <!-- 任务历史列表 -->
                <div v-if="currentStatus === 'tasks'" class="chat-list">
                    <div class="task-list-header">
                        <button class="tm-sidebar-new-btn" @click="resetTask">
                            <i class="fas fa-plus"></i> 新建任务
                        </button>
                    </div>
                    <div v-if="taskListLoading" style="padding:20px;text-align:center;color:var(--text-muted);font-size:12px;">加载中...</div>
                    <div v-else-if="taskList.length === 0" style="padding:30px 16px;text-align:center;color:var(--text-muted);font-size:13px;">
                        <div style="font-size:28px;margin-bottom:8px;">📋</div>
                        暂无任务记录
                    </div>
                    <div v-for="task in taskList" :key="task.conversation_id"
                         class="chat-item" @click="loadTaskRecord(task.conversation_id)">
                        <span class="chat-title" :title="task.goal" style="flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">
                            <i class="fas fa-cog" style="font-size:11px;margin-right:4px;color:var(--task-color);"></i>{{ task.goal }}
                        </span>
                        <span style="font-size:10px;color:var(--text-muted);white-space:nowrap;">{{ task.message_count }}条</span>
                        <button @click.stop="deleteTaskRecord(task.conversation_id)" title="删除"
                                style="background:none;border:none;color:var(--text-muted);cursor:pointer;font-size:11px;padding:2px 4px;margin-left:2px;">
                            <i class="fas fa-times"></i>
                        </button>
                    </div>
                </div>

                <div class="sidebar-footer">
                    <div class="model-info">
                        <i class="fas fa-link"></i>
                        <span>{{ backendUrl }}</span>
                    </div>
                    <div style="margin-top:10px;text-align:center;">
                        <a href="/blueprint.html" style="display:inline-flex;align-items:center;gap:6px;color:var(--primary-light);text-decoration:none;font-size:13px;padding:6px 10px;border:1px solid var(--border-color);border-radius:8px;transition:all .2s;">
                            🧩 模型配置 / 蓝图
                        </a>
                    </div>
                </div>
            </div>

            <!-- 侧边栏拖拽调整宽度手柄 -->
            <div class="sidebar-resize-handle" id="sidebarResizeHandle"></div>

            <!-- 右侧聊天区域 -->
            <div class="main-content">
                <!-- 顶部装饰 -->
                <div class="top-decoration">
                    <div class="decoration-line"></div>
                </div>

                <!-- 消息列表 -->
                <div class="messages-container" ref="messagesContainer" @click="closeAllPopups">

                    <!-- ====== 任务创建面板（task模式且空闲时显示） ====== -->
                    <div v-if="modeType === 'task' && task.status === 'idle'" class="tm-console" style="margin-bottom:12px;">
                        <div class="tm-empty">
                            <div class="tm-empty-icon">🧭</div>
                            <h2>布置一个任务</h2>
                            <p>描述目标并选择工作区，Nemo会自主规划、调用工具完成任务</p>
                            <textarea class="tm-goal-input" v-model="taskGoalDraft"
                                placeholder="例如：帮我梳理 /project 目录下的接口文档，并生成一份 API 变更清单"></textarea>
                            <div class="tm-templates">
                                <button class="tm-template-chip" v-for="(t, tIdx) in taskTemplates" :key="tIdx"
                                        @click="taskGoalDraft = t">{{ t }}</button>
                            </div>
                            <div class="tm-empty-workspace-row">
                                <span>工作区：</span>
                                <div style="position:relative;">
                                    <button class="tm-workspace-select-btn" @click.stop="showWorkspaceMenu = !showWorkspaceMenu">
                                        <i class="fas fa-folder"></i>
                                        {{ selectedWorkspace ? selectedWorkspace.name : '请选择工作区' }}
                                        <i class="fas fa-chevron-down"></i>
                                    </button>
                                    <div class="tm-workspace-menu" v-if="showWorkspaceMenu" @click.stop>
                                        <div class="tm-workspace-menu-item" v-for="ws in workspaces" :key="ws.id"
                                             :class="{ active: selectedWorkspaceId === ws.id }"
                                             @click="selectWorkspace(ws.id)">
                                            <i class="fas fa-folder"></i>
                                            <div style="flex:1;min-width:0;">
                                                <div class="tm-wmi-name">{{ ws.name }}</div>
                                                <div class="tm-wmi-path">{{ ws.path }}</div>
                                            </div>
                                            <i class="fas fa-pen" style="font-size:10px;color:var(--text-muted);cursor:pointer;margin-left:4px;" @click.stop="editWorkspace(ws)" title="修改路径"></i>
                                            <i class="fas fa-times" style="font-size:10px;color:var(--text-muted);cursor:pointer;margin-left:4px;" @click.stop="removeWorkspace(ws.id)" title="移除"></i>
                                        </div>
                                        <div class="tm-workspace-menu-item tm-add-new" @click="openDirBrowser">
                                            <i class="fas fa-plus"></i> 连接新工作区
                                        </div>
                                    </div>
                                </div>
                            </div>
                            <button class="tm-start-btn" :disabled="!taskGoalDraft.trim() || !selectedWorkspaceId" @click="startTask">
                                <i class="fas fa-play"></i> 开始任务
                            </button>
                        </div>
                    </div>

                    <!-- ====== 任务面板（运行/完成时显示） — 全屏布局 ====== -->
                    <div v-if="modeType === 'task' && task.status !== 'idle'" class="tm-console tm-fullscreen">

                        <!-- 运行/完成态 -->
                            <div class="tm-header">
                                <div class="tm-header-main">
                                    <div class="tm-goal-row">
                                        <span class="tm-status-pill" :class="task.status">{{ taskStatusLabel }}</span>
                                        <template v-if="!editingTaskGoal">
                                            <div class="tm-goal-text" :title="task.goal">{{ task.goal }}</div>
                                            <button class="tm-edit-goal-btn" @click="editingTaskGoal = true" title="编辑任务目标">
                                                <i class="fas fa-pen"></i>
                                            </button>
                                        </template>
                                        <template v-else>
                                            <input class="tm-goal-edit-input" v-model="task.goal"
                                                   @keydown.enter="editingTaskGoal = false"
                                                   @blur="editingTaskGoal = false">
                                        </template>
                                    </div>
                                    <div class="tm-controls">
                                        <button class="tm-ctrl-btn" v-if="task.status === 'executing'" @click="pauseTask" title="暂停任务">
                                            <i class="fas fa-pause"></i>
                                        </button>
                                        <button class="tm-ctrl-btn" v-if="task.status === 'paused'" @click="resumeTask" title="继续任务">
                                            <i class="fas fa-play"></i>
                                        </button>
                                        <button class="tm-ctrl-btn tm-danger" @click="stopTask" title="终止任务">
                                            <i class="fas fa-stop"></i>
                                        </button>
                                    </div>
                                </div>
                                <div class="tm-meta-bar">
                                    <div class="tm-meta-item tm-context-meter"
                                         title="点击查看上下文用量明细"
                                         @click="toggleCtxTooltip($event)">
                                        <i class="fas fa-microchip"></i>
                                        <div class="tm-context-track">
                                            <div class="tm-context-fill" :class="taskContextLevelClass"
                                                 :style="{ width: taskContextPercent + '%' }"></div>
                                        </div>
                                        <span class="tm-context-text">{{ taskContextPercent }}%</span>
                                        <span class="tm-context-raw">{{ formatK(task.context.used) }}/{{ formatK(task.context.max) }}</span>
                                        <!-- 上下文明细悬浮窗 -->
                                        <div v-if="task.contextUsage" class="tm-context-detail"
                                             :style="ctxTooltipStyle"
                                             v-show="ctxTooltipVisible">
                                            <div class="tm-ctx-detail-head"><span class="tm-ctx-detail-title">上下文窗口用量明细</span><span class="tm-ctx-close" @click.stop="hideCtxTooltip()" title="关闭">×</span></div>
                                            <div class="tm-ctx-detail-bar">
                                                <div class="tm-ctx-bar-seg system" :style="{ width: ctxBarWidth('system_prompt') }"></div>
                                                <div class="tm-ctx-bar-seg history" :style="{ width: ctxBarWidth('history') }"></div>
                                                <div class="tm-ctx-bar-seg tools" :style="{ width: ctxBarWidth('tool_definitions') }"></div>
                                                <div class="tm-ctx-bar-seg results" :style="{ width: ctxBarWidth('tool_results') }"></div>
                                                <div class="tm-ctx-bar-seg input" :style="{ width: ctxBarWidth('current_input') }"></div>
                                            </div>
                                            <div class="tm-ctx-detail-row">
                                                <span class="tm-ctx-detail-label"><span class="tm-ctx-dot system"></span>系统提示</span>
                                                <span class="tm-ctx-detail-val">{{ formatK(task.contextUsage.system_prompt) }}</span>
                                                <span class="tm-ctx-detail-pct">{{ ctxPct('system_prompt') }}%</span>
                                            </div>
                                            <div class="tm-ctx-detail-row">
                                                <span class="tm-ctx-detail-label"><span class="tm-ctx-dot history"></span>对话历史</span>
                                                <span class="tm-ctx-detail-val">{{ formatK(task.contextUsage.history) }}</span>
                                                <span class="tm-ctx-detail-pct">{{ ctxPct('history') }}%</span>
                                            </div>
                                            <div class="tm-ctx-detail-row">
                                                <span class="tm-ctx-detail-label"><span class="tm-ctx-dot tools"></span>工具定义</span>
                                                <span class="tm-ctx-detail-val">{{ formatK(task.contextUsage.tool_definitions) }}</span>
                                                <span class="tm-ctx-detail-pct">{{ ctxPct('tool_definitions') }}%</span>
                                            </div>
                                            <div class="tm-ctx-detail-row">
                                                <span class="tm-ctx-detail-label"><span class="tm-ctx-dot results"></span>工具结果</span>
                                                <span class="tm-ctx-detail-val">{{ formatK(task.contextUsage.tool_results) }}</span>
                                                <span class="tm-ctx-detail-pct">{{ ctxPct('tool_results') }}%</span>
                                            </div>
                                            <div class="tm-ctx-detail-row">
                                                <span class="tm-ctx-detail-label"><span class="tm-ctx-dot input"></span>当前输入</span>
                                                <span class="tm-ctx-detail-val">{{ formatK(task.contextUsage.current_input) }}</span>
                                                <span class="tm-ctx-detail-pct">{{ ctxPct('current_input') }}%</span>
                                            </div>
                                            <div class="tm-ctx-detail-total">
                                                <span>总计</span>
                                                <span>{{ formatK(task.contextUsage.total) }} tokens</span>
                                            </div>
                                        </div>
                                    </div>
                                    <button class="tm-meta-item tm-ctx-compress-btn"
                                            v-if="task.contextUsage && task.contextUsage.total > 0"
                                            @click.stop="compressContext"
                                            title="压缩上下文窗口，释放 token 空间">
                                        <i class="fas fa-compress-alt"></i>
                                        <span>压缩上下文</span>
                                    </button>
                                    <button class="tm-meta-item tm-memory-agent-btn"
                                            :class="{ active: useMemoryAgent }"
                                            @click.stop="toggleMemoryAgent"
                                            :title="useMemoryAgent ? '记忆子Agent已启用，点击关闭' : '启用记忆子Agent，从历史记忆中检索信息'">
                                        <i class="fas fa-brain"></i>
                                        <span>{{ useMemoryAgent ? '记忆Agent: 开' : '记忆Agent: 关' }}</span>
                                    </button>
                                    <div class="tm-meta-item tm-stats-badge"
                                         v-if="task.totalTokens > 0 || task.elapsedSec > 0"
                                         title="任务统计">
                                        <i class="fas fa-chart-bar"></i>
                                        <span v-if="task.totalTokens > 0">{{ formatK(task.totalTokens) }} tokens</span>
                                        <span v-if="task.totalTokens > 0 && task.elapsedSec > 0" class="tm-stats-sep">·</span>
                                        <span v-if="task.elapsedSec > 0">{{ task.elapsedSec }}s</span>
                                    </div>
                                    <div class="tm-meta-item tm-permission-badge" title="所有工具调用将自动执行">
                                        <i class="fas fa-unlock"></i>
                                        <span>权限模式：全部允许</span>
                                        <span class="tm-upcoming-tag">自定义策略即将开放</span>
                                    </div>
                                    <div class="tm-meta-item tm-workspace-badge" @click.stop="showWorkspaceMenu = !showWorkspaceMenu">
                                        <i class="fas fa-folder-open"></i>
                                        <span>{{ selectedWorkspace ? selectedWorkspace.name : '未选择' }}</span>
                                        <code class="tm-workspace-path" v-if="selectedWorkspace">{{ selectedWorkspace.path }}</code>
                                        <i class="fas fa-chevron-down"></i>
                                        <div class="tm-workspace-menu" v-if="showWorkspaceMenu" @click.stop>
                                            <div class="tm-workspace-menu-item" v-for="ws in workspaces" :key="ws.id"
                                                 :class="{ active: selectedWorkspaceId === ws.id }"
                                                 @click="selectWorkspace(ws.id)">
                                                <i class="fas fa-folder"></i>
                                                <div>
                                                    <div class="tm-wmi-name">{{ ws.name }}</div>
                                                    <div class="tm-wmi-path">{{ ws.path }}</div>
                                                </div>
                                            </div>
                                            <div class="tm-workspace-menu-item tm-add-new" @click="openDirBrowser">
                                                <i class="fas fa-plus"></i> 连接新工作区
                                            </div>
                                        </div>
                                    </div>
                                    <button class="tm-meta-item tm-file-tree-toggle" :class="{ active: showFileTree }"
                                            @click.stop="showFileTree = !showFileTree">
                                        <i class="fas fa-sitemap"></i> 工作区文件
                                    </button>
                                </div>
                            </div>
                            <div class="tm-body" ref="tmBody">
                                <!-- 聊天消息区域（对话式） -->
                                <div class="tm-chat-area" v-if="taskMessages.length > 0" ref="tmChatArea">
                                    <div v-for="(msg, mIdx) in taskMessages" :key="mIdx" class="tm-msg" :class="msg.role">
                                        <div class="tm-msg-avatar">
                                            <span v-if="msg.role === 'user'">👤</span>
                                            <span v-else>🤖</span>
                                        </div>
                                        <div class="tm-msg-body">
                                            <!-- 用户消息 -->
                                            <div v-if="msg.role === 'user'" class="tm-msg-content">{{ msg.content }}</div>

                                            <!-- AI 消息：结构化卡片 -->
                                        <div v-else-if="msg.role === 'ai' && (msg.content || richStepsOf(msg).length > 0)" class="tm-timeline tm-tl-bubble">
                                            <div class="tm-tl-head" @click="msg._expanded = !(msg._expanded !== false)">
                                                <span class="tm-tl-title">🤖 模型回复 #{{ mIdx }}</span>
                                                <span v-if="msg.usage && msg.usage.total_tokens" class="tm-msg-card-tokens">{{ msg.usage.total_tokens }} tokens</span>
                                                <i :class="['fas', msg._expanded !== false ? 'fa-chevron-down' : 'fa-chevron-right']"></i>
                                            </div>
                                            <template v-if="msg._expanded !== false">
                                                <div v-for="(step, si) in richStepsOf(msg)" :key="step.id" class="tm-step tm-tl-step">
                                                    <div class="tm-step-rail">
                                                        <div class="tm-step-dot" :class="step.status">
                                                            <i v-if="step.status === 'running'" class="fas fa-spinner fa-spin"></i>
                                                            <i v-else-if="step.status === 'success'" class="fas fa-check"></i>
                                                            <i v-else-if="step.status === 'error'" class="fas fa-times"></i>
                                                            <span v-else>{{ si + 1 }}</span>
                                                        </div>
                                                        <div class="tm-step-line"></div>
                                                    </div>
                                                    <div class="tm-step-card">
                                                        <div class="tm-step-card-header" @click="step.collapsed = !step.collapsed">
                                                            <span>{{ si + 1 }}. {{ step.title }}</span>
                                                            <i :class="['fas', step.collapsed ? 'fa-chevron-right' : 'fa-chevron-down']"></i>
                                                        </div>
                                                        <div class="tm-step-card-body" v-show="!step.collapsed">
                                                <div v-if="step.timeline && step.timeline.length > 0" class="timeline-section">
                                                    <div class="timeline-header" @click="toggleStepTimeline(step.id)">
                                                        <div class="timeline-icon-wrapper">
                                                            <i class="fas fa-brain timeline-main-icon"></i>
                                                        </div>
                                                        <span class="timeline-title">思考与工具调用</span>
                                                        <i :class="['fas', step.showTimeline ? 'fa-chevron-down' : 'fa-chevron-right']"></i>
                                                    </div>
                                                    <div v-show="step.showTimeline" class="timeline-content">
                                                        <div v-for="(item, iIdx) in step.timeline" :key="iIdx" class="timeline-item">
                                                            <div class="timeline-dot" :class="item.type === 'tool' ? item.status : item.type"></div>
                                                            <div class="timeline-item-body">
                                                                <template v-if="item.type === 'thinking'">
                                                                    <div class="timeline-thinking">{{ item.content }}</div>
                                                                </template>
                                                                <template v-else-if="item.type === 'error'">
                                                                    <div class="timeline-error">
                                                                        <i class="fas fa-exclamation-triangle"></i>
                                                                        <span>{{ item.message }}</span>
                                                                    </div>
                                                                </template>
                                                                <template v-else>
                                                                    <div class="timeline-tool">
                                                                        <i class="fas fa-wrench timeline-tool-icon"></i>
                                                                        <span class="timeline-tool-name">{{ item.toolName }}</span>
                                                                        <span class="timeline-tool-status" :class="item.status">
                                                                            <i v-if="item.status === 'running'" class="fas fa-spinner fa-spin"></i>
                                                                            <i v-else-if="item.status === 'completed'" class="fas fa-check"></i>
                                                                            <i v-else class="fas fa-times"></i>
                                                                        </span>
                                                                    </div>
                                                                    <div v-if="item.input !== undefined || item.output !== undefined" class="tm-tool-io">
                                                                        <div class="tm-tool-io-col">
                                                                            <div class="tm-tool-io-label">输入参数</div>
                                                                            <pre class="tm-tool-io-content">{{ formatToolIO(item.input) }}</pre>
                                                                        </div>
                                                                        <div class="tm-tool-io-col">
                                                                            <div class="tm-tool-io-label">输出结果</div>
                                                                            <pre class="tm-tool-io-content">{{ item.output || '（等待返回...）' }}</pre>
                                                                        </div>
                                                                    </div>
                                                                </template>
                                                            </div>
                                                        </div>
                                                    </div>
                                                </div>
                                                <!-- LLM 输入输出监控 -->
                                                <div v-if="step.llmMonitor" class="llm-monitor-section">
                                                    <div class="llm-monitor-header" @click="step._showLlmMonitor = !step._showLlmMonitor">
                                                        <div class="llm-monitor-icon-wrapper">
                                                            <i class="fas fa-server llm-monitor-icon"></i>
                                                        </div>
                                                        <span class="llm-monitor-title">LLM 调用 #{{ step.llmMonitor.input?.turn || step.llmMonitor.output?.turn || '?' }}</span>
                                                        <span v-if="step.llmMonitor.output?.usage" class="llm-monitor-tokens">
                                                            {{ (step.llmMonitor.output.usage.input_tokens || 0) + (step.llmMonitor.output.usage.output_tokens || 0) }} tokens
                                                        </span>
                                                        <i :class="['fas', step._showLlmMonitor ? 'fa-chevron-down' : 'fa-chevron-right']"></i>
                                                    </div>
                                                    <div v-show="step._showLlmMonitor" class="llm-monitor-content">
                                                        <!-- 输入消息列表 -->
                                                        <div v-if="step.llmMonitor.input?.messages" class="llm-monitor-block">
                                                            <div class="llm-monitor-block-title">
                                                                <i class="fas fa-arrow-up"></i> 输入消息
                                                                <span class="llm-monitor-badge">{{ step.llmMonitor.input.messages.length }} 条</span>
                                                            </div>
                                                            <div class="llm-monitor-messages">
                                                                <div v-for="(msg, mIdx) in step.llmMonitor.input.messages" :key="mIdx"
                                                                     class="llm-monitor-msg" :class="'role-' + msg.role">
                                                                    <div class="llm-monitor-msg-role">
                                                                        <i v-if="msg.role === 'user'" class="fas fa-user"></i>
                                                                        <i v-else-if="msg.role === 'assistant'" class="fas fa-robot"></i>
                                                                        <i v-else-if="msg.role === 'tool'" class="fas fa-wrench"></i>
                                                                        <i v-else class="fas fa-cog"></i>
                                                                        <span>{{ msg.role === 'user' ? '用户' : msg.role === 'assistant' ? '助手' : msg.role === 'tool' ? '工具结果' : '系统' }}</span>
                                                                        <span v-if="msg.tool_calls?.length" class="llm-monitor-tool-chips">
                                                                            <span v-for="(tc, tIdx) in msg.tool_calls" :key="tIdx" class="llm-monitor-tool-chip">{{ tc.name }}</span>
                                                                        </span>
                                                                        <span v-if="msg.is_error" class="llm-monitor-error-badge">错误</span>
                                                                    </div>
                                                                    <pre class="llm-monitor-msg-preview">{{ msg.preview || '(空)' }}</pre>
                                                                </div>
                                                            </div>
                                                        </div>
                                                        <!-- 输出内容 -->
                                                        <div v-if="step.llmMonitor.output" class="llm-monitor-block">
                                                            <div class="llm-monitor-block-title">
                                                                <i class="fas fa-arrow-down"></i> 模型输出
                                                            </div>
                                                            <div v-if="step.llmMonitor.output.thinking" class="llm-monitor-thinking">
                                                                <div class="llm-monitor-thinking-label"><i class="fas fa-brain"></i> 思考过程</div>
                                                                <pre class="llm-monitor-thinking-content">{{ step.llmMonitor.output.thinking }}</pre>
                                                            </div>
                                                            <div v-if="step.llmMonitor.output.text" class="llm-monitor-output-text">
                                                                <div class="llm-monitor-output-label"><i class="fas fa-comment-dots"></i> 回复文本</div>
                                                                <pre class="llm-monitor-text-content">{{ step.llmMonitor.output.text }}</pre>
                                                            </div>
                                                            <div v-if="step.llmMonitor.output.tool_calls?.length" class="llm-monitor-output-tools">
                                                                <div class="llm-monitor-output-label"><i class="fas fa-tools"></i> 工具调用</div>
                                                                <div v-for="(tc, tIdx) in step.llmMonitor.output.tool_calls" :key="tIdx" class="llm-monitor-tool-call-item">
                                                                    <span class="llm-monitor-tool-chip">{{ tc.name }}</span>
                                                                    <pre class="llm-monitor-tool-call-args">{{ formatToolIO(tc.input) }}</pre>
                                                                </div>
                                                            </div>
                                                            <div v-if="step.llmMonitor.output.usage" class="llm-monitor-usage">
                                                                <span><i class="fas fa-arrow-up"></i> 输入 {{ step.llmMonitor.output.usage.input_tokens || 0 }} tokens</span>
                                                                <span><i class="fas fa-arrow-down"></i> 输出 {{ step.llmMonitor.output.usage.output_tokens || 0 }} tokens</span>
                                                            </div>
                                                        </div>
                                                    </div>
                                                </div>
                                                        </div>
                                                    </div>
                                                </div>
                                                <div v-if="msg.content" class="tm-tl-text text-content markdown-body" v-html="renderMarkdown(msg.content)"></div>
                                                <div v-else class="tm-tl-empty"><i class="fas fa-hourglass-half"></i> 等待模型生成内容…</div>
                                            </template>
                                        </div>
                                        </div>
                                    </div>
                                    <div v-if="task.status === 'done'" class="tm-new-task-row">
                                        <button class="tm-new-task-btn" @click="resetTask"><i class="fas fa-redo"></i> 开始新任务</button>
                                    </div>
                                    <!-- AI 正在输入指示器 -->
                                    <div v-if="task.status === 'executing' && taskInputSending" class="tm-msg ai typing">
                                        <div class="tm-msg-avatar"><span>🤖</span></div>
                                        <div class="tm-msg-body">
                                            <div class="tm-msg-typing"><span></span><span></span><span></span></div>
                                        </div>
                                    </div>
                                </div>
                                <div class="tm-workspace-panel" v-if="showFileTree">
                                    <div class="tm-workspace-panel-header">
                                        <span>{{ selectedWorkspace ? selectedWorkspace.name : '' }}</span>
                                        <button @click="showFileTree = false"><i class="fas fa-times"></i></button>
                                    </div>
                                    <div class="tm-file-tree">
                                        <div v-for="node in workspaceFileTree" :key="node.path" class="tm-file-node"
                                             :class="{ modified: node.modified }"
                                             :style="{ paddingLeft: (node.depth * 14) + 'px' }">
                                            <i :class="node.type === 'dir' ? 'fas fa-folder' : 'fas fa-file-alt'"></i>
                                            <span>{{ node.name }}</span>
                                            <span v-if="node.modified" class="tm-modified-dot"></span>
                                        </div>
                                    </div>
                                </div>
                            </div>

                            <!-- 底部输入栏（任务模式专用） -->
                            <div class="tm-input-bar">
                                <div class="tm-input-wrapper">
                                    <textarea v-model="taskInput"
                                              placeholder="输入追加指令…（Shift+Enter 换行）"
                                              @keydown.enter.exact.prevent="sendTaskMessage"
                                              @keydown.enter.shift.exact="taskInput += '\n'"
                                              rows="1"
                                              ref="taskInputRef"></textarea>
                                    <button class="tm-send-btn" @click="sendTaskMessage"
                                            :disabled="!taskInput.trim() || taskInputSending">
                                        <i v-if="taskInputSending" class="fas fa-spinner fa-spin"></i>
                                        <i v-else class="fas fa-paper-plane"></i>
                                    </button>
                                </div>
                            </div>
                    </div>

                    <!-- ====== 聊天视图（仅对话模式显示） ====== -->
                    <div v-if="modeType === 'chat' && currentChat && currentChat.messages.length === 0" class="empty-state">
                        <div class="empty-icon-wrapper">
                            <div class="empty-icon">🤖</div>
                            <div class="icon-glow"></div>
                        </div>
                        <h2>你好，我是Nemo</h2>
                        <p>有什么可以帮助你的吗？</p>
                        <div class="quick-actions">
                            <div class="quick-action" @click="quickPrompt('介绍一下你自己')">
                                <i class="fas fa-user"></i>
                                <span>介绍一下你自己</span>
                            </div>
                            <div class="quick-action" @click="quickPrompt('帮我写一个Python示例')">
                                <i class="fas fa-code"></i>
                                <span>帮我写代码</span>
                            </div>
                            <div class="quick-action" @click="quickPrompt('分析一段文本')">
                                <i class="fas fa-file-alt"></i>
                                <span>分析文本</span>
                            </div>
                        </div>
                    </div>

                    <!-- 树视图工具条 -->
                    <div v-show="showAccordion && modeType === 'chat'" class="accordion-toolbar">
                        <button class="reset-main-btn" @click="addBranchAtCurrentLevel" title="在当前活跃分支所在层级新增一条并排对话">➕ 新增并排分支</button>
                    </div>
                    <!-- 树视图：有分支时由 JS 递归渲染，手风琴替换分支轮次 -->
                    <div v-show="showAccordion && modeType === 'chat'" id="messageTree" class="tree-view"></div>

                    <!-- 线性视图：无分支时 Vue 渲染 -->
                    <div v-if="!showAccordion && modeType === 'chat'">
                    <div v-for="(msg, index) in currentChat?.messages || []" :key="index" :class="['message', msg.role]">
                        <div class="message-avatar">
                            {{ msg.role === 'user' ? '👤' : '🤖' }}
                        </div>
                        <div class="message-content">
                            <!-- 用户消息 -->
                            <div v-if="msg.role === 'user'" class="user-message">
                                <span v-if="msg.file" class="file-attachment">
                                    <i class="fas fa-paperclip"></i>
                                    {{ msg.fileName }}
                                </span>
                                <div v-if="editingMessageId !== msg.id">{{ msg.content }}</div>
                            </div>

                            <!-- Copy 按钮 -->
                            <div v-if="msg.role === 'user'" class="copy-btn copy-btn-user" @click="copyMessage(msg)">
                                <i v-if="!msg.copied" class="fas fa-copy"></i>
                                <i v-else class="fas fa-check"></i>
                            </div>

                            <!-- 用户消息操作按钮 -->
                            <div v-if="msg.role === 'user'" class="message-actions">
                                <button class="action-btn edit-btn"
                                        @click="startEditMessage(msg.id, msg.content)"
                                        title="编辑消息">
                                    <i class="fas fa-edit"></i> 编辑
                                </button>
                            </div>

                            <!-- 编辑表单 -->
                            <div v-if="editingMessageId === msg.id" class="edit-form">
                                <textarea v-model="editText" class="edit-textarea"></textarea>
                                <div class="edit-mode-select">
                                    <label>
                                        <input type="radio" v-model="createBranch" :value="true">
                                        分支重新回复（保留原消息）
                                    </label>
                                    <label>
                                        <input type="radio" v-model="createBranch" :value="false">
                                        不分支重新回复（覆盖原消息）
                                    </label>
                                </div>
                                <div class="edit-actions">
                                    <button @click="submitEdit" class="save-btn">保存并重新生成</button>
                                    <button @click="cancelEditMessage" class="cancel-btn">取消</button>
                                </div>
                            </div>

                            <!-- AI 消息 -->
                            <div v-if="msg.role !== 'user'" class="ai-message">
                                <!-- 思考过程（思考+工具调用统一时间线） -->
                                <div v-if="msg.timeline && msg.timeline.length > 0" class="timeline-section">
                                    <div class="timeline-header" @click="toggleTimeline(msg.id)">
                                        <div class="timeline-icon-wrapper">
                                            <i class="fas fa-brain timeline-main-icon"></i>
                                        </div>
                                        <span class="timeline-title">思考过程</span>
                                        <i :class="['fas', msg.showTimeline ? 'fa-chevron-down' : 'fa-chevron-right']"></i>
                                    </div>
                                    <div v-show="msg.showTimeline" class="timeline-content">
                                        <div v-for="(item, idx) in msg.timeline" :key="idx" class="timeline-item">
                                            <div class="timeline-dot" :class="item.type === 'tool' ? item.status : item.type"></div>
                                            <div class="timeline-item-body">
                                                <template v-if="item.type === 'thinking'">
                                                    <div class="timeline-thinking">{{ item.content }}</div>
                                                </template>
                                                <template v-else-if="item.type === 'error'">
                                                    <div class="timeline-error">
                                                        <i class="fas fa-exclamation-triangle"></i>
                                                        <span>{{ item.message }}</span>
                                                        <span v-if="item.detail" class="timeline-error-detail">{{ item.detail }}</span>
                                                    </div>
                                                </template>
                                                <template v-else>
                                                    <div class="timeline-tool">
                                                        <i class="fas fa-wrench timeline-tool-icon"></i>
                                                        <span class="timeline-tool-name">{{ item.toolName }}</span>
                                                        <span class="timeline-tool-status" :class="item.status">
                                                            <i v-if="item.status === 'running'" class="fas fa-spinner fa-spin"></i>
                                                            <i v-else-if="item.status === 'completed'" class="fas fa-check"></i>
                                                            <i v-else class="fas fa-times"></i>
                                                        </span>
                                                    </div>
                                                </template>
                                            </div>
                                        </div>
                                    </div>
                                </div>

                                <!-- 文本内容 -->
                                <div class="text-content markdown-body" v-html="renderMarkdown(msg.content)"></div>

                                <!-- 加载动画 -->
                                <div v-if="isSending && isLastMessage(msg)" class="thinking-loading">
                                    <span class="dot"></span>
                                    <span class="dot"></span>
                                    <span class="dot"></span>
                                </div>

                                <!-- Token 消耗统计 -->
                                <div v-if="msg.usage && msg.usage.total_tokens > 0" class="usage-bar">
                                    <i class="fas fa-coins usage-icon"></i>
                                    <span class="usage-detail">
                                        {{ msg.usage.total_tokens }} tokens
                                        <span v-if="msg.usage.prompt_tokens" class="usage-breakdown">
                                            (输入 {{ msg.usage.prompt_tokens }} / 输出 {{ msg.usage.completion_tokens }})
                                        </span>
                                    </span>
                                    <span v-if="msg.usage.estimated_cost > 0" class="usage-cost">
                                        ≈ ¥{{ msg.usage.estimated_cost.toFixed(4) }}
                                    </span>
                                    <span v-if="msg.usage.is_estimated" class="usage-estimated" title="本地估算值">
                                        <i class="fas fa-question-circle"></i>
                                    </span>
                                </div>

                                <!-- 参考链接 -->
                                <div v-if="msg.reference && msg.reference.length > 0" class="reference-section">
                                    <div class="reference-header" @click="toggleReference(msg.id)">
                                        <div class="reference-icon-wrapper">
                                            <i class="fas fa-book reference-icon"></i>
                                        </div>
                                        <span class="reference-title">参考来源 ({{ msg.reference.length }})</span>
                                        <i :class="['fas', msg.showReference ? 'fa-chevron-down' : 'fa-chevron-right']"></i>
                                    </div>
                                    <div v-show="msg.showReference" class="reference-content">
                                        <template v-for="(ref, rIndex) in msg.reference" :key="rIndex">
                                            <a v-if="ref && ref.url"
                                               :href="ref.url" target="_blank" class="reference-link">
                                                <div class="ref-icon">
                                                    <i class="fas fa-external-link-alt"></i>
                                                </div>
                                                <div class="ref-info">
                                                    <div class="ref-title-text">{{ ref.title || '无标题' }}</div>
                                                    <div class="ref-url-text">{{ ref.url }}</div>
                                                </div>
                                            </a>
                                        </template>
                                    </div>
                                </div>

                                <!-- 推荐问题 -->
                                <div v-if="msg.recommend && msg.recommend.length > 0" class="recommend-section">
                                    <div class="recommend-items">
                                        <div v-for="(question, qIndex) in msg.recommend" :key="qIndex"
                                             class="recommend-item"
                                             @click="sendRecommendQuestion(question)">
                                            <div class="recommend-icon">
                                                <i class="fas fa-lightbulb"></i>
                                            </div>
                                            <div class="recommend-text">{{ question }}</div>
                                            <div class="recommend-arrow">
                                                <i class="fas fa-arrow-right"></i>
                                            </div>
                                        </div>
                                    </div>
                                </div>

                                <!-- PPT下载 -->
                                <div v-if="msg.pptFile" class="ppt-download">
                                    <a :href="msg.pptFile" download class="ppt-link">
                                        <i class="fas fa-download"></i>
                                        下载生成的PPT
                                    </a>
                                </div>

                                <!-- Copy 按钮 -->
                                <div class="copy-btn" @click="copyMessage(msg)">
                                    <i v-if="!msg.copied" class="fas fa-copy"></i>
                                    <i v-else class="fas fa-check"></i>
                                </div>

                                <!-- 重新生成按钮 -->
                                <div class="message-actions" style="display: flex; opacity: 1;">
                                    <button class="action-btn regenerate-btn"
                                            @click="regenerateMessage(msg.id)"
                                            title="重新生成">
                                        <i class="fas fa-redo"></i> 重新生成
                                    </button>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- 目录浏览器弹窗 -->
                <div class="confirm-dialog-overlay" v-if="showDirBrowser" @click="showDirBrowser = false">
                    <div class="confirm-dialog" style="max-width:480px;max-height:70vh;display:flex;flex-direction:column;" @click.stop>
                        <div style="font-weight:600;font-size:14px;margin-bottom:10px;">
                            <i class="fas fa-folder-open"></i> 选择工作区目录
                        </div>
                        <!-- 当前路径面包屑 -->
                        <div style="display:flex;align-items:center;gap:6px;margin-bottom:8px;">
                            <button class="tm-ctrl-btn" style="width:28px;height:28px;font-size:11px;" @click="dirBrowserGoUp" title="返回上级">
                                <i class="fas fa-arrow-up"></i>
                            </button>
                            <input :value="dirBrowserPath" @keydown.enter="dirBrowserNavigate($event.target.value)"
                                   style="flex:1;background:var(--bg-tertiary);border:1px solid var(--border-color);color:var(--text-primary);padding:6px 10px;border-radius:6px;font-size:12px;font-family:monospace;" />
                        </div>
                        <!-- 目录列表 -->
                        <div style="flex:1;overflow-y:auto;min-height:200px;max-height:400px;border:1px solid var(--border-color);border-radius:8px;background:var(--bg-secondary);">
                            <div v-if="dirBrowserLoading" style="padding:20px;text-align:center;color:var(--text-muted);">加载中...</div>
                            <div v-else-if="dirBrowserError" style="padding:12px;color:var(--danger-color);font-size:12px;">{{ dirBrowserError }}</div>
                            <div v-else-if="dirBrowserItems.length === 0" style="padding:20px;text-align:center;color:var(--text-muted);">此目录下没有子文件夹</div>
                            <div v-for="item in dirBrowserItems" :key="item.path"
                                 class="tm-file-node" @click="dirBrowserNavigate(item.path)"
                                 style="cursor:pointer;">
                                <i class="fas fa-folder" style="color:var(--task-color);"></i>
                                <span>{{ item.name }}</span>
                            </div>
                        </div>
                        <!-- 底部按钮 -->
                        <div style="display:flex;justify-content:space-between;align-items:center;margin-top:12px;">
                            <span style="font-size:11px;color:var(--text-muted);max-width:260px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">
                                当前: {{ dirBrowserPath }}
                            </span>
                            <div style="display:flex;gap:8px;">
                                <button style="padding:7px 14px;border-radius:8px;border:1px solid var(--border-color);background:var(--bg-secondary);color:var(--text-secondary);cursor:pointer;font-size:12px;" @click="showDirBrowser = false">取消</button>
                                <button style="padding:7px 14px;border-radius:8px;border:none;background:var(--primary-color);color:#fff;cursor:pointer;font-size:12px;font-weight:600;" @click="dirBrowserConfirm">选择此目录</button>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- 输入区域（仅对话模式显示） -->
                <div class="input-area" v-if="modeType === 'chat'">
                    <!-- 模式选择区 -->
                    <div class="mode-selector">
                        <div class="tm-chat-cluster">
                            <button type="button" class="tm-mode-pill tm-chat-pill" :class="{ active: modeType === 'chat' }"
                                    @click="switchToChatMode">
                                <span>{{ currentChatAgent.icon }}</span>
                                <span>{{ currentChatAgent.name }}</span>
                            </button>
                            <button type="button" class="tm-drawer-toggle-btn" :class="{ open: showAgentDrawer }"
                                    @click.stop="showAgentDrawer = !showAgentDrawer">
                                <i class="fas fa-chevron-up"></i>
                            </button>
                            <div class="tm-agent-drawer" v-if="showAgentDrawer" @click.stop>
                                <div class="tm-agent-drawer-title">选择对话助手</div>
                                <div class="tm-agent-drawer-item" v-for="agent in agents" :key="agent.id"
                                     :class="{ active: modeType === 'chat' && selectedAgent === agent.id }"
                                     @click="chooseSubAgent(agent.id)">
                                    <span class="tm-adi-icon">{{ agent.icon }}</span>
                                    <span class="tm-adi-text">
                                        <span class="tm-adi-name">{{ agent.name }}</span>
                                        <span class="tm-adi-desc">{{ getAgentDesc(agent.id) }}</span>
                                    </span>
                                    <i v-if="modeType === 'chat' && selectedAgent === agent.id" class="fas fa-check tm-adi-check"></i>
                                </div>
                            </div>
                        </div>
                        <div class="tm-mode-divider"></div>
                        <button type="button" class="tm-mode-pill tm-task-pill" :class="{ active: modeType === 'task' }"
                                @click="switchToTaskMode">
                            <span>🤖</span>
                            <span>任务模式</span>
                            <span class="tm-running-dot" v-if="task.status === 'executing'"></span>
                        </button>
                    </div>

                    <!-- 文件预览区域 -->
                    <div v-if="selectedFile" class="file-preview">
                        <div class="file-preview-item">
                            <div class="file-icon-wrapper">
                                <i class="fas fa-file file-icon"></i>
                            </div>
                            <div class="file-info">
                                <div class="file-name">{{ selectedFile.name }}</div>
                                <div class="file-size">{{ formatFileSize(selectedFile.size) }}</div>
                                <div v-if="isUploading" class="upload-parsing">
                                    <i class="fas fa-spinner fa-spin"></i>
                                    <span>解析中...</span>
                                </div>
                            </div>
                            <div class="file-actions">
                                <button v-if="!isUploading" class="remove-file" @click="removeFile" title="删除文件">
                                    <i class="fas fa-trash-alt"></i>
                                </button>
                            </div>
                        </div>
                    </div>

                    <!-- 输入容器 -->
                    <div class="input-container">
                        <!-- 文件上传按钮（文件问答、技能助手模式可用） -->
                        <button v-if="(selectedAgent === 'file' || selectedAgent === 'skills') && !selectedFile" class="file-btn"
                                :class="{ disabled: isUploading }"
                                :disabled="isUploading"
                                @click="$refs.fileInput.click()"
                                title="上传文件（限1个）">
                            <i class="fas fa-paperclip"></i>
                        </button>
                        <input ref="fileInput" type="file" @change="handleFileSelect" style="display: none;">

                        <!-- 文件图标（文件问答模式显示） -->
                        <div v-if="selectedFile && !isUploading" class="input-file-icon" title="文件问答模式">
                            <i class="fas fa-file-alt"></i>
                        </div>

                        <!-- 输入框 -->
                        <textarea v-model="inputMessage"
                                  :placeholder="selectedAgent === 'file' && selectedFile ? '文件问答模式... (删除文件可切换回对话助手)' : '输入消息... (支持 Markdown，Shift+Enter 换行)'"
                                  @keydown.enter.exact.prevent="sendMessage"
                                  @keydown.enter.shift.exact="inputMessage += '\n'"
                                  rows="1"
                                  ref="textareaInput"></textarea>

                        <!-- 发送/停止按钮 -->
                        <button :class="['send-btn', { stop: isSending, disabled: !isSending && (!canSend || isUploading) }]"
                                @click="isSending ? stopMessage() : sendMessage()"
                                :disabled="isSending ? false : (!canSend || isUploading)">
                            <i v-if="isSending" class="fas fa-stop"></i>
                            <i v-else class="fas fa-paper-plane"></i>
                        </button>
                    </div>
                </div>
            </div>
        </div>

        <!-- 连接状态提示 -->
        <div v-if="connectionError" class="connection-error">
            <i class="fas fa-exclamation-triangle"></i>
            <span>{{ connectionError }}</span>
            <button @click="testConnection" class="retry-btn">重试</button>
        </div>

        <!-- 自定义确认对话框 -->
        <div v-if="showConfirmDialog" class="confirm-dialog-overlay">
            <div class="confirm-dialog">
                <div class="confirm-icon">
                    <i class="fas fa-exclamation-circle"></i>
                </div>
                <h3>{{ confirmTitle }}</h3>
                <p>{{ confirmMessage }}</p>
                <div class="confirm-buttons">
                    <button class="confirm-btn cancel" @click="confirmCancel">取消</button>
                    <button class="confirm-btn danger" @click="confirmOk">确认删除</button>
                </div>
            </div>
        </div>

        <!-- 删除确认弹窗 -->
        <div class="modal-overlay" id="deleteModal" v-if="showDeleteModal" @click.self="closeDeleteModal">
            <div class="modal-content">
                <h3>⚠️ 确认删除</h3>
                <p>此操作将<strong>永久删除</strong>该对话及全部消息记录，且<strong>不可恢复</strong>。</p>
                <p>请输入 <code>DELETE</code> 确认操作：</p>
                <input type="text"
                       v-model="deleteConfirmText"
                       placeholder="输入 DELETE"
                       class="delete-confirm-input">
                <div class="modal-actions">
                    <button class="btn-cancel" @click="closeDeleteModal">取消</button>
                    <button class="btn-danger"
                            :disabled="deleteConfirmText !== 'DELETE'"
                            @click="confirmDelete">
                        确认删除
                    </button>
                </div>
            </div>
        </div>
    </div>
    </div>
</template>
