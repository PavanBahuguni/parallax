import React, { useState, useEffect, useRef } from 'react'
import AnsiRenderer from '../utils/AnsiRenderer'
import './LogViewer.css'

interface LogViewerProps {
  logs: string[]
  variant?: 'terminal' | 'full'
  maxHeight?: string
}

const LogViewer: React.FC<LogViewerProps> = ({ logs, variant = 'full', maxHeight }) => {
  const [groups, setGroups] = useState<LogGroup[]>([])
  const bottomRef = useRef<HTMLDivElement>(null)

  const cleanLog = (log: string) => {
    if (!log) return ''
    // Remove backend logging prefixes like "10:16:43 | INFO     | [executor] "
    // Matches: Time | Level | [source] Message
    return log.replace(/^\d{2}:\d{2}:\d{2}\s*\|\s*[A-Z]+\s*\|\s*\[.*?\]\s*/, '')
              .replace(/^\d{2}:\d{2}:\d{2}\s*\|\s*[A-Z]+\s*\|\s*/, '')
              .replace(/^\[.*?\]\s*/, '')
  }

  useEffect(() => {
    // Group logs
    const newGroups: LogGroup[] = []
    let currentGroup: LogGroup | null = null

    logs.forEach((rawLog) => {
      const log = cleanLog(rawLog)
      
      // Check if line is a header
      // We look for specific keywords or emoji indicators that mark major sections
      const isHeader = 
        log.includes('====') || 
        log.includes('Goal:') || 
        log.includes('TRIPLE-CHECK EXECUTOR') ||
        log.includes('Executing Gateway Plan') ||
        log.includes('HIDDEN FIELD CHECK') ||
        log.includes('Test Case Result') ||
        log.includes('Deterministic Execution') ||
        log.includes('Tests:') ||
        (log.includes('Step') && log.includes(':')) ||
        // Check for major status indicators with emojis
        /(\s|^)(🚪|🔍|❌|✅|⚠️|🚀|▶️)(\s|$)/.test(log)

      if (isHeader) {
        if (currentGroup) {
          newGroups.push(currentGroup)
        }
        currentGroup = {
          header: log,
          logs: [],
          expanded: true // Will be overridden
        }
      } else {
        if (!currentGroup) {
          currentGroup = {
            header: 'Initialization',
            logs: [],
            expanded: false
          }
        }
        // Only add non-empty logs or if it's not just a separator line
        if (log.trim() && !log.match(/^={5,}$/)) {
          currentGroup.logs.push(log)
        }
      }
    })

    if (currentGroup) {
      newGroups.push(currentGroup)
    }
    setGroups(prevGroups => {
      return newGroups.map((newGroup, i) => {
        // Try to find matching group in previous state
        const prevGroup = prevGroups.find(g => g.header === newGroup.header)
        if (prevGroup) {
          return { ...newGroup, expanded: prevGroup.expanded }
        }
        // Default behavior: expand only the last group, collapse others
        // But if it's the very first render (prevGroups empty), maybe expand all? 
        // Or stick to "last expanded" for cleaner view.
        const isLast = i === newGroups.length - 1
        return { ...newGroup, expanded: isLast }
      })
    })
  }, [logs])

  // Auto-scroll for terminal variant
  useEffect(() => {
    if (variant === 'terminal') {
      bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
    }
  }, [logs, variant])

  if (variant === 'terminal') {
    return (
      <div className="log-viewer terminal" style={{ maxHeight }}>
        {logs.map((rawLog, i) => {
          const log = cleanLog(rawLog)
          if (!log.trim()) return null
          return (
            <div key={i} className="log-line">
              <AnsiRenderer text={log} />
            </div>
          )
        })}
        <div ref={bottomRef} />
      </div>
    )
  }

  return (
    <div className="log-viewer full" style={{ maxHeight }}>
      {groups.map((group, i) => (
        <div key={i} className="log-group">
          <div 
            className="log-group-header" 
            onClick={() => {
              const newGroups = [...groups]
              newGroups[i].expanded = !newGroups[i].expanded
              setGroups(newGroups)
            }}
          >
            <span className="log-group-icon">{group.expanded ? '▼' : '▶'}</span>
            <span className="log-group-title">
              <AnsiRenderer text={cleanLog(group.header)} />
            </span>
          </div>
          {group.expanded && (
            <div className="log-group-body">
              {group.logs.map((rawLog, j) => {
                const log = cleanLog(rawLog)
                if (!log.trim()) return null
                return (
                  <div key={j} className="log-line">
                    <AnsiRenderer text={log} />
                  </div>
                )
              })}
              {group.logs.length === 0 && (
                <div className="log-line empty">No details</div>
              )}
            </div>
          )}
        </div>
      ))}
      <div ref={bottomRef} />
    </div>
  )
}

interface LogGroup {
  header: string
  logs: string[]
  expanded: boolean
}

export default LogViewer
