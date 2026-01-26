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
      if (project) {
        await api.updateProject(project.id, formData as ProjectUpdate)
      } else {
        await api.createProject(formData as ProjectCreate)
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
    <form className="pf" onSubmit={handleSubmit}>
      {error && (
        <div className="pf-error">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <circle cx="12" cy="12" r="10"/>
            <line x1="15" y1="9" x2="9" y2="15"/>
            <line x1="9" y1="9" x2="15" y2="15"/>
          </svg>
          {error}
        </div>
      )}

      <div className="pf-section">
        <h3 className="pf-section-title">Basic Information</h3>
        
        <div className="pf-field">
          <label htmlFor="name" className="pf-label">
            Project Name <span className="pf-required">*</span>
          </label>
          <input
            id="name"
            type="text"
            className="pf-input"
            value={formData.name}
            onChange={(e) => handleChange('name', e.target.value)}
            required
            placeholder="e.g., Partner Portal"
          />
        </div>

        <div className="pf-field">
          <label htmlFor="description" className="pf-label">Description</label>
          <textarea
            id="description"
            className="pf-textarea"
            value={formData.description || ''}
            onChange={(e) => handleChange('description', e.target.value)}
            rows={2}
            placeholder="Brief description of the project"
          />
        </div>
      </div>

      <div className="pf-section">
        <h3 className="pf-section-title">URLs & Endpoints</h3>
        
        <div className="pf-field">
          <label htmlFor="ui_url" className="pf-label">
            UI URL <span className="pf-required">*</span>
          </label>
          <input
            id="ui_url"
            type="url"
            className="pf-input"
            value={formData.ui_url}
            onChange={(e) => handleChange('ui_url', e.target.value)}
            required
            placeholder="http://localhost:5173"
          />
          <span className="pf-hint">The URL where your frontend application is running</span>
        </div>

        <div className="pf-row">
          <div className="pf-field">
            <label htmlFor="api_base_url" className="pf-label">API Base URL</label>
            <input
              id="api_base_url"
              type="url"
              className="pf-input"
              value={formData.api_base_url || ''}
              onChange={(e) => handleChange('api_base_url', e.target.value)}
              placeholder="http://localhost:8000"
            />
          </div>

          <div className="pf-field">
            <label htmlFor="openapi_url" className="pf-label">OpenAPI URL</label>
            <input
              id="openapi_url"
              type="url"
              className="pf-input"
              value={formData.openapi_url || ''}
              onChange={(e) => handleChange('openapi_url', e.target.value)}
              placeholder="https://api.example.com/openapi.json"
            />
          </div>
        </div>
      </div>

      <div className="pf-section">
        <h3 className="pf-section-title">Database & Backend</h3>
        
        <div className="pf-field">
          <label htmlFor="database_url" className="pf-label">Database URL</label>
          <input
            id="database_url"
            type="text"
            className="pf-input pf-input-mono"
            value={formData.database_url || ''}
            onChange={(e) => handleChange('database_url', e.target.value)}
            placeholder="postgresql://user:pass@host:port/db"
          />
        </div>

        <div className="pf-field">
          <label htmlFor="backend_path" className="pf-label">Backend Path</label>
          <input
            id="backend_path"
            type="text"
            className="pf-input pf-input-mono"
            value={formData.backend_path || ''}
            onChange={(e) => handleChange('backend_path', e.target.value)}
            placeholder="/path/to/backend"
          />
        </div>
      </div>

      <div className="pf-info">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <circle cx="12" cy="12" r="10"/>
          <line x1="12" y1="16" x2="12" y2="12"/>
          <line x1="12" y1="8" x2="12.01" y2="8"/>
        </svg>
        <span>Personas can be configured after creating the project</span>
      </div>

      <div className="pf-actions">
        <button type="button" onClick={onClose} disabled={loading} className="pf-btn pf-btn-secondary">
          Cancel
        </button>
        <button type="submit" disabled={loading} className="pf-btn pf-btn-primary">
          {loading ? (
            <>
              <div className="pf-spinner"></div>
              Saving...
            </>
          ) : (
            project ? 'Update Project' : 'Create Project'
          )}
        </button>
      </div>
    </form>
  )
}

export default ProjectForm
