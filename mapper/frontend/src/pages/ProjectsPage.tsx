import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, Project } from '../api/client'
import ProjectForm from '../components/ProjectForm'
import './ProjectsPage.css'

function ProjectsPage() {
  const [projects, setProjects] = useState<Project[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [showForm, setShowForm] = useState(false)

  useEffect(() => {
    loadProjects()
  }, [])

  const loadProjects = async () => {
    try {
      setLoading(true)
      const data = await api.getProjects()
      setProjects(data)
      setError(null)
    } catch (err: any) {
      setError(err.message || 'Failed to load projects')
    } finally {
      setLoading(false)
    }
  }

  const handleDelete = async (projectId: string, e: React.MouseEvent) => {
    e.stopPropagation()
    e.preventDefault()
    if (!confirm('Are you sure you want to delete this project?')) {
      return
    }

    try {
      await api.deleteProject(projectId)
      await loadProjects()
    } catch (err: any) {
      alert(`Failed to delete project: ${err.message}`)
    }
  }

  if (loading) {
    return (
      <div className="pp">
        <div className="pp-container">
          <div className="pp-loading">
            <div className="pp-spinner"></div>
            <span>Loading projects...</span>
          </div>
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="pp">
        <div className="pp-container">
          <div className="pp-error-state">
            <div className="pp-error-icon">!</div>
            <h2>Error Loading Projects</h2>
            <p>{error}</p>
            <button onClick={loadProjects} className="pp-btn pp-btn-primary">
              Try Again
            </button>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="pp">
      <div className="pp-container">
        {/* Header */}
        <header className="pp-header">
          <div className="pp-header-left">
            <h1 className="pp-title">Projects</h1>
            <p className="pp-subtitle">Manage your QA test projects and configurations</p>
          </div>
          <div className="pp-header-actions">
            <button onClick={loadProjects} className="pp-btn pp-btn-secondary">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <polyline points="23 4 23 10 17 10"/>
                <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/>
              </svg>
              Refresh
            </button>
            <button onClick={() => setShowForm(true)} className="pp-btn pp-btn-primary">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <line x1="12" y1="5" x2="12" y2="19"/>
                <line x1="5" y1="12" x2="19" y2="12"/>
              </svg>
              New Project
            </button>
          </div>
        </header>

        {/* Modal */}
        {showForm && (
          <div className="pp-modal-overlay" onClick={() => setShowForm(false)}>
            <div className="pp-modal" onClick={(e) => e.stopPropagation()}>
              <div className="pp-modal-header">
                <h2>Create New Project</h2>
                <button className="pp-modal-close" onClick={() => setShowForm(false)}>
                  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <line x1="18" y1="6" x2="6" y2="18"/>
                    <line x1="6" y1="6" x2="18" y2="18"/>
                  </svg>
                </button>
              </div>
              <ProjectForm
                onClose={() => setShowForm(false)}
                onSuccess={() => {
                  setShowForm(false)
                  loadProjects()
                }}
              />
            </div>
          </div>
        )}

        {/* Content */}
        {projects.length === 0 ? (
          <div className="pp-empty">
            <div className="pp-empty-icon">
              <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>
              </svg>
            </div>
            <h2>No projects yet</h2>
            <p>Create your first project to start testing</p>
            <button onClick={() => setShowForm(true)} className="pp-btn pp-btn-primary">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <line x1="12" y1="5" x2="12" y2="19"/>
                <line x1="5" y1="12" x2="19" y2="12"/>
              </svg>
              Create Project
            </button>
          </div>
        ) : (
          <div className="pp-grid">
            {projects.map((project) => (
              <ProjectCard key={project.id} project={project} onDelete={handleDelete} />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

function ProjectCard({
  project,
  onDelete,
}: {
  project: Project
  onDelete: (projectId: string, e: React.MouseEvent) => void
}) {
  const personaCount = project.personas?.length || 0
  
  return (
    <Link to={`/projects/${project.id}`} className="pp-card">
      <div className="pp-card-header">
        <div className="pp-card-icon">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>
          </svg>
        </div>
        <button
          className="pp-card-delete"
          onClick={(e) => onDelete(project.id, e)}
          title="Delete project"
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <polyline points="3 6 5 6 21 6"/>
            <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>
          </svg>
        </button>
      </div>
      
      <h2 className="pp-card-title">{project.name}</h2>
      
      {project.description && (
        <p className="pp-card-desc">{project.description}</p>
      )}
      
      <div className="pp-card-meta">
        <div className="pp-card-url">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <circle cx="12" cy="12" r="10"/>
            <line x1="2" y1="12" x2="22" y2="12"/>
            <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/>
          </svg>
          <span>{project.ui_url}</span>
        </div>
      </div>
      
      <div className="pp-card-footer">
        <div className="pp-card-stats">
          {personaCount > 0 && (
            <span className="pp-card-stat">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/>
                <circle cx="9" cy="7" r="4"/>
                <path d="M23 21v-2a4 4 0 0 0-3-3.87"/>
                <path d="M16 3.13a4 4 0 0 1 0 7.75"/>
              </svg>
              {personaCount} persona{personaCount !== 1 ? 's' : ''}
            </span>
          )}
        </div>
        {project.updated_at && (
          <span className="pp-card-date">
            {new Date(project.updated_at).toLocaleDateString()}
          </span>
        )}
      </div>
    </Link>
  )
}

export default ProjectsPage
