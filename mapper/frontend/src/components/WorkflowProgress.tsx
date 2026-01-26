import { useEffect, useState, useRef } from 'react'
import LogViewer from '../components/LogViewer'
import AnsiRenderer from '../utils/AnsiRenderer'
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

interface StepState {
  status: 'pending' | 'running' | 'completed' | 'failed' | 'skipped'
  message: string
  logs: string[]
}

const PIPELINE_STEPS = ['analyze', 'map', 'generate-mission', 'execute'] as const

export default function WorkflowProgress({ taskId, executionId, onComplete }: WorkflowProgressProps) {
  const [updates, setUpdates] = useState<WorkflowUpdate[]>([])
  const [connected, setConnected] = useState(false)
  const [expandedStep, setExpandedStep] = useState<string | null>(null)
  const logsEndRef = useRef<HTMLDivElement>(null)
  
  // Derive workflow status from updates
  let workflowStatus: 'idle' | 'running' | 'completed' | 'failed' = 'idle'
  
  // Aggregate updates by step
  const stepStates: Record<string, StepState> = {}
  PIPELINE_STEPS.forEach(step => {
    stepStates[step] = { status: 'pending', message: '', logs: [] }
  })
  
  updates.forEach(update => {
    if (update.step === 'workflow') {
      if (update.status === 'running') workflowStatus = 'running'
      else if (update.status === 'completed') workflowStatus = 'completed'
      else if (update.status === 'failed') workflowStatus = 'failed'
      return
    }
    
    if (stepStates[update.step]) {
      stepStates[update.step].status = update.status
      stepStates[update.step].message = update.message
      stepStates[update.step].logs.push(update.message)
    }
  })

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
    const wsUrl = `ws://localhost:8001/ws/tasks/${taskId}`
    const websocket = new WebSocket(wsUrl)

    websocket.onopen = () => {
      setConnected(true)
    }

    websocket.onmessage = (event) => {
      try {
        if (event.data === 'pong') return
        
        const update: WorkflowUpdate = JSON.parse(event.data)
        setUpdates((prev) => {
          const exists = prev.some(u => u.timestamp === update.timestamp)
          if (exists) return prev
          return [...prev, update].sort((a, b) => 
            new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime()
          )
        })
        
        if (update.step === 'workflow' && (update.status === 'completed' || update.status === 'failed')) {
          if (onComplete) {
            onComplete(update.status === 'completed')
          }
        }
      } catch (err) {
        console.error('Error parsing WebSocket message:', err)
      }
    }

    websocket.onerror = () => setConnected(false)
    websocket.onclose = () => setConnected(false)

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

  // Auto-scroll logs
  useEffect(() => {
    logsEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [updates])

  const getStepLabel = (step: string) => {
    const labels: Record<string, string> = {
      'analyze': 'Analyze',
      'map': 'Map',
      'generate-mission': 'Generate',
      'execute': 'Execute'
    }
    return labels[step] || step
  }

  const getStepDescription = (step: string) => {
    const descriptions: Record<string, string> = {
      'analyze': 'Analyze PR changes',
      'map': 'Semantic mapping',
      'generate-mission': 'Generate test plan',
      'execute': 'Execute tests'
    }
    return descriptions[step] || step
  }

  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'completed': return '✓'
      case 'failed': return '✗'
      case 'running': return ''
      case 'skipped': return '—'
      default: return ''
    }
  }

  const currentStepIndex = PIPELINE_STEPS.findIndex(s => stepStates[s].status === 'running')
  const completedSteps = PIPELINE_STEPS.filter(s => 
    stepStates[s].status === 'completed' || stepStates[s].status === 'skipped'
  ).length

  // Determine active step for live output (running step, or last completed/failed if none running)
  let activeStep = PIPELINE_STEPS[0]
  const runningStep = PIPELINE_STEPS.find(s => stepStates[s].status === 'running')
  if (runningStep) {
    activeStep = runningStep
  } else {
    // Find last non-pending step
    const reversedSteps = [...PIPELINE_STEPS].reverse()
    const lastActive = reversedSteps.find(s => stepStates[s].status !== 'pending')
    if (lastActive) {
      activeStep = lastActive
    }
  }

  // Filter updates for the active step
  const activeStepUpdates = updates.filter(u => u.step === activeStep)

  return (
    <div className="workflow-progress-v2">
      {/* Header */}
      <div className="wp-header">
        <div className="wp-title">
          <h3>Test Execution Pipeline</h3>
          <span className={`wp-badge ${workflowStatus}`}>
            {workflowStatus === 'running' && <span className="wp-spinner" />}
            {workflowStatus.charAt(0).toUpperCase() + workflowStatus.slice(1)}
          </span>
        </div>
        <div className={`wp-connection ${connected ? 'connected' : ''}`}>
          <span className="wp-dot" />
          {connected ? 'Live' : 'Disconnected'}
        </div>
      </div>

      {/* Pipeline Steps */}
      <div className="wp-pipeline">
        {PIPELINE_STEPS.map((step, index) => {
          const state = stepStates[step]
          const isActive = state.status === 'running'
          const isDone = state.status === 'completed' || state.status === 'skipped'
          const isFailed = state.status === 'failed'
          
          return (
            <div key={step} className="wp-step-wrapper">
              <div 
                className={`wp-step ${state.status} ${expandedStep === step ? 'expanded' : ''}`}
                onClick={() => setExpandedStep(expandedStep === step ? null : step)}
              >
                <div className={`wp-step-icon ${state.status}`}>
                  {isActive ? (
                    <span className="wp-step-spinner" />
                  ) : (
                    <span>{getStatusIcon(state.status) || (index + 1)}</span>
                  )}
                </div>
                <div className="wp-step-info">
                  <span className="wp-step-label">{getStepLabel(step)}</span>
                  <span className="wp-step-desc">{getStepDescription(step)}</span>
                </div>
              </div>
              {index < PIPELINE_STEPS.length - 1 && (
                <div className={`wp-connector ${isDone || isFailed ? state.status : ''}`} />
              )}
            </div>
          )
        })}
      </div>

      {/* Progress Bar */}
      <div className="wp-progress-bar">
        <div 
          className={`wp-progress-fill ${workflowStatus}`}
          style={{ width: `${(completedSteps / PIPELINE_STEPS.length) * 100}%` }}
        />
      </div>

      {/* Expanded Step Details */}
      {expandedStep && stepStates[expandedStep].logs.length > 0 && (
        <div className="wp-step-details">
          <div className="wp-step-details-header">
            <span>{getStepLabel(expandedStep)} Logs</span>
            <button onClick={() => setExpandedStep(null)}>×</button>
          </div>
          <div className="wp-step-logs">
            <LogViewer logs={stepStates[expandedStep].logs} variant="full" />
          </div>
        </div>
      )}

      {/* Live Logs Terminal */}
      {updates.length > 0 && (
        <div className="wp-terminal">
          <div className="wp-terminal-header">
            <span className="wp-terminal-title">Live Output: {getStepLabel(activeStep)}</span>
            <div className="wp-terminal-dots">
              <span /><span /><span />
            </div>
          </div>
          <div className="wp-terminal-body">
            {activeStepUpdates.slice(-15).map((update, i) => (
              <div key={i} className={`wp-terminal-line ${update.status}`}>
                <span className="wp-terminal-time">
                  {new Date(update.timestamp).toLocaleTimeString('en-US', { 
                    hour12: false, 
                    hour: '2-digit', 
                    minute: '2-digit', 
                    second: '2-digit' 
                  })}
                </span>
                <span className="wp-terminal-msg">
                  <AnsiRenderer text={update.message} />
                </span>
              </div>
            ))}
            <div ref={logsEndRef} />
          </div>
        </div>
      )}

      {updates.length === 0 && (
        <div className="wp-empty">
          <div className="wp-empty-icon">⏳</div>
          <p>Waiting for workflow to start...</p>
        </div>
      )}
    </div>
  )
}
