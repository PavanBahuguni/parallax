import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, Task } from '../api/client'
import './DashboardPage.css'

function DashboardPage() {
  const [tasks, setTasks] = useState<Task[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    loadTasks()
  }, [])

  const loadTasks = async () => {
    try {
      setLoading(true)
      const data = await api.getTasks()
      setTasks(data)
      setError(null)
    } catch (err: any) {
      setError(err.message || 'Failed to load tasks')
    } finally {
      setLoading(false)
    }
  }

  if (loading) {
    return (
      <div className="dashboard-page">
        <div className="container">
          <div className="loading">Loading tasks...</div>
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="dashboard-page">
        <div className="container">
          <div className="error">Error: {error}</div>
        </div>
      </div>
    )
  }

  return (
    <div className="dashboard-page">
      <div className="container">
        <div className="page-header">
          <h1>Tasks</h1>
          <button onClick={loadTasks}>Refresh</button>
        </div>

        {tasks.length === 0 ? (
          <div className="empty-state">
            <p>No tasks found. Create a task.md file in the mapper directory.</p>
          </div>
        ) : (
          <div className="tasks-grid">
            {tasks.map((task) => (
              <TaskCard key={task.id} task={task} />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

function TaskCard({ task }: { task: Task }) {
  return (
    <Link to={`/tasks/${task.id}`} className="task-card">
      <div className="task-header">
        <h2>{task.title}</h2>
        <span className="task-id">{task.id}</span>
      </div>
      <p className="task-description">
        {task.description.substring(0, 150)}
        {task.description.length > 150 ? '...' : ''}
      </p>
      {task.pr_link && (
        <a
          href={task.pr_link}
          target="_blank"
          rel="noopener noreferrer"
          className="task-pr-link"
          onClick={(e) => e.stopPropagation()}
        >
          View PR →
        </a>
      )}
      <div className="task-footer">
        <span className="task-path">{task.file_path}</span>
        {task.updated_at && (
          <span className="task-updated">
            Updated: {new Date(task.updated_at).toLocaleDateString()}
          </span>
        )}
      </div>
    </Link>
  )
}

export default DashboardPage
