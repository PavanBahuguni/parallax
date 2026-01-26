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

  const handleRunWorkflow = async () => {
    if (!taskId) return
    try {
      setError(null)
      setShowAutomatedWorkflow(true)
      setRunningOperation('automated-workflow')
      
      await new Promise(resolve => setTimeout(resolve, 500))
      
      const execution = await api.runAutomatedWorkflow(taskId)
      setWorkflowExecution(execution)
      
      const pollInterval = setInterval(async () => {
        try {
          const updated = await api.getExecution(execution.execution_id)
          if (updated.status === 'completed' || updated.status === 'failed') {
            clearInterval(pollInterval)
            setRunningOperation(null)
            setWorkflowExecution(updated)
            loadExecutions()
          }
        } catch (err: any) {
          console.error('Polling error:', err)
          if (err.response?.status === 404) {
            clearInterval(pollInterval)
            setRunningOperation(null)
            setError('Execution not found (backend may have restarted)')
          }
        }
      }, 2000)
      
      setTimeout(() => {
        clearInterval(pollInterval)
        setRunningOperation(null)
      }, 600000)
    } catch (err: any) {
      setError(err.message || 'Failed to start automated workflow')
      setRunningOperation(null)
      setShowAutomatedWorkflow(false)
    }
  }

  const handleGenerateMission = async () => {
    if (!taskId || runningOperation === 'generate-mission') return
    
    try {
      setError(null)
      setRunningOperation('generate-mission')
      
      const execution = await api.runTaskOperation(taskId, 'generate-mission')
      
      const pollInterval = setInterval(async () => {
        try {
          const updated = await api.getExecution(execution.execution_id)
          if (updated.status === 'completed' || updated.status === 'failed') {
            clearInterval(pollInterval)
            setRunningOperation(null)
            loadExecutions()
          }
        } catch (err: any) {
          console.error('Polling error:', err)
          if (err.response?.status === 404) {
            clearInterval(pollInterval)
            setRunningOperation(null)
            setError('Execution not found (backend may have restarted)')
          }
        }
      }, 1000)
      
      setTimeout(() => {
        clearInterval(pollInterval)
        setRunningOperation(prev => prev === 'generate-mission' ? null : prev)
      }, 300000)
    } catch (err: any) {
      setError(err.message || 'Failed to generate mission')
      setRunningOperation(null)
    }
  }

  if (loading) {
    return (
      <div className="tdp">
        <div className="tdp-container">
          <div className="tdp-loading">
            <div className="tdp-loading-spinner"></div>
            <span>Loading task...</span>
          </div>
        </div>
      </div>
    )
  }

  if (error && !task) {
    return (
      <div className="tdp">
        <div className="tdp-container">
          <div className="tdp-error-state">
            <div className="tdp-error-icon">!</div>
            <h2>Error Loading Task</h2>
            <p>{error}</p>
            <button onClick={() => navigate('/')} className="tdp-btn tdp-btn-secondary">
              Back to Tasks
            </button>
          </div>
        </div>
      </div>
    )
  }

  if (!task) return null

  return (
    <div className="tdp">
      <div className="tdp-container">
        {/* Header */}
        <header className="tdp-header">
          <button onClick={() => navigate('/')} className="tdp-back-btn">
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
              <path d="M10 12L6 8L10 4" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
            </svg>
            Back
          </button>
          
          <div className="tdp-header-content">
            <div className="tdp-title-row">
              <h1 className="tdp-title">{task.title || 'Untitled Task'}</h1>
              <span className="tdp-task-id">{task.id}</span>
            </div>
            
            {task.pr_link && (
              <a href={task.pr_link} target="_blank" rel="noopener noreferrer" className="tdp-pr-link">
                <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
                  <path fillRule="evenodd" d="M7.177 3.073L9.573.677A.25.25 0 0110 .854v4.792a.25.25 0 01-.427.177L7.177 3.427a.25.25 0 010-.354zM3.75 2.5a.75.75 0 100 1.5.75.75 0 000-1.5zm-2.25.75a2.25 2.25 0 113 2.122v5.256a2.251 2.251 0 11-1.5 0V5.372A2.25 2.25 0 011.5 3.25zM11 2.5h-1V4h1a1 1 0 011 1v5.628a2.251 2.251 0 101.5 0V5A2.5 2.5 0 0011 2.5zm1 10.25a.75.75 0 111.5 0 .75.75 0 01-1.5 0zM3.75 12a.75.75 0 100 1.5.75.75 0 000-1.5z"/>
                </svg>
                View Pull Request
              </a>
            )}
          </div>
        </header>

        {/* Description Card */}
        <section className="tdp-card">
          <div className="tdp-card-header">
            <h2 className="tdp-card-title">Description</h2>
          </div>
          <div className="tdp-card-body">
            <div className="tdp-description">{task.description || 'No description provided.'}</div>
          </div>
        </section>

        {/* Actions Card */}
        <section className="tdp-card">
          <div className="tdp-card-header">
            <h2 className="tdp-card-title">Actions</h2>
          </div>
          <div className="tdp-card-body">
            <div className="tdp-actions">
              <button
                onClick={handleRunWorkflow}
                disabled={runningOperation !== null}
                className={`tdp-action-btn tdp-action-primary ${runningOperation === 'automated-workflow' ? 'running' : ''}`}
              >
                {runningOperation === 'automated-workflow' ? (
                  <>
                    <div className="tdp-btn-spinner"></div>
                    <span>Running Workflow...</span>
                  </>
                ) : (
                  <>
                    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <polygon points="5 3 19 12 5 21 5 3"/>
                    </svg>
                    <div className="tdp-action-text">
                      <span className="tdp-action-title">Run Automated Workflow</span>
                      <span className="tdp-action-desc">Analyze, map, generate mission, and execute tests</span>
                    </div>
                  </>
                )}
              </button>

              <button
                onClick={handleGenerateMission}
                disabled={runningOperation !== null}
                className={`tdp-action-btn tdp-action-secondary ${runningOperation === 'generate-mission' ? 'running' : ''}`}
              >
                {runningOperation === 'generate-mission' ? (
                  <>
                    <div className="tdp-btn-spinner"></div>
                    <span>Generating...</span>
                  </>
                ) : (
                  <>
                    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
                      <polyline points="14 2 14 8 20 8"/>
                      <line x1="12" y1="18" x2="12" y2="12"/>
                      <line x1="9" y1="15" x2="15" y2="15"/>
                    </svg>
                    <div className="tdp-action-text">
                      <span className="tdp-action-title">Generate Mission</span>
                      <span className="tdp-action-desc">Regenerate test plan from task</span>
                    </div>
                  </>
                )}
              </button>
            </div>

            {error && (
              <div className="tdp-error-msg">
                <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
                  <path d="M8 15A7 7 0 108 1a7 7 0 000 14zm0-9.5a.75.75 0 01.75.75v3a.75.75 0 01-1.5 0v-3A.75.75 0 018 5.5zm0 7a1 1 0 100-2 1 1 0 000 2z"/>
                </svg>
                {error}
              </div>
            )}
          </div>
        </section>

        {/* Workflow Progress */}
        {showAutomatedWorkflow && taskId && (
          <WorkflowProgress
            taskId={taskId}
            executionId={workflowExecution?.execution_id}
            onComplete={(success) => {
              setRunningOperation(null)
              loadExecutions()
              if (workflowExecution?.execution_id) {
                api.getExecution(workflowExecution.execution_id).then(setWorkflowExecution)
              }
            }}
          />
        )}

        {/* Execution History */}
        <section className="tdp-card">
          <div className="tdp-card-header">
            <h2 className="tdp-card-title">Execution History</h2>
            <span className="tdp-card-badge">{executions.length}</span>
          </div>
          <div className="tdp-card-body tdp-no-padding">
            {executions.length === 0 ? (
              <div className="tdp-empty">
                <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                  <circle cx="12" cy="12" r="10"/>
                  <line x1="12" y1="8" x2="12" y2="12"/>
                  <line x1="12" y1="16" x2="12.01" y2="16"/>
                </svg>
                <p>No executions yet</p>
                <span>Run the automated workflow to get started</span>
              </div>
            ) : (
              <div className="tdp-executions">
                {executions.map((execution) => (
                  <ExecutionRow key={execution.execution_id} execution={execution} />
                ))}
              </div>
            )}
          </div>
        </section>

        {/* Semantic Graph */}
        {(() => {
          const mapExecution = executions.find(
            (e) => e.execution_type === 'map' && e.status === 'completed' && e.result?.graph
          )
          if (mapExecution?.result?.graph) {
            return (
              <section className="tdp-card">
                <div className="tdp-card-header">
                  <h2 className="tdp-card-title">Semantic Graph</h2>
                </div>
                <div className="tdp-card-body">
                  <SemanticGraphViewer
                    graph={{
                      nodes: mapExecution.result.graph.nodes || [],
                      edges: mapExecution.result.graph.edges || [],
                      api_endpoints: mapExecution.result.graph.api_endpoints,
                      db_tables: mapExecution.result.graph.db_tables,
                    }}
                  />
                </div>
              </section>
            )
          }
          return null
        })()}
      </div>
    </div>
  )
}

import ExecutionReport from '../components/ExecutionReport'
import AnsiRenderer from '../utils/AnsiRenderer'

function ExecutionRow({ execution }: { execution: Execution }) {
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

  const displayExecution = details || execution

  const getStatusClass = (status: string) => {
    switch (status) {
      case 'completed': return 'success'
      case 'failed': return 'error'
      case 'running': return 'warning'
      default: return 'neutral'
    }
  }

  const formatType = (type: string) => {
    return type.split('-').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ')
  }

  return (
    <div className={`tdp-exec-row ${expanded ? 'expanded' : ''}`}>
      <div className="tdp-exec-header" onClick={loadDetails}>
        <div className="tdp-exec-info">
          <span className="tdp-exec-type">{formatType(execution.execution_type)}</span>
          <span className={`tdp-exec-status tdp-status-${getStatusClass(execution.status)}`}>
            {execution.status}
          </span>
        </div>
        <div className="tdp-exec-meta">
          <span className="tdp-exec-time">
            {new Date(execution.started_at).toLocaleString()}
          </span>
          <svg 
            className={`tdp-exec-chevron ${expanded ? 'open' : ''}`}
            width="16" height="16" viewBox="0 0 16 16" fill="none"
          >
            <path d="M4 6L8 10L12 6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
          </svg>
        </div>
      </div>

      {expanded && displayExecution && (
        <div className="tdp-exec-details">
          {displayExecution.error && (
            <div className="tdp-exec-error">
              <strong>Error:</strong> {displayExecution.error}
            </div>
          )}

          {displayExecution.result && (
            <div className="tdp-exec-result">
              {displayExecution.execution_type === 'execute' && displayExecution.result.report ? (
                <ExecutionReport report={displayExecution.result.report} />
              ) : displayExecution.execution_type === 'automated-workflow' && displayExecution.result.steps ? (
                <WorkflowStepsResults result={displayExecution.result} />
              ) : displayExecution.execution_type === 'map' && displayExecution.result.graph ? (
                <div className="tdp-graph-summary">
                  Graph created: {displayExecution.result.graph.nodes_count || displayExecution.result.graph.nodes?.length || 0} nodes, {displayExecution.result.graph.edges_count || displayExecution.result.graph.edges?.length || 0} edges
                </div>
              ) : (
                <details>
                  <summary>View Raw Result</summary>
                  <div style={{ background: '#1e293b', padding: '12px', borderRadius: '8px', overflowX: 'auto' }}>
                    <AnsiRenderer text={JSON.stringify(displayExecution.result, null, 2)} />
                  </div>
                </details>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function WorkflowStepsResults({ result }: { result: any }) {
  const [expandedStep, setExpandedStep] = useState<string | null>(null)

  const toggleStep = (step: string) => {
    if (expandedStep === step) {
      setExpandedStep(null)
    } else {
      setExpandedStep(step)
    }
  }

  return (
    <div className="tdp-workflow-steps">
      {Object.entries(result.steps || {}).map(([step, stepResult]: [string, any]) => {
        // Allow expanding if there's a report OR an error OR output
        const hasDetails = (step === 'execute' && stepResult.report) || stepResult.error || stepResult.output
        
        return (
          <div key={step} className="tdp-wf-step-container">
            <div 
              className={`tdp-wf-step ${stepResult.success ? 'success' : 'failed'} ${hasDetails ? 'clickable' : ''}`}
              onClick={() => hasDetails && toggleStep(step)}
            >
              <span className="tdp-wf-step-icon">{stepResult.success ? '✓' : '✗'}</span>
              <span className="tdp-wf-step-name">{step}</span>
              {hasDetails && (
                <span className="tdp-wf-step-chevron">
                  {expandedStep === step ? '▼' : '▶'}
                </span>
              )}
              {stepResult.skipped && <span className="tdp-wf-skipped">Skipped</span>}
            </div>
            
            {expandedStep === step && hasDetails && (
              <div className="tdp-wf-step-details">
                {step === 'execute' && stepResult.report ? (
                  <ExecutionReport report={stepResult.report} />
                ) : (
                  <div className="tdp-step-raw-output">
                    {stepResult.error && (
                      <div className="tdp-step-error">
                        <strong>Error:</strong>
                        <div className="tdp-code-block">
                          <AnsiRenderer text={stepResult.error} />
                        </div>
                      </div>
                    )}
                    {!stepResult.error && stepResult.output && (
                      <div className="tdp-step-output">
                        <strong>Output:</strong>
                        <div className="tdp-code-block">
                          <AnsiRenderer text={stepResult.output} />
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </div>
            )}
          </div>
        )
      })}
      <div className={`tdp-overall ${result.overall_success ? 'pass' : 'fail'}`}>
        {result.overall_success ? 'Workflow Completed Successfully' : 'Workflow Failed'}
      </div>
    </div>
  )
}

export default TaskDetailPage
