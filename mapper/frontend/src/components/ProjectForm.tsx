import { useState } from 'react'
import { api, ProjectCreate, ProjectUpdate, Project } from '../api/client'
import './ProjectForm.css'

interface ProjectFormProps {
  project?: Project
  onClose: () => void
  onSuccess: () => void
}

function ProjectForm({ project, onClose, onSuccess }: ProjectFormProps) {
  const [formData, setFormData] = useState<ProjectCreate | ProjectUpdate>({
    name: project?.name || '',
    description: project?.description || '',
    ui_url: project?.ui_url || '',
    api_base_url: project?.api_base_url || '',
    openapi_url: project?.openapi_url || '',
    database_url: project?.database_url || '',
    backend_path: project?.backend_path || '',
    personas: (project?.personas || []) as any,
  })
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true)
    setError(null)

    try {
      const data = {
        ...formData,
        // Personas are already in the correct format from PersonasSection
      }

      if (project) {
        await api.updateProject(project.id, data as ProjectUpdate)
      } else {
        await api.createProject(data as ProjectCreate)
      }

      onSuccess()
    } catch (err: any) {
      setError(err.message || 'Failed to save project')
    } finally {
      setLoading(false)
    }
  }

  const handleChange = (field: keyof ProjectCreate, value: string) => {
    setFormData((prev) => ({ ...prev, [field]: value }))
  }

  return (
    <div className="project-form">
      <div className="form-header">
        <h2>{project ? 'Edit Project' : 'Create New Project'}</h2>
        <button className="close-btn" onClick={onClose}>
          ×
        </button>
      </div>

      <form onSubmit={handleSubmit}>
        {error && <div className="form-error">{error}</div>}

        <div className="form-group">
          <label htmlFor="name">
            Project Name <span className="required">*</span>
          </label>
          <input
            id="name"
            type="text"
            value={formData.name}
            onChange={(e) => handleChange('name', e.target.value)}
            required
            placeholder="e.g., Partner Portal"
          />
        </div>

        <div className="form-group">
          <label htmlFor="description">Description</label>
          <textarea
            id="description"
            value={formData.description || ''}
            onChange={(e) => handleChange('description', e.target.value)}
            rows={3}
            placeholder="Brief description of the project"
          />
        </div>

        <div className="form-group">
          <label htmlFor="ui_url">
            UI URL <span className="required">*</span>
          </label>
          <input
            id="ui_url"
            type="url"
            value={formData.ui_url}
            onChange={(e) => handleChange('ui_url', e.target.value)}
            required
            placeholder="http://localhost:5173"
          />
        </div>

        <div className="form-group">
          <label htmlFor="api_base_url">API Base URL</label>
          <input
            id="api_base_url"
            type="url"
            value={formData.api_base_url || ''}
            onChange={(e) => handleChange('api_base_url', e.target.value)}
            placeholder="http://localhost:8000"
          />
        </div>

        <div className="form-group">
          <label htmlFor="openapi_url">OpenAPI URL</label>
          <input
            id="openapi_url"
            type="url"
            value={formData.openapi_url || ''}
            onChange={(e) => handleChange('openapi_url', e.target.value)}
            placeholder="https://api.example.com/openapi.json"
          />
        </div>

        <div className="form-group">
          <label htmlFor="database_url">Database URL</label>
          <input
            id="database_url"
            type="text"
            value={formData.database_url || ''}
            onChange={(e) => handleChange('database_url', e.target.value)}
            placeholder="postgresql://user:pass@host:port/db"
          />
        </div>

        <div className="form-group">
          <label htmlFor="backend_path">Backend Path</label>
          <input
            id="backend_path"
            type="text"
            value={formData.backend_path || ''}
            onChange={(e) => handleChange('backend_path', e.target.value)}
            placeholder="/path/to/backend"
          />
        </div>

        <div className="form-group">
          <label>Personas</label>
          <small className="form-hint" style={{ display: 'block', marginBottom: '0.5rem' }}>
            Personas can be managed in the Project Detail page after creation. Each persona includes gateway instructions for authentication.
          </small>
        </div>

        <div className="form-actions">
          <button type="button" onClick={onClose} disabled={loading}>
            Cancel
          </button>
          <button type="submit" disabled={loading} className="primary">
            {loading ? 'Saving...' : project ? 'Update' : 'Create'}
          </button>
        </div>
      </form>
    </div>
  )
}

export default ProjectForm
