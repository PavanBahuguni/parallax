import { useEffect, useState } from 'react'
import { useParams, Link, useNavigate } from 'react-router-dom'
import { api, Project, Task, Execution } from '../api/client'
import SemanticGraphViewer from '../components/SemanticGraphViewer'
import PersonasSection from '../components/PersonasSection'
import type { Persona } from '../components/PersonasSection'
import './ProjectDetailPage.css'

function ProjectDetailPage() {
  const { projectId } = useParams<{ projectId: string }>()
  const navigate = useNavigate()
  const [project, setProject] = useState<Project | null>(null)
  const [tasks, setTasks] = useState<Task[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [showEditForm, setShowEditForm] = useState(false)
  const [graph, setGraph] = useState<any>(null)
  const [regenerationStatus, setRegenerationStatus] = useState<Execution | null>(null)
  const [isRegenerating, setIsRegenerating] = useState(false)
  const [pollIntervalId, setPollIntervalId] = useState<NodeJS.Timeout | null>(null)
  const [headlessMode, setHeadlessMode] = useState(true)
  const [selectedPersona, setSelectedPersona] = useState<string | null>(null)

  useEffect(() => {
    if (projectId) {
      loadProject()
      loadTasks()
    }
    
    // Cleanup polling interval on unmount
    return () => {
      if (pollIntervalId) {
        clearInterval(pollIntervalId)
      }
    }
  }, [projectId])

  // Load graph after project is loaded (so we can use project personas)
  useEffect(() => {
    if (projectId && project) {
      // Load first persona's graph by default
      const personas = project.personas || []
      if (personas.length > 0 && !selectedPersona) {
        const firstPersona = personas[0]
        const firstPersonaName = typeof firstPersona === 'string' ? firstPersona : firstPersona.name || firstPersona
        setSelectedPersona(firstPersonaName)
      } else if (personas.length === 0) {
        loadGraph()
      }
    }
  }, [projectId, project])
  
  // Reload graph when selected persona changes
  useEffect(() => {
    if (projectId && project && selectedPersona) {
      loadGraph(selectedPersona)
    }
  }, [selectedPersona, projectId, project])

  const loadProject = async () => {
    if (!projectId) return
    try {
      const data = await api.getProject(projectId)
      setProject(data)
      setError(null)
    } catch (err: any) {
      setError(err.message || 'Failed to load project')
    } finally {
      setLoading(false)
    }
  }

  const loadTasks = async () => {
    if (!projectId) return
    try {
      const data = await api.getProjectTasks(projectId)
      setTasks(data)
    } catch (err: any) {
      console.error('Failed to load tasks:', err)
      // Fallback to file-based tasks if DB not available
      try {
        const fileTasks = await api.getTasks()
        setTasks(fileTasks)
      } catch (e) {
        // Ignore
      }
    }
  }

  const loadGraph = async (personaName?: string) => {
    if (!projectId) return
    try {
      // Load graph for specific persona, or first persona if none specified
      const personas = project?.personas || []
      let targetPersona = personaName
      
      if (!targetPersona && personas.length > 0) {
        const firstPersona = personas[0]
        targetPersona = typeof firstPersona === 'string' ? firstPersona : firstPersona.name || firstPersona
      }
      
      if (!targetPersona) {
        // Fallback: try loading without persona (will use default)
        const data = await api.getSemanticGraph(undefined, projectId)
        setGraph(data)
        setSelectedPersona(null)
        return
      }

      const data = await api.getSemanticGraph(targetPersona, projectId)
      setGraph(data)
      setSelectedPersona(targetPersona)
    } catch (err) {
      // Graph may not exist yet
      console.log(`Graph not available for persona ${personaName}:`, err)
      setGraph(null)
    }
  }

  const handleDelete = async () => {
    if (!projectId) return
    if (!confirm('Are you sure you want to delete this project? All tasks will be deleted too.')) {
      return
    }

    try {
      await api.deleteProject(projectId)
      navigate('/')
    } catch (err: any) {
      alert(`Failed to delete project: ${err.message}`)
    }
  }

  const handleRegenerateSemanticMaps = async () => {
    if (!projectId) return
    
    const personas = project?.personas || []
    if (personas.length === 0) {
      alert('No personas defined for this project. Please add personas first.')
      return
    }

    if (!confirm(`This will regenerate semantic maps for ${personas.length} persona(s). This may take several minutes. Continue?`)) {
      return
    }

    try {
      setIsRegenerating(true)
      setRegenerationStatus(null)
      
      const response = await api.regenerateSemanticMaps(projectId, headlessMode)
      
      // Set initial status
      let initialExecution: Execution
      try {
        initialExecution = await api.getExecution(response.execution_id)
        setRegenerationStatus(initialExecution)
      } catch (err) {
        console.error('Error getting initial execution status:', err)
        // Continue anyway
      }
      
      // Poll for execution status
      let pollCount = 0
      const maxPolls = 300 // 10 minutes max (300 * 2 seconds)
      const pollInterval = setInterval(async () => {
        pollCount++
        
        if (pollCount > maxPolls) {
          clearInterval(pollInterval)
          setPollIntervalId(null)
          setIsRegenerating(false)
          alert('Regeneration is taking longer than expected. Please check the execution status manually.')
          return
        }
        
        try {
          const execution = await api.getExecution(response.execution_id)
          setRegenerationStatus(execution)
          
          if (execution.status === 'completed' || execution.status === 'failed') {
            clearInterval(pollInterval)
            setPollIntervalId(null)
            setIsRegenerating(false)
            
            if (execution.status === 'completed') {
              // Reload graph after successful regeneration
              await loadGraph()
            }
          }
        } catch (err) {
          console.error('Error polling execution status:', err)
          // Continue polling
        }
      }, 2000) // Poll every 2 seconds
      
      // Store interval ID for cleanup
      setPollIntervalId(pollInterval)
      
    } catch (err: any) {
      setIsRegenerating(false)
      alert(`Failed to start regeneration: ${err.message}`)
    }
  }

  if (loading) {
    return (
      <div className="project-detail-page">
        <div className="container">
          <div className="loading">Loading project...</div>
        </div>
      </div>
    )
  }

  if (error || !project) {
    return (
      <div className="project-detail-page">
        <div className="container">
          <div className="error">Error: {error || 'Project not found'}</div>
          <Link to="/">← Back to Projects</Link>
        </div>
      </div>
    )
  }

  return (
    <div className="project-detail-page">
      <div className="container">
        <div className="page-header">
          <div>
            <Link to="/" className="back-link">
              ← Back to Projects
            </Link>
            <h1>{project.name}</h1>
            {project.description && <p className="project-description">{project.description}</p>}
          </div>
          <div className="header-actions">
            <button onClick={() => setShowEditForm(true)}>Edit</button>
            <button onClick={handleDelete} className="danger">
              Delete
            </button>
          </div>
        </div>

        {showEditForm && (
          <div className="modal-overlay" onClick={() => setShowEditForm(false)}>
            <div className="modal-content" onClick={(e) => e.stopPropagation()}>
              <ProjectForm
                project={project}
                onClose={() => setShowEditForm(false)}
                onSuccess={() => {
                  setShowEditForm(false)
                  loadProject()
                }}
              />
            </div>
          </div>
        )}

        <div className="project-sections">
          {/* Project Configuration */}
          <section className="project-config">
            <h2>Configuration</h2>
            <div className="config-grid">
              <div className="config-item">
                <span className="config-label">UI URL:</span>
                <span className="config-value">{project.ui_url}</span>
              </div>
              {project.api_base_url && (
                <div className="config-item">
                  <span className="config-label">API Base URL:</span>
                  <span className="config-value">{project.api_base_url}</span>
                </div>
              )}
              {project.openapi_url && (
                <div className="config-item">
                  <span className="config-label">OpenAPI URL:</span>
                  <span className="config-value">{project.openapi_url}</span>
                </div>
              )}
              {project.database_url && (
                <div className="config-item">
                  <span className="config-label">Database URL:</span>
                  <span className="config-value">{project.database_url}</span>
                </div>
              )}
              {project.backend_path && (
                <div className="config-item">
                  <span className="config-label">Backend Path:</span>
                  <span className="config-value">{project.backend_path}</span>
                </div>
              )}
            </div>
          </section>

          {/* Personas Section */}
          <section className="personas-management-section">
            <div className="section-header">
              <h2>Personas</h2>
              <div className="regenerate-controls">
                <label className="headless-toggle">
                  <input
                    type="checkbox"
                    checked={!headlessMode}
                    onChange={(e) => setHeadlessMode(!e.target.checked)}
                    disabled={isRegenerating}
                  />
                  <span>Show browser (non-headless)</span>
                </label>
                <button 
                  onClick={handleRegenerateSemanticMaps}
                  disabled={isRegenerating || (project.personas || []).length === 0}
                  className="regenerate-button"
                >
                  {isRegenerating ? 'Regenerating...' : 'Regenerate Semantic Maps'}
                </button>
              </div>
            </div>
            
            {regenerationStatus && (
              <div className={`regeneration-status ${regenerationStatus.status}`}>
                <div className="status-header">
                  <strong>Regeneration Status: {regenerationStatus.status}</strong>
                  {regenerationStatus.status === 'running' && <span className="spinner">⏳</span>}
                </div>
                {regenerationStatus.result && (
                  <div className="status-details">
                    {regenerationStatus.result.results && (
                      <div className="persona-results">
                        {regenerationStatus.result.results.map((result: any, idx: number) => (
                          <div key={idx} className={`persona-result ${result.success ? 'success' : 'failed'}`}>
                            <span className="persona-name">{result.persona}:</span>
                            <span className="persona-status">
                              {result.success ? (
                                <>✅ Success ({result.graph?.nodes_count || 0} nodes, {result.graph?.edges_count || 0} edges)</>
                              ) : (
                                <>❌ Failed</>
                              )}
                            </span>
                          </div>
                        ))}
                      </div>
                    )}
                    {regenerationStatus.result.successful !== undefined && (
                      <div className="summary">
                        {regenerationStatus.result.successful} of {regenerationStatus.result.total_personas} persona(s) completed successfully
                      </div>
                    )}
                  </div>
                )}
                {regenerationStatus.error && (
                  <div className="error-message">Error: {regenerationStatus.error}</div>
                )}
              </div>
            )}
            
            <PersonasSection
              personas={(project.personas || []) as Persona[]}
              onChange={async (updatedPersonas) => {
                try {
                  await api.updateProject(projectId!, {
                    personas: updatedPersonas,
                  })
                  await loadProject()
                } catch (err: any) {
                  alert(`Failed to update personas: ${err.message}`)
                }
              }}
            />
          </section>

          {/* Tasks List */}
          <section className="tasks-section">
            <div className="section-header">
              <h2>Tasks</h2>
              <button onClick={loadTasks}>Refresh</button>
            </div>

            {tasks.length === 0 ? (
              <div className="empty-state">
                <p>No tasks found.</p>
                <p className="hint">
                  Tasks are loaded from <code>mapper/tasks/*.md</code> files.
                  Create task markdown files in the tasks directory to see them here.
                </p>
                <p className="hint" style={{ marginTop: '0.5rem', fontSize: '0.875rem', color: '#999' }}>
                  Future: Tasks will be synced from Jira.
                </p>
              </div>
            ) : (
              <div className="tasks-list">
                {tasks.map((task) => (
                  <TaskCard key={task.id} task={task} projectId={projectId!} />
                ))}
              </div>
            )}
          </section>

          {/* Semantic Graph */}
          <section className="graph-section">
            <div className="section-header">
              <h2>Semantic Graph</h2>
              {project.personas && project.personas.length > 1 && (
                <div className="persona-selector">
                  <label htmlFor="persona-select">View Graph for:</label>
                  <select
                    id="persona-select"
                    value={selectedPersona || ''}
                    onChange={(e) => setSelectedPersona(e.target.value || null)}
                  >
                    {project.personas.map((persona: any) => {
                      const personaName = typeof persona === 'string' ? persona : persona.name || persona
                      return (
                        <option key={personaName} value={personaName}>
                          {personaName}
                        </option>
                      )
                    })}
                  </select>
                </div>
              )}
            </div>
            {graph && graph.nodes && graph.nodes.length > 0 ? (
              <SemanticGraphViewer graph={graph} />
            ) : (
              <div className="empty-state">
                <p>No graph available{selectedPersona ? ` for persona "${selectedPersona}"` : ''}.</p>
                <p className="hint">
                  Run "Regenerate Semantic Maps" to generate the graph for this persona.
                </p>
              </div>
            )}
          </section>
        </div>
      </div>
    </div>
  )
}

function TaskCard({ task, projectId }: { task: Task; projectId: string }) {
  return (
    <Link to={`/projects/${projectId}/tasks/${task.id}`} className="task-card">
      <div className="task-header">
        <h3>{task.title}</h3>
        <span className="task-id">{task.id}</span>
      </div>
      <p className="task-description">
        {task.description?.substring(0, 150)}
        {task.description && task.description.length > 150 ? '...' : ''}
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

// Import ProjectForm
import ProjectForm from '../components/ProjectForm'

export default ProjectDetailPage
