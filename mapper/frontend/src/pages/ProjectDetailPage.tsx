import { useEffect, useState } from 'react'
import { useParams, Link, useNavigate } from 'react-router-dom'
import { api, Project, Task, Execution } from '../api/client'
import SemanticGraphViewer from '../components/SemanticGraphViewer'
import PersonasSection from '../components/PersonasSection'
import type { Persona } from '../components/PersonasSection'
import ProjectForm from '../components/ProjectForm'
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
    
    return () => {
      if (pollIntervalId) {
        clearInterval(pollIntervalId)
      }
    }
  }, [projectId])

  useEffect(() => {
    if (projectId && project) {
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
      const personas = project?.personas || []
      let targetPersona = personaName
      
      if (!targetPersona && personas.length > 0) {
        const firstPersona = personas[0]
        targetPersona = typeof firstPersona === 'string' ? firstPersona : firstPersona.name || firstPersona
      }
      
      if (!targetPersona) {
        const data = await api.getSemanticGraph(undefined, projectId)
        setGraph(data)
        setSelectedPersona(null)
        return
      }

      const data = await api.getSemanticGraph(targetPersona, projectId)
      setGraph(data)
      setSelectedPersona(targetPersona)
    } catch (err) {
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
      
      let initialExecution: Execution
      try {
        initialExecution = await api.getExecution(response.execution_id)
        setRegenerationStatus(initialExecution)
      } catch (err) {
        console.error('Error getting initial execution status:', err)
      }
      
      let pollCount = 0
      const maxPolls = 300
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
              await loadGraph()
            }
          }
        } catch (err) {
          console.error('Error polling execution status:', err)
        }
      }, 2000)
      
      setPollIntervalId(pollInterval)
      
    } catch (err: any) {
      setIsRegenerating(false)
      alert(`Failed to start regeneration: ${err.message}`)
    }
  }

  if (loading) {
    return (
      <div className="pdp">
        <div className="pdp-container">
          <div className="pdp-loading">
            <div className="pdp-spinner"></div>
            <span>Loading project...</span>
          </div>
        </div>
      </div>
    )
  }

  if (error || !project) {
    return (
      <div className="pdp">
        <div className="pdp-container">
          <div className="pdp-error-state">
            <div className="pdp-error-icon">!</div>
            <h2>Error Loading Project</h2>
            <p>{error || 'Project not found'}</p>
            <button onClick={() => navigate('/')} className="pdp-btn pdp-btn-secondary">
              Back to Projects
            </button>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="pdp">
      <div className="pdp-container">
        {/* Header */}
        <header className="pdp-header">
          <button onClick={() => navigate('/')} className="pdp-back-btn">
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
              <path d="M10 12L6 8L10 4" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
            </svg>
            Back
          </button>
          
          <div className="pdp-header-content">
            <div className="pdp-title-row">
              <h1 className="pdp-title">{project.name}</h1>
              <div className="pdp-actions">
                <button onClick={() => setShowEditForm(true)} className="pdp-btn pdp-btn-secondary">
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>
                    <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>
                  </svg>
                  Edit
                </button>
                <button onClick={handleDelete} className="pdp-btn pdp-btn-danger">
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <polyline points="3 6 5 6 21 6"/>
                    <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>
                  </svg>
                  Delete
                </button>
              </div>
            </div>
            {project.description && <p className="pdp-description">{project.description}</p>}
          </div>
        </header>

        {showEditForm && (
          <div className="pdp-modal-overlay" onClick={() => setShowEditForm(false)}>
            <div className="pdp-modal" onClick={(e) => e.stopPropagation()}>
              <div className="pdp-modal-header">
                <h2>Edit Project</h2>
                <button className="pdp-modal-close" onClick={() => setShowEditForm(false)}>
                  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <line x1="18" y1="6" x2="6" y2="18"/>
                    <line x1="6" y1="6" x2="18" y2="18"/>
                  </svg>
                </button>
              </div>
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

        <div className="pdp-grid">
          {/* Main Column */}
          <div className="pdp-main-col">
            {/* Configuration */}
            <section className="pdp-card">
              <div className="pdp-card-header">
                <h2 className="pdp-card-title">Configuration</h2>
              </div>
              <div className="pdp-card-body">
                <div className="pdp-config-grid">
                  <div className="pdp-config-item">
                    <span className="pdp-config-label">UI URL</span>
                    <a href={project.ui_url} target="_blank" rel="noopener noreferrer" className="pdp-config-value link">
                      {project.ui_url}
                      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                        <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>
                        <polyline points="15 3 21 3 21 9"/>
                        <line x1="10" y1="14" x2="21" y2="3"/>
                      </svg>
                    </a>
                  </div>
                  {project.api_base_url && (
                    <div className="pdp-config-item">
                      <span className="pdp-config-label">API Base URL</span>
                      <span className="pdp-config-value">{project.api_base_url}</span>
                    </div>
                  )}
                  {project.openapi_url && (
                    <div className="pdp-config-item">
                      <span className="pdp-config-label">OpenAPI URL</span>
                      <a href={project.openapi_url} target="_blank" rel="noopener noreferrer" className="pdp-config-value link">
                        {project.openapi_url}
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                          <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>
                          <polyline points="15 3 21 3 21 9"/>
                          <line x1="10" y1="14" x2="21" y2="3"/>
                        </svg>
                      </a>
                    </div>
                  )}
                  {project.database_url && (
                    <div className="pdp-config-item">
                      <span className="pdp-config-label">Database URL</span>
                      <span className="pdp-config-value mono">{project.database_url}</span>
                    </div>
                  )}
                  {project.backend_path && (
                    <div className="pdp-config-item">
                      <span className="pdp-config-label">Backend Path</span>
                      <span className="pdp-config-value mono">{project.backend_path}</span>
                    </div>
                  )}
                </div>
              </div>
            </section>

            {/* Tasks */}
            <section className="pdp-card">
              <div className="pdp-card-header">
                <h2 className="pdp-card-title">Tasks</h2>
                <button onClick={loadTasks} className="pdp-icon-btn" title="Refresh Tasks">
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <polyline points="23 4 23 10 17 10"/>
                    <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/>
                  </svg>
                </button>
              </div>
              <div className="pdp-card-body pdp-no-padding">
                {tasks.length === 0 ? (
                  <div className="pdp-empty">
                    <div className="pdp-empty-icon">📝</div>
                    <p>No tasks found</p>
                    <span className="pdp-hint">Tasks are loaded from mapper/tasks/*.md files</span>
                  </div>
                ) : (
                  <div className="pdp-tasks-list">
                    {tasks.map((task) => (
                      <TaskCard key={task.id} task={task} projectId={projectId!} />
                    ))}
                  </div>
                )}
              </div>
            </section>

            {/* Semantic Graph */}
            <section className="pdp-card">
              <div className="pdp-card-header">
                <h2 className="pdp-card-title">Semantic Graph</h2>
                <div className="pdp-header-actions">
                  {project.personas && project.personas.length > 1 && (
                    <div className="pdp-select-wrapper">
                      <select
                        value={selectedPersona || ''}
                        onChange={(e) => setSelectedPersona(e.target.value || null)}
                        className="pdp-select"
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
                  {graph && graph.nodes && graph.nodes.length > 0 && (
                    <Link to={`/projects/${projectId}/graph`} className="pdp-fullscreen-btn">
                      ⛶ Full Screen
                    </Link>
                  )}
                </div>
              </div>
              <div className="pdp-card-body pdp-graph-container">
                {graph && graph.nodes && graph.nodes.length > 0 ? (
                  <SemanticGraphViewer graph={graph} />
                ) : (
                  <div className="pdp-empty">
                    <div className="pdp-empty-icon">🕸️</div>
                    <p>No graph available{selectedPersona ? ` for ${selectedPersona}` : ''}</p>
                    <span className="pdp-hint">Run "Regenerate Semantic Maps" to generate</span>
                  </div>
                )}
              </div>
            </section>
          </div>

          {/* Sidebar Column */}
          <div className="pdp-sidebar-col">
            {/* Personas */}
            <section className="pdp-card">
              <div className="pdp-card-header">
                <h2 className="pdp-card-title">Personas</h2>
              </div>
              <div className="pdp-card-body">
                <div className="pdp-regen-controls">
                  <label className="pdp-toggle">
                    <input
                      type="checkbox"
                      checked={!headlessMode}
                      onChange={(e) => setHeadlessMode(!e.target.checked)}
                      disabled={isRegenerating}
                    />
                    <span className="pdp-toggle-slider"></span>
                    <span className="pdp-toggle-label">Show Browser</span>
                  </label>
                  <button 
                    onClick={handleRegenerateSemanticMaps}
                    disabled={isRegenerating || (project.personas || []).length === 0}
                    className="pdp-btn pdp-btn-primary pdp-btn-full"
                  >
                    {isRegenerating ? (
                      <>
                        <div className="pdp-spinner-sm"></div>
                        Regenerating...
                      </>
                    ) : (
                      <>
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                          <path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/>
                          <polyline points="9 22 9 12 15 12 15 22"/>
                        </svg>
                        Regenerate Maps
                      </>
                    )}
                  </button>
                </div>

                {regenerationStatus && (
                  <div className={`pdp-status ${regenerationStatus.status}`}>
                    <div className="pdp-status-header">
                      <strong>Status: {regenerationStatus.status}</strong>
                    </div>
                    {regenerationStatus.result?.results && (
                      <div className="pdp-status-list">
                        {regenerationStatus.result.results.map((result: any, idx: number) => (
                          <div key={idx} className={`pdp-status-item ${result.success ? 'success' : 'failed'}`}>
                            <span>{result.persona}</span>
                            <span>{result.success ? '✅' : '❌'}</span>
                          </div>
                        ))}
                      </div>
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
              </div>
            </section>
          </div>
        </div>
      </div>
    </div>
  )
}

function TaskCard({ task, projectId }: { task: Task; projectId: string }) {
  return (
    <Link to={`/projects/${projectId}/tasks/${task.id}`} className="pdp-task-row">
      <div className="pdp-task-main">
        <div className="pdp-task-header">
          <span className="pdp-task-id">{task.id}</span>
          <h3 className="pdp-task-title">{task.title}</h3>
        </div>
        <p className="pdp-task-desc">
          {task.description?.substring(0, 120)}
          {task.description && task.description.length > 120 ? '...' : ''}
        </p>
      </div>
      <div className="pdp-task-meta">
        {task.pr_link && (
          <span className="pdp-task-badge pr">PR Linked</span>
        )}
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="pdp-chevron">
          <polyline points="9 18 15 12 9 6"/>
        </svg>
      </div>
    </Link>
  )
}

export default ProjectDetailPage
