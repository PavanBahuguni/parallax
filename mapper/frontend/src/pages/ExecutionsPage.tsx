import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, Execution } from '../api/client'
import './ExecutionsPage.css'

function ExecutionsPage() {
  const [executions, setExecutions] = useState<Execution[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    loadExecutions()
    // Poll for updates every 2 seconds
    const interval = setInterval(loadExecutions, 2000)
    return () => clearInterval(interval)
  }, [])

  const loadExecutions = async () => {
    try {
      const data = await api.getExecutions()
      setExecutions(data)
      setError(null)
    } catch (err: any) {
      setError(err.message || 'Failed to load executions')
    } finally {
      setLoading(false)
    }
  }

  if (loading) {
    return (
      <div className="executions-page">
        <div className="container">
          <div className="loading">Loading executions...</div>
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="executions-page">
        <div className="container">
          <div className="error">Error: {error}</div>
        </div>
      </div>
    )
  }

  return (
    <div className="executions-page">
      <div className="container">
        <div className="page-header">
          <h1>Execution History</h1>
          <button onClick={loadExecutions}>Refresh</button>
        </div>

        {executions.length === 0 ? (
          <div className="empty-state">
            <p>No executions yet. Run a task operation to see results here.</p>
          </div>
        ) : (
          <div className="executions-list">
            {executions.map((execution) => (
              <ExecutionCard key={execution.execution_id} execution={execution} />
            ))}
          </div>
        )}
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
        <div className="execution-main-info">
          <Link
            to={`/tasks/${execution.task_id}`}
            className="execution-task-link"
            onClick={(e) => e.stopPropagation()}
          >
            {execution.task_id}
          </Link>
          <span className="execution-type">{execution.execution_type}</span>
          <span
            className="execution-status"
            style={{ color: getStatusColor(execution.status) }}
          >
            {getStatusIcon(execution.status)} {execution.status}
          </span>
        </div>
        <div className="execution-time-info">
          <div className="execution-time">
            Started: {new Date(execution.started_at).toLocaleString()}
          </div>
          {execution.completed_at && (
            <div className="execution-time">
              Completed: {new Date(execution.completed_at).toLocaleString()}
            </div>
          )}
        </div>
        <span className="expand-icon">{expanded ? '▼' : '▶'}</span>
      </div>
      {expanded && details && (
        <div className="execution-details">
          {details.error && (
            <div className="execution-error">
              <strong>Error:</strong> {details.error}
            </div>
          )}
          {details.result && (
            <div className="execution-result">
              <strong>Result:</strong>
              <pre>{JSON.stringify(details.result, null, 2)}</pre>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export default ExecutionsPage
