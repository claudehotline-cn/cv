<template>
  <div class="markdown-body" v-html="renderedContent"></div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import MarkdownIt from 'markdown-it'
import markdownItKatex from 'markdown-it-katex'
import hljs from 'highlight.js'
import 'highlight.js/styles/atom-one-dark.css'
import 'katex/dist/katex.min.css'

const props = defineProps<{
  content: string
  autoMath?: boolean
}>()

const md = new MarkdownIt({
  html: true,
  linkify: true,
  typographer: true,
  breaks: true,
  highlight: function (str, lang) {
    if (lang && hljs.getLanguage(lang)) {
      try {
        return hljs.highlight(str, { language: lang }).value
      } catch (__) {}
    }
    // 自动检测语言
    try {
      return hljs.highlightAuto(str).value
    } catch (__) {}
    return '' // 使用外部默认 escaping
  }
})

md.use(markdownItKatex, {
  throwOnError: false,
  strict: 'ignore',
})

function normalizeMathWhitespaceInDisplayBlocks(input: string) {
  // PDF extractors often insert lots of newlines/spaces inside a single formula.
  // This keeps display math readable and helps KaTeX parse more consistently.
  return String(input || '').replace(/(^|\n)\s*\$\$\s*([\s\S]*?)\s*\$\$\s*(?=\n|$)/g, (_m, p1, inner) => {
    let x = String(inner || '')
    // Preserve explicit LaTeX line breaks.
    x = x.replace(/\\\\/g, '__KATEX_BR__')
    x = x.replace(/\s+/g, ' ').trim()
    x = x.replace(/__KATEX_BR__/g, '\\\\')

    // If a display block contains a redundant inline `$...$`, strip it.
    const trimmed = x.trim()
    if (trimmed.startsWith('$') && trimmed.endsWith('$') && (trimmed.match(/\$/g) || []).length === 2) {
      x = trimmed.slice(1, -1).trim()
    }

    // Handle patterns like: `i = $\frac{...}{...}$` inside a display block.
    // KaTeX doesn't accept `$` delimiters inside `$$...$$`.
    const dollarCount = (x.match(/\$/g) || []).length
    if (dollarCount === 2) {
      x = x.replace(/\$([^$]+)\$/g, '$1').trim()
    }
    return `${p1}$$\n${x}\n$$`
  })
}

function normalizeInlineMathSpacing(input: string) {
  // Some KaTeX markdown plugins don't treat `$ <expr> $` as math.
  // Trim only when the content looks like TeX/math.
  return String(input || '').replace(/\$([^\n$]{1,800})\$/g, (m, inner) => {
    const raw = String(inner || '')
    const looksMath = /\\[a-zA-Z]+|\^\{|_\{|=|\b\d+\b/.test(raw)
    if (!looksMath) return m
    const trimmed = raw.replace(/\s+/g, ' ').trim()
    return `$${trimmed}$`
  })
}

function normalizeMathDelimiters(input: string) {
  // Support common LaTeX bracket delimiters in addition to $/$$.
  // KaTeX plugin handles $...$ and $$...$$.
  let s = String(input || '')
    // Common KaTeX-unsupported environments seen in math content.
    .replace(/\\begin\{align\*?\}/g, '\\begin{aligned}')
    .replace(/\\end\{align\*?\}/g, '\\end{aligned}')

  // Wrap LaTeX environments into $$...$$ so markdown-it-katex can render them.
  // This is a best-effort heuristic; it only targets \begin{...}...\end{...} blocks.
  s = s.replace(
    /(^|\n)\s*(\\begin\{([a-zA-Z*]+)\}[\s\S]*?\\end\{\3\})\s*(?=\n|$)/g,
    (_m, p1, block) => `${p1}\n$$\n${block}\n$$\n`
  )

  // Sometimes delimiters get double-escaped before reaching the renderer.
  // Handle both \( \) and \\( \\) forms.
  s = s
    .replace(/\\\\\[/g, '\\[')
    .replace(/\\\\\]/g, '\\]')
    .replace(/\\\\\(/g, '\\(')
    .replace(/\\\\\)/g, '\\)')

  // Convert \[ \] and \( \) to $$ / $.
  const out = s
    // double backslash variants first
    .replace(/\\\\\[/g, '$$')
    .replace(/\\\\\]/g, '$$')
    .replace(/\\\\\(/g, '$')
    .replace(/\\\\\)/g, '$')
    // single backslash variants
    .replace(/\\\[/g, '$$')
    .replace(/\\\]/g, '$$')
    .replace(/\\\(/g, '$')
    .replace(/\\\)/g, '$')

  return normalizeInlineMathSpacing(normalizeMathWhitespaceInDisplayBlocks(out))
}

function autoWrapBareLatex(input: string) {
  const s = String(input || '')
  if (!s) return ''

  const lines = s.split('\n')
  const out: string[] = []
  let inCode = false
  let fence: string | null = null
  let inDisplayMath = false

  const isFence = (t: string) => t.startsWith('```') || t.startsWith('~~~')

  for (const line of lines) {
    const t = line.trim()
    if (t === '$$') {
      inDisplayMath = !inDisplayMath
      out.push(line)
      continue
    }
    if (isFence(t)) {
      const f = t.slice(0, 3)
      if (!inCode) {
        inCode = true
        fence = f
      } else if (fence === f) {
        inCode = false
        fence = null
      }
      out.push(line)
      continue
    }
    if (inCode) {
      out.push(line)
      continue
    }

    if (inDisplayMath) {
      out.push(line)
      continue
    }

    // Skip lines already containing explicit math delimiters.
    if (t.includes('$') || t.includes('\\(') || t.includes('\\)') || t.includes('\\[') || t.includes('\\]')) {
      out.push(line)
      continue
    }

    const hasCmd = /\\[a-zA-Z]+/.test(t)
    const hasScript = /(_\{|\^\{)/.test(t)
    const hasOps = /[=+\-*/]/.test(t)
    const looksMath = (hasCmd && (hasOps || hasScript)) || (hasScript && hasOps)
    if (!looksMath) {
      out.push(line)
      continue
    }

    const starts: number[] = []
    const i1 = line.indexOf('\\')
    if (i1 >= 0) starts.push(i1)
    const m1 = line.match(/[A-Za-z]\s*_[{]/)
    if (m1?.index !== undefined) starts.push(m1.index)
    const m2 = line.match(/[A-Za-z]\s*\^[{]/)
    if (m2?.index !== undefined) starts.push(m2.index)
    if (!starts.length) {
      out.push(line)
      continue
    }

    const start = Math.min(...starts)
    const prefix = line.slice(0, start).trimEnd()
    const expr = line.slice(start).trim()
    if (!expr) {
      out.push(line)
      continue
    }
    const eqPrefix = prefix.trim()
    const shouldMergePrefix = /^[A-Za-z][A-Za-z0-9_]*\s*=\s*$/.test(eqPrefix)
    const merged = shouldMergePrefix ? `${eqPrefix} ${expr}` : expr
    const wrapped = merged.length > 140 ? `$$\n${merged}\n$$` : `$${merged}$`
    out.push(!shouldMergePrefix && prefix ? `${prefix} ${wrapped}` : wrapped)
  }

  return out.join('\n')
}

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
  let s = normalizeMathDelimiters(props.content || '')
  if (props.autoMath) s = autoWrapBareLatex(s)
  return md.render(s)
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

/* Code block specific styles */
.markdown-body :deep(pre code) {
  background: transparent;
  color: #abb2bf; /* Atom One Dark default foreground */
  padding: 0;
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

.markdown-body :deep(.katex-display) {
  overflow-x: auto;
  overflow-y: hidden;
  padding: 8px 0;
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
