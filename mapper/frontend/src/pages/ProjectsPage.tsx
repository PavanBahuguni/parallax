import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, Project } from '../api/client'
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
      <div className="projects-page">
        <div className="container">
          <div className="loading">Loading projects...</div>
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="projects-page">
        <div className="container">
          <div className="error">Error: {error}</div>
          <button onClick={loadProjects}>Retry</button>
        </div>
      </div>
    )
  }

  return (
    <div className="projects-page">
      <div className="container">
        <div className="page-header">
          <h1>Projects</h1>
          <div className="header-actions">
            <button onClick={loadProjects}>Refresh</button>
            <button onClick={() => setShowForm(true)} className="primary">
              + Add Project
            </button>
          </div>
        </div>

        {showForm && (
          <div className="modal-overlay" onClick={() => setShowForm(false)}>
            <div className="modal-content" onClick={(e) => e.stopPropagation()}>
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

        {projects.length === 0 ? (
          <div className="empty-state">
            <p>No projects found. Create your first project to get started.</p>
            <button onClick={() => setShowForm(true)} className="primary">
              Create Project
            </button>
          </div>
        ) : (
          <div className="projects-grid">
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
  return (
    <Link to={`/projects/${project.id}`} className="project-card">
      <div className="project-header">
        <h2>{project.name}</h2>
        <button
          className="delete-btn"
          onClick={(e) => onDelete(project.id, e)}
          title="Delete project"
        >
          ×
        </button>
      </div>
      {project.description && <p className="project-description">{project.description}</p>}
      <div className="project-info">
        <div className="info-item">
          <span className="label">UI URL:</span>
          <span className="value">{project.ui_url}</span>
        </div>
        {project.api_base_url && (
          <div className="info-item">
            <span className="label">API Base:</span>
            <span className="value">{project.api_base_url}</span>
          </div>
        )}
        {project.personas && project.personas.length > 0 && (
          <div className="info-item">
            <span className="label">Personas:</span>
            <span className="value">{project.personas.map(p => p.name).join(', ')}</span>
          </div>
        )}
      </div>
      <div className="project-footer">
        {project.updated_at && (
          <span className="project-updated">
            Updated: {new Date(project.updated_at).toLocaleDateString()}
          </span>
        )}
      </div>
    </Link>
  )
}

// Import ProjectForm component (will be created next)
import ProjectForm from '../components/ProjectForm'

export default ProjectsPage
