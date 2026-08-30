<script>
  import { onMount, onDestroy, untrack } from 'svelte';
  import { Editor } from '@tiptap/core';
  import StarterKit from '@tiptap/starter-kit';
  import Link from '@tiptap/extension-link';
  import Image from '@tiptap/extension-image';
  import Placeholder from '@tiptap/extension-placeholder';
  import Underline from '@tiptap/extension-underline';
  import { isSafeEmbeddedResourceUrl } from '../../lib/remoteContent.js';

  const EmbeddedImage = Image.extend({
    parseHTML() {
      return [{
        tag: 'img[src]',
        getAttrs: node => (
          isSafeEmbeddedResourceUrl(node.getAttribute('src')) ? {} : false
        ),
      }];
    },
  });

  let {
    content = '',
    onUpdate = null,
    onReady = null,
    placeholder = 'Write your message...',
    externalScroll = false,
    autofocus = false,
    ariaLabel = 'Message body',
    surface = 'message',
  } = $props();

  let editorElement = $state(null);
  let editor = $state(null);
  let lastSetContent = $state(untrack(() => content || ''));

  onMount(() => {
    editor = new Editor({
      element: editorElement,
      extensions: [
        StarterKit.configure({
          heading: { levels: [1, 2, 3] },
          // Keep the explicitly configured extensions below as the single
          // source of truth. Recent StarterKit releases bundle both.
          link: false,
          underline: false,
        }),
        Underline,
        Link.configure({
          openOnClick: false,
          HTMLAttributes: {
            class: 'text-accent-600 underline',
          },
        }),
        EmbeddedImage.configure({
          inline: true,
        }),
        Placeholder.configure({
          placeholder: placeholder,
        }),
      ],
      content: content,
      editorProps: {
        attributes: {
          class: 'prose prose-sm dark:prose-invert max-w-none min-h-[300px] outline-none px-6 py-4',
          role: 'textbox',
          'aria-label': ariaLabel,
          'aria-multiline': 'true',
        },
      },
      onUpdate: ({ editor: ed }) => {
        const html = ed.getHTML();
        // Parent editors mirror this value back through `content`. Remembering
        // the user-authored HTML prevents that feedback from being mistaken
        // for an external replacement, which would reset the caret.
        lastSetContent = html;
        onUpdate?.(html);
      },
    });

    if (autofocus) {
      const active = document.activeElement;
      const focusIsLost = !active
        || active === document.body
        || active.matches?.('main')
        || !active.isConnected;
      if (focusIsLost) editor.commands.focus('end');
    }
    onReady?.();
  });

  // Sync content prop changes into TipTap after mount
  $effect(() => {
    if (!editor) return;
    const nextContent = content || '';
    const currentContent = editor.getHTML();
    if (nextContent === untrack(() => lastSetContent) || nextContent === currentContent) return;
    lastSetContent = nextContent;
    editor.commands.setContent(nextContent, { emitUpdate: false });
  });

  onDestroy(() => {
    if (editor) {
      editor.destroy();
    }
  });

  function toggleBold() {
    if (editor) editor.chain().focus().toggleBold().run();
  }
  function toggleItalic() {
    if (editor) editor.chain().focus().toggleItalic().run();
  }
  function toggleUnderline() {
    if (editor) editor.chain().focus().toggleUnderline().run();
  }
  function toggleStrike() {
    if (editor) editor.chain().focus().toggleStrike().run();
  }
  function toggleBulletList() {
    if (editor) editor.chain().focus().toggleBulletList().run();
  }
  function toggleOrderedList() {
    if (editor) editor.chain().focus().toggleOrderedList().run();
  }
  function toggleBlockquote() {
    if (editor) editor.chain().focus().toggleBlockquote().run();
  }
  function toggleCode() {
    if (editor) editor.chain().focus().toggleCode().run();
  }
  function toggleCodeBlock() {
    if (editor) editor.chain().focus().toggleCodeBlock().run();
  }
  function setLink() {
    if (!editor) return;
    const previousUrl = editor.getAttributes('link').href;
    const url = window.prompt('URL', previousUrl);
    if (url === null) return;
    if (url === '') {
      editor.chain().focus().extendMarkRange('link').unsetLink().run();
      return;
    }
    editor.chain().focus().extendMarkRange('link').setLink({ href: url }).run();
  }
  function addHorizontalRule() {
    if (editor) editor.chain().focus().setHorizontalRule().run();
  }

  function isActive(name, attrs) {
    if (!editor) return false;
    return editor.isActive(name, attrs);
  }
</script>

<div class="rich-editor flex flex-col flex-1" style="background: var(--bg-secondary)" data-editor-surface={surface}>
  <!-- Toolbar -->
  {#if editor}
    <div class="editor-toolbar flex items-center gap-0.5 px-4 py-2 border-b flex-wrap" style="border-color: var(--border-color)" role="toolbar" aria-label="Message formatting">
      <button
        type="button"
        onclick={toggleBold}
        class="editor-tool p-1.5 rounded transition-fast"
        style="color: {isActive('bold') ? 'var(--text-primary)' : 'var(--text-tertiary)'}; background: {isActive('bold') ? 'var(--bg-hover)' : 'transparent'}"
        title="Bold"
        aria-label="Bold"
        aria-pressed={isActive('bold')}
      >
        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2.5">
          <path d="M6 4h8a4 4 0 014 4 4 4 0 01-4 4H6z"/><path d="M6 12h9a4 4 0 014 4 4 4 0 01-4 4H6z"/>
        </svg>
      </button>
      <button
        type="button"
        onclick={toggleItalic}
        class="editor-tool p-1.5 rounded transition-fast"
        style="color: {isActive('italic') ? 'var(--text-primary)' : 'var(--text-tertiary)'}; background: {isActive('italic') ? 'var(--bg-hover)' : 'transparent'}"
        title="Italic"
        aria-label="Italic"
        aria-pressed={isActive('italic')}
      >
        <svg class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <line x1="19" y1="4" x2="10" y2="4"/><line x1="14" y1="20" x2="5" y2="20"/><line x1="15" y1="4" x2="9" y2="20"/>
        </svg>
      </button>
      <button
        type="button"
        onclick={toggleUnderline}
        class="editor-tool p-1.5 rounded transition-fast"
        style="color: {isActive('underline') ? 'var(--text-primary)' : 'var(--text-tertiary)'}; background: {isActive('underline') ? 'var(--bg-hover)' : 'transparent'}"
        title="Underline"
        aria-label="Underline"
        aria-pressed={isActive('underline')}
      >
        <svg class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M6 3v7a6 6 0 0012 0V3"/><line x1="4" y1="21" x2="20" y2="21"/>
        </svg>
      </button>
      <button
        type="button"
        onclick={toggleStrike}
        class="editor-tool p-1.5 rounded transition-fast"
        style="color: {isActive('strike') ? 'var(--text-primary)' : 'var(--text-tertiary)'}; background: {isActive('strike') ? 'var(--bg-hover)' : 'transparent'}"
        title="Strikethrough"
        aria-label="Strikethrough"
        aria-pressed={isActive('strike')}
      >
        <svg class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <line x1="4" y1="12" x2="20" y2="12"/><path d="M17.3 4.9c-1.2-1-2.8-1.5-4.5-1.4-2.7.2-4.6 1.8-4.6 4.1 0 1.3.7 2.4 2.1 3.1"/><path d="M8 16.1c0 2.5 2 4.4 4.8 4.4 2.8 0 4.7-1.7 4.9-4.2"/>
        </svg>
      </button>

      <div class="w-px h-5 mx-1" style="background: var(--border-color)"></div>

      <button
        type="button"
        onclick={toggleBulletList}
        class="editor-tool p-1.5 rounded transition-fast"
        style="color: {isActive('bulletList') ? 'var(--text-primary)' : 'var(--text-tertiary)'}; background: {isActive('bulletList') ? 'var(--bg-hover)' : 'transparent'}"
        title="Bullet List"
        aria-label="Bullet list"
        aria-pressed={isActive('bulletList')}
      >
        <svg class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <line x1="9" y1="6" x2="20" y2="6"/><line x1="9" y1="12" x2="20" y2="12"/><line x1="9" y1="18" x2="20" y2="18"/>
          <circle cx="4" cy="6" r="1.5" fill="currentColor"/><circle cx="4" cy="12" r="1.5" fill="currentColor"/><circle cx="4" cy="18" r="1.5" fill="currentColor"/>
        </svg>
      </button>
      <button
        type="button"
        onclick={toggleOrderedList}
        class="editor-tool p-1.5 rounded transition-fast"
        style="color: {isActive('orderedList') ? 'var(--text-primary)' : 'var(--text-tertiary)'}; background: {isActive('orderedList') ? 'var(--bg-hover)' : 'transparent'}"
        title="Numbered List"
        aria-label="Numbered list"
        aria-pressed={isActive('orderedList')}
      >
        <svg class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <line x1="10" y1="6" x2="21" y2="6"/><line x1="10" y1="12" x2="21" y2="12"/><line x1="10" y1="18" x2="21" y2="18"/>
          <text x="2" y="8" fill="currentColor" font-size="8" font-weight="600">1</text>
          <text x="2" y="14" fill="currentColor" font-size="8" font-weight="600">2</text>
          <text x="2" y="20" fill="currentColor" font-size="8" font-weight="600">3</text>
        </svg>
      </button>

      <div class="w-px h-5 mx-1" style="background: var(--border-color)"></div>

      <button
        type="button"
        onclick={toggleBlockquote}
        class="editor-tool p-1.5 rounded transition-fast"
        style="color: {isActive('blockquote') ? 'var(--text-primary)' : 'var(--text-tertiary)'}; background: {isActive('blockquote') ? 'var(--bg-hover)' : 'transparent'}"
        title="Blockquote"
        aria-label="Blockquote"
        aria-pressed={isActive('blockquote')}
      >
        <svg class="w-4 h-4" viewBox="0 0 24 24" fill="currentColor">
          <path d="M4.583 17.321C3.553 16.227 3 15 3 13.011c0-3.5 2.457-6.637 6.03-8.188l.893 1.378c-3.335 1.804-3.987 4.145-4.247 5.621.537-.278 1.24-.375 1.929-.311C9.591 11.71 11 13.2 11 15c0 1.86-1.567 3.387-3.5 3.387-1.19 0-2.317-.465-2.917-1.066zM14.583 17.321C13.553 16.227 13 15 13 13.011c0-3.5 2.457-6.637 6.03-8.188l.893 1.378c-3.335 1.804-3.987 4.145-4.247 5.621.537-.278 1.24-.375 1.929-.311C19.591 11.71 21 13.2 21 15c0 1.86-1.567 3.387-3.5 3.387-1.19 0-2.317-.465-2.917-1.066z"/>
        </svg>
      </button>
      <button
        type="button"
        onclick={toggleCode}
        class="editor-tool p-1.5 rounded transition-fast"
        style="color: {isActive('code') ? 'var(--text-primary)' : 'var(--text-tertiary)'}; background: {isActive('code') ? 'var(--bg-hover)' : 'transparent'}"
        title="Inline Code"
        aria-label="Inline code"
        aria-pressed={isActive('code')}
      >
        <svg class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/>
        </svg>
      </button>
      <button
        type="button"
        onclick={setLink}
        class="editor-tool p-1.5 rounded transition-fast"
        style="color: {isActive('link') ? 'var(--text-primary)' : 'var(--text-tertiary)'}; background: {isActive('link') ? 'var(--bg-hover)' : 'transparent'}"
        title="Link"
        aria-label="Link"
        aria-pressed={isActive('link')}
      >
        <svg class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M10 13a5 5 0 007.54.54l3-3a5 5 0 00-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 00-7.54-.54l-3 3a5 5 0 007.07 7.07l1.71-1.71"/>
        </svg>
      </button>
      <button
        type="button"
        onclick={addHorizontalRule}
        class="editor-tool p-1.5 rounded transition-fast"
        style="color: var(--text-tertiary)"
        title="Horizontal Rule"
        aria-label="Insert horizontal rule"
      >
        <svg class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <line x1="3" y1="12" x2="21" y2="12"/>
        </svg>
      </button>
    </div>
  {/if}

  <!-- Editor -->
  <div class="{externalScroll ? '' : 'flex-1 overflow-y-auto'}" bind:this={editorElement} style="color: var(--text-primary)"></div>
</div>

<style>
  :global(.tiptap) {
    outline: none;
    min-height: 300px;
  }
  :global(.tiptap p.is-editor-empty:first-child::before) {
    content: attr(data-placeholder);
    float: left;
    color: var(--text-tertiary);
    pointer-events: none;
    height: 0;
  }
  :global(.tiptap ul) {
    list-style: disc;
    padding-left: 1.5rem;
  }
  :global(.tiptap ol) {
    list-style: decimal;
    padding-left: 1.5rem;
  }
  :global(.tiptap blockquote) {
    border-left: 3px solid var(--border-color);
    padding-left: 1rem;
    margin: 0.5rem 0;
    color: var(--text-secondary);
  }
  :global(.tiptap code) {
    background: var(--bg-tertiary);
    border-radius: 0.25rem;
    padding: 0.1rem 0.3rem;
    font-size: 0.875em;
  }
  :global(.tiptap pre) {
    background: var(--bg-tertiary);
    border-radius: 0.5rem;
    padding: 0.75rem 1rem;
    overflow-x: auto;
  }
  :global(.tiptap pre code) {
    background: none;
    padding: 0;
  }
  :global(.tiptap hr) {
    border: none;
    border-top: 1px solid var(--border-color);
    margin: 1rem 0;
  }
  :global(.tiptap a) {
    color: var(--color-accent-600);
    text-decoration: underline;
  }
  :global(.tiptap img) {
    max-width: 100%;
    border-radius: 0.5rem;
  }
  :global(.tiptap p) {
    margin: 0.25rem 0;
  }

  .editor-tool {
    min-width: 2rem;
    min-height: 2rem;
  }

  @media (max-width: 767px) {
    .editor-toolbar {
      gap: 0.125rem;
      padding-inline: 0.5rem;
    }

    .editor-tool {
      min-width: 2.75rem;
      min-height: 2.75rem;
    }
  }
</style>
