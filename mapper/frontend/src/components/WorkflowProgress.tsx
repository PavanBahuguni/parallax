import { useEffect, useState } from 'react'
import './WorkflowProgress.css'

export interface WorkflowUpdate {
  step: string
  status: 'running' | 'completed' | 'failed' | 'skipped'
  message: string
  timestamp: string
  data?: any
}

interface WorkflowProgressProps {
  taskId: string
  executionId?: string
  onComplete?: (success: boolean) => void
}

export default function WorkflowProgress({ taskId, executionId, onComplete }: WorkflowProgressProps) {
  const [updates, setUpdates] = useState<WorkflowUpdate[]>([])
  const [ws, setWs] = useState<WebSocket | null>(null)
  const [connected, setConnected] = useState(false)
  
  // Load historical updates from execution if available
  useEffect(() => {
    if (executionId) {
      loadHistoricalUpdates()
    }
  }, [executionId])
  
  const loadHistoricalUpdates = async () => {
    if (!executionId) return
    
    try {
      const response = await fetch(`http://localhost:8001/api/executions/${executionId}`)
      if (response.ok) {
        const execution = await response.json()
        if (execution.result?.updates && Array.isArray(execution.result.updates)) {
          // Merge with existing updates, avoiding duplicates
          setUpdates((prev) => {
            const existingTimestamps = new Set(prev.map(u => u.timestamp))
            const newUpdates = execution.result.updates.filter((u: WorkflowUpdate) => 
              !existingTimestamps.has(u.timestamp)
            )
            return [...prev, ...newUpdates].sort((a, b) => 
              new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime()
            )
          })
        }
      }
    } catch (err) {
      console.error('Failed to load historical updates:', err)
    }
  }

  useEffect(() => {
    // Connect to WebSocket
    // Use ws://localhost:8001 directly (not proxied through Vite)
    const wsUrl = `ws://localhost:8001/ws/tasks/${taskId}`
    console.log('Connecting to WebSocket:', wsUrl)
    const websocket = new WebSocket(wsUrl)

    websocket.onopen = () => {
      console.log('WebSocket connected')
      setConnected(true)
      setWs(websocket)
    }

    websocket.onmessage = (event) => {
      try {
        // Handle pong response
        if (event.data === 'pong') {
          return
        }
        
        const update: WorkflowUpdate = JSON.parse(event.data)
        console.log('WebSocket update received:', update)
        // Add new update, avoiding duplicates by timestamp
        setUpdates((prev) => {
          const exists = prev.some(u => u.timestamp === update.timestamp)
          if (exists) return prev
          return [...prev, update].sort((a, b) => 
            new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime()
          )
        })
        
        // Check if workflow is complete
        if (update.step === 'workflow' && (update.status === 'completed' || update.status === 'failed')) {
          if (onComplete) {
            onComplete(update.status === 'completed')
          }
        }
      } catch (err) {
        console.error('Error parsing WebSocket message:', err, event.data)
      }
    }

    websocket.onerror = (error) => {
      console.error('WebSocket error:', error)
      setConnected(false)
    }

    websocket.onclose = () => {
      console.log('WebSocket disconnected')
      setConnected(false)
    }

    // Send ping every 30 seconds to keep connection alive
    const pingInterval = setInterval(() => {
      if (websocket.readyState === WebSocket.OPEN) {
        websocket.send('ping')
      }
    }, 30000)

    return () => {
      clearInterval(pingInterval)
      websocket.close()
    }
  }, [taskId, onComplete])

  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'completed':
        return '✅'
      case 'failed':
        return '❌'
      case 'running':
        return '🔄'
      case 'skipped':
        return '⏭️'
      default:
        return '⏳'
    }
  }

  const getStatusClass = (status: string) => {
    return `status-${status}`
  }

  const getStepName = (step: string) => {
    const stepNames: Record<string, string> = {
      'analyze': 'Analyzing Changes',
      'map': 'Semantic Mapping',
      'generate-mission': 'Generating Mission',
      'execute': 'Executing Tests',
      'workflow': 'Workflow'
    }
    return stepNames[step] || step
  }

  return (
    <div className="workflow-progress">
      <div className="workflow-progress-header">
        <h3>🤖 Automated Workflow Progress</h3>
        <span className={`connection-status ${connected ? 'connected' : 'disconnected'}`}>
          {connected ? '🟢 Connected' : '🔴 Disconnected'}
        </span>
      </div>
      
      {updates.length === 0 ? (
        <div className="workflow-progress-empty">
          Waiting for updates...
        </div>
      ) : (
        <div className="workflow-progress-list">
          {updates.map((update, index) => (
            <div key={index} className={`workflow-update ${getStatusClass(update.status)}`}>
              <div className="update-header">
                <span className="update-icon">{getStatusIcon(update.status)}</span>
                <span className="update-step">{getStepName(update.step)}</span>
                <span className="update-status">{update.status}</span>
              </div>
              <div className="update-message">{update.message}</div>
              {update.data && Object.keys(update.data).length > 0 && (
                <div className="update-data">
                  <pre>{JSON.stringify(update.data, null, 2)}</pre>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
