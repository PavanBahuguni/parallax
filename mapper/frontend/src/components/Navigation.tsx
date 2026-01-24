import { Link, useLocation } from 'react-router-dom'
import './Navigation.css'

function Navigation() {
  const location = useLocation()

  return (
    <nav className="navigation">
      <div className="nav-container">
        <Link to="/" className="nav-logo">
          🧪 Agentic QA Dashboard
        </Link>
        <div className="nav-links">
          <Link
            to="/"
            className={location.pathname === '/' ? 'active' : ''}
          >
            Projects
          </Link>
          <Link
            to="/executions"
            className={location.pathname === '/executions' ? 'active' : ''}
          >
            Executions
          </Link>
          <Link
            to="/graph"
            className={location.pathname === '/graph' ? 'active' : ''}
          >
            Graph
          </Link>
        </div>
      </div>
    </nav>
  )
}

export default Navigation
