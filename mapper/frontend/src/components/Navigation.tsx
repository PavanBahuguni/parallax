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
            Tasks
          </Link>
          <Link
            to="/executions"
            className={location.pathname === '/executions' ? 'active' : ''}
          >
            Executions
          </Link>
        </div>
      </div>
    </nav>
  )
}

export default Navigation
