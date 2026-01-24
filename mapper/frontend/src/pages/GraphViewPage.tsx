import { useEffect, useState } from 'react'
import { api } from '../api/client'
import SemanticGraphViewer from '../components/SemanticGraphViewer'
import './GraphViewPage.css'

function GraphViewPage() {
  const [graph, setGraph] = useState<any>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    loadGraph()
  }, [])

  const loadGraph = async () => {
    try {
      setLoading(true)
      setError(null)
      const data = await api.getSemanticGraph()
      setGraph(data)
    } catch (err: any) {
      setError(err.message || 'Failed to load semantic graph')
      console.error('Error loading graph:', err)
    } finally {
      setLoading(false)
    }
  }

  if (loading) {
    return (
      <div className="graph-view-page">
        <div className="container">
          <div className="loading">Loading semantic graph...</div>
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="graph-view-page">
        <div className="container">
          <div className="error-section">
            <h2>⚠️ Error Loading Graph</h2>
            <p>{error}</p>
            <button onClick={loadGraph}>Retry</button>
            <div className="error-hint">
              <p>Make sure:</p>
              <ul>
                <li>The semantic mapper has been run (semantic_graph.json exists)</li>
                <li>The backend server is running on port 8001</li>
                <li>Check the backend logs for errors</li>
              </ul>
            </div>
          </div>
        </div>
      </div>
    )
  }

  if (!graph || !graph.nodes || graph.nodes.length === 0) {
    return (
      <div className="graph-view-page">
        <div className="container">
          <div className="empty-state">
            <h2>📊 No Graph Data</h2>
            <p>The semantic graph is empty or hasn't been generated yet.</p>
            <p>Run the semantic mapper first to discover your application's structure.</p>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="graph-view-page">
      <div className="container">
        <div className="page-header">
          <h1>🗺️ Semantic Graph Visualization</h1>
          <button onClick={loadGraph}>🔄 Refresh</button>
        </div>

        <div className="graph-info">
          <div className="info-card">
            <span className="info-label">Nodes:</span>
            <span className="info-value">{graph.nodes?.length || 0}</span>
          </div>
          <div className="info-card">
            <span className="info-label">Edges:</span>
            <span className="info-value">{graph.edges?.length || 0}</span>
          </div>
          {graph.api_endpoints && (
            <div className="info-card">
              <span className="info-label">API Endpoints:</span>
              <span className="info-value">{Object.keys(graph.api_endpoints).length}</span>
            </div>
          )}
          {graph.db_tables && (
            <div className="info-card">
              <span className="info-label">DB Tables:</span>
              <span className="info-value">{Object.keys(graph.db_tables).length}</span>
            </div>
          )}
        </div>

        <div className="graph-container">
          <SemanticGraphViewer graph={graph} />
        </div>

        <div className="graph-legend">
          <h3>Legend</h3>
          <ul>
            <li>
              <span className="legend-node"></span>
              <strong>Nodes</strong> = Pages/Routes discovered in your application
            </li>
            <li>
              <span className="legend-edge"></span>
              <strong>Edges</strong> = Navigation paths between pages
            </li>
            <li>
              <span className="legend-tip">💡</span>
              <strong>Tip:</strong> Hover over nodes to see details, click to inspect in console
            </li>
          </ul>
        </div>
      </div>
    </div>
  )
}

export default GraphViewPage
