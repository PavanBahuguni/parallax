import { useEffect, useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { api, Project } from '../api/client'
import SemanticGraphViewer from '../components/SemanticGraphViewer'
import './ProjectGraphPage.css'

function ProjectGraphPage() {
  const { projectId } = useParams<{ projectId: string }>()
  const [project, setProject] = useState<Project | null>(null)
  const [graph, setGraph] = useState<any>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [selectedPersona, setSelectedPersona] = useState<string | null>(null)

  useEffect(() => {
    if (projectId) {
      loadProject()
    }
  }, [projectId])

  useEffect(() => {
    if (project && selectedPersona) {
      loadGraph(selectedPersona)
    }
  }, [selectedPersona, project])

  const loadProject = async () => {
    if (!projectId) return
    try {
      setLoading(true)
      const data = await api.getProject(projectId)
      setProject(data)
      
      // Set first persona as default
      if (data.personas && data.personas.length > 0) {
        const firstPersona = data.personas[0]
        const personaName = typeof firstPersona === 'string' ? firstPersona : firstPersona.name
        setSelectedPersona(personaName)
      } else {
        // No personas, load default graph
        await loadGraph()
      }
    } catch (err: any) {
      setError(err.message || 'Failed to load project')
    } finally {
      setLoading(false)
    }
  }

  const loadGraph = async (personaName?: string) => {
    if (!projectId) return
    try {
      const data = await api.getSemanticGraph(personaName, projectId)
      setGraph(data)
    } catch (err) {
      console.log(`Graph not available for persona ${personaName}:`, err)
      setGraph(null)
    }
  }

  const getPersonas = (): string[] => {
    if (!project?.personas) return []
    return project.personas.map(p => typeof p === 'string' ? p : p.name)
  }

  if (loading) {
    return (
      <div className="project-graph-page">
        <div className="loading">Loading...</div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="project-graph-page">
        <div className="error-section">
          <h2>Error</h2>
          <p>{error}</p>
          <Link to={`/projects/${projectId}`}>← Back to Project</Link>
        </div>
      </div>
    )
  }

  const personas = getPersonas()

  return (
    <div className="project-graph-page">
      <div className="graph-page-header">
        <div className="header-left">
          <Link to={`/projects/${projectId}`} className="back-link">
            ← Back to {project?.name || 'Project'}
          </Link>
          <h1>Semantic Graph</h1>
        </div>
        <div className="header-right">
          {personas.length > 1 && (
            <div className="persona-select-wrapper">
              <label>Persona:</label>
              <select 
                value={selectedPersona || ''} 
                onChange={(e) => setSelectedPersona(e.target.value)}
              >
                {personas.map(p => (
                  <option key={p} value={p}>{p}</option>
                ))}
              </select>
            </div>
          )}
          {personas.length === 1 && (
            <span className="persona-badge">{personas[0]}</span>
          )}
          <button onClick={() => loadGraph(selectedPersona || undefined)} className="refresh-btn">
            🔄 Refresh
          </button>
        </div>
      </div>

      <div className="graph-stats-bar">
        {graph && (
          <>
            <div className="stat-item">
              <span className="stat-label">Nodes:</span>
              <span className="stat-value">{graph.nodes?.length || 0}</span>
            </div>
            <div className="stat-item">
              <span className="stat-label">Edges:</span>
              <span className="stat-value">{graph.edges?.length || 0}</span>
            </div>
            {graph.api_endpoints && (
              <div className="stat-item">
                <span className="stat-label">API Endpoints:</span>
                <span className="stat-value">{Object.keys(graph.api_endpoints).length}</span>
              </div>
            )}
          </>
        )}
      </div>

      <div className="graph-fullscreen-container">
        {graph && graph.nodes && graph.nodes.length > 0 ? (
          <SemanticGraphViewer graph={graph} />
        ) : (
          <div className="empty-state">
            <div className="empty-icon">🕸️</div>
            <p>No graph available{selectedPersona ? ` for ${selectedPersona}` : ''}</p>
            <span className="hint">Run "Regenerate Semantic Maps" from the project page to generate</span>
          </div>
        )}
      </div>

      <div className="graph-legend-bar">
        <div className="legend-item">
          <span className="legend-dot green"></span>
          <span>Entry Point</span>
        </div>
        <div className="legend-item">
          <span className="legend-dot blue"></span>
          <span>Page/Route</span>
        </div>
        <div className="legend-item">
          <span className="legend-dot orange"></span>
          <span>Has Tests</span>
        </div>
        <div className="legend-item">
          <span className="legend-dot gray"></span>
          <span>External Link</span>
        </div>
        <div className="legend-tip">
          💡 Hover over nodes to see details and related tests
        </div>
      </div>
    </div>
  )
}

export default ProjectGraphPage
