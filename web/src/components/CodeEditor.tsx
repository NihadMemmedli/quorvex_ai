'use client';
import Editor, { type EditorProps } from '@monaco-editor/react';
import { forwardRef, useImperativeHandle, useRef } from 'react';

interface CodeEditorProps {
  value: string;
  onChange: (value: string) => void;
  language: 'typescript' | 'markdown' | 'json' | 'javascript';
  readOnly?: boolean;
  height?: string | number;
  ariaLabel?: string;
  wrapperClassName?: string;
  wrapperTestId?: string;
  options?: EditorProps['options'];
}

const CodeEditor = forwardRef<HTMLDivElement, CodeEditorProps>(function CodeEditor({
  value,
  onChange,
  language,
  readOnly = false,
  height = '100%',
  ariaLabel,
  wrapperClassName,
  wrapperTestId,
  options,
}, ref) {
  const wrapperRef = useRef<HTMLDivElement | null>(null);
  useImperativeHandle(ref, () => wrapperRef.current as HTMLDivElement);

  return (
    <div
      ref={wrapperRef}
      className={wrapperClassName}
      data-testid={wrapperTestId}
      style={{ height, minHeight: 0 }}
    >
      <Editor
        height={height}
        language={language}
        value={value}
        onChange={(val) => onChange(val || '')}
        onMount={(editor) => {
          if (wrapperRef.current && wrapperTestId) {
            (wrapperRef.current as HTMLDivElement & { __monacoEditor?: typeof editor }).__monacoEditor = editor;
          }
        }}
        theme="vs-dark"
        options={{
          minimap: { enabled: false },
          fontSize: 14,
          lineNumbers: 'on',
          scrollBeyondLastLine: false,
          wordWrap: 'on',
          automaticLayout: true,
          padding: { top: 16, bottom: 16 },
          ...options,
          readOnly,
          ariaLabel,
        }}
      />
    </div>
  );
});

export default CodeEditor;
