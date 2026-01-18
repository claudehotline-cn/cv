<template>
  <div class="markdown-body" v-html="renderedContent"></div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import MarkdownIt from 'markdown-it'

const props = defineProps<{
  content: string
}>()

const md = new MarkdownIt({
  html: true,
  linkify: true,
  typographer: true,
  breaks: true,
})

// Configure renderer rules for better styling
const defaultFence = md.renderer.rules.fence

md.renderer.rules.fence = function(tokens, idx, options, env, self) {
  const token = tokens[idx]
  const info = token.info ? md.utils.unescapeAll(token.info).trim() : ''
  const langName = info.split(/\s+/g)[0]
  
  // Wrap code block with language label
  return `
    <div class="code-block-wrapper">
      ${langName ? `<div class="code-lang">${langName}</div>` : ''}
      ${defaultFence ? defaultFence(tokens, idx, options, env, self) : ''}
    </div>
  `
}

const renderedContent = computed(() => {
  return md.render(props.content || '')
})
</script>

<style scoped>
.markdown-body {
  line-height: 1.7;
  font-size: 15px;
  color: var(--text-primary);
}

.markdown-body :deep(h1),
.markdown-body :deep(h2),
.markdown-body :deep(h3) {
  margin-top: 1.5em;
  margin-bottom: 0.8em;
  font-weight: 600;
  color: var(--text-primary);
}

.markdown-body :deep(p) {
  margin: 0.8em 0;
}

.markdown-body :deep(strong) {
  color: var(--text-primary);
  font-weight: 600;
}

.markdown-body :deep(a) {
  color: var(--accent-primary);
  text-decoration: none;
  border-bottom: 1px dashed var(--accent-primary);
}

.markdown-body :deep(a:hover) {
  border-bottom-style: solid;
}

.markdown-body :deep(ul),
.markdown-body :deep(ol) {
  padding-left: 1.5em;
  margin: 1em 0;
}

.markdown-body :deep(li) {
  margin: 0.4em 0;
}

.markdown-body :deep(blockquote) {
  margin: 1.5em 0;
  padding-left: 1em;
  border-left: 3px solid var(--accent-primary);
  font-style: italic;
  color: var(--text-secondary);
  background: rgba(99, 102, 241, 0.05);
  padding: 8px 12px;
  border-radius: 0 4px 4px 0;
}

/* Code Styles */
.markdown-body :deep(.code-block-wrapper) {
  margin: 1.2em 0;
  border-radius: 8px;
  overflow: hidden;
  border: 1px solid var(--border-color);
  background: #1e1e1e; /* Classic code editor bg */
}

.markdown-body :deep(.code-lang) {
  background: #2d2d2d;
  color: #a0a0a0;
  font-size: 11px;
  padding: 4px 12px;
  text-align: right;
  font-family: var(--font-mono);
  border-bottom: 1px solid #333;
}

.markdown-body :deep(pre) {
  margin: 0;
  padding: 16px;
  overflow-x: auto;
  background: transparent;
}

.markdown-body :deep(code) {
  font-family: var(--font-mono);
  font-size: 13px;
}

/* Inline code */
.markdown-body :deep(p code),
.markdown-body :deep(li code) {
  background: rgba(99, 102, 241, 0.1);
  color: var(--accent-primary);
  padding: 2px 5px;
  border-radius: 4px;
}

.markdown-body :deep(table) {
  width: 100%;
  border-collapse: collapse;
  margin: 1.5em 0;
  font-size: 14px;
}

.markdown-body :deep(th),
.markdown-body :deep(td) {
  padding: 10px 14px;
  border: 1px solid var(--border-color);
}

.markdown-body :deep(th) {
  background: rgba(255, 255, 255, 0.05);
  font-weight: 600;
  text-align: left;
}
</style>
