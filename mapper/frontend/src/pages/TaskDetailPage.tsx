import { useEffect, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { api, Task, Execution } from '../api/client'
import SemanticGraphViewer from '../components/SemanticGraphViewer'
import WorkflowProgress from '../components/WorkflowProgress'
import './TaskDetailPage.css'

function TaskDetailPage() {
  const { taskId } = useParams<{ taskId: string }>()
  const navigate = useNavigate()
  const [task, setTask] = useState<Task | null>(null)
  const [executions, setExecutions] = useState<Execution[]>([])
  const [loading, setLoading] = useState(true)
  const [runningOperation, setRunningOperation] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [showAutomatedWorkflow, setShowAutomatedWorkflow] = useState(false)
  const [workflowExecution, setWorkflowExecution] = useState<Execution | null>(null)

  useEffect(() => {
    if (taskId) {
      loadTask()
      loadExecutions()
    }
  }, [taskId])

  const loadTask = async () => {
    if (!taskId) return
    try {
      const data = await api.getTask(taskId)
      setTask(data)
    } catch (err: any) {
      setError(err.message || 'Failed to load task')
    }
  }

  const loadExecutions = async () => {
    if (!taskId) return
    try {
      const data = await api.getExecutions(taskId)
      setExecutions(data)
    } catch (err: any) {
      console.error('Failed to load executions:', err)
    } finally {
      setLoading(false)
    }
  }

  const runOperation = async (operation: 'map' | 'generate-mission' | 'execute') => {
    if (!taskId) return

    try {
      setRunningOperation(operation)
      setError(null)
      const execution = await api.runTaskOperation(taskId, operation)
      
      // Poll for updates
      const pollInterval = setInterval(async () => {
        try {
          const updated = await api.getExecution(execution.execution_id)
          if (updated.status === 'completed' || updated.status === 'failed') {
            clearInterval(pollInterval)
            setRunningOperation(null)
            loadExecutions()
          }
        } catch (err) {
          console.error('Polling error:', err)
        }
      }, 1000)

      // Stop polling after 5 minutes
      setTimeout(() => {
        clearInterval(pollInterval)
        setRunningOperation(null)
      }, 300000)

      loadExecutions()
    } catch (err: any) {
      setError(err.message || 'Failed to run operation')
      setRunningOperation(null)
    }
  }

  if (loading) {
    return (
      <div className="task-detail-page">
        <div className="container">
          <div className="loading">Loading task...</div>
        </div>
      </div>
    )
  }

  if (error && !task) {
    return (
      <div className="task-detail-page">
        <div className="container">
          <div className="error">Error: {error}</div>
          <button onClick={() => navigate('/')}>Back to Tasks</button>
        </div>
      </div>
    )
  }

  if (!task) {
    return null
  }

  return (
    <div className="task-detail-page">
      <div className="container">
        <button onClick={() => navigate('/')} className="back-button">
          ← Back to Tasks
        </button>

        <div className="task-detail-header">
          <div>
            <h1>{task.title}</h1>
            <span className="task-id-badge">{task.id}</span>
          </div>
          {task.pr_link && (
            <a
              href={task.pr_link}
              target="_blank"
              rel="noopener noreferrer"
              className="pr-link-button"
            >
              View PR →
            </a>
          )}
        </div>

        <div className="task-description-section">
          <h2>Description</h2>
          <pre className="task-description-text">{task.description}</pre>
        </div>

        <div className="actions-section">
          <h2>Actions</h2>
          <div className="action-buttons">
            <button
              onClick={async () => {
                if (!taskId) return
                try {
                  setError(null)
                  // Show workflow progress immediately
                  setShowAutomatedWorkflow(true)
                  setRunningOperation('automated-workflow')
                  
                  // Small delay to ensure WebSocket connection is established
                  await new Promise(resolve => setTimeout(resolve, 500))
                  
                  const execution = await api.runAutomatedWorkflow(taskId)
                  setWorkflowExecution(execution)
                  
                  // Load updates from execution result if available
                  if (execution.result?.updates && Array.isArray(execution.result.updates)) {
                    // Updates will be loaded by WorkflowProgress component
                  }
                  
                  // Poll for completion
                  const pollInterval = setInterval(async () => {
                    try {
                      const updated = await api.getExecution(execution.execution_id)
                      if (updated.status === 'completed' || updated.status === 'failed') {
                        clearInterval(pollInterval)
                        setRunningOperation(null)
                        setWorkflowExecution(updated)
                        loadExecutions()
                      }
                    } catch (err) {
                      console.error('Polling error:', err)
                    }
                  }, 2000)
                  
                  setTimeout(() => {
                    clearInterval(pollInterval)
                    setRunningOperation(null)
                  }, 600000) // 10 minutes
                } catch (err: any) {
                  setError(err.message || 'Failed to start automated workflow')
                  setRunningOperation(null)
                  setShowAutomatedWorkflow(false)
                }
              }}
              disabled={runningOperation !== null}
              className={`automated-button ${runningOperation === 'automated-workflow' ? 'running' : ''}`}
            >
              {runningOperation === 'automated-workflow' ? (
                <>
                  <span className="spinner">🔄</span> Running Automated Workflow...
                </>
              ) : (
                <>
                  <span className="robot-icon">🤖</span> Run Automated Workflow
                  <span className="button-subtitle">Intelligently maps, generates mission, and executes tests</span>
                </>
              )}
            </button>
            
            <button
              onClick={async () => {
                if (!taskId) return
                const isRunning = runningOperation === 'generate-mission'
                if (isRunning) return // Prevent double-click
                
                try {
                  setError(null)
                  setRunningOperation('generate-mission')
                  
                  const execution = await api.runTaskOperation(taskId, 'generate-mission')
                  
                  // Poll for completion
                  const pollInterval = setInterval(async () => {
                    try {
                      const updated = await api.getExecution(execution.execution_id)
                      if (updated.status === 'completed' || updated.status === 'failed') {
                        clearInterval(pollInterval)
                        if (runningOperation === 'generate-mission') {
                          setRunningOperation(null)
                        }
                        loadExecutions()
                        if (updated.status === 'completed') {
                          alert('✅ Mission generated successfully!')
                        } else {
                          alert(`❌ Mission generation failed: ${updated.error || 'Unknown error'}`)
                        }
                      }
                    } catch (err) {
                      console.error('Polling error:', err)
                    }
                  }, 1000)
                  
                  setTimeout(() => {
                    clearInterval(pollInterval)
                    if (runningOperation === 'generate-mission') {
                      setRunningOperation(null)
                    }
                  }, 300000) // 5 minutes
                } catch (err: any) {
                  setError(err.message || 'Failed to generate mission')
                  if (runningOperation === 'generate-mission') {
                    setRunningOperation(null)
                  }
                }
              }}
              disabled={runningOperation === 'generate-mission'}
              className={`action-button generate-mission-button ${runningOperation === 'generate-mission' ? 'running' : ''}`}
            >
              {runningOperation === 'generate-mission' ? (
                <>
                  <span className="spinner">🔄</span> Generating Mission...
                </>
              ) : (
                <>
                  <span className="icon">📝</span> Generate Mission
                  <span className="button-subtitle">Force regenerate mission.json from task file</span>
                </>
              )}
            </button>
          </div>
          {error && <div className="error-message">{error}</div>}
        </div>

        {showAutomatedWorkflow && taskId && (
          <WorkflowProgress
            taskId={taskId}
            executionId={workflowExecution?.execution_id}
            onComplete={(success) => {
              // Don't hide workflow progress - keep it visible to show updates
              setRunningOperation(null)
              loadExecutions()
              // Update workflowExecution to get latest updates
              if (workflowExecution?.execution_id) {
                api.getExecution(workflowExecution.execution_id).then(setWorkflowExecution)
              }
            }}
          />
        )}

        <div className="executions-section">
          <h2>Execution History</h2>
          {executions.length === 0 ? (
            <div className="empty-state">No executions yet</div>
          ) : (
            <div className="executions-list">
              {executions.map((execution) => (
                <ExecutionCard key={execution.execution_id} execution={execution} />
              ))}
            </div>
          )}
        </div>

        {/* Semantic Graph Viewer */}
        {(() => {
          try {
            const mapExecution = executions.find(
              (e) => e.execution_type === 'map' && e.status === 'completed' && e.result?.graph
            )
            if (mapExecution?.result?.graph) {
              // Use the graph structure exactly as the mapper produces it
              return (
                <div className="graph-section">
                  <h2>Semantic Graph Visualization</h2>
                  <SemanticGraphViewer
                    graph={{
                      nodes: mapExecution.result.graph.nodes || [],
                      edges: mapExecution.result.graph.edges || [],
                      // Include any additional fields the mapper might add
                      api_endpoints: mapExecution.result.graph.api_endpoints,
                      db_tables: mapExecution.result.graph.db_tables,
                    }}
                  />
                </div>
              )
            }
          } catch (error) {
            console.error('Error rendering graph:', error)
            return (
              <div className="graph-section">
                <h2>Semantic Graph Visualization</h2>
                <div className="error-message">
                  Error loading graph: {String(error)}
                </div>
              </div>
            )
          }
          return null
        })()}
      </div>
    </div>
  )
}

function ExecutionCard({ execution }: { execution: Execution }) {
  const [expanded, setExpanded] = useState(false)
  const [details, setDetails] = useState<Execution | null>(null)

  const loadDetails = async () => {
    if (!expanded && !details) {
      try {
        const data = await api.getExecution(execution.execution_id)
        setDetails(data)
      } catch (err) {
        console.error('Failed to load execution details:', err)
      }
    }
    setExpanded(!expanded)
  }

  // Use details if available, otherwise use execution
  const displayExecution = details || execution

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'completed':
        return '#4caf50'
      case 'failed':
        return '#f44336'
      case 'running':
        return '#ff9800'
      default:
        return '#999'
    }
  }

  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'completed':
        return '✅'
      case 'failed':
        return '❌'
      case 'running':
        return '🔄'
      default:
        return '⏳'
    }
  }

  return (
    <div className="execution-card">
      <div className="execution-header" onClick={loadDetails}>
        <div className="execution-info">
          <span className="execution-type">{execution.execution_type}</span>
          <span
            className="execution-status"
            style={{ color: getStatusColor(execution.status) }}
          >
            {getStatusIcon(execution.status)} {execution.status}
          </span>
        </div>
        <div className="execution-time">
          {new Date(execution.started_at).toLocaleString()}
        </div>
        <span className="expand-icon">{expanded ? '▼' : '▶'}</span>
      </div>
      {expanded && displayExecution && (
        <div className="execution-details">
          {displayExecution.error && (
            <div className="execution-error">
              <strong>Error:</strong> {displayExecution.error}
            </div>
          )}
          {displayExecution.result && (
            <div className="execution-result">
              <strong>Result:</strong>
              {displayExecution.execution_type === 'map' && displayExecution.result.graph ? (
                <div className="graph-summary">
                  <p>
                    ✅ Graph created: {displayExecution.result.graph.nodes_count} nodes,{' '}
                    {displayExecution.result.graph.edges_count} edges
                  </p>
                  {displayExecution.result.output && (
                    <details>
                      <summary>View Output</summary>
                      <pre>{displayExecution.result.output}</pre>
                    </details>
                  )}
                </div>
              ) : displayExecution.execution_type === 'execute' && displayExecution.result.report ? (
                <div className="test-results">
                  <h4>Triple-Check Results:</h4>
                  <div className="triple-check-results">
                    <div className={`check-result ${displayExecution.result.report.triple_check?.database?.success ? 'pass' : 'fail'}`}>
                      <span>{displayExecution.result.report.triple_check?.database?.success ? '✅' : '❌'}</span>
                      <div style={{ flex: 1 }}>
                        <span><strong>Database:</strong> {displayExecution.result.report.triple_check?.database?.success ? 'PASS' : 'FAIL'}</span>
                        {displayExecution.result.report.triple_check?.database?.details && (
                          <div className="check-details">{JSON.stringify(displayExecution.result.report.triple_check.database.details, null, 2)}</div>
                        )}
                      </div>
                    </div>
                    <div className={`check-result ${displayExecution.result.report.triple_check?.api?.success ? 'pass' : 'fail'}`}>
                      <span>{displayExecution.result.report.triple_check?.api?.success ? '✅' : '❌'}</span>
                      <div style={{ flex: 1 }}>
                        <span><strong>API:</strong> {displayExecution.result.report.triple_check?.api?.success ? 'PASS' : 'FAIL'}</span>
                        {displayExecution.result.report.triple_check?.api?.details && (
                          <div className="check-details">{JSON.stringify(displayExecution.result.report.triple_check.api.details, null, 2)}</div>
                        )}
                      </div>
                    </div>
                    <div className={`check-result ${displayExecution.result.report.triple_check?.ui?.success ? 'pass' : 'fail'}`}>
                      <span>{displayExecution.result.report.triple_check?.ui?.success ? '✅' : '❌'}</span>
                      <div style={{ flex: 1 }}>
                        <span><strong>UI:</strong> {displayExecution.result.report.triple_check?.ui?.success ? 'PASS' : 'FAIL'}</span>
                        {displayExecution.result.report.triple_check?.ui?.details && (
                          <div className="check-details">{JSON.stringify(displayExecution.result.report.triple_check.ui.details, null, 2)}</div>
                        )}
                      </div>
                    </div>
                  </div>
                  <div className={`overall-result ${displayExecution.result.report.overall_success ? 'pass' : 'fail'}`}>
                    <strong>Overall: {displayExecution.result.report.overall_success ? '✅ PASS' : '❌ FAIL'}</strong>
                  </div>
                  {displayExecution.result.output && (
                    <details>
                      <summary>View Full Output</summary>
                      <pre>{displayExecution.result.output}</pre>
                    </details>
                  )}
                </div>
              ) : displayExecution.execution_type === 'automated-workflow' && displayExecution.result.steps ? (
                <div className="workflow-results">
                  <h4>Workflow Steps:</h4>
                  {Object.entries(displayExecution.result.steps).map(([step, result]: [string, any]) => (
                    <div key={step} className={`workflow-step ${result.success ? 'success' : 'failed'}`}>
                      <span>{result.success ? '✅' : '❌'}</span>
                      <span><strong>{step}:</strong> {result.success ? 'Completed' : 'Failed'}</span>
                      {result.skipped && <span className="skipped-badge">(Skipped)</span>}
                    </div>
                  ))}
                  <div className={`overall-result ${displayExecution.result.overall_success ? 'pass' : 'fail'}`}>
                    <strong>Overall: {displayExecution.result.overall_success ? '✅ PASS' : '❌ FAIL'}</strong>
                  </div>
                  {displayExecution.result.updates && Array.isArray(displayExecution.result.updates) && displayExecution.result.updates.length > 0 && (
                    <div className="workflow-updates-history">
                      <h4>Workflow Updates:</h4>
                      <div className="updates-list">
                        {displayExecution.result.updates.map((update: any, index: number) => (
                          <div key={index} className={`update-item update-${update.status}`}>
                            <div className="update-header">
                              <span className="update-step">{update.step}</span>
                              <span className="update-status">{update.status}</span>
                              <span className="update-time">{new Date(update.timestamp).toLocaleTimeString()}</span>
                            </div>
                            <div className="update-message">{update.message}</div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              ) : (
                <pre>{JSON.stringify(displayExecution.result, null, 2)}</pre>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export default TaskDetailPage
