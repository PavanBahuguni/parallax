import React from 'react'

interface AnsiRendererProps {
  text: string
}

const AnsiRenderer: React.FC<AnsiRendererProps> = ({ text }) => {
  if (!text) return null

  // Split text by ANSI escape codes
  const parts = text.split(/(\u001b\[(?:\d+(?:;\d+)*)?m)/g)
  
  const spans: React.ReactNode[] = []
  let currentStyle: React.CSSProperties = {}
  let key = 0

  for (let i = 0; i < parts.length; i++) {
    const part = parts[i]

    if (!part) continue

    if (part.startsWith('\u001b[')) {
      // It's an ANSI code
      const codes = part.slice(2, -1).split(';').map(Number)
      
      for (const code of codes) {
        if (code === 0) {
          // Reset
          currentStyle = {}
        } else if (code === 1) {
          // Bold
          currentStyle.fontWeight = 'bold'
        } else if (code === 2) {
          // Dim
          currentStyle.opacity = 0.7
        } else if (code === 3) {
          // Italic
          currentStyle.fontStyle = 'italic'
        } else if (code === 4) {
          // Underline
          currentStyle.textDecoration = 'underline'
        } else if (code >= 30 && code <= 37) {
          // Foreground colors
          const colors = ['black', '#ef4444', '#22c55e', '#eab308', '#3b82f6', '#d946ef', '#06b6d4', 'white']
          currentStyle.color = colors[code - 30]
        } else if (code >= 90 && code <= 97) {
          // Bright foreground colors
          const colors = ['gray', '#f87171', '#4ade80', '#facc15', '#60a5fa', '#e879f9', '#22d3ee', 'white']
          currentStyle.color = colors[code - 90]
        }
        // Ignore backgrounds and other codes for simplicity
      }
    } else {
      // It's text
      spans.push(
        <span key={key++} style={{ ...currentStyle }}>
          {part}
        </span>
      )
    }
  }

  return <>{spans}</>
}

export default AnsiRenderer
