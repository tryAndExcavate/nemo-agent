import { createApp } from 'vue'
import App from './App.vue'
import './styles/style.css'
import './styles/task-mode.css'
import 'highlight.js/styles/github-dark.css'
import { __copyCode } from './lib/utils.js'

// renderMarkdown 生成的 HTML 内联 onclick 依赖全局 __copyCode
window.__copyCode = __copyCode

createApp(App).mount('#app-root')
